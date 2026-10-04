"""High legs by 2-wire resistance at NORMAL IN: the analysis.

    uv run --with numpy --with matplotlib python analyze.py <run_dir> <out_dir>

<run_dir> holds the raw logs: Parquet parts of the 1 Hz meter readings (timestamp_utc, value) and
schedule.jsonl, the divider transitions ("dwell" events with range, pattern N/I and TMP275). The
supply is unplugged; the meter's ohms range follows the divider's range (300k / 3M / 30M); each
range is measured N, I, I, N per 12-minute cycle.

Each dwell is reduced to its mean after dropping the first SETTLE_S seconds (the sample straddling
a switch is an over-range reading, and the 30 MOhm range is still settling for ~10 s after it).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

SETTLE_S = 20.0
NOMINAL = {"1E-5": 100_001.0, "1E-6": 1_000_001.0, "1E-7": 10_000_001.0}
TOL = {"1E-5": "0.1 %", "1E-6": "0.1 %", "1E-7": "1 %"}

run = Path(sys.argv[1])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

samples = (
    pl.read_parquet(run / "part-*.parquet")
    .filter(pl.col("value").is_not_null())
    .select("timestamp_utc", "value", "status")
    .sort("timestamp_utc")
)
dwells = (
    pl.DataFrame([json.loads(x) for x in (run / "schedule.jsonl").read_text().splitlines() if '"dwell"' in x])
    .with_columns(pl.col("timestamp_utc").str.to_datetime(time_zone="UTC", time_unit="us").alias("start"))
    .select("start", "cycle", "index", "pattern", pl.col("range").alias("div"), "temp_c")
    .sort("start")
)
tagged = samples.join_asof(dwells, left_on="timestamp_utc", right_on="start").with_columns(
    ((pl.col("timestamp_utc") - pl.col("start")).dt.total_seconds()).alias("t")
)

# Settling: mean deviation from the dwell's late mean, by second into the dwell.
late = tagged.filter(pl.col("t") >= 30).group_by("cycle", "index").agg(pl.col("value").mean().alias("late"))
settling = (
    tagged.join(late, on=["cycle", "index"])
    .filter(pl.col("t") >= 1)
    .with_columns(((pl.col("value") / pl.col("late") - 1) * 1e6).alias("ppm"))
    .group_by("div", pl.col("t").floor().cast(pl.Int32).alias("sec"))
    .agg(pl.col("ppm").mean())
    .filter(pl.col("sec") <= 30)
    .sort("div", "sec")
)

per_dwell = (
    tagged.filter(pl.col("t") >= SETTLE_S)
    .group_by("cycle", "index", "pattern", "div")
    .agg(
        pl.col("start").first(),
        pl.col("value").mean().alias("r_ohm"),
        pl.col("value").std().alias("sd_ohm"),
        pl.len().alias("samples"),
        pl.col("temp_c").first(),
    )
    .sort("cycle", "index")
)
per_dwell.select(
    pl.col("start").dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias("utc"),
    "cycle",
    pl.col("div").alias("range"),
    "pattern",
    pl.col("r_ohm").round(3),
    pl.col("sd_ohm").round(3),
    "samples",
    pl.col("temp_c").alias("tmp275_c"),
).write_csv(out / "dwells.csv")

# The step: the cycle where 1E-7 moved by more than 30 ppm from the previous cycle.
c7 = per_dwell.filter(pl.col("div") == "1E-7").group_by("cycle").agg(pl.col("r_ohm").mean()).sort("cycle")
jumps = (c7["r_ohm"].diff() / c7["r_ohm"] * 1e6).to_list()
step_cycle = next((int(c7["cycle"][i]) for i, j in enumerate(jumps) if j is not None and abs(j) > 30), None)
step_utc = (
    str(per_dwell.filter((pl.col("cycle") == step_cycle) & (pl.col("index") == 0))["start"][0]) if step_cycle else None
)

ranges = {}
for r in ("1E-5", "1E-6", "1E-7"):
    x = per_dwell.filter(pl.col("div") == r)
    n = x.filter(pl.col("pattern") == "N")["r_ohm"]
    i = x.filter(pl.col("pattern") == "I")["r_ohm"]
    cyc = x.group_by("cycle").agg(pl.col("r_ohm").mean()).sort("cycle")
    mean = float(x["r_ohm"].mean())
    entry = {
        "nominal_ohm": NOMINAL[r],
        "tolerance": TOL[r],
        "mean_ohm": mean,
        "vs_nominal_ppm": (mean / NOMINAL[r] - 1) * 1e6,
        "n_mean_ohm": float(n.mean()),
        "i_mean_ohm": float(i.mean()),
        "n_minus_i_ppm": float((n.mean() - i.mean()) / mean * 1e6),
        "cycle_sd_ppm": float(cyc["r_ohm"].std() / mean * 1e6),
        "cycles": cyc.height,
    }
    if step_cycle is not None:
        before = cyc.filter(pl.col("cycle") < step_cycle)["r_ohm"]
        after = cyc.filter(pl.col("cycle") >= step_cycle)["r_ohm"]
        entry["before_step_ohm"] = float(before.mean())
        entry["after_step_ohm"] = float(after.mean())
        entry["step_ppm"] = float((after.mean() - before.mean()) / before.mean() * 1e6)
    ranges[r] = entry

status = samples.group_by("status").len()
summary = {
    "run": run.name,
    "quantity": "2-wire resistance across NORMAL IN, divider injecting on each range, OUT open, supply unplugged: R_H + R_L + contacts + leads",
    "meter": "HP 3478A, 2-wire ohms, 5.5 digits, autozero on, 1 Hz; range 300k / 3M / 30M following the divider",
    "start_utc": str(dwells["start"][0]),
    "duration_h": float((samples["timestamp_utc"].max() - samples["timestamp_utc"].min()).total_seconds() / 3600),
    "samples": samples.height,
    "status": {row["status"]: row["len"] for row in status.to_dicts()},
    "settle_s_dropped": SETTLE_S,
    "tmp275_span_c": [float(dwells["temp_c"].min()), float(dwells["temp_c"].max())],
    "step": {
        "cycle": step_cycle,
        "near_utc": step_utc,
        "note": "1E-6 and 1E-7 fell together; coincided with the operator leaving the bench; cause not identified",
    },
    "ranges": ranges,
}
(out / "summary.json").write_text(json.dumps(summary, indent=2))

# -- figure: per-dwell deviation from each range's first-cycle mean ----------------------------
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
COL = {"1E-5": "#1f6f5c", "1E-6": "#2f5d9a", "1E-7": "#b4532a"}
fig, axes = plt.subplots(4, 1, figsize=(10, 9), sharex=True, gridspec_kw={"hspace": 0.12})
t0 = dwells["start"][0]
for ax, r in zip(axes[:3], ("1E-5", "1E-6", "1E-7"), strict=True):
    x = per_dwell.filter(pl.col("div") == r)
    ref = float(x.filter(pl.col("cycle") == 0)["r_ohm"].mean())
    for pat, marker in (("N", "o"), ("I", "s")):
        xp = x.filter(pl.col("pattern") == pat)
        hrs = ((xp["start"] - t0).dt.total_seconds() / 3600).to_numpy()
        ax.plot(hrs, (xp["r_ohm"].to_numpy() / ref - 1) * 1e6, marker, ms=3.5, color=COL[r],
                mfc=COL[r] if pat == "N" else "none", label=f"{pat}")
    ax.set_ylabel(f"{r}\nppm")
    ax.legend(loc="lower left", frameon=False, ncol=2, fontsize=8)
hrs = ((dwells["start"] - t0).dt.total_seconds() / 3600).to_numpy()
axes[3].plot(hrs, dwells["temp_c"].to_numpy(), color="#7a7f86", lw=1)
axes[3].set_ylabel("TMP275\n°C")
axes[3].set_xlabel(f"hours since {str(t0)[:16]} UTC")
fig.suptitle("Total resistance per range, normal (filled) and inverted (open) polarity", x=0.07, ha="left")
fig.savefig(out / "high_legs.png", dpi=150, bbox_inches="tight")
plt.close(fig)

print(json.dumps(summary, indent=1))
print(settling.filter(pl.col("sec") <= 15).pivot(on="div", index="sec", values="ppm"))

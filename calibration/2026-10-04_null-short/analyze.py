"""Null run (b): the full ratio-run schedule with NORMAL IN shorted and no supply.

    uv run --with numpy --with matplotlib python analyze.py <run_dir> <out_dir>

<run_dir> holds the raw logs: Parquet parts of the 1 Hz meter readings on OUT (timestamp_utc,
value in volts) and schedule.jsonl (the divider transitions). Each dwell is reduced to its mean
after dropping the first SETTLE_S seconds; each ABBA block to S = (N1 + N2 - I1 - I2) / 4.

With nothing to divide, S should be zero. Its mean per range is the switching bias the ratio run
would see; the uncertainty is the scatter of independent blocks / sqrt(n), checked against a
split-halves comparison.
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

SETTLE_S = 2.0
V_CAL = 29.0
NOMINAL_K = {"1E-5": 1 / 100_001, "1E-6": 1 / 1_000_001, "1E-7": 1 / 10_000_001}

run = Path(sys.argv[1])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

samples = (
    pl.read_parquet(run / "part-*.parquet")
    .filter(pl.col("value").is_not_null())
    .select("timestamp_utc", "value")
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

# Settling: deviation from the dwell's late mean, by second, for injecting dwells.
late = tagged.filter(pl.col("t") >= 30).group_by("cycle", "index").agg(pl.col("value").mean().alias("late"))
settle_profile = (
    tagged.join(late, on=["cycle", "index"])
    .with_columns(((pl.col("value") - pl.col("late")) * 1e9).alias("nv"))
    .group_by(pl.col("t").floor().cast(pl.Int32).alias("sec"))
    .agg(pl.col("nv").mean())
    .filter(pl.col("sec") <= 10)
    .sort("sec")
)

per_dwell = (
    tagged.filter(pl.col("t") >= SETTLE_S)
    .group_by("cycle", "index", "pattern", "div")
    .agg(
        pl.col("start").first(),
        pl.col("value").mean().alias("v"),
        pl.col("value").std().alias("sd"),
        pl.len().alias("n"),
        pl.col("temp_c").first(),
    )
    .sort("cycle", "index")
)
per_dwell.select(
    pl.col("start").dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias("utc"),
    "cycle",
    pl.col("div").alias("range"),
    "pattern",
    (pl.col("v") * 1e9).round(2).alias("mean_nv"),
    (pl.col("sd") * 1e9).round(1).alias("sd_nv"),
    pl.col("n").alias("samples"),
    pl.col("temp_c").alias("tmp275_c"),
).write_csv(out / "dwells.csv")

# Blocks: within a cycle, the four dwells of one range, in N I I N order.
blocks = (
    per_dwell.filter(pl.col("pattern") != "Z")
    .sort("cycle", "index")
    .group_by("cycle", "div", maintain_order=True)
    .agg(pl.col("v"), pl.col("pattern"), pl.col("start").first(), pl.col("temp_c").first())
    .filter(pl.col("pattern").list.join("") == "NIIN")
    .with_columns(
        (
            (pl.col("v").list.get(0) + pl.col("v").list.get(3) - pl.col("v").list.get(1) - pl.col("v").list.get(2))
            / 4
            * 1e9
        ).alias("s_nv"),
        # Curvature ABBA does not cancel: (N1 - N2) - (I1 - I2), a diagnostic only.
        ((pl.col("v").list.get(0) + pl.col("v").list.get(2) - pl.col("v").list.get(1) - pl.col("v").list.get(3)) / 4 * 1e9).alias(
            "abab_nv"
        ),
    )
    .select("start", "cycle", "div", "s_nv", "abab_nv", "temp_c")
)
blocks.select(
    pl.col("start").dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias("utc"),
    "cycle",
    pl.col("div").alias("range"),
    pl.col("s_nv").round(2),
    pl.col("temp_c").alias("tmp275_c"),
).write_csv(out / "blocks.csv")

results = {}
for r in ("1E-5", "1E-6", "1E-7"):
    s = blocks.filter(pl.col("div") == r)["s_nv"].to_numpy()
    n = len(s)
    mean, sd = float(s.mean()), float(s.std(ddof=1))
    se = sd / np.sqrt(n)
    half = n // 2
    signal_nv = V_CAL * NOMINAL_K[r] * 1e9
    results[r] = {
        "blocks": n,
        "mean_s_nv": mean,
        "se_nv": float(se),
        "block_sd_nv": sd,
        "first_half_nv": float(s[:half].mean()),
        "second_half_nv": float(s[half:].mean()),
        "signal_at_29v_nv": signal_nv,
        "mean_as_ppm_of_signal": mean / signal_nv * 1e6,
        "se_as_ppm_of_signal": se / signal_nv * 1e6,
    }
alls = blocks["s_nv"].to_numpy()
pooled = {"blocks": len(alls), "mean_s_nv": float(alls.mean()), "se_nv": float(alls.std(ddof=1) / np.sqrt(len(alls)))}

# Offsets: the injecting level (N+I)/2 per range vs the ISOLATE dwell. With IN shorted these differ
# only by an offset that is constant in polarity, which ABBA removes from S regardless.
zero = per_dwell.filter(pl.col("pattern") == "Z")
level = {
    "isolate_mean_nv": float(zero["v"].mean() * 1e9),
    "inject_mean_nv": {r: float(per_dwell.filter((pl.col("div") == r) & (pl.col("pattern") != "Z"))["v"].mean() * 1e9) for r in results},
    "meter_zero_span_nv": [float(per_dwell["v"].min() * 1e9), float(per_dwell["v"].max() * 1e9)],
}


def oadev(x: np.ndarray, m: int) -> float:
    c = np.cumsum(np.r_[0.0, x])
    means = (c[m:] - c[:-m]) / m
    d = means[m:] - means[:-m]
    return float(np.sqrt(0.5 * np.mean(d**2)))


adev = {}
for r in results:
    s = blocks.filter(pl.col("div") == r)["s_nv"].to_numpy()
    adev[r] = [{"blocks": m, "adev_nv": oadev(s, m)} for m in (1, 2, 4, 8, 16) if 2 * m < len(s) // 2]

summary = {
    "run": run.name,
    "setup": "copper link across NORMAL IN, supply unplugged; HP 3478A on OUT, 30 mV range, 5.5 digits, autozero on, 1 Hz",
    "schedule": "per 13-min cycle: ABBA (N,I,I,N) 60 s dwells on 1E-5, 1E-6, 1E-7, then one ISOLATE dwell",
    "start_utc": str(dwells["start"][0]),
    "duration_h": float((samples["timestamp_utc"].max() - samples["timestamp_utc"].min()).total_seconds() / 3600),
    "samples": samples.height,
    "failed": 0,
    "settle_s_dropped": SETTLE_S,
    "tmp275_span_c": [float(dwells["temp_c"].min()), float(dwells["temp_c"].max())],
    "per_range": results,
    "pooled": pooled,
    "levels": level,
    "block_adev": adev,
    "settling_profile_nv": settle_profile.to_dicts(),
}
(out / "summary.json").write_text(json.dumps(summary, indent=2))

# -- figure -------------------------------------------------------------------------------------
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
COL = {"1E-5": "#1f6f5c", "1E-6": "#2f5d9a", "1E-7": "#b4532a"}
fig, axes = plt.subplots(3, 1, figsize=(10, 7.5), sharex=True, gridspec_kw={"hspace": 0.12})
t0 = dwells["start"][0]
for ax, r in zip(axes, results, strict=True):
    b = blocks.filter(pl.col("div") == r)
    hrs = ((b["start"] - t0).dt.total_seconds() / 3600).to_numpy()
    s = b["s_nv"].to_numpy()
    ax.plot(hrs, s, "o", ms=3, color=COL[r], alpha=0.6)
    run_mean = np.cumsum(s) / np.arange(1, len(s) + 1)
    ax.plot(hrs, run_mean, color="#1a1d21", lw=1.3)
    ax.axhline(0, color="#9aa1a8", lw=0.8)
    m, e = results[r]["mean_s_nv"], results[r]["se_nv"]
    ax.set_ylabel(f"{r}\nS (nV)")
    ax.set_title(f"{r}: {m:+.1f} ± {e:.1f} nV over {results[r]['blocks']} blocks", loc="left", fontsize=10)
axes[-1].set_xlabel(f"hours since {str(t0)[:16]} UTC")
fig.suptitle("Shorted input: ABBA block signal per range (dots) and running mean (line)", x=0.07, ha="left")
fig.savefig(out / "null_blocks.png", dpi=150, bbox_inches="tight")
plt.close(fig)

print(json.dumps({k: summary[k] for k in ("duration_h", "tmp275_span_c", "per_range", "pooled", "levels", "block_adev")}, indent=1))
print(settle_profile)

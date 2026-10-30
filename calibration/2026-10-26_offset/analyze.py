"""The 1E-6 offset test: is ladder 2's -0.75 nV on the 1E-6 range real?

    uv run --with numpy python analyze.py <data_root> <out_dir>

Reads <data_root>/2026-10-25_offset-1e6_001 and reduces it exactly as the second injection ladder
does, by importing ../2026-10-17_ladder/analyze.py: first 2 s of each dwell dropped, ABBA blocks S = (N1 + N2 - I1 -
I2)/4, blocks broken by a stop excluded, 1E-6 predicted as S_1E-5 * k_1E-6 / k_1E-5 with the stored
k0, error bars block scatter / sqrt(n). Writes <out_dir>/summary.json and blocks.csv.

Two things beyond the ladder's reduction:

* Residual by block position. Each cycle is 1E-6, 1E-6, null, 1E-6, 1E-6, 1E-5. In the ladder every
  1E-6 block followed a range or output change; here blocks 1 and 4 follow another 1E-6 block. A
  transient left by switching would show as a difference between the two kinds.
* The combination with the ladder's six 1E-6 residuals, read from its summary.json.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).resolve().parent
LADDER = HERE.parent / "2026-10-17_ladder"
RUN = "2026-10-25_offset-1e6_001"
# What each 1E-6 block follows within the 6-block cycle.
AFTER = {0: "1E-5 (range change)", 1: "1E-6", 3: "null (output change)", 4: "1E-6"}

spec = importlib.util.spec_from_file_location("ladder", LADDER / "analyze.py")
ladder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ladder)  # type: ignore[union-attr]


def weighted(values: list[float], ses: list[float]) -> dict:
    w = 1 / np.array(ses) ** 2
    m = float(np.sum(w * values) / w.sum())
    return {
        "residual_nv": m,
        "se_nv": float(1 / np.sqrt(w.sum())),
        "chi2_about_mean": float(np.sum(w * (np.array(values) - m) ** 2)),
        "dof": len(values) - 1,
    }


def main() -> None:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    samples, dwells, tagged = ladder.load(root / RUN, None)
    b = ladder.blocks(tagged)
    meta = json.loads((root / RUN / "metadata.json").read_text())
    span = (samples["timestamp_utc"][-1] - samples["timestamp_utc"][0]).total_seconds()
    starts = dwells["start"].to_numpy()
    dwell_s = float(np.median(np.diff(starts).astype("timedelta64[us]").astype(float) / 1e6))
    t0 = b["start"].min()

    ref = ladder.stat(b.filter(pl.col("kind") == "1E-5")["S"].to_numpy())
    res: dict = {
        "run": RUN,
        "started_at_utc": meta["started_at_utc"],
        "ended_at_utc": meta["ended_at_utc"],
        "samples": samples.height,
        "failed": int(samples["value"].null_count()),
        "span_h": span / 3600,
        "readings_per_s": samples.height / span,
        "dwell_s_actual": dwell_s,
        "dwells_recorded": dwells.height,
        "tmp275_span_c": [float(dwells["temp_c"].min()), float(dwells["temp_c"].max())],
        "blocks_kept": b.height,
        "reference": ref
        | {
            "delivered_mv": ref["mean_nv"] * 1e-6 / ladder.K["1E-5"],
            "delivered_se_mv": ref["se_nv"] * 1e-6 / ladder.K["1E-5"],
        },
    }
    r6 = (
        b.filter(pl.col("kind") == "1E-5")
        .with_columns(((pl.col("start") - t0).dt.total_seconds() // 21600).alias("bin"))
        .group_by("bin")
        .agg(pl.col("S").mean())
        .sort("bin")
    )
    res["delivered_mv_by_6h"] = [round(float(v) * 1e-6 / ladder.K["1E-5"], 3) for v in r6["S"]]
    for kind in ("1E-6", "null"):
        x = b.filter(pl.col("kind") == kind)
        s = x["S"].to_numpy()
        res[kind] = (
            ladder.stat(s) | ladder.residual(ladder.stat(s), ref, kind) | ladder.checks(x, s, t0)
        )
    res["1E-6_minus_null_residual"] = {
        "nv": res["1E-6"]["residual_nv"] - res["null"]["mean_nv"],
        "se_nv": float(np.hypot(res["1E-6"]["residual_se_nv"], res["null"]["se_nv"])),
    }
    res["settle_check_nv"] = {
        f"{st:g}s": {
            k: float(ladder.blocks(tagged, st).filter(pl.col("kind") == k)["S"].mean())
            for k in ("1E-5", "1E-6", "null")
        }
        for st in (1.0, 2.0, 3.0, 5.0)
    }

    # Residual by position in the cycle.
    by_pos = {}
    for blk, after in AFTER.items():
        s = b.filter((pl.col("kind") == "1E-6") & (pl.col("blk") == blk))["S"].to_numpy()
        by_pos[str(blk)] = (
            {"after": after} | ladder.stat(s) | ladder.residual(ladder.stat(s), ref, "1E-6")
        )
    res["1E-6_by_position"] = by_pos
    sw = b.filter((pl.col("kind") == "1E-6") & pl.col("blk").is_in([0, 3]))["S"].to_numpy()
    rp = b.filter((pl.col("kind") == "1E-6") & pl.col("blk").is_in([1, 4]))["S"].to_numpy()
    d = sw.mean() - rp.mean()
    dse = float(np.hypot(sw.std(ddof=1) / np.sqrt(len(sw)), rp.std(ddof=1) / np.sqrt(len(rp))))
    res["1E-6_after_switch_minus_after_1E-6"] = {"nv": float(d), "se_nv": dse}

    # Residual by 6-hour bin, each bin against its own reference.
    bins = []
    for v in sorted(set(((b["start"] - t0).dt.total_seconds() // 21600).to_list())):
        x = b.filter(((pl.col("start") - t0).dt.total_seconds() // 21600) == v)
        s5, s6 = (
            x.filter(pl.col("kind") == "1E-5")["S"].to_numpy(),
            x.filter(pl.col("kind") == "1E-6")["S"].to_numpy(),
        )
        if len(s6) < 20:
            continue
        r = ladder.residual(ladder.stat(s6), ladder.stat(s5), "1E-6")
        bins.append(
            {
                "hours": float(v * 6),
                "residual_nv": r["residual_nv"],
                "residual_se_nv": r["residual_se_nv"],
            }
        )
    res["1E-6_residual_by_6h"] = bins

    # With ladder 2.
    lad = json.loads((LADDER / "summary.json").read_text(encoding="utf-8"))
    l6 = [x for x in lad["ladder"] if x["kind"] == "1E-6"]
    combined = {
        "ladder_2": lad["mean_residual_by_range"]["1E-6"],
        "this_run": {
            "residual_nv": res["1E-6"]["residual_nv"],
            "se_nv": res["1E-6"]["residual_se_nv"],
        },
        "ladder_2_points": [
            {
                "setpoint": x["setpoint"],
                "residual_nv": x["residual_nv"],
                "residual_se_nv": x["residual_se_nv"],
            }
            for x in l6
        ],
    }
    combined["all_seven"] = weighted(
        [x["residual_nv"] for x in l6] + [res["1E-6"]["residual_nv"]],
        [x["residual_se_nv"] for x in l6] + [res["1E-6"]["residual_se_nv"]],
    )
    ten = next(x for x in l6 if x["setpoint"] == "10 mV")
    combined["10mV_ladder_minus_this_run"] = {
        "nv": ten["residual_nv"] - res["1E-6"]["residual_nv"],
        "se_nv": float(np.hypot(ten["residual_se_nv"], res["1E-6"]["residual_se_nv"])),
    }
    l2 = lad["mean_residual_by_range"]["1E-6"]
    combined["ladder_2_minus_this_run"] = {
        "nv": l2["residual_nv"] - res["1E-6"]["residual_nv"],
        "se_nv": float(np.hypot(l2["se_nv"], res["1E-6"]["residual_se_nv"])),
    }
    summary = {
        "k0_records_v2": ladder.K,
        "settle_s_dropped": ladder.SETTLE_S,
        "max_block_span_s": ladder.MAX_BLOCK_SPAN_S,
        "run": res,
        "combined_1E-6": combined,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    b.select(
        "cycle",
        "blk",
        "kind",
        pl.col("S").round(3).alias("S_nv"),
        pl.col("temp_c").round(4),
        pl.col("start").dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias("utc"),
    ).write_csv(out / "blocks.csv")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

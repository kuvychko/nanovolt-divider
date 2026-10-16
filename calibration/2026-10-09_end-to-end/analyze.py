"""End-to-end injection: the divider ladder at 1 V and 0.1 V, and the supply at 0 V (null c).

    uv run --with numpy --with matplotlib python analyze.py <e2e-1v> <e2e-100mv> <null-supply-zero> <out_dir>

Each <run> holds the raw logs: Parquet parts of the meter readings on OUT (timestamp_utc, value in
volts) and schedule.jsonl (the divider transitions, with the TMP275). Each dwell is reduced to its
mean after dropping the first SETTLE_S seconds, and each ABBA block to S = (N1 + N2 - I1 - I2) / 4.
Isolated blocks (patterns n, i, i, n) are the in-run null (a).

1E-5 is the in-run reference. Each smaller range is predicted as S_5 * k_i / k_5, with k from the
ratio run, so the supply's actual output and the meter's gain cancel. What is left is a test of the
ratios and of the 30 mV range's linearity down to the smallest signal. At the 0 V setpoint the same
reference measures what the supply actually delivers.
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
# k0 at T0 = 25.3 C from the ratio run (2026-10-05). Their own uncertainties (2.4 / 19 / 297 ppm)
# are negligible against the nV-level errors here.
K = {"1E-5": 9.98131e-6, "1E-6": 9.98234e-7, "1E-7": 9.9646e-8}
RANGES = ["1E-5", "1E-6", "1E-7"]
COL = {"1E-5": "#2a78d6", "1E-6": "#eb6834", "1E-7": "#1baf7a", "null": "#52514e"}


def load_blocks(run: Path, settle: float = SETTLE_S) -> tuple[pl.DataFrame, dict]:
    samples = pl.read_parquet(run / "part-*.parquet").sort("timestamp_utc")
    ok = samples.filter(pl.col("value").is_not_null()).select("timestamp_utc", "value")
    dwells = (
        pl.DataFrame([json.loads(x) for x in (run / "schedule.jsonl").read_text().splitlines() if '"dwell"' in x])
        .with_columns(pl.col("timestamp_utc").str.to_datetime(time_zone="UTC", time_unit="us").alias("start"))
        .select("start", "cycle", "index", "pattern", pl.col("range").alias("div"), "temp_c", "psu_volts")
        .sort("start")
    )
    tagged = ok.join_asof(dwells, left_on="timestamp_utc", right_on="start").with_columns(
        ((pl.col("timestamp_utc") - pl.col("start")).dt.total_seconds()).alias("t"),
        (pl.col("value") * 1e9).alias("nv"),
    )
    per_dwell = (
        tagged.filter(pl.col("t") >= settle)
        .group_by("cycle", "index", "pattern", "div")
        .agg(pl.col("nv").mean().alias("m"), pl.col("start").first())
        .with_columns((pl.col("index") // 4).alias("blk"), (pl.col("index") % 4).alias("pos"))
        .sort("cycle", "index")
    )
    blocks = (
        per_dwell.group_by("cycle", "blk")
        .agg(
            pl.col("div").first(),
            # Isolated if any of its dwells is n or i: never trust row order for this.
            pl.col("pattern").is_in(["n", "i"]).any().alias("isolated"),
            pl.col("m").sort_by("pos").alias("ms"),
            pl.col("start").min(),
        )
        .filter(pl.col("ms").list.len() == 4)
        .with_columns(
            (
                (pl.col("ms").list.get(0) + pl.col("ms").list.get(3) - pl.col("ms").list.get(1) - pl.col("ms").list.get(2))
                / 4
            ).alias("S"),
            pl.when(pl.col("isolated")).then(pl.lit("null")).otherwise(pl.col("div")).alias("kind"),
        )
        .drop("ms")
        .sort("cycle", "blk")
    )
    span = (samples["timestamp_utc"][-1] - samples["timestamp_utc"][0]).total_seconds()
    meta = {
        "run": run.name,
        "setpoint_v": float(dwells["psu_volts"][0]),
        "samples": len(samples),
        "failed": int(samples.filter(pl.col("value").is_null()).height),
        "duration_h": span / 3600,
        "readings_per_s": len(samples) / span,
        "tmp275_span_c": [float(dwells["temp_c"].min()), float(dwells["temp_c"].max())],
        "settle_s_dropped": settle,
    }
    return blocks, meta


def stat(x: np.ndarray) -> dict:
    return {"mean_nv": float(x.mean()), "se_nv": float(x.std(ddof=1) / np.sqrt(len(x))),
            "block_sd_nv": float(x.std(ddof=1)), "blocks": len(x)}


def ladder(blocks: pl.DataFrame) -> dict:
    """Recovered vs predicted per range, against the in-run 1E-5 reference."""
    out: dict = {}
    ref = stat(blocks.filter(pl.col("kind") == "1E-5")["S"].to_numpy())
    out["reference"] = ref | {"delivered_v": ref["mean_nv"] * 1e-9 / K["1E-5"],
                              "delivered_se_v": ref["se_nv"] * 1e-9 / K["1E-5"]}
    for r in RANGES[1:]:
        s = stat(blocks.filter(pl.col("kind") == r)["S"].to_numpy())
        ratio = K[r] / K["1E-5"]
        pred, pred_se = ref["mean_nv"] * ratio, ref["se_nv"] * ratio
        diff, diff_se = s["mean_nv"] - pred, float(np.hypot(s["se_nv"], pred_se))
        out[r] = s | {
            "predicted_nv": pred,
            "predicted_se_nv": pred_se,
            "residual_nv": diff,
            "residual_se_nv": diff_se,
            "residual_sigma": diff / diff_se,
            "residual_ppm": 1e6 * diff / pred if abs(pred) > 50 else None,
            "residual_ppm_se": 1e6 * diff_se / abs(pred) if abs(pred) > 50 else None,
        }
    out["null_a"] = stat(blocks.filter(pl.col("kind") == "null")["S"].to_numpy())
    return out


def main() -> None:
    runs = [Path(p) for p in sys.argv[1:4]]
    out = Path(sys.argv[4])
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)

    summary: dict = {"k_from_ratio_run": K, "phases": []}
    frames = []
    for run in runs:
        blocks, meta = load_blocks(run)
        phase = meta | ladder(blocks)
        # Settling choice: the target ranges' means for 1, 2 and 3 s dropped.
        phase["settle_check_nv"] = {
            f"{s:g}s": {r: float(load_blocks(run, s)[0].filter(pl.col("kind") == r)["S"].mean()) for r in RANGES[1:] + ["null"]}
            for s in (1.0, 3.0)
        }
        summary["phases"].append(phase)
        frames.append(blocks.select(pl.lit(run.name).alias("run"), "cycle", "kind", pl.col("S").round(3).alias("S_nv"),
                                    pl.col("start").dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias("utc")))
        print(f"\n{run.name}: setpoint {meta['setpoint_v']} V, {meta['samples']} samples, {meta['failed']} failed, "
              f"{meta['duration_h']:.2f} h, TMP275 {meta['tmp275_span_c']}")
        ref = phase["reference"]
        print(f"  1E-5 reference {ref['mean_nv']:.2f} ± {ref['se_nv']:.2f} nV -> delivered "
              f"{ref['delivered_v']*1e3:.4f} ± {ref['delivered_se_v']*1e3:.4f} mV")
        for r in RANGES[1:]:
            p = phase[r]
            ppm = f", {p['residual_ppm']:+.0f} ± {p['residual_ppm_se']:.0f} ppm" if p["residual_ppm"] is not None else ""
            print(f"  {r}: {p['mean_nv']:+.3f} ± {p['se_nv']:.3f} nV, predicted {p['predicted_nv']:+.3f}; "
                  f"residual {p['residual_nv']:+.3f} ± {p['residual_se_nv']:.3f} nV ({p['residual_sigma']:+.2f} sigma{ppm})")
        n = phase["null_a"]
        print(f"  null (a): {n['mean_nv']:+.3f} ± {n['se_nv']:.3f} nV, block sd {n['block_sd_nv']:.2f}")

    pl.concat(frames).write_csv(out / "data" / "blocks.csv")
    (out / "data" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    # -- figure: residual (recovered - predicted) in nV per phase and range ------------------------
    fig, ax = plt.subplots(figsize=(8, 4.2))
    labels, x = [], 0
    for phase in summary["phases"]:
        for r in RANGES[1:]:
            p = phase[r]
            ax.errorbar(x, p["residual_nv"], yerr=p["residual_se_nv"], fmt="o", ms=8, color=COL[r], capsize=4, lw=2)
            labels.append(f"{r}\n{phase['setpoint_v']:g} V\n({p['predicted_nv']:.3g} nV)")
            x += 1
        n = phase["null_a"]
        ax.errorbar(x, n["mean_nv"], yerr=n["se_nv"], fmt="s", ms=8, color=COL["null"], capsize=4, lw=2)
        labels.append(f"null (a)\n{phase['setpoint_v']:g} V\n(0)")
        x += 1.5
    ticks = [i for i in np.arange(0, x, 1.0)][: len(labels)]
    pos = []
    xi = 0.0
    for _ in summary["phases"]:
        pos += [xi, xi + 1, xi + 2]
        xi += 3.5
    ax.set_xticks(pos, labels, fontsize=8)
    ax.axhline(0, color="#999", lw=1)
    ax.set_ylabel("recovered − predicted (nV)")
    ax.set_title("End-to-end: each range against the in-run 1E-5 reference (±1σ)", fontsize=10)
    ax.grid(axis="y", color="#e6e6e6", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    del ticks
    fig.tight_layout()
    fig.savefig(out / "figures" / "end_to_end_residuals.png", dpi=150)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()

"""Injection ladder: known signals from ~1 uV down to 0.72 nV through the nanovolt divider.

    uv run --with numpy --with polars --with tzdata python analyze.py <data_root> <out_dir>

Reads seven runs under <data_root> (the five ladder segments, the 10 mV repeat and the 2026-10-11
detection run for the 15 mV rungs) and writes <out_dir>/summary.json, blocks.csv and
waveforms.json. make_figures.py draws the figures from those files alone.

Each run holds Parquet parts of the meter readings on OUT and schedule.jsonl, one line per dwell with
the time it actually started. Every sample is attributed to the dwell whose recorded start precedes
it; the first SETTLE_S seconds of each dwell are dropped; each ABBA block (N, I, I, N by K4
polarity) is reduced to S = (N1 + N2 - I1 - I2)/4. Isolated blocks (K4 switching, output open) are
the in-run hardware null.

Amplitudes are anchored inside each run: the 1E-5 range is the reference, and the 1E-6 and 1E-7
signals are predicted as S_1E-5 * k_i / k_1E-5 with the divider's stored k0. The null is predicted
as zero. Error bars are block scatter / sqrt(n).

A block is kept only if its four dwells are contiguous: a stop or a resume inside a block puts a gap
between its halves, and ABBA cancels linear drift only across equal, adjacent dwells.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl

SETTLE_S = 2.0
# The stored records (docs/calibration.md, "Stored records"), from the ratio run.
K = {"1E-5": 9.981310305817e-6, "1E-6": 9.982338738050e-7, "1E-7": 9.964552424139e-8}
# A block's four dwell starts span ~3 x 15.5 s. Anything longer has a stop or a resume inside it.
MAX_BLOCK_SPAN_S = 60.0
# Waveform grid inside a block, in seconds.
BIN_S = 0.5

# (setpoint label, run, last valid UTC instant or None)
RUNS = [
    ("1 V", "2026-10-17_inj2-1v_001", None),
    ("0.3 V", "2026-10-17_inj2-300mv_001", None),
    ("0.1 V", "2026-10-17_inj2-100mv_001", None),
    ("30 mV", "2026-10-17_inj2-30mv_001", None),
    ("15 mV", "2026-10-11_nv-detect-1nv_001", None),
    # The host lost power at 15:51 UTC on 10-19. After the restart the supply was driven to 29 V
    # under this run, so only the part before the outage is used.
    ("10 mV", "2026-10-17_inj2-10mv_001", datetime(2026, 10, 19, 15, 52, tzinfo=UTC)),
    ("10 mV", "2026-10-22_inj2-10mv_002", None),
]


def load(run: Path, until: datetime | None) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    samples = pl.read_parquet(run / "part-*.parquet").sort("timestamp_utc")
    dwells = (
        pl.DataFrame(
            [
                json.loads(x)
                for x in (run / "schedule.jsonl").read_text().splitlines()
                if '"dwell"' in x
            ]
        )
        .with_columns(
            pl.col("timestamp_utc").str.to_datetime(time_zone="UTC", time_unit="us").alias("start")
        )
        .select("start", "cycle", "index", "pattern", pl.col("range").alias("div"), "temp_c")
        .sort("start")
    )
    if until is not None:
        samples = samples.filter(pl.col("timestamp_utc") < until)
        dwells = dwells.filter(pl.col("start") < until)
    # A dwell interrupted by a stop and repeated on resume has two records; the later one owns it.
    dwells = dwells.unique(["cycle", "index"], keep="last").sort("start")
    ok = samples.filter(pl.col("value").is_not_null()).select("timestamp_utc", "value")
    tagged = ok.join_asof(dwells, left_on="timestamp_utc", right_on="start").with_columns(
        # total_seconds() truncates to whole seconds; the waveforms need the fraction.
        ((pl.col("timestamp_utc") - pl.col("start")).dt.total_microseconds() / 1e6).alias("t"),
        (pl.col("value") * 1e9).alias("nv"),
    )
    return samples, dwells, tagged


def blocks(tagged: pl.DataFrame, settle: float = SETTLE_S) -> pl.DataFrame:
    per_dwell = (
        tagged.filter(pl.col("t") >= settle)
        .group_by("cycle", "index", "pattern", "div")
        .agg(
            pl.col("nv").mean().alias("m"),
            pl.len().alias("n"),
            pl.col("start").first(),
            pl.col("temp_c").first(),
        )
        .with_columns((pl.col("index") // 4).alias("blk"), (pl.col("index") % 4).alias("pos"))
        .sort("cycle", "index")
    )
    full = per_dwell["n"].median()
    return (
        per_dwell.group_by("cycle", "blk")
        .agg(
            pl.col("div").first(),
            pl.col("pattern").is_in(["n", "i"]).any().alias("isolated"),
            pl.col("m").sort_by("pos").alias("ms"),
            pl.col("pos").sort().alias("poss"),
            pl.col("n").min().alias("n_min"),
            pl.col("start").min(),
            ((pl.col("start").max() - pl.col("start").min()).dt.total_microseconds() / 1e6).alias(
                "span_s"
            ),
            pl.col("temp_c").mean(),
        )
        .filter(
            (pl.col("poss").list.len() == 4)
            & (pl.col("span_s") <= MAX_BLOCK_SPAN_S)
            # A dwell cut short by a stop is complete in the schedule but short of samples.
            & (pl.col("n_min") >= 0.8 * full)
        )
        .with_columns(
            (
                (
                    pl.col("ms").list.get(0)
                    + pl.col("ms").list.get(3)
                    - pl.col("ms").list.get(1)
                    - pl.col("ms").list.get(2)
                )
                / 4
            ).alias("S"),
            pl.when(pl.col("isolated")).then(pl.lit("null")).otherwise(pl.col("div")).alias("kind"),
        )
        .drop("ms", "poss")
        .sort("cycle", "blk")
    )


def stat(x: np.ndarray) -> dict:
    return {
        "mean_nv": float(x.mean()),
        "se_nv": float(x.std(ddof=1) / np.sqrt(len(x))),
        "block_sd_nv": float(x.std(ddof=1)),
        "blocks": len(x),
    }


def checks(b: pl.DataFrame, s: np.ndarray, t0: datetime) -> dict:
    """Are the error bars honest? Lag-1 autocorrelation, 6-hour bins, halves, temperature."""
    hours = ((b["start"] - t0).dt.total_seconds() / 3600).to_numpy()
    mean = s.mean()
    bins = np.floor(hours / 6)
    bm, bse = [], []
    for v in np.unique(bins):
        x = s[bins == v]
        if len(x) >= 10:
            bm.append(x.mean())
            bse.append(x.std(ddof=1) / np.sqrt(len(x)))
    bm, bse = np.array(bm), np.array(bse)
    h = len(s) // 2
    T = b["temp_c"].to_numpy()
    A = np.vstack([np.ones_like(T), T - T.mean()]).T
    coef, rss, *_ = np.linalg.lstsq(A, s, rcond=None)
    slope_se = np.sqrt(rss[0] / (len(s) - 2)) / np.sqrt(np.sum((T - T.mean()) ** 2))
    return {
        "lag1_autocorrelation": float(np.corrcoef(s[:-1], s[1:])[0, 1]),
        "bins_6h_chi2": float(np.sum(((bm - mean) / bse) ** 2)),
        "bins_6h_dof": len(bm) - 1,
        "halves_nv": [float(s[:h].mean()), float(s[h:].mean())],
        "halves_se_nv": [
            float(s[:h].std(ddof=1) / np.sqrt(h)),
            float(s[h:].std(ddof=1) / np.sqrt(len(s) - h)),
        ],
        "temperature_slope_nv_per_c": float(coef[1]),
        "temperature_slope_se": float(slope_se),
    }


def waveform(tagged: pl.DataFrame, b: pl.DataFrame, kind: str, dwell_s: float) -> dict:
    """One block as measured, and every block of that kind averaged on a common time grid.

    Time within a block is the dwell's position times the median dwell length plus the time since
    the dwell's recorded start, so the switching dead time at each flip stays where it happened.
    Each block's own mean is removed first: the meter's offset wanders by far more than the signal.
    """
    keep = b.filter(pl.col("kind") == kind).select("cycle", "blk", "S")
    x = (
        tagged.with_columns((pl.col("index") // 4).alias("blk"), (pl.col("index") % 4).alias("pos"))
        .join(keep, on=["cycle", "blk"])
        .with_columns((pl.col("pos") * dwell_s + pl.col("t")).alias("tb"))
        .filter(pl.col("t") < dwell_s)
        .with_columns((pl.col("nv") - pl.col("nv").mean().over("cycle", "blk")).alias("dv"))
    )
    order = keep.sort("cycle", "blk")
    mid = order.row(len(order) // 2, named=True)
    one = x.filter((pl.col("cycle") == mid["cycle"]) & (pl.col("blk") == mid["blk"])).sort("tb")
    # Bins are cut inside each dwell. Cut on the block's time axis instead, the bin at each flip
    # mixes the end of one dwell with the start of the next and draws a ramp that is not there.
    grid = (
        x.with_columns((pl.col("t") // BIN_S).cast(pl.Int32).alias("tbin"))
        .group_by("pos", "tbin")
        .agg(
            pl.col("dv").mean().alias("m"),
            (pl.col("dv").std() / pl.len().sqrt()).alias("se"),
            pl.len().alias("n"),
        )
        # The last bin of a dwell catches only the odd late sample; too few to average.
        .filter(pl.col("n") >= 0.2 * pl.col("n").median())
        .sort("pos", "tbin")
    )
    return {
        "blocks": len(keep),
        "example": {
            "cycle": mid["cycle"],
            "blk": mid["blk"],
            "S_nv": round(mid["S"], 3),
            "t": [round(v, 3) for v in one["tb"]],
            "v_nv": [round(v, 2) for v in one["dv"]],
        },
        "grid_pos": grid["pos"].to_list(),
        "grid_dwell_t": [round((v + 0.5) * BIN_S, 3) for v in grid["tbin"]],
        "grid_t": [
            round(p * dwell_s + (v + 0.5) * BIN_S, 3)
            for p, v in zip(grid["pos"], grid["tbin"], strict=True)
        ],
        "mean_nv": [round(v, 3) for v in grid["m"]],
        "se_nv": [round(v, 3) for v in grid["se"]],
    }


def residual(meas: dict, ref: dict, kind: str) -> dict:
    ratio = K[kind] / K["1E-5"] if kind != "null" else 0.0
    pred, pred_se = ref["mean_nv"] * ratio, ref["se_nv"] * ratio
    se = float(np.hypot(meas["se_nv"], pred_se))
    return {
        "predicted_nv": pred,
        "predicted_se_nv": pred_se,
        "residual_nv": meas["mean_nv"] - pred,
        "residual_se_nv": se,
        "residual_sigma": (meas["mean_nv"] - pred) / se,
        "sigma_from_zero": meas["mean_nv"] / meas["se_nv"],
    }


def pool(parts: list[dict]) -> dict:
    """Inverse-variance mean of independent runs, each already measured against its own reference."""
    w = np.array([1 / p["residual_se_nv"] ** 2 for p in parts])
    out = {}
    for key in ("mean_nv", "predicted_nv", "residual_nv"):
        out[key] = float(np.sum(w * [p[key] for p in parts]) / w.sum())
    wm = np.array([1 / p["se_nv"] ** 2 for p in parts])
    out["se_nv"] = float(1 / np.sqrt(wm.sum()))
    out["residual_se_nv"] = float(1 / np.sqrt(w.sum()))
    out["residual_sigma"] = out["residual_nv"] / out["residual_se_nv"]
    out["sigma_from_zero"] = out["mean_nv"] / out["se_nv"]
    out["blocks"] = int(sum(p["blocks"] for p in parts))
    return out


def main() -> None:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {
        "k0_records_v2": K,
        "settle_s_dropped": SETTLE_S,
        "max_block_span_s": MAX_BLOCK_SPAN_S,
        "runs": [],
    }
    all_blocks, waves = [], {}
    by_setpoint: dict[str, list] = {}

    for label, name, until in RUNS:
        run = root / name
        samples, dwells, tagged = load(run, until)
        b = blocks(tagged)
        meta = json.loads((run / "metadata.json").read_text())
        span = (samples["timestamp_utc"][-1] - samples["timestamp_utc"][0]).total_seconds()
        starts = dwells["start"].to_numpy()
        dwell_s = float(np.median(np.diff(starts).astype("timedelta64[us]").astype(float) / 1e6))
        planned = int(dwells["cycle"].max() + 1) * int(dwells["index"].max() + 1)
        res: dict = {
            "setpoint": label,
            "run": name,
            "used_until_utc": until.isoformat() if until else None,
            "started_at_utc": meta["started_at_utc"],
            "ended_at_utc": meta["ended_at_utc"],
            "samples": samples.height,
            "failed": int(samples["value"].null_count()),
            "span_h": span / 3600,
            "readings_per_s": samples.height / span,
            "dwell_s_actual": dwell_s,
            "dwells_recorded": dwells.height,
            "dwells_planned_through_last_cycle": planned,
            "tmp275_span_c": [float(dwells["temp_c"].min()), float(dwells["temp_c"].max())],
            "blocks_kept": b.height,
        }
        ref = stat(b.filter(pl.col("kind") == "1E-5")["S"].to_numpy())
        res["reference"] = ref | {
            "delivered_mv": ref["mean_nv"] * 1e-6 / K["1E-5"],
            "delivered_se_mv": ref["se_nv"] * 1e-6 / K["1E-5"],
        }
        t0 = b["start"].min()
        r6 = (
            b.filter(pl.col("kind") == "1E-5")
            .with_columns(((pl.col("start") - t0).dt.total_seconds() // 21600).alias("bin"))
            .group_by("bin")
            .agg(pl.col("S").mean())
            .sort("bin")
        )
        res["delivered_mv_by_6h"] = [round(float(v) * 1e-6 / K["1E-5"], 3) for v in r6["S"]]
        for kind in ("1E-6", "1E-7", "null"):
            x = b.filter(pl.col("kind") == kind)
            s = x["S"].to_numpy()
            res[kind] = stat(s) | residual(stat(s), ref, kind) | checks(x, s, t0)
        res["settle_check_nv"] = {
            f"{st:g}s": {
                k: float(blocks(tagged, st).filter(pl.col("kind") == k)["S"].mean())
                for k in ("1E-5", "1E-6", "1E-7", "null")
            }
            for st in (1.0, 3.0)
        }
        summary["runs"].append(res)
        by_setpoint.setdefault(label, []).append(res)
        all_blocks.append(b.with_columns(pl.lit(name).alias("run")))
        print(
            f"{name} ({label}): {res['samples']} samples, {res['failed']} failed, {res['span_h']:.2f} h, "
            f"{res['dwells_recorded']}/{res['dwells_planned_through_last_cycle']} dwells, {b.height} blocks; "
            f"delivered {res['reference']['delivered_mv']:.3f} ± {res['reference']['delivered_se_mv']:.3f} mV; "
            f"dwell {dwell_s:.2f} s"
        )
        for kind in ("1E-6", "1E-7", "null"):
            r = res[kind]
            print(
                f"   {kind:5s} {r['mean_nv']:+9.3f} ± {r['se_nv']:.3f} nV (n {r['blocks']}, sd {r['block_sd_nv']:.1f}) "
                f"pred {r['predicted_nv']:8.3f}: {r['residual_nv']:+.2f} nV {r['residual_sigma']:+.2f}σ; "
                f"r1 {r['lag1_autocorrelation']:+.3f}; 6h χ² {r['bins_6h_chi2']:.1f}/{r['bins_6h_dof']}"
            )

        # Waveforms: one row per signal level, taken from the run that carries it.
        rows = {"1 V": ["1E-6", "1E-7"], "0.1 V": ["1E-7"], "30 mV": ["1E-7"], "15 mV": ["1E-7"]}
        if name == "2026-10-22_inj2-10mv_002":
            rows[label] = ["1E-7", "null"]
        for kind in rows.get(label, []):
            w = waveform(tagged, b, kind, dwell_s)
            w |= {
                "run": name,
                "setpoint": label,
                "kind": kind,
                "dwell_s": dwell_s,
                "signal_nv": res[kind]["predicted_nv"],
                "measured_nv": res[kind]["mean_nv"],
                "measured_se_nv": res[kind]["se_nv"],
            }
            waves[f"{label} {kind}"] = w

    # -- the ladder: every 1E-6 and 1E-7 signal against its in-run prediction ---------------------------
    ladder = []
    for label, parts in by_setpoint.items():
        for kind in ("1E-6", "1E-7", "null"):
            p = (
                pool([r[kind] for r in parts])
                if len(parts) > 1
                else {
                    k: parts[0][kind][k]
                    for k in (
                        "mean_nv",
                        "se_nv",
                        "predicted_nv",
                        "residual_nv",
                        "residual_se_nv",
                        "residual_sigma",
                        "sigma_from_zero",
                        "blocks",
                    )
                }
            )
            ladder.append({"setpoint": label, "kind": kind, "runs": [r["run"] for r in parts]} | p)
    summary["ladder"] = ladder
    sig = [x for x in ladder if x["kind"] != "null"]
    chi2 = float(sum(x["residual_sigma"] ** 2 for x in sig))
    summary["ladder_chi2"] = {"chi2": chi2, "dof": len(sig)}
    for kind in ("1E-6", "1E-7", "null"):
        xs = [x for x in ladder if x["kind"] == kind]
        w = np.array([1 / x["residual_se_nv"] ** 2 for x in xs])
        m = float(np.sum(w * [x["residual_nv"] for x in xs]) / w.sum())
        summary.setdefault("mean_residual_by_range", {})[kind] = {
            "residual_nv": m,
            "se_nv": float(1 / np.sqrt(w.sum())),
            "chi2_about_mean": float(
                np.sum(w * (np.array([x["residual_nv"] for x in xs]) - m) ** 2)
            ),
            "dof": len(xs) - 1,
        }
    print(f"\nladder χ² {chi2:.1f} / {len(sig)}")
    for x in ladder:
        print(
            f"  {x['setpoint']:6s} {x['kind']:5s} {x['mean_nv']:+9.3f} ± {x['se_nv']:.3f} nV, pred {x['predicted_nv']:8.3f}: "
            f"{x['residual_nv']:+.2f} ± {x['residual_se_nv']:.2f} nV ({x['residual_sigma']:+.2f}σ), "
            f"{x['sigma_from_zero']:.1f}σ from 0, n {x['blocks']}"
        )
    for kind, v in summary["mean_residual_by_range"].items():
        print(
            f"  mean residual {kind}: {v['residual_nv']:+.3f} ± {v['se_nv']:.3f} nV, χ² about it {v['chi2_about_mean']:.1f}/{v['dof']}"
        )

    # 10 mV target minus null, both runs pooled.
    tg = next(x for x in ladder if x["setpoint"] == "10 mV" and x["kind"] == "1E-7")
    nl = next(x for x in ladder if x["setpoint"] == "10 mV" and x["kind"] == "null")
    d, dse = tg["mean_nv"] - nl["mean_nv"], float(np.hypot(tg["se_nv"], nl["se_nv"]))
    summary["10mV_target_minus_null"] = {"nv": d, "se_nv": dse, "sigma": d / dse}
    print(f"  10 mV target - null {d:.3f} ± {dse:.3f} nV ({d / dse:.1f}σ)")

    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "waveforms.json").write_text(json.dumps(waves) + "\n", encoding="utf-8")
    pl.concat(all_blocks).select(
        "run",
        "cycle",
        "blk",
        "kind",
        pl.col("S").round(3).alias("S_nv"),
        pl.col("temp_c").round(4),
        pl.col("start").dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias("utc"),
    ).write_csv(out / "blocks.csv")
    print(f"\nwrote {out / 'data'}")


if __name__ == "__main__":
    main()

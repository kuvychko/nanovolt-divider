"""Detection limit: a ~1.3 nV signal through the nanovolt divider, with its pilot and noise basis.

    uv run --with numpy --with matplotlib python analyze.py \\
        <null-short> <pilot-az-on_001> <pilot-az-off_001> <pilot-az-on_002> <nv-detect-1nv> \\
        <end-to-end summary.json> <out_dir>

Each run directory holds the raw logs: Parquet parts of the meter readings on OUT (timestamp_utc,
value in volts) and schedule.jsonl (the divider transitions, with the TMP275). Each dwell is reduced
to its mean after dropping the first SETTLE_S seconds, each ABBA block to S = (N1 + N2 - I1 - I2)/4.
Isolated blocks (n, i, i, n: K4 switching, output open) are the in-run hardware null.

* Noise basis: the shorted-input null run (1 Hz, signal zero) cut into pseudo-ABBA blocks of any dwell
  length, as noise per unit time, sd(S) * sqrt(block seconds).
* Pilot: autozero on / off / on, 2 h each, the main run's schedule.
* Main run: 1E-5 is the in-run reference; 1E-6 and 1E-7 are predicted as S_5 * k_i / k_5 with k from
  the ratio run. The null is predicted as zero. Error bars are block scatter / sqrt(n), checked
  against lag-1 autocorrelation, 12-hour bins and split halves.
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
K = {"1E-5": 9.98131e-6, "1E-6": 9.98234e-7, "1E-7": 9.9646e-8}  # ratio run, T0 = 25.3 C
COL = {"1E-5": "#2a78d6", "1E-6": "#eb6834", "1E-7": "#1baf7a", "null": "#52514e"}


def load(run: Path) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    samples = pl.read_parquet(run / "part-*.parquet").sort("timestamp_utc")
    ok = samples.filter(pl.col("value").is_not_null()).select("timestamp_utc", "value")
    dwells = (
        pl.DataFrame([json.loads(x) for x in (run / "schedule.jsonl").read_text().splitlines() if '"dwell"' in x])
        .with_columns(pl.col("timestamp_utc").str.to_datetime(time_zone="UTC", time_unit="us").alias("start"))
        .select("start", "cycle", "index", "pattern", pl.col("range").alias("div"), "temp_c")
        .sort("start")
    )
    tagged = ok.join_asof(dwells, left_on="timestamp_utc", right_on="start").with_columns(
        ((pl.col("timestamp_utc") - pl.col("start")).dt.total_seconds()).alias("t"),
        (pl.col("value") * 1e9).alias("nv"),
    )
    return samples, dwells, tagged


def blocks(tagged: pl.DataFrame, settle: float = SETTLE_S) -> pl.DataFrame:
    per_dwell = (
        tagged.filter(pl.col("t") >= settle)
        .group_by("cycle", "index", "pattern", "div")
        .agg(pl.col("nv").mean().alias("m"), pl.col("start").first(), pl.col("temp_c").first())
        .with_columns((pl.col("index") // 4).alias("blk"), (pl.col("index") % 4).alias("pos"))
        .sort("cycle", "index")
    )
    return (
        per_dwell.group_by("cycle", "blk")
        .agg(
            pl.col("div").first(),
            pl.col("pattern").is_in(["n", "i"]).any().alias("isolated"),
            pl.col("m").sort_by("pos").alias("ms"),
            pl.col("start").min(),
            pl.col("temp_c").mean(),
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


def stat(x: np.ndarray) -> dict:
    return {"mean_nv": float(x.mean()), "se_nv": float(x.std(ddof=1) / np.sqrt(len(x))),
            "block_sd_nv": float(x.std(ddof=1)), "blocks": len(x)}


def run_meta(samples: pl.DataFrame, dwells: pl.DataFrame) -> dict:
    span = (samples["timestamp_utc"][-1] - samples["timestamp_utc"][0]).total_seconds()
    return {"samples": len(samples), "failed": int(samples["value"].null_count()), "duration_h": span / 3600,
            "readings_per_s": len(samples) / span,
            "tmp275_span_c": [float(dwells["temp_c"].min()), float(dwells["temp_c"].max())]}


# -- 1. noise basis: pseudo-ABBA on the shorted-input run ------------------------------------------
def dwell_scan(run: Path) -> list[dict]:
    _, _, tagged = load(run)
    v = tagged.filter(pl.col("t") >= SETTLE_S)["nv"].to_numpy()
    white = np.std(np.diff(v)) / np.sqrt(2)
    rows = []
    for n in [5, 10, 15, 20, 30, 45, 60, 90, 120]:
        m = len(v) // (4 * n)
        b = v[: m * 4 * n].reshape(m, 4, n).mean(axis=2)
        s = (b[:, 0] + b[:, 3] - b[:, 1] - b[:, 2]) / 4
        rows.append({"dwell_s": n, "blocks": int(m), "block_sd_nv": float(s.std(ddof=1)),
                     "white_nv": float(white / np.sqrt(n) / 2),
                     "noise_per_time": float(s.std(ddof=1) * np.sqrt(4 * n))})
    return rows


def main() -> None:
    null_short, on1, off, on2, main_run = (Path(p) for p in sys.argv[1:6])
    e2e = json.loads(Path(sys.argv[6]).read_text())
    out = Path(sys.argv[7])
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    summary: dict = {"k_from_ratio_run": K, "settle_s_dropped": SETTLE_S}

    scan = dwell_scan(null_short)
    summary["noise_basis_null_short"] = {"run": null_short.name, "sampling": "1 Hz, autozero on", "scan": scan}
    print("noise per unit time (nV*sqrt(s)) by pseudo-dwell: " + ", ".join(f"{r['dwell_s']} s {r['noise_per_time']:.0f}" for r in scan))

    # -- 2. pilot ----------------------------------------------------------------------------------
    pilot = []
    for run, az in ((on1, True), (off, False), (on2, True)):
        samples, dwells, tagged = load(run)
        b = blocks(tagged)
        within = tagged.filter(pl.col("t") >= SETTLE_S).group_by("cycle", "index").agg(pl.col("nv").std().alias("sd"))
        z = b.filter(pl.col("kind").is_in(["1E-7", "null"]))["S"].to_numpy()
        row = {"run": run.name, "autozero": az} | run_meta(samples, dwells) | {
            "within_dwell_sd_nv": float(within["sd"].median()),
            "block_sd_nv_1e7_and_null": float(z.std(ddof=1)),
            # A block is 4 x 15 s dwells of wall time, switching included.
            "noise_per_time": float(z.std(ddof=1) * np.sqrt(60.0)),
            "reference_nv": stat(b.filter(pl.col("kind") == "1E-5")["S"].to_numpy()),
        }
        pilot.append(row)
        print(f"pilot {run.name}: autozero {'on' if az else 'off'}, {row['readings_per_s']:.2f}/s, within-dwell sd "
              f"{row['within_dwell_sd_nv']:.0f} nV, block sd {row['block_sd_nv_1e7_and_null']:.1f} nV, "
              f"{row['noise_per_time']:.0f} nV*sqrt(s), {row['failed']} failed")
    summary["pilot"] = pilot

    # -- 3. main run -------------------------------------------------------------------------------
    samples, dwells, tagged = load(main_run)
    b = blocks(tagged)
    meta = run_meta(samples, dwells)
    print(f"\nmain {main_run.name}: {meta['samples']} samples, {meta['failed']} failed, {meta['duration_h']:.2f} h, "
          f"{meta['readings_per_s']:.3f}/s, TMP275 {meta['tmp275_span_c']}")
    res: dict = {"run": main_run.name} | meta
    ref = stat(b.filter(pl.col("kind") == "1E-5")["S"].to_numpy())
    res["reference"] = ref | {"delivered_mv": ref["mean_nv"] * 1e-6 / K["1E-5"],
                              "delivered_se_mv": ref["se_nv"] * 1e-6 / K["1E-5"]}
    t0 = b["start"].min()
    b = b.with_columns(((pl.col("start") - t0).dt.total_seconds() / 3600).alias("hours"))
    for kind in ["1E-6", "1E-7", "null"]:
        x = b.filter(pl.col("kind") == kind)
        s = x["S"].to_numpy()
        st = stat(s)
        ratio = K[kind] / K["1E-5"] if kind != "null" else 0.0
        pred, pred_se = ref["mean_nv"] * ratio, ref["se_nv"] * ratio
        diff_se = float(np.hypot(st["se_nv"], pred_se))
        bins = (x.with_columns((pl.col("hours") // 12).alias("bin")).group_by("bin")
                .agg(pl.col("S").mean().alias("m"), pl.col("S").std().alias("sd"), pl.len().alias("n")).sort("bin"))
        bm, bse = bins["m"].to_numpy(), (bins["sd"] / bins["n"].sqrt()).to_numpy()
        h = len(s) // 2
        T = x["temp_c"].to_numpy()
        A = np.vstack([np.ones_like(T), T - T.mean()]).T
        coef, rss, *_ = np.linalg.lstsq(A, s, rcond=None)
        slope_se = np.sqrt(rss[0] / (len(s) - 2)) / np.sqrt(np.sum((T - T.mean()) ** 2))
        res[kind] = st | {
            "predicted_nv": pred, "predicted_se_nv": pred_se,
            "residual_nv": st["mean_nv"] - pred, "residual_se_nv": diff_se,
            "residual_sigma": (st["mean_nv"] - pred) / diff_se,
            "sigma_from_zero": st["mean_nv"] / st["se_nv"],
            "lag1_autocorrelation": float(np.corrcoef(s[:-1], s[1:])[0, 1]),
            "bins_12h_nv": [round(float(v), 3) for v in bm],
            "bins_12h_chi2": float(np.sum(((bm - st["mean_nv"]) / bse) ** 2)), "bins_12h_dof": len(bm) - 1,
            "halves_nv": [float(s[:h].mean()), float(s[h:].mean())],
            "halves_se_nv": [float(s[:h].std(ddof=1) / np.sqrt(h)), float(s[h:].std(ddof=1) / np.sqrt(len(s) - h))],
            "temperature_slope_nv_per_c": float(coef[1]), "temperature_slope_se": float(slope_se),
        }
        r = res[kind]
        print(f"  {kind:5s} {r['mean_nv']:+.3f} ± {r['se_nv']:.3f} nV (sd {r['block_sd_nv']:.2f}, n {r['blocks']}), "
              f"predicted {pred:.3f}: residual {r['residual_sigma']:+.2f} sigma; {r['sigma_from_zero']:.1f} sigma from 0; "
              f"r1 {r['lag1_autocorrelation']:+.3f}; 12h chi2 {r['bins_12h_chi2']:.1f}/{r['bins_12h_dof']}; "
              f"T slope {r['temperature_slope_nv_per_c']:+.2f} ± {r['temperature_slope_se']:.2f} nV/C")
    tg, nl = res["1E-7"], res["null"]
    res["target_minus_null_nv"] = tg["mean_nv"] - nl["mean_nv"]
    res["target_minus_null_se_nv"] = float(np.hypot(tg["se_nv"], nl["se_nv"]))
    res["target_minus_null_sigma"] = res["target_minus_null_nv"] / res["target_minus_null_se_nv"]
    print(f"  target - null {res['target_minus_null_nv']:.3f} ± {res['target_minus_null_se_nv']:.3f} nV "
          f"({res['target_minus_null_sigma']:.1f} sigma)")
    by_day = b.filter(pl.col("kind") == "1E-5").with_columns((pl.col("hours") // 24).alias("day")).group_by("day").agg(pl.col("S").mean()).sort("day")
    res["reference_by_day_mv"] = [round(float(v) * 1e-6 / K["1E-5"], 3) for v in by_day["S"]]
    res["settle_check_nv"] = {
        f"{s:g}s": {k: float(blocks(tagged, s).filter(pl.col("kind") == k)["S"].mean()) for k in ["1E-5", "1E-6", "1E-7", "null"]}
        for s in (1.0, 3.0)
    }
    summary["main"] = res
    (out / "data" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    b.select("cycle", "blk", "kind", pl.col("S").round(3).alias("S_nv"), pl.col("temp_c").round(4),
             pl.col("start").dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias("utc")).write_csv(out / "data" / "blocks.csv")

    # -- figure 1: running means of target and null, converging on prediction and zero --------------
    fig, ax = plt.subplots(figsize=(9, 4.4))
    for kind, label in (("1E-7", "1E-7 target"), ("null", "hardware null")):
        x = b.filter(pl.col("kind") == kind)
        s, hrs = x["S"].to_numpy(), x["hours"].to_numpy()
        n = np.arange(1, len(s) + 1)
        run_mean = np.cumsum(s) / n
        band = res[kind]["block_sd_nv"] / np.sqrt(n)
        keep = n >= 40
        ax.fill_between(hrs[keep], (run_mean - band)[keep], (run_mean + band)[keep], color=COL[kind], alpha=0.18, lw=0)
        ax.plot(hrs[keep], run_mean[keep], color=COL[kind], lw=2, label=label)
        ax.annotate(f"{label}: {res[kind]['mean_nv']:+.2f} ± {res[kind]['se_nv']:.2f} nV",
                    (hrs[-1], run_mean[-1]), xytext=(-8, 14 if kind == "1E-7" else -18), textcoords="offset points",
                    ha="right", fontsize=9, color="#0b0b0b")
    ax.axhline(tg["predicted_nv"], color=COL["1E-7"], ls="--", lw=1)
    ax.text(25, tg["predicted_nv"] - 0.3, f"predicted {tg['predicted_nv']:.2f} nV (1E-5 reference × k₇/k₅)", fontsize=8, color="#52514e")
    ax.axhline(0, color="#999", lw=1)
    ax.set_xlabel("hours into the run")
    ax.set_ylabel("running mean of S (nV), ±1σ")
    ax.set_ylim(-2.5, 4)
    ax.set_title("1.3 nV through the divider: running mean of 2,880 target and 2,880 null blocks", fontsize=10)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    ax.grid(color="#e6e6e6", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "figures" / "detection_running_mean.png", dpi=150)

    # -- figure 2: the whole ladder, residual in nV against predicted signal ------------------------
    pts = []
    for ph in e2e["phases"]:
        if ph["setpoint_v"] <= 0:
            continue
        for r in ("1E-6", "1E-7"):
            pts.append((ph[r]["predicted_nv"], ph[r]["residual_nv"], ph[r]["residual_se_nv"], r, f"{ph['setpoint_v']:g} V"))
    for r in ("1E-6", "1E-7"):
        pts.append((res[r]["predicted_nv"], res[r]["residual_nv"], res[r]["residual_se_nv"], r, "15 mV setpoint"))
    fig, ax = plt.subplots(figsize=(8, 4.2))
    seen = set()
    for x, y, e, r, lab in pts:
        ax.errorbar(x, y, yerr=e, fmt="o", ms=8, color=COL[r], capsize=4, lw=2, label=None if r in seen else r)
        seen.add(r)
        # 1E-6 at the 15 mV setpoint and 1E-7 at 0.1 V sit at similar signals: label one below, one above.
        dy = -16 if (r == "1E-6" and "mV" in lab) else 8
        ax.annotate(lab, (x, y), xytext=(8, dy), textcoords="offset points", fontsize=8, color="#52514e")
    ax.legend(loc="lower right", frameon=False, fontsize=9, title="range", title_fontsize=8)
    ax.axhline(0, color="#999", lw=1)
    ax.set_xscale("log")
    ax.set_xlabel("predicted signal at OUT (nV)")
    ax.set_ylabel("recovered − predicted (nV), ±1σ")
    ax.set_title("Every injected signal, 1 µV down to 1.3 nV, against its in-run prediction", fontsize=10)
    ax.grid(color="#e6e6e6", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "figures" / "ladder_residuals.png", dpi=150)

    # -- figure 3: noise per unit time ---------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot([r["dwell_s"] for r in scan], [r["noise_per_time"] for r in scan], "o-", color=COL["1E-5"], lw=2, ms=7,
            label="shorted input, 1 Hz, autozero on (pseudo-ABBA)")
    for p, mk in zip(pilot, ("s", "D", "s")):
        ax.plot(15, p["noise_per_time"], mk, ms=9, color=COL["1E-6"] if p["autozero"] else COL["null"])
    ax.annotate("pilot, ~2.3/s, autozero on", (15, pilot[0]["noise_per_time"]), xytext=(10, -14), textcoords="offset points", fontsize=8)
    ax.annotate("pilot, ~4.4/s, autozero OFF", (15, pilot[1]["noise_per_time"]), xytext=(10, -4), textcoords="offset points", fontsize=8)
    ax.set_ylim(70, 4000)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("dwell length (s)")
    ax.set_ylabel("block noise × √(block time)  (nV·√s)")
    ax.set_title("Noise per unit time: shorter dwells and faster sampling win; autozero off loses", fontsize=10)
    ax.legend(loc="center right", frameon=False, fontsize=8)
    ax.grid(color="#e6e6e6", lw=0.8, which="both")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "figures" / "noise_per_time.png", dpi=150)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()

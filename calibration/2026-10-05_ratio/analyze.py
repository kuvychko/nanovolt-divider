"""Run R: the divider ratios at 29 V.

    uv run --with numpy --with matplotlib python analyze.py \
        <ratio_run> <anchor_before> <anchor_after> <high_legs_summary.json> <out_dir>

Inputs are raw run directories: Parquet parts of the 1 Hz meter readings (timestamp_utc, value) and
schedule.jsonl, the divider transitions ("dwell" events: cycle, index, pattern, range, temp_c).
divider.jsonl (TMP275 every 10 s) gives the temperature series.

Per range r and ABBA block b, S = (N1 + N2 - I1 - I2) / 4 from dwell means (first SETTLE_S seconds
dropped), and k = S / V_in.

V_in(t) for range r is pinned by the two input anchors, each read under range r's own load, and
carried between them by the supply's temperature model from the unloaded supply run:

    V_in,r(t) = V_r,before * [1 + gamma * (T_s(t) - T_s(before))] * [1 + delta * (t - t_before)]

T_s is the TMP275 through a first-order lag tau_s. delta is chosen so the model meets the after
anchor; the residual mismatch between the anchors is reported, not hidden.

k(T) is then fitted per range as k0 * [1 + alpha * (T_d - T0)], with T_d the TMP275 through the
divider's own first-order lag tau_d (scanned).
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
GAMMA = -14.0e-6  # supply tempco per degC, from the unloaded supply run
GAMMA_U = 2.0e-6
TAU_S_MIN = 45.0  # supply lag behind the TMP275; the supply run found ~20-70 min
TAU_S_RANGE = (20.0, 70.0)
NOMINAL = {"1E-5": 1 / 100_001, "1E-6": 1 / 1_000_001, "1E-7": 1 / 10_000_001}
RANGES = ("1E-5", "1E-6", "1E-7")

ratio_dir, before_dir, after_dir, legs_json, out = (Path(a) for a in sys.argv[1:6])
out.mkdir(parents=True, exist_ok=True)


def load(run: Path) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    s = (
        pl.read_parquet(run / "part-*.parquet")
        .filter(pl.col("value").is_not_null())
        .select("timestamp_utc", "value")
        .sort("timestamp_utc")
    )
    d = (
        pl.DataFrame([json.loads(x) for x in (run / "schedule.jsonl").read_text().splitlines() if '"dwell"' in x])
        .with_columns(pl.col("timestamp_utc").str.to_datetime(time_zone="UTC", time_unit="us").alias("start"))
        .select("start", "cycle", "index", "pattern", pl.col("range").alias("div"), "temp_c")
        .sort("start")
    )
    rows = [json.loads(x) for x in (run / "divider.jsonl").read_text().splitlines() if x.strip()]
    t = (
        pl.DataFrame([r for r in rows if r.get("event") == "poll" and r.get("temp_c") is not None])
        .select(
            pl.col("timestamp_utc").str.to_datetime(time_zone="UTC", time_unit="us"),
            pl.col("temp_c").cast(pl.Float64),
        )
        .sort("timestamp_utc")
    )
    return s, d, t


def dwell_means(s: pl.DataFrame, d: pl.DataFrame) -> pl.DataFrame:
    return (
        s.join_asof(d, left_on="timestamp_utc", right_on="start")
        .with_columns(((pl.col("timestamp_utc") - pl.col("start")).dt.total_seconds()).alias("t"))
        .filter(pl.col("t") >= SETTLE_S)
        .group_by("cycle", "index", "pattern", "div")
        .agg(
            pl.col("start").first(),
            pl.col("value").mean().alias("v"),
            pl.col("value").std().alias("sd"),
            pl.len().alias("n"),
            pl.col("temp_c").first(),
        )
        .sort("start")
    )


def blocks_of(dw: pl.DataFrame) -> pl.DataFrame:
    return (
        dw.with_columns((pl.col("index") // 4).alias("blk"))
        .group_by("cycle", "blk", maintain_order=True)
        .agg(
            pl.col("v"),
            pl.col("pattern").str.join("").alias("pat"),
            pl.col("div").first(),
            pl.col("start").first(),
            pl.col("start").last().alias("end"),
        )
        .filter(pl.col("v").list.len() == 4)
        .with_columns(
            ((pl.col("v").list.get(0) + pl.col("v").list.get(3) - pl.col("v").list.get(1) - pl.col("v").list.get(2)) / 4).alias(
                "S"
            ),
            # Mid-time of the block (start of dwell 0 plus two dwells).
            (pl.col("start") + (pl.col("end") - pl.col("start")) / 2 + pl.duration(seconds=30)).alias("mid"),
        )
    )


# -- temperature on a 10 s grid, and first-order lags ---------------------------------------------
def lagged(temps: pl.DataFrame, times: pl.Series, tau_min: float) -> np.ndarray:
    t0 = temps["timestamp_utc"][0]
    ts = (temps["timestamp_utc"] - t0).dt.total_seconds().to_numpy()
    T = temps["temp_c"].to_numpy()
    grid = np.arange(ts[0], ts[-1] + 10, 10.0)
    Tg = np.interp(grid, ts, T)
    if tau_min > 0:
        a = 1 - np.exp(-10.0 / (tau_min * 60))
        out_ = np.empty_like(Tg)
        out_[0] = Tg[0]
        for i in range(1, len(Tg)):
            out_[i] = out_[i - 1] + a * (Tg[i] - out_[i - 1])
        Tg = out_
    q = (times - t0).dt.total_seconds().to_numpy()
    return np.interp(q, grid, Tg)


# -- anchors: V_in per range under that range's load ----------------------------------------------
def anchor(run: Path) -> dict[str, object]:
    s, d, _ = load(run)
    dw = dwell_means(s, d)
    per = {}
    for r in RANGES:
        x = dw.filter((pl.col("div") == r) & pl.col("pattern").is_in(["N", "I"]))
        per[r] = float(x["v"].mean())
    iso = dw.filter(pl.col("pattern").is_in(["n", "i", "Z"]))
    return {
        "per_range_v": per,
        "unloaded_v": float(iso["v"].mean()),
        "time_utc": dw["start"].min() + (dw["start"].max() - dw["start"].min()) / 2,
        "temp_c": float(dw["temp_c"].mean()),
        "dwell_sd_v": float(dw["sd"].mean()),
    }


A0 = anchor(before_dir)
A1 = anchor(after_dir)

s, d, temps = load(ratio_dir)
dw = dwell_means(s, d)
blocks = blocks_of(dw)

# The anchors' TMP275 come from their own telemetry; join everything on one temperature record.
_, _, t_before = load(before_dir)
_, _, t_after = load(after_dir)
temps_all = pl.concat([t_before, temps, t_after]).sort("timestamp_utc").unique("timestamp_utc", keep="first")


def vin_model(times: pl.Series, r: str, gamma: float, tau_s: float) -> tuple[np.ndarray, float]:
    """V_in for range r at `times`, and the drift delta (per hour) that closes the anchors."""
    anchors_t = pl.Series([A0["time_utc"], A1["time_utc"]])
    Ts_anchor = lagged(temps_all, anchors_t, tau_s)
    Ts = lagged(temps_all, times, tau_s)
    v0, v1 = A0["per_range_v"][r], A1["per_range_v"][r]
    span_h = (A1["time_utc"] - A0["time_utc"]).total_seconds() / 3600
    # Model value at the after anchor without drift; delta closes the remaining gap.
    v1_model = v0 * (1 + gamma * (Ts_anchor[1] - Ts_anchor[0]))
    delta = (v1 / v1_model - 1) / span_h
    h = (times - A0["time_utc"]).dt.total_seconds().to_numpy() / 3600
    return v0 * (1 + gamma * (Ts - Ts_anchor[0])) * (1 + delta * h), delta


def fit_k(r: str, gamma: float = GAMMA, tau_s: float = TAU_S_MIN, mask=None) -> dict[str, object]:
    x = blocks.filter((pl.col("pat") == "NIIN") & (pl.col("div") == r))
    if mask is not None:
        x = x.filter(mask)
    vin, delta = vin_model(x["mid"], r, gamma, tau_s)
    k = x["S"].to_numpy() / vin
    best = None
    for tau_d in (0, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 150, 180, 240, 300):
        Td = lagged(temps_all, x["mid"], tau_d)
        T0 = round(float(Td.mean()), 1)
        X = np.column_stack([np.ones_like(Td), Td - T0])
        beta, *_ = np.linalg.lstsq(X, k, rcond=None)
        res = k - X @ beta
        sse = float(res @ res)
        if best is None or sse < best["sse"]:
            best = {"sse": sse, "tau_d_min": tau_d, "T0": T0, "k0": float(beta[0]), "slope": float(beta[1]), "res": res, "Td": Td}
    best["alpha_per_c"] = best["slope"] / best["k0"]
    best["k"] = k
    best["vin"] = vin
    best["delta_per_h"] = delta
    best["n"] = len(k)
    best["mid"] = x["mid"]
    return best


results = {}
for r in RANGES:
    base = fit_k(r)
    k = base["k"]
    # Statistical: jackknife over 6 h segments of the k0 and alpha estimates.
    hrs = ((base["mid"] - base["mid"][0]).dt.total_seconds() / 3600).to_numpy()
    seg = np.floor(hrs / 6).astype(int)
    k0s, als = [], []
    for g in np.unique(seg):
        keep = seg != g
        Td = base["Td"][keep]
        X = np.column_stack([np.ones(keep.sum()), Td - base["T0"]])
        b, *_ = np.linalg.lstsq(X, k[keep], rcond=None)
        k0s.append(b[0])
        als.append(b[1] / b[0])
    nj = len(k0s)
    jk = lambda v: float(np.sqrt((nj - 1) / nj * np.sum((np.array(v) - np.mean(v)) ** 2)))  # noqa: E731
    u_k0_stat_ppm = jk(k0s) / base["k0"] * 1e6
    u_alpha_stat = jk(als)
    # Supply model systematics: gamma +/- 2 ppm/C, and its lag across the observed range.
    vary = {}
    for name, kw in (
        ("gamma+", {"gamma": GAMMA + GAMMA_U}),
        ("gamma-", {"gamma": GAMMA - GAMMA_U}),
        ("tau_s_short", {"tau_s": TAU_S_RANGE[0]}),
        ("tau_s_long", {"tau_s": TAU_S_RANGE[1]}),
    ):
        v = fit_k(r, **kw)
        vary[name] = {
            "k0_ppm": (v["k0"] / base["k0"] - 1) * 1e6,
            "alpha_ppm_per_c": (v["alpha_per_c"] - base["alpha_per_c"]) * 1e6,
        }
    u_k0_gamma = max(abs(vary["gamma+"]["k0_ppm"]), abs(vary["gamma-"]["k0_ppm"]))
    u_al_gamma = max(abs(vary["gamma+"]["alpha_ppm_per_c"]), abs(vary["gamma-"]["alpha_ppm_per_c"]))
    u_k0_tau = max(abs(vary["tau_s_short"]["k0_ppm"]), abs(vary["tau_s_long"]["k0_ppm"]))
    u_al_tau = max(abs(vary["tau_s_short"]["alpha_ppm_per_c"]), abs(vary["tau_s_long"]["alpha_ppm_per_c"]))
    results[r] = {
        "blocks": base["n"],
        "k0": base["k0"],
        "T0_c": base["T0"],
        "k0_vs_nominal_ppm": (base["k0"] / NOMINAL[r] - 1) * 1e6,
        "alpha_ppm_per_c": base["alpha_per_c"] * 1e6,
        "tau_d_min": base["tau_d_min"],
        "resid_rms_ppm": float(np.std(base["res"]) / base["k0"] * 1e6),
        "u_k0_stat_ppm": u_k0_stat_ppm,
        "u_alpha_stat_ppm_per_c": u_alpha_stat * 1e6,
        "u_k0_supply_gamma_ppm": u_k0_gamma,
        "u_alpha_supply_gamma_ppm_per_c": u_al_gamma,
        "u_k0_supply_lag_ppm": u_k0_tau,
        "u_alpha_supply_lag_ppm_per_c": u_al_tau,
        "supply_drift_delta_ppm_per_h": base["delta_per_h"] * 1e6,
        "variations": vary,
    }
    results[r]["_k"] = base["k"]
    results[r]["_mid"] = base["mid"]
    results[r]["_Td"] = base["Td"]

# Range ratios, block by block in the same cycle: V_in cancels apart from its load difference.
ratios = {}
for a, b_ in (("1E-5", "1E-6"), ("1E-6", "1E-7")):
    xa = blocks.filter((pl.col("pat") == "NIIN") & (pl.col("div") == a)).select("cycle", pl.col("S").alias("sa"))
    xb = blocks.filter((pl.col("pat") == "NIIN") & (pl.col("div") == b_)).select("cycle", pl.col("S").alias("sb"))
    j = xa.join(xb, on="cycle")
    rr = (j["sa"] / j["sb"]).to_numpy()
    load = A0["per_range_v"][a] / A0["per_range_v"][b_]  # V_in differs by load between ranges
    rr = rr / load
    nom = NOMINAL[a] / NOMINAL[b_]
    ratios[f"k{a}/k{b_}"] = {
        "mean_vs_nominal_ppm": float((rr.mean() / nom - 1) * 1e6),
        "u_stat_ppm": float(rr.std(ddof=1) / np.sqrt(len(rr)) / nom * 1e6),
        "from_k0_vs_nominal_ppm": float(((results[a]["k0"] / results[b_]["k0"]) / nom - 1) * 1e6),
    }

# Null (a): the isolated ABBA block.
iso = blocks.filter(pl.col("pat") == "niin")["S"].to_numpy()
null_a = {"blocks": len(iso), "mean_nv": float(iso.mean() * 1e9), "se_nv": float(iso.std(ddof=1) / np.sqrt(len(iso)) * 1e9)}

# R_L consistency: R_L,i = k_i * R_total,i, at the ratio run's T0 (R_total measured at 25.5-26.3 C).
legs = json.loads(legs_json.read_text())
rl = {}
for r in RANGES:
    R_tot = legs["ranges"][r]["mean_ohm"]
    rl[r] = {"R_total_ohm": R_tot, "R_L_ohm": results[r]["k0"] * R_tot}

anchors = {
    name: {
        "time_utc": str(a["time_utc"]),
        "tmp275_c": a["temp_c"],
        "v_in_per_range_v": a["per_range_v"],
        "v_unloaded_v": a["unloaded_v"],
        "load_drop_ppm": {r: (a["per_range_v"][r] / a["unloaded_v"] - 1) * 1e6 for r in RANGES},
    }
    for name, a in (("before", A0), ("after", A1))
}

summary = {
    "run": ratio_dir.name,
    "setup": "UDP3305S-E CH1 at 29 V into NORMAL IN; HP 3478A on OUT, 30 mV range, 5.5 digits, autozero on, 1 Hz",
    "schedule": "per 16-min cycle: ABBA (N,I,I,N) 60 s dwells on 1E-5, 1E-6, 1E-7, then an isolated ABBA block (null a)",
    "samples": s.height,
    "duration_h": float((s["timestamp_utc"].max() - s["timestamp_utc"].min()).total_seconds() / 3600),
    "tmp275_span_c": [float(temps["temp_c"].min()), float(temps["temp_c"].max())],
    "supply_model": {"gamma_ppm_per_c": GAMMA * 1e6, "gamma_u_ppm_per_c": GAMMA_U * 1e6, "tau_s_min": TAU_S_MIN},
    "anchors": anchors,
    "per_range": {r: {k: v for k, v in res.items() if not k.startswith("_")} for r, res in results.items()},
    "range_ratios": ratios,
    "null_a": null_a,
    "r_l_consistency": rl,
}
(out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

rows = []
for r in RANGES:
    res = results[r]
    for t, k_, Td in zip(res["_mid"], res["_k"], res["_Td"], strict=True):
        rows.append({"utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "range": r, "k": k_, "tmp275_lagged_c": round(float(Td), 4)})
pl.DataFrame(rows).write_csv(out / "blocks_k.csv")
blocks.select(
    pl.col("mid").dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias("utc"),
    "cycle",
    pl.col("div").alias("range"),
    pl.col("pat").alias("pattern"),
    (pl.col("S") * 1e9).round(2).alias("s_nv"),
).write_csv(out / "blocks_s.csv")

# -- figures --------------------------------------------------------------------------------------
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
COL = {"1E-5": "#1f6f5c", "1E-6": "#2f5d9a", "1E-7": "#b4532a"}
fig, axes = plt.subplots(4, 1, figsize=(10, 10), sharex=True, gridspec_kw={"hspace": 0.15})
t0 = blocks["mid"][0]
for ax, r in zip(axes[:3], RANGES, strict=True):
    res = results[r]
    h = ((res["_mid"] - t0).dt.total_seconds() / 3600).to_numpy()
    ppm = (res["_k"] / NOMINAL[r] - 1) * 1e6
    ax.plot(h, ppm, "o", ms=2.5, color=COL[r], alpha=0.5)
    model = (res["k0"] * (1 + res["alpha_ppm_per_c"] * 1e-6 * (res["_Td"] - res["T0_c"])) / NOMINAL[r] - 1) * 1e6
    ax.plot(h, model, color="#1a1d21", lw=1.2)
    ax.set_ylabel(f"{r}\nk vs nominal (ppm)")
iso_b = blocks.filter(pl.col("pat") == "niin")
axes[3].plot(((iso_b["mid"] - t0).dt.total_seconds() / 3600).to_numpy(), iso_b["S"].to_numpy() * 1e9, "o", ms=2.5, color="#7a7f86")
axes[3].axhline(0, color="#9aa1a8", lw=0.8)
axes[3].set_ylabel("isolated block\nS (nV)")
axes[3].set_xlabel(f"hours since {str(t0)[:16]} UTC")
fig.suptitle("Run R: ratio per ABBA block (dots), fitted k(T) (line), and the isolated-block null", x=0.07, ha="left")
fig.savefig(out / "ratio_blocks.png", dpi=150, bbox_inches="tight")
plt.close(fig)

fig, axes = plt.subplots(1, 3, figsize=(12, 4))
for ax, r in zip(axes, RANGES, strict=True):
    res = results[r]
    ppm = (res["_k"] / res["k0"] - 1) * 1e6
    ax.plot(res["_Td"], ppm, "o", ms=2.5, color=COL[r], alpha=0.5)
    xs = np.linspace(res["_Td"].min(), res["_Td"].max(), 20)
    ax.plot(xs, res["alpha_ppm_per_c"] * (xs - res["T0_c"]), color="#1a1d21", lw=1.2)
    ax.set_title(f"{r}: α = {res['alpha_ppm_per_c']:+.1f} ppm/°C", loc="left", fontsize=10)
    ax.set_xlabel(f"TMP275, lag {res['tau_d_min']} min (°C)")
axes[0].set_ylabel("k / k0 − 1 (ppm)")
fig.tight_layout()
fig.savefig(out / "ratio_vs_temperature.png", dpi=150, bbox_inches="tight")
plt.close(fig)

print(json.dumps({k: summary[k] for k in ("anchors", "per_range", "range_ratios", "null_a", "r_l_consistency", "tmp275_span_c")}, indent=1, default=str))

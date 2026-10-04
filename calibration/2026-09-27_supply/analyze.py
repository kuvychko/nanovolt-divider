"""Run P' (supply tempco, unloaded): the full analysis.

From the published 1-minute data (this directory's minute.csv), which reproduces summary.json and
the figures:

    uv run --with numpy --with matplotlib --with polars --with tzdata python analyze.py --minute minute.csv <out_dir>

From the raw logs, which also writes minute.csv:

    uv run --with numpy --with matplotlib --with polars --with tzdata python analyze.py <run_dir> <out_dir>

<run_dir> holds the raw logs, which are not in this repository: Parquet parts of the 1 Hz meter
readings (columns timestamp_utc, value) and divider.jsonl, the divider telemetry (one JSON object
per line; "poll" events carry timestamp_utc and temp_c). Starting from minute.csv gives the same
fits; only "samples" differs, because the CSV counts just the samples inside the 1-minute means.

Self-contained on purpose (polars + numpy + matplotlib only), so the same script can travel with the
published result. Everything is done on 1-minute means of the 1 Hz meter readings, joined to 1-minute
means of the divider's TMP275 telemetry.

Model, fitted after the switch-on settling is dropped:

    y(t) = a + gamma * T_eff(t) + delta * t        y in ppm of 29 V, t in hours

with T_eff either the TMP275 delayed by L minutes (pure delay) or passed through a first-order lag of
time constant tau (exponential filter). Both are scanned; the better one is reported.

Uncertainty is not the fit's formal error, which assumes independent minutes. It comes from the
spread of independent pieces: per-day fits, and a jackknife over 6-hour segments.
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

V_NOM = 29.0
SETTLE_H = 30.0
LAGS_MIN = np.arange(0, 241, 1)

from_minute = sys.argv[1] == "--minute"
src = Path(sys.argv[2] if from_minute else sys.argv[1])
out = Path(sys.argv[-1])
out.mkdir(parents=True, exist_ok=True)

# -- load -----------------------------------------------------------------------------------------
if from_minute:
    # The published reduction: already on the 1-minute grid, TMP275 already interpolated.
    frame = pl.read_csv(src).select(
        pl.col("utc").str.to_datetime(time_zone="UTC", time_unit="us").alias("timestamp_utc"),
        pl.col("v_in_v").alias("v"),
        pl.col("v_sd_v").alias("v_sd"),
        pl.col("samples").alias("n"),
        pl.col("tmp275_c").alias("temp_c"),
    )
    run_name = "2026-09-27_psu-tempco_001"
    n_samples = int(frame["n"].sum())
else:
    samples = (
        pl.read_parquet(src / "part-*.parquet")
        .filter(pl.col("value").is_not_null())
        .select("timestamp_utc", "value")
        .sort("timestamp_utc")
    )
    rows = [json.loads(x) for x in (src / "divider.jsonl").read_text().splitlines() if x.strip()]
    temps = (
        pl.DataFrame([r for r in rows if r.get("event") == "poll"])
        .select(
            pl.col("timestamp_utc").str.to_datetime(time_zone="UTC", time_unit="us"),
            pl.col("temp_c").cast(pl.Float64),
        )
        .sort("timestamp_utc")
    )

    minute = (
        samples.group_by_dynamic("timestamp_utc", every="1m")
        .agg(pl.col("value").mean().alias("v"), pl.col("value").std().alias("v_sd"), pl.len().alias("n"))
        .filter(pl.col("n") >= 50)
    )
    tmin = temps.group_by_dynamic("timestamp_utc", every="1m").agg(pl.col("temp_c").mean())
    # A regular 1-minute grid, so lags are index shifts and gaps stay gaps.
    grid = pl.DataFrame(
        {
            "timestamp_utc": pl.datetime_range(
                minute["timestamp_utc"].min(),
                minute["timestamp_utc"].max(),
                interval="1m",
                time_zone="UTC",
                time_unit="us",
                eager=True,
            )
        }
    )
    frame = (
        grid.join(minute, on="timestamp_utc", how="left")
        .join(tmin, on="timestamp_utc", how="left")
        .with_columns(pl.col("temp_c").interpolate().fill_null(strategy="forward").fill_null(strategy="backward"))
    )
    run_name = src.name
    n_samples = samples.height
t0 = frame["timestamp_utc"][0]
h = ((frame["timestamp_utc"] - t0).dt.total_seconds() / 3600).to_numpy()
v = frame["v"].to_numpy()
y = (v / V_NOM - 1) * 1e6
T = frame["temp_c"].to_numpy()
have = ~np.isnan(y)


def delayed(lag: int) -> np.ndarray:
    if lag == 0:
        return T.copy()
    return np.r_[np.full(lag, np.nan), T[:-lag]]


def first_order(tau_min: float) -> np.ndarray:
    if tau_min <= 0:
        return T.copy()
    alpha = 1 - np.exp(-1.0 / tau_min)
    out_ = np.empty_like(T)
    out_[0] = T[0]
    for i in range(1, len(T)):
        out_[i] = out_[i - 1] + alpha * (T[i] - out_[i - 1])
    return out_


def fit(teff: np.ndarray, sel: np.ndarray):
    ok = sel & ~np.isnan(teff) & have
    X = np.column_stack([np.ones(ok.sum()), teff[ok] - 25.0, h[ok] - h[ok].mean()])
    beta, *_ = np.linalg.lstsq(X, y[ok], rcond=None)
    res = y[ok] - X @ beta
    return beta, res, ok


post = h >= SETTLE_H


def scan(sel: np.ndarray, kind: str):
    best = None
    curve = []
    for lag in LAGS_MIN:
        teff = delayed(int(lag)) if kind == "delay" else first_order(float(lag))
        beta, res, ok = fit(teff, sel)
        sse = float(res @ res) / ok.sum()
        curve.append((int(lag), float(np.sqrt(sse))))
        if best is None or sse < best[0]:
            best = (sse, int(lag), beta, res, ok)
    return best, curve


best_d, curve_d = scan(post, "delay")
best_f, curve_f = scan(post, "first_order")
kind, best, curve = (
    ("delay", best_d, curve_d) if best_d[0] <= best_f[0] else ("first_order", best_f, curve_f)
)
sse, lag, beta, res, ok = best
teff_best = delayed(lag) if kind == "delay" else first_order(lag)


def lag_interval(curve: list[tuple[int, float]]) -> tuple[int, int]:
    """Lags whose residual rms is within 1 % of the best: the flat bottom of the profile."""
    rms = np.array([c[1] for c in curve])
    lags = np.array([c[0] for c in curve])
    within = lags[rms <= rms.min() * 1.01]
    return int(within.min()), int(within.max())


# -- per-day fits (each full 24 h after settling), with the lag re-scanned per day ----------------
days = []
start = SETTLE_H
while start + 24 <= h.max() + 1e-9:
    sel = (h >= start) & (h < start + 24)
    b, c = scan(sel, kind)
    span = T[sel & have]
    days.append(
        {
            "start_h": start,
            "gamma_ppm_per_c": float(b[2][1]),
            "lag_min": b[1],
            "drift_ppm_per_h": float(b[2][2]),
            "resid_rms_ppm": float(np.sqrt(b[0])),
            "temp_span_c": [float(span.min()), float(span.max())],
        }
    )
    start += 24
g_days = np.array([d["gamma_ppm_per_c"] for d in days])
lag_days = np.array([d["lag_min"] for d in days])

# -- jackknife over 6 h segments at the best lag --------------------------------------------------
seg = np.floor((h - SETTLE_H) / 6).astype(int)
g_jk = []
for k in np.unique(seg[post]):
    b, _, _ = fit(teff_best, post & (seg != k))
    g_jk.append(b[1])
g_jk = np.array(g_jk)
n_jk = len(g_jk)
se_jk = float(np.sqrt((n_jk - 1) / n_jk * ((g_jk - g_jk.mean()) ** 2).sum()))

# -- warm-up scan: gamma from successively later starts ------------------------------------------
warmup = []
for s in (2, 6, 12, 18, 24, 30, 36, 48, 60):
    b, _, _ = fit(teff_best, h >= s)
    warmup.append({"skip_h": s, "gamma_ppm_per_c": float(b[1]), "drift_ppm_per_h": float(b[2])})

# -- residual Allan deviation (overlapping), tau0 = 1 min ----------------------------------------
resid = np.full_like(y, np.nan)
resid[ok] = res
r = resid[post]
r = r[~np.isnan(r)]  # minutes with data; the run's one gap is 33 s, inside a minute


def oadev(x: np.ndarray, m: int) -> float:
    c = np.cumsum(np.r_[0.0, x])
    means = (c[m:] - c[:-m]) / m
    d = means[m:] - means[:-m]
    return float(np.sqrt(0.5 * np.mean(d**2)))


adev = []
m = 1
while 2 * m < len(r) // 3:
    adev.append({"tau_min": m, "adev_ppm": oadev(r, m)})
    m *= 2

# -- settling ---------------------------------------------------------------------------------------
hourly = (
    frame.with_columns(pl.Series("h", h).floor().alias("hr"), pl.Series("ppm", y))
    .group_by("hr")
    .agg(pl.col("ppm").mean(), pl.col("temp_c").mean())
    .sort("hr")
)

summary = {
    "run": run_name,
    "quantity": "UDP3305S-E CH1 output at the divider's NORMAL IN, divider isolated (no load)",
    "setpoint_v": V_NOM,
    "meter": "HP 3478A, DC V, 30 V range, 5.5 digits, autozero on, 1 Hz",
    "temperature": "divider TMP275 (1/16 degC), polled every 10 s",
    "start_utc": str(frame["timestamp_utc"][0]),
    "end_utc": str(frame["timestamp_utc"][-1]),
    "duration_h": float(h.max()),
    "samples": n_samples,
    "samples_counted": "samples in the 1-minute means" if from_minute else "all readings",
    "failed_samples": 0,
    "gaps": ["33 s at 2026-09-27T23:23:07Z (service restart to extend the run)"],
    "tmp275_span_c": [float(np.nanmin(T)), float(np.nanmax(T))],
    "v_first_hour_v": float(np.nanmean(v[h < 1])),
    "settling": {
        "skip_h": SETTLE_H,
        "change_over_skip_ppm": float(np.nanmean(y[(h >= SETTLE_H - 1) & (h < SETTLE_H)]) - np.nanmean(y[h < 1])),
    },
    "model": f"y_ppm = a + gamma*(T_eff - 25 C) + delta*(t - t_mean); T_eff = TMP275 {kind}",
    "fit": {
        "lag_kind": kind,
        "lag_min": lag,
        "lag_min_flat_interval": lag_interval(curve),
        "gamma_ppm_per_c": float(beta[1]),
        "gamma_uv_per_c": float(beta[1]) * V_NOM,
        "gamma_se_jackknife_6h": se_jk,
        "drift_ppm_per_h": float(beta[2]),
        "intercept_ppm_at_25c": float(beta[0]),
        "v_at_25c_v": V_NOM * (1 + float(beta[0]) * 1e-6),
        "resid_rms_ppm": float(np.std(res)),
        "resid_rms_uv": float(np.std(res)) * V_NOM,
        "pure_delay_best": {"lag_min": best_d[1], "resid_rms_ppm": float(np.sqrt(best_d[0]))},
        "first_order_best": {"tau_min": best_f[1], "resid_rms_ppm": float(np.sqrt(best_f[0]))},
    },
    "per_day": days,
    "per_day_gamma_mean_sd": [float(g_days.mean()), float(g_days.std(ddof=1))] if len(days) > 1 else None,
    "per_day_lag_min": lag_days.tolist(),
    "warmup_scan": warmup,
    "residual_adev": adev,
}
(out / "summary.json").write_text(json.dumps(summary, indent=2))

if not from_minute:
    minute_out = frame.select(
        pl.col("timestamp_utc").dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias("utc"),
        pl.col("v").round(7).alias("v_in_v"),
        pl.col("v_sd").round(7).alias("v_sd_v"),
        pl.col("n").alias("samples"),
        pl.col("temp_c").round(4).alias("tmp275_c"),
    )
    minute_out.write_csv(out / "minute.csv")

# -- figures -------------------------------------------------------------------------------------
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
INK, ACC, WARM, MUTE = "#1a1d21", "#1f6f5c", "#b4532a", "#9aa1a8"

fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"hspace": 0.08})
a1.plot(h, y, color=ACC, lw=0.6)
a1.axvspan(0, SETTLE_H, color=MUTE, alpha=0.18, lw=0)
a1.text(SETTLE_H / 2, np.nanmax(y), "settling\n(excluded)", ha="center", va="top", color=INK, fontsize=9)
a1.set_ylabel("V_in − 29 V (ppm)")
a2.plot(h, T, color=WARM, lw=0.8)
a2.set_ylabel("TMP275 (°C)")
a2.set_xlabel("hours since start (2026-09-27 22:53 UTC)")
fig.suptitle("Supply at 29 V, unloaded: output and bench temperature", x=0.07, ha="left")
fig.savefig(out / "timeseries.png", dpi=150, bbox_inches="tight")
plt.close(fig)

fig, ax = plt.subplots(figsize=(6.5, 5))
detr = y[ok] - beta[2] * (h[ok] - h[ok].mean())
ax.scatter(teff_best[ok], detr, s=2, color=ACC, alpha=0.35, lw=0)
xs = np.linspace(np.nanmin(teff_best[ok]), np.nanmax(teff_best[ok]), 50)
ax.plot(xs, beta[0] + beta[1] * (xs - 25.0), color=INK, lw=1.4)
lag_label = f"delayed {lag} min" if kind == "delay" else f"first-order lag, τ = {lag} min"
ax.set_xlabel(f"TMP275, {lag_label} (°C)")
ax.set_ylabel("V_in − 29 V, drift removed (ppm)")
ax.set_title(f"γ = {beta[1]:.1f} ± {se_jk:.1f} ppm/°C  ({beta[1] * V_NOM:.0f} µV/°C)", loc="left")
fig.savefig(out / "tempco.png", dpi=150, bbox_inches="tight")
plt.close(fig)

fig, ax = plt.subplots(figsize=(6.5, 4.5))
taus = np.array([a["tau_min"] for a in adev])
ads = np.array([a["adev_ppm"] for a in adev])
ax.loglog(taus, ads, "o-", color=ACC, ms=4)
ax.set_xlabel("averaging time τ (min)")
ax.set_ylabel("Allan deviation of residual (ppm)")
ax.set_title("What remains after the temperature and drift model", loc="left")
fig.savefig(out / "residual_adev.png", dpi=150, bbox_inches="tight")
plt.close(fig)

print(json.dumps({k: summary[k] for k in ("duration_h", "tmp275_span_c", "settling", "fit")}, indent=1))
print("per-day:", json.dumps(days, indent=1))
print("warm-up:", json.dumps(warmup))
print("adev:", json.dumps(adev))

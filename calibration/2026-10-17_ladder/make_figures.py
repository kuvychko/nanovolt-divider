"""Figures for the injection ladder, drawn from summary.json and waveforms.json alone.

    uv run --with numpy --with matplotlib python make_figures.py

waveforms.png: per signal level, one ABBA block as measured beside every block at that level averaged.
recovery.png:  every injected signal against its in-run prediction, log-log, with residuals in nV.

The dwells are N, I, I, N by K4 polarity, so the signal swings +S, -S, -S, +S about the block mean
rather than stepping up from zero.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = OUT = HERE
summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))
waves = json.loads((DATA / "waveforms.json").read_text(encoding="utf-8"))

INK, INK2, INK3 = "#12171c", "#4b555e", "#8a939b"
GRID, BG, BAND = "#e4e8ec", "#ffffff", "#eef4fa"
BLUE, ORANGE = "#2a78d6", "#eb6834"
LSB = 100.0
ROLL_S = 5.0
SETTLE_S = summary["settle_s_dropped"]

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "text.color": INK,
        "axes.labelcolor": INK2,
        "xtick.color": INK3,
        "ytick.color": INK3,
        "axes.edgecolor": GRID,
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "savefig.facecolor": BG,
    }
)


def rolling(t: np.ndarray, v: np.ndarray, width: float, edges: np.ndarray) -> np.ndarray:
    """Centred mean over `width` seconds that never reaches across a polarity flip."""
    seg = np.searchsorted(edges, t, side="right")
    out = np.full(v.size, np.nan)
    for i in range(v.size):
        sel = (np.abs(t - t[i]) <= width / 2) & (seg == seg[i])
        out[i] = v[sel].mean()
    return out


def fmt_nv(x: float) -> str:
    return f"{x:.0f} nV" if x >= 9.5 else f"{x:.2f} nV" if x < 1 else f"{x:.1f} nV"


# ---------------------------------------------------------------- waveforms
order = [
    "1 V 1E-6",
    "1 V 1E-7",
    "0.1 V 1E-7",
    "30 mV 1E-7",
    "15 mV 1E-7",
    "10 mV 1E-7",
    "10 mV null",
]
show = [waves[k] for k in order]
rows = len(show)
fig, axes = plt.subplots(rows, 2, figsize=(11.5, 2.0 * rows + 1.6), dpi=200, sharex=True)
D = float(np.median([w["dwell_s"] for w in show]))
BLOCK = 4 * D
edges = np.array([D, 2 * D, 3 * D])
# One scale for every raw row, so the per-sample noise stays the same size down the page and the
# signal is seen shrinking into it.
RAW_HALF = 1450.0

for r, w in enumerate(show):
    sig = w["signal_nv"] if w["kind"] != "null" else 0.0
    t_grid = np.array(w["grid_t"])
    m = np.array(w["mean_nv"])
    se = np.array(w["se_nv"])
    # Room for the band, which near the bottom of the ladder is as large as the signal.
    ens_half = max(sig * 1.7, 3.6)
    for c in (0, 1):
        ax = axes[r][c]
        ax.axvspan(D, 3 * D, color=BAND, zorder=0, lw=0)
        if c == 0:
            t = np.array(w["example"]["t"])
            v = np.array(w["example"]["v_nv"])
            ax.plot(t, v, color=BLUE, lw=0.7, alpha=0.35, zorder=3)
            ax.plot(t, rolling(t, v, ROLL_S, edges), color=BLUE, lw=2.0, zorder=4)
            half = RAW_HALF
        else:
            # The first SETTLE_S of each dwell is not part of S; leave it out of the average too.
            settled = np.array(w["grid_dwell_t"]) >= SETTLE_S
            seg = np.array(w["grid_pos"])
            tg, mg, sg = t_grid[settled], m[settled], se[settled]
            smooth = rolling(tg, mg, ROLL_S, edges)
            for k in range(4):
                sel = seg[settled] == k
                ax.fill_between(
                    tg[sel], (mg - sg)[sel], (mg + sg)[sel], color=BLUE, alpha=0.13, lw=0, zorder=2
                )
                ax.plot(tg[sel], smooth[sel], color=BLUE, lw=2.2, zorder=4)
            half = ens_half
        for lo, hi, level in ((0, D, sig), (D, 3 * D, -sig), (3 * D, BLOCK, sig)):
            ax.hlines(level, lo, hi, color=ORANGE, lw=1.5, ls=(0, (4, 3)), zorder=5)
        ax.set_ylim(-half, half)
        ax.set_xlim(0, BLOCK)
        ax.grid(True, color=GRID, lw=0.7, zorder=1)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(labelsize=9)
        if c == 0:
            ax.set_yticks([-1000, 0, 1000])
        elif sig >= 2:
            ax.set_yticks([-sig, 0, sig])
            ax.set_yticklabels([f"{-sig:.3g}", "0", f"{sig:.3g}"])
        else:
            ax.set_yticks([-2, 0, 2])

    label = "null" if w["kind"] == "null" else fmt_nv(sig)
    sub = (
        "isolated, no signal"
        if w["kind"] == "null"
        else f"{sig / LSB:.3g} counts"
        if sig >= 10
        else f"1/{LSB / sig:.0f} count"
    )
    src = f"{w['setpoint']} setpoint" + (f", {w['kind']}" if w["kind"] != "null" else "")
    axes[r][0].text(
        -0.43,
        0.66,
        label,
        transform=axes[r][0].transAxes,
        fontsize=14,
        fontweight="bold",
        color=INK,
    )
    axes[r][0].text(-0.43, 0.40, sub, transform=axes[r][0].transAxes, fontsize=9.5, color=INK3)
    axes[r][0].text(-0.43, 0.18, src, transform=axes[r][0].transAxes, fontsize=8.5, color=INK3)
    meas = (
        f"{w['measured_nv']:+.2f} ± {w['measured_se_nv']:.2f} nV"
        if w["measured_nv"] < 10
        else f"{w['measured_nv']:.1f} ± {w['measured_se_nv']:.1f} nV"
    )
    axes[r][1].text(
        0.995,
        0.93,
        f"{w['blocks']:,} blocks · S = {meas}",
        transform=axes[r][1].transAxes,
        fontsize=8.5,
        color=INK2,
        ha="right",
        va="top",
    )

axes[0][0].set_title("One block, as measured", fontsize=12.5, color=INK, loc="left", pad=9)
axes[0][1].set_title(
    "Every block at that level, averaged", fontsize=12.5, color=INK, loc="left", pad=9
)
for c in (0, 1):
    axes[-1][c].set_xlabel("seconds within the ABBA block (N, I, I, N)", fontsize=10.5)
    axes[-1][c].set_xticks([0, 15, 30, 45, 60])

fig.text(
    0.038,
    0.985,
    "Down to a hundredth of a count",
    fontsize=19,
    fontweight="bold",
    color=INK,
    va="top",
)
fig.text(
    0.038,
    0.962,
    "HP 3478A on its 30 mV range, where one count is 100 nV, reading the nanovolt divider's output. "
    "The shaded middle is\nthe two inverted dwells; dashed orange is ±S, the signal predicted from the run's "
    "own 1E-5 reference. Each block's\nmean is removed. The left column shares one ±1450 nV scale; the right "
    f"is zoomed per row, with a {ROLL_S:.0f} s running mean and ±1σ band.\nThe average leaves out the first "
    f"{SETTLE_S:.0f} s of each dwell, which the analysis drops.",
    fontsize=10,
    color=INK2,
    va="top",
    linespacing=1.5,
)
fig.subplots_adjust(left=0.2, right=0.985, top=0.875, bottom=0.06, hspace=0.26, wspace=0.16)
fig.savefig(OUT / "waveforms.png")
plt.close(fig)
print(f"wrote {OUT / 'waveforms.png'}")


# ---------------------------------------------------------------- recovery ladder
ladder = summary["ladder"]
pts = [x for x in ladder if x["kind"] != "null"]
nulls = [x for x in ladder if x["kind"] == "null"]
w = np.array([1 / x["se_nv"] ** 2 for x in nulls])
null_mean = float(np.sum(w * [x["mean_nv"] for x in nulls]) / w.sum())
null_se = float(1 / np.sqrt(w.sum()))
chi2 = summary["ladder_chi2"]

fig, (ax, bx) = plt.subplots(2, 1, figsize=(8.4, 7.0), dpi=200, sharex=True, height_ratios=[2.4, 1])
lo, hi = 0.35, 2000.0
ax.plot([lo, hi], [lo, hi], color=INK3, lw=1.4, ls=(0, (5, 4)), zorder=2, label="perfect recovery")
ax.axvspan(lo, LSB, color=BAND, zorder=0, lw=0)
ax.text(0.46, 1300, "below one quantization count", fontsize=10, color=BLUE, va="top")
ax.text(
    0.46,
    640,
    f"null, all 6 setpoints pooled: {null_mean:+.2f} ± {null_se:.2f} nV",
    fontsize=10,
    color=INK,
    va="top",
    fontweight="bold",
)
for kind, col, mk in (("1E-6", BLUE, "o"), ("1E-7", ORANGE, "s")):
    xs = [x for x in pts if x["kind"] == kind]
    x = np.array([p["predicted_nv"] for p in xs])
    y = np.array([p["mean_nv"] for p in xs])
    e = np.array([p["se_nv"] for p in xs])
    r = np.array([p["residual_nv"] for p in xs])
    re = np.array([p["residual_se_nv"] for p in xs])
    ax.errorbar(
        x,
        y,
        yerr=e,
        fmt=mk,
        ms=7.5,
        color=col,
        ecolor=col,
        elinewidth=1.6,
        capsize=3.5,
        mew=0,
        zorder=4,
        label=f"{kind} range",
    )
    bx.errorbar(
        x,
        r,
        yerr=re,
        fmt=mk,
        ms=6.5,
        color=col,
        ecolor=col,
        elinewidth=1.6,
        capsize=3.5,
        mew=0,
        zorder=4,
    )
    # 1E-6 at one setpoint and 1E-7 at the next one up land at nearly the same signal, so the two
    # ranges are labelled on opposite sides of their points.
    dx, ha = (9, "left") if kind == "1E-6" else (-9, "right")
    for p in xs:
        ax.annotate(
            p["setpoint"],
            (p["predicted_nv"], p["mean_nv"]),
            xytext=(dx, -3 if kind == "1E-6" else 3),
            textcoords="offset points",
            fontsize=8,
            color=INK3,
            ha=ha,
            va="center",
        )
    # No sigma labels on the residuals: 1E-6 and 1E-7 points sit within a few percent of each other
    # in signal at 30 and 100 nV, and their labels overprint. The report's table carries them.
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlim(lo, hi)
ax.set_ylim(lo, hi)
ax.set_ylabel("recovered signal S (nV)", fontsize=11)
ax.legend(loc="lower right", fontsize=10, frameon=False)
# Residuals in nanovolts with their own bars, not in sigma: at 1 uV and at 0.7 nV the bars differ
# 5x, and a sigma axis would hide which points are actually tight.
bx.axhline(0, color=INK3, lw=1.3, ls=(0, (5, 4)), zorder=2)
bx.set_xscale("log")
bx.set_xlim(lo, hi)
bx.set_ylim(-4.8, 3.2)
bx.set_xlabel("signal predicted from the in-run 1E-5 reference (nV)", fontsize=11)
bx.set_ylabel("recovered − predicted (nV)", fontsize=11)
for a in (ax, bx):
    a.grid(True, color=GRID, lw=0.8, zorder=1)
    a.set_axisbelow(True)
    for side in ("top", "right"):
        a.spines[side].set_visible(False)
    a.tick_params(labelsize=10.5)
    a.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:g}"))
ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:g}"))

blocks = sum(r["blocks_kept"] for r in summary["runs"])
hours = sum(r["span_h"] for r in summary["runs"])
fig.text(
    0.06,
    0.968,
    "Recovering signals from 1 µV to 0.7 nV",
    fontsize=17,
    fontweight="bold",
    color=INK,
    va="top",
)
fig.text(
    0.06,
    0.925,
    f"{blocks:,} ABBA blocks over {hours:.0f} h at six supply setpoints. χ² = {chi2['chi2']:.1f} for "
    f"{chi2['dof']} signals.\nEach run is anchored on its own 1E-5 reference; the divider's stored k0 scales "
    "it to 1E-6 and 1E-7.",
    fontsize=10.5,
    color=INK2,
    va="top",
    linespacing=1.5,
)
fig.subplots_adjust(left=0.105, right=0.975, top=0.85, bottom=0.09, hspace=0.10)
fig.savefig(OUT / "recovery.png")
plt.close(fig)
print(f"wrote {OUT / 'recovery.png'}")

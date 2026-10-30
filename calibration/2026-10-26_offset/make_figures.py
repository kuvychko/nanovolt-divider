"""Figure for the 1E-6 offset test, drawn from summary.json alone.

    uv run --with numpy --with matplotlib python make_figures.py

residuals.png: top, every 1E-6 residual (measured minus predicted from the in-run 1E-5 reference):
the second ladder's six setpoints, this run whole and by block position, and all seven combined. Bottom,
this run's residual in 6-hour bins, each bin against its own reference.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = OUT = HERE
summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))
run, comb = summary["run"], summary["combined_1E-6"]

INK, INK2, INK3 = "#12171c", "#4b555e", "#8a939b"
GRID, BG = "#e4e8ec", "#ffffff"
BLUE, ORANGE = "#2a78d6", "#eb6834"

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

# (label, residual, se, colour, marker, bold)
rows = [
    (f"Ladder 2, {p['setpoint']}", p["residual_nv"], p["residual_se_nv"], BLUE, "o", False)
    for p in comb["ladder_2_points"]
]
rows.append(
    (
        "Ladder 2, all six",
        comb["ladder_2"]["residual_nv"],
        comb["ladder_2"]["se_nv"],
        BLUE,
        "D",
        True,
    )
)
rows.append(
    (
        "This run, all 1E-6 blocks",
        run["1E-6"]["residual_nv"],
        run["1E-6"]["residual_se_nv"],
        ORANGE,
        "D",
        True,
    )
)
for blk in ("0", "3", "1", "4"):
    p = run["1E-6_by_position"][blk]
    rows.append(
        (
            f"  block {blk}, after {p['after']}",
            p["residual_nv"],
            p["residual_se_nv"],
            ORANGE,
            "s",
            False,
        )
    )
rows.append(
    (
        "All seven combined",
        comb["all_seven"]["residual_nv"],
        comb["all_seven"]["se_nv"],
        INK,
        "D",
        True,
    )
)

fig, (ax, bx) = plt.subplots(2, 1, figsize=(9, 8.6), gridspec_kw={"height_ratios": [2.2, 1]})
y = np.arange(len(rows))[::-1].astype(float)
for yi, (_label, r, se, col, mk, bold) in zip(y, rows, strict=True):
    ax.errorbar(
        r, yi, xerr=se, fmt=mk, color=col, ms=8 if bold else 6, lw=2, capsize=0, mec=BG, mew=1.2
    )
    ax.text(3.3, yi, f"{r:+.2f} ± {se:.2f}", va="center", ha="right", fontsize=9, color=INK2)
ax.axvline(0, color=INK3, lw=1, zorder=0)
ax.set_yticks(y, [r[0] for r in rows], fontsize=9.5)
for t, r in zip(ax.get_yticklabels(), rows, strict=True):
    t.set_fontweight("bold" if r[5] else "normal")
ax.set_xlim(-3.6, 3.4)
ax.set_xlabel("1E-6 residual: measured − predicted (nV)")
ax.grid(axis="x", color=GRID, lw=0.8)
ax.set_axisbelow(True)
ax.tick_params(length=0)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.set_title(
    "The 1E-6 offset does not reproduce", loc="left", fontsize=13, fontweight="bold", pad=12
)

bins = run["1E-6_residual_by_6h"]
h = np.array([b["hours"] + 3 for b in bins])
r = np.array([b["residual_nv"] for b in bins])
se = np.array([b["residual_se_nv"] for b in bins])
bx.errorbar(h, r, yerr=se, fmt="o", color=ORANGE, ms=6, lw=2, capsize=0, mec=BG, mew=1.2)
bx.axhline(0, color=INK3, lw=1, zorder=0)
bx.axhline(run["1E-6"]["residual_nv"], color=ORANGE, lw=1, ls="--", zorder=0)
bx.set_xlabel("Hours into the run")
bx.set_ylabel("Residual (nV)")
bx.set_xlim(0, 78)
bx.grid(axis="y", color=GRID, lw=0.8)
bx.set_axisbelow(True)
bx.tick_params(length=0)
for s in ("top", "right"):
    bx.spines[s].set_visible(False)
bx.set_title(
    f"This run in 6-hour bins: χ² {run['1E-6']['bins_6h_chi2']:.1f} / {run['1E-6']['bins_6h_dof']} about its mean",
    loc="left",
    fontsize=10.5,
    color=INK2,
)
fig.tight_layout()
fig.savefig(OUT / "residuals.png", dpi=150)
print(f"wrote {OUT / 'residuals.png'}")

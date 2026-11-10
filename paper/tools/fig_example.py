"""Schematic of one ScopeCache entry (Fig. 2): cells grouped by month, department, and brand."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
plt.rcParams.update({"font.size": 7.5, "font.family": "serif", "pdf.fonttype": 42})
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fig, ax = plt.subplots(figsize=(3.4, 1.55))
depts, brands, quarters = ["$d_1$", "$d_2$", "$d_3$"], ["$b_1$", "$b_2$"], ["Q1", "Q2", "Q3"]
x0 = 0.9
for qi, q in enumerate(quarters):
    for bi, b in enumerate(brands):
        col = x0 + qi * 2.3 + bi * 1.05
        ax.text(col + 0.5, 3.25, b, ha="center", va="bottom")
        for di, d in enumerate(depts):
            y = 2 - di
            shade = "#9ecae1" if bi == 0 else "white"
            ax.add_patch(Rectangle((col, y), 1, 0.9, facecolor=shade, edgecolor="#444444", lw=0.6))
    ax.text(x0 + qi * 2.3 + 1.02, 3.65, q, ha="center", va="bottom", fontweight="bold")
for di, d in enumerate(depts):
    ax.text(x0 - 0.15, 2 - di + 0.45, d, ha="right", va="center")
# u1 outline: d1, d2 everywhere
ax.add_patch(Rectangle((x0 - 0.05, 0.95), 3 * 2.3 - 0.2, 2.0, fill=False, edgecolor="#e6550d", lw=1.2, ls="--"))
ax.text(x0 + 3 * 2.3 - 0.15, 1.95, "$u_1$", color="black", ha="left", va="center")
ax.text(x0 + 3 * 2.3 - 0.15, 0.45, "$u_3$", color="black", ha="left", va="center")
# u3 outline: (d1, b2) cells and the d3 row
for qi in range(3):
    ax.add_patch(Rectangle((x0 + qi * 2.3 + 1.05 - 0.04, 1.96), 1.08, 0.98, fill=False, edgecolor="#31a354", lw=1.1, ls=":"))
ax.add_patch(Rectangle((x0 - 0.08, -0.06), 3 * 2.3 - 0.14, 1.02, fill=False, edgecolor="#31a354", lw=1.1, ls=":"))
ax.set_xlim(0.2, 8.3); ax.set_ylim(-0.2, 4.2); ax.axis("off")
fig.tight_layout(pad=0.1)
fig.savefig(os.path.join(HERE, "fig_example.pdf")); fig.savefig(os.environ.get("PNG_OUT", os.devnull), dpi=200, format="png")

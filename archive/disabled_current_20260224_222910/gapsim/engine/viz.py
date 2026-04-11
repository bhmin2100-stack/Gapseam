from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

Point = Tuple[float, float]

def render_snapshot(
    pts: List[Point],
    out_png: Path,
    *,
    title: str = "",
) -> None:
    fig = plt.figure()
    ax = fig.add_subplot(111)

    if len(pts) >= 2:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, linewidth=1.5)

        # fill Si below boundary
        y_min = min(ys)
        y_pad = max((max(ys) - y_min) * 0.2, 50.0)
        floor_y = y_min - y_pad * 2
        ax.fill(xs + [xs[-1], xs[0]], ys + [floor_y, floor_y], alpha=0.2)

        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, linestyle=":", linewidth=0.7)

    if title:
        ax.set_title(title)

    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

from gapsim.domain.recipe import Recipe
from gapsim.io.recipe_io import load_recipe
from gapsim.engine.run_logger import create_run_dir, write_json, make_meta
from gapsim.engine.types import EngineState, RunContext
from gapsim.engine.viz import render_snapshot
from gapsim.engine.steps.conformal_growth import ConformalGrowthStep

_STEP_TABLE = {
    "conformal_growth": ConformalGrowthStep(),
}

class EngineRunner:
    def __init__(self, runs_root: Path | str = "runs") -> None:
        self.runs_root = Path(runs_root)

    def run(
        self,
        recipe_path: Path | str,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        snapshot_cb: Optional[Callable[[Path], None]] = None,
        message_cb: Optional[Callable[[str], None]] = None,
    ) -> Path:
        rp = Path(recipe_path)
        recipe: Recipe = load_recipe(rp)

        meta = recipe.meta or {}
        case_name = str(meta.get("case_name") or "case")
        snap_int = int(meta.get("snapshot_interval") or 10)
        snap_int = max(1, snap_int)

        run_dir = create_run_dir(self.runs_root, case_name)
        ctx = RunContext(run_dir=str(run_dir))

        def canceled() -> bool:
            return bool(cancel_check()) if cancel_check else False

        def emit_progress(k: int, total: int) -> None:
            if progress_cb is not None:
                progress_cb(k, total)

        def emit_snapshot(path: Path) -> None:
            if snapshot_cb is not None:
                snapshot_cb(path)

        def say(msg: str) -> None:
            if message_cb is not None:
                message_cb(msg)

        total_steps = 0
        for step_spec in recipe.steps:
            if not isinstance(step_spec, dict):
                continue
            step_id = str(step_spec.get("id") or "")
            params = step_spec.get("params", {}) or {}
            if _STEP_TABLE.get(step_id) is None:
                continue
            total_steps += max(1, int(params.get("cycles", 1)))
        total_steps = max(total_steps, 1)

        # dump recipe + meta
        (run_dir / "recipe.json").write_text(rp.read_text(encoding="utf-8"), encoding="utf-8")
        write_json(run_dir / "meta.json", make_meta("0.0.1-step", meta))
        write_json(run_dir / "events.json", [])

        # initial state from geometry
        state = EngineState(points=list(recipe.geometry.points))

        # metrics
        metrics_path = run_dir / "metrics.csv"
        with metrics_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["k", "step_id", "dt", "base_rate"])

            # snapshot 0
            snapshot0 = run_dir / "snapshot_000.png"
            render_snapshot(state.points, snapshot0, title="k=0")
            emit_snapshot(snapshot0)
            k = 0
            emit_progress(k, total_steps)

            # execute steps
            canceled_run = False
            for step_spec in recipe.steps:
                if canceled():
                    say("Canceled.")
                    canceled_run = True
                    break

                if not isinstance(step_spec, dict):
                    continue
                step_id = str(step_spec.get("id") or "")
                params = step_spec.get("params", {}) or {}
                step = _STEP_TABLE.get(step_id)
                if step is None:
                    continue

                cycles = int(params.get("cycles", 1))
                cycles = max(1, cycles)

                for i in range(cycles):
                    if canceled():
                        say("Canceled.")
                        canceled_run = True
                        break

                    state = step.apply(state, ctx, params)
                    k += 1

                    dt = float(params.get("dt", 1.0))
                    base_rate = float(params.get("base_rate", 1.0))
                    w.writerow([k, step_id, f"{dt:.6f}", f"{base_rate:.6f}"])

                    if (k % snap_int) == 0:
                        out_png = run_dir / f"snapshot_{k:03d}.png"
                        render_snapshot(state.points, out_png, title=f"k={k}")
                        emit_snapshot(out_png)
                    emit_progress(k, total_steps)

                if canceled_run:
                    break

            # final snapshot (if not already)
            final_snapshot = run_dir / f"snapshot_{k:03d}.png"
            if (not canceled_run) and (final_snapshot.exists() is False):
                render_snapshot(state.points, final_snapshot, title=f"k={k}")
                emit_snapshot(final_snapshot)

            if canceled_run:
                say("Run canceled.")
            else:
                emit_progress(total_steps, total_steps)
                say("Run complete.")

        return run_dir

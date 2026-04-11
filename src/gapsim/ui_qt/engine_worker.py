from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from gapsim.engine.runner import EngineRunner

class EngineWorker(QObject):
    progress = Signal(int, int)        # step, total
    detail = Signal(object)
    message = Signal(str)
    finished = Signal(str)             # run_dir
    error = Signal(str)

    def __init__(self, recipe_path: Path, runs_root: Path | str = "runs") -> None:
        super().__init__()
        self.recipe_path = Path(recipe_path)
        self.runs_root = Path(runs_root)
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def _canceled(self) -> bool:
        return self._cancel

    def _cleanup_recipe_path(self) -> None:
        # MainWindow writes transient recipes via mkstemp("gapsim_recipe_*.json")
        if not self.recipe_path.name.startswith("gapsim_recipe_"):
            return
        try:
            self.recipe_path.unlink(missing_ok=True)
        except Exception:
            pass

    @Slot()
    def run(self) -> None:
        try:
            runner = EngineRunner(self.runs_root)

            def progress_cb(step: int, total: int) -> None:
                self.progress.emit(step, total)

            def message_cb(s: str) -> None:
                self.message.emit(s)

            def detail_cb(payload: object) -> None:
                self.detail.emit(payload)

            run_dir = runner.run(
                self.recipe_path,
                cancel_check=self._canceled,
                progress_cb=progress_cb,
                message_cb=message_cb,
                detail_cb=detail_cb,
            )
            self.finished.emit(str(run_dir))
        except Exception as e:
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")
        finally:
            self._cleanup_recipe_path()

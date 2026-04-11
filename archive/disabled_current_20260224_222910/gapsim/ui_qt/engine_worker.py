from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from gapsim.engine.runner import EngineRunner


class EngineWorker(QObject):
    progress = Signal(int, int)        # k, total
    message = Signal(str)
    snapshot_saved = Signal(str)       # png path
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

    @Slot()
    def run(self) -> None:
        try:
            runner = EngineRunner(self.runs_root)

            def progress_cb(k: int, total: int) -> None:
                self.progress.emit(k, total)

            def snapshot_cb(p: Path) -> None:
                self.snapshot_saved.emit(str(p))

            def message_cb(msg: str) -> None:
                self.message.emit(msg)

            run_dir = runner.run(
                self.recipe_path,
                cancel_check=self._canceled,
                progress_cb=progress_cb,
                snapshot_cb=snapshot_cb,
                message_cb=message_cb,
            )

            self.finished.emit(str(run_dir))

        except Exception as e:
            tb = traceback.format_exc()
            self.error.emit(f"{e}\n\n{tb}")

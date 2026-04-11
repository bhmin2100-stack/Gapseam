from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QSplitter,
    QVBoxLayout,
    QLabel,
    QStackedWidget,
    QToolBar,
    QSpinBox,
    QPushButton,
    QHBoxLayout,
    QFrame,
    QFileDialog,
    QLineEdit,
    QDoubleSpinBox,
    QComboBox,
    QMessageBox,
)
from PySide6.QtGui import QAction, QKeySequence, QPixmap, QDesktopServices
from PySide6.QtCore import Qt, QThread, QUrl

from gapsim.ui_qt.views.structure_view import StructureView
from gapsim.ui_qt.controllers.structure_ctrl import StructureController
from gapsim.ui_qt.controllers.smoothing_ctrl import SmoothingController
from gapsim.ui_qt.models.points_table import PointsTableModel
from gapsim.ui_qt.models.points_table_view import PointsTableView

from gapsim.domain.recipe import Recipe, GeometrySpec, SmoothingSpec, SCHEMA_VERSION
from gapsim.domain.units import LengthUnit
from gapsim.io.recipe_io import save_recipe as save_recipe_file, load_recipe as load_recipe_file

from gapsim.ui_qt.engine_worker import EngineWorker

Point = Tuple[float, float]  # (x, y_user)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GapSim")
        self.resize(1280, 820)

        self._current_path: Optional[Path] = None

        # engine run state
        self._engine_thread: Optional[QThread] = None
        self._engine_worker: Optional[EngineWorker] = None
        self._last_run_dir: Optional[Path] = None

        # ---------------- Top bar ----------------
        tb = QToolBar("Top")
        self.addToolBar(tb)

        act_open = QAction("Open", self)
        act_save = QAction("Save", self)
        act_save_as = QAction("Save As", self)

        act_structure = QAction("Structure", self)
        act_smoothing = QAction("Smoothing", self)
        act_run = QAction("Run", self)
        act_results = QAction("Results", self)

        act_undo = QAction("Undo", self)
        act_undo.setShortcut(QKeySequence.Undo)  # Ctrl+Z

        tb.addAction(act_open)
        tb.addAction(act_save)
        tb.addAction(act_save_as)
        tb.addSeparator()
        tb.addAction(act_structure)
        tb.addAction(act_smoothing)
        tb.addAction(act_run)
        tb.addAction(act_results)
        tb.addSeparator()
        tb.addAction(act_undo)

        # ---------------- Main layout ----------------
        splitter = QSplitter(Qt.Horizontal)

        self.view = StructureView()
        splitter.addWidget(self.view)

        self.right_stack = QStackedWidget()
        splitter.addWidget(self.right_stack)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # =========================
        # Panel 1) Structure Define
        # =========================
        self.structure_panel = QWidget()
        sp = QVBoxLayout(self.structure_panel)
        sp.addWidget(QLabel("Structure Define (X/Y) — Ctrl+V paste / Ctrl+C copy / Del rows"))

        self.points_model = PointsTableModel()
        self.points_table = PointsTableView()
        self.points_table.setModel(self.points_model)
        sp.addWidget(self.points_table)

        # ==================
        # Panel 2) Smoothing
        # ==================
        self.smoothing_panel = QWidget()
        smp = QVBoxLayout(self.smoothing_panel)
        smp.addWidget(QLabel("Smoothing"))

        row = QHBoxLayout()
        row.addWidget(QLabel("Segments"))
        self.spin_segments = QSpinBox()
        self.spin_segments.setRange(1, 1_000_000)
        self.spin_segments.setValue(200)
        row.addWidget(self.spin_segments)

        row.addSpacing(12)

        row.addWidget(QLabel("Iterations"))
        self.spin_iters = QSpinBox()
        self.spin_iters.setRange(0, 1_000_000)
        self.spin_iters.setValue(5)
        row.addWidget(self.spin_iters)

        row.addSpacing(12)

        self.btn_run_smooth = QPushButton("Run")
        self.btn_revert = QPushButton("Revert")
        self.btn_save_params = QPushButton("Save Params")
        row.addWidget(self.btn_run_smooth)
        row.addWidget(self.btn_revert)
        row.addWidget(self.btn_save_params)

        row.addStretch(1)
        smp.addLayout(row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        smp.addWidget(line)

        smp.addWidget(QLabel("Smoothing Result (read-only; Ctrl+C copy)"))

        self.smooth_model = PointsTableModel()
        self.smooth_table = PointsTableView()
        self.smooth_table.setModel(self.smooth_model)
        self.smooth_table.setEditTriggers(PointsTableView.NoEditTriggers)
        smp.addWidget(self.smooth_table)

        # =================
        # Panel 3) Run (Engine)
        # =================
        self.run_panel = QWidget()
        rp = QVBoxLayout(self.run_panel)
        rp.addWidget(QLabel("Run (Engine) — Step-based runner (snapshots in runs/)"))

        # row: case name
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Case name"))
        self.edit_case = QLineEdit("case")
        r1.addWidget(self.edit_case)
        rp.addLayout(r1)

        # row: cycles/dt/snapshot interval
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Cycles"))
        self.spin_cycles = QSpinBox()
        self.spin_cycles.setRange(1, 10_000_000)
        self.spin_cycles.setValue(200)
        r2.addWidget(self.spin_cycles)

        r2.addSpacing(10)
        r2.addWidget(QLabel("dt"))
        self.spin_dt = QDoubleSpinBox()
        self.spin_dt.setDecimals(6)
        self.spin_dt.setRange(1e-9, 1e9)
        self.spin_dt.setValue(1.0)
        r2.addWidget(self.spin_dt)

        r2.addSpacing(10)
        r2.addWidget(QLabel("snapshot interval"))
        self.spin_snap_int = QSpinBox()
        self.spin_snap_int.setRange(1, 1_000_000)
        self.spin_snap_int.setValue(10)
        r2.addWidget(self.spin_snap_int)

        r2.addStretch(1)
        rp.addLayout(r2)

        # row: base_rate/epsilon
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("base_rate"))
        self.spin_base_rate = QDoubleSpinBox()
        self.spin_base_rate.setDecimals(6)
        self.spin_base_rate.setRange(0.0, 1e12)
        self.spin_base_rate.setValue(1.0)
        r3.addWidget(self.spin_base_rate)

        r3.addSpacing(10)
        r3.addWidget(QLabel("epsilon"))
        self.spin_epsilon = QDoubleSpinBox()
        self.spin_epsilon.setDecimals(6)
        self.spin_epsilon.setRange(0.0, 1e12)
        self.spin_epsilon.setValue(10.0)
        r3.addWidget(self.spin_epsilon)

        r3.addStretch(1)
        rp.addLayout(r3)

        # row: sealed mode
        r4 = QHBoxLayout()
        r4.addWidget(QLabel("Sealed mode"))
        self.combo_sealed = QComboBox()
        self.combo_sealed.addItem("A: flux=0", "A")
        self.combo_sealed.addItem("B: decay→0", "B")
        r4.addWidget(self.combo_sealed)

        r4.addSpacing(10)
        r4.addWidget(QLabel("decay_k"))
        self.spin_decay_k = QDoubleSpinBox()
        self.spin_decay_k.setDecimals(8)
        self.spin_decay_k.setRange(0.0, 1e9)
        self.spin_decay_k.setValue(0.01)
        self.spin_decay_k.setEnabled(False)
        r4.addWidget(self.spin_decay_k)

        r4.addStretch(1)
        rp.addLayout(r4)

        # run buttons
        r5 = QHBoxLayout()
        self.btn_engine_run = QPushButton("Run")
        self.btn_engine_stop = QPushButton("Stop")
        self.btn_engine_stop.setEnabled(False)
        r5.addWidget(self.btn_engine_run)
        r5.addWidget(self.btn_engine_stop)

        self.lbl_engine_status = QLabel("Idle")
        r5.addSpacing(10)
        r5.addWidget(self.lbl_engine_status)
        r5.addStretch(1)
        rp.addLayout(r5)

        # =====================
        # Panel 4) Results (minimal)
        # =====================
        self.results_panel = QWidget()
        res = QVBoxLayout(self.results_panel)
        res.addWidget(QLabel("Results (minimal)"))

        self.lbl_run_dir = QLabel("Run dir: -")
        self.btn_open_run_dir = QPushButton("Open Run Folder")
        self.btn_open_run_dir.setEnabled(False)

        rr0 = QHBoxLayout()
        rr0.addWidget(self.lbl_run_dir)
        rr0.addStretch(1)
        rr0.addWidget(self.btn_open_run_dir)
        res.addLayout(rr0)

        self.lbl_snapshot = QLabel("snapshot preview")
        self.lbl_snapshot.setAlignment(Qt.AlignCenter)
        self.lbl_snapshot.setMinimumHeight(320)
        self.lbl_snapshot.setStyleSheet("border: 1px solid #999;")
        res.addWidget(self.lbl_snapshot)

        # ---------------- add panels to stack ----------------
        self.right_stack.addWidget(self.structure_panel)  # index 0
        self.right_stack.addWidget(self.smoothing_panel)  # index 1
        self.right_stack.addWidget(self.run_panel)        # index 2
        self.right_stack.addWidget(self.results_panel)    # index 3

        # ---------------- Controllers ----------------
        self.structure_ctrl = StructureController(self.view, self.points_model)
        self.smoothing_ctrl = SmoothingController(self.view)

        # initial default points
        self.structure_ctrl.set_points([
            (200.0, 0.0),
            (100.0, 0.0),
            (50.0, -400.0),
            (-50.0, -400.0),
            (-100.0, 0.0),
            (-200.0, 0.0),
        ])

        # ---------------- Wiring ----------------
        act_structure.triggered.connect(self.on_structure)
        act_smoothing.triggered.connect(self.on_smoothing)
        act_run.triggered.connect(self.on_run_panel)
        act_results.triggered.connect(self.on_results_panel)
        act_undo.triggered.connect(self.structure_ctrl.undo)

        act_open.triggered.connect(self.on_open)
        act_save.triggered.connect(self.on_save)
        act_save_as.triggered.connect(self.on_save_as)

        self.btn_run_smooth.clicked.connect(self.on_smoothing_run)
        self.btn_revert.clicked.connect(self.on_smoothing_revert)
        self.btn_save_params.clicked.connect(self.on_smoothing_save_params)

        self.combo_sealed.currentIndexChanged.connect(self._on_sealed_changed)
        self.btn_engine_run.clicked.connect(self.on_engine_run)
        self.btn_engine_stop.clicked.connect(self.on_engine_stop)

        self.btn_open_run_dir.clicked.connect(self.on_open_run_dir)

        # start in structure
        self.right_stack.setCurrentWidget(self.structure_panel)
        self.view.set_point_radius_px(4)

        root2 = QWidget()
        layout2 = QVBoxLayout(root2)
        layout2.addWidget(splitter)
        self.setCentralWidget(root2)

        self.statusBar().showMessage("Ready", 2000)

    # ---------- smoothing input selection ----------
    def _active_profile_points(self) -> List[Point]:
        structure_pts = list(self.points_model.get_points())
        last = getattr(self.smoothing_ctrl.state, "last_result", None)
        base = getattr(self.smoothing_ctrl.state, "base_points", [])
        if last and len(last) >= 2 and base and list(base) == structure_pts:
            return list(last)
        return structure_pts

    # ---------- recipe (SSOT) ----------
    def _ui_to_domain_recipe(self) -> Recipe:
        structure_pts = list(self.points_model.get_points())

        steps = [
            {
                "id": "conformal_growth",
                "params": {
                    "cycles": int(self.spin_cycles.value()),
                    "dt": float(self.spin_dt.value()),
                    "base_rate": float(self.spin_base_rate.value()),
                    "epsilon": float(self.spin_epsilon.value()),
                    "sealed_mode": {
                        "option": str(self.combo_sealed.currentData()),
                        "decay_k": float(self.spin_decay_k.value()),
                    },
                },
            }
        ]

        meta = {
            "case_name": self.edit_case.text().strip() or "case",
            "snapshot_interval": int(self.spin_snap_int.value()),
            "smoothing_payload": self.smoothing_ctrl.get_saved_payload(),
        }

        return Recipe(
            schema_version=SCHEMA_VERSION,
            geometry=GeometrySpec(
                points=structure_pts,
                unit=LengthUnit.ANGSTROM,
                bottom_closed=True,
                top_open=True,
                side_walls_infinite=True,
            ),
            smoothing=SmoothingSpec(
                segment_n=int(self.spin_segments.value()),
                iterations=int(self.spin_iters.value()),
            ),
            steps=steps,
            addons=[],
            meta=meta,
        )

    def _apply_domain_recipe_to_ui(self, r: Recipe) -> None:
        pts = list(r.geometry.points)
        if len(pts) < 2:
            self.statusBar().showMessage("Open failed: geometry.points < 2", 5000)
            return

        # structure
        self.points_model.set_points(pts)
        self.view.set_points_xy(pts)

        # smoothing
        self.spin_segments.setValue(max(1, int(r.smoothing.segment_n or 1)))
        self.spin_iters.setValue(max(0, int(r.smoothing.iterations or 0)))
        self.smoothing_ctrl.set_base_points(pts)
        self.smoothing_ctrl.set_params(self.spin_segments.value(), self.spin_iters.value())
        self.smooth_model.set_points([])

        # meta
        meta = r.meta or {}
        self.edit_case.setText(str(meta.get("case_name") or "case"))
        if "snapshot_interval" in meta:
            self.spin_snap_int.setValue(max(1, int(meta.get("snapshot_interval"))))

        # steps[0]
        if r.steps and isinstance(r.steps[0], dict):
            s0 = r.steps[0]
            params = s0.get("params", {}) or {}

            if "cycles" in params:
                self.spin_cycles.setValue(max(1, int(params.get("cycles"))))
            if "dt" in params:
                self.spin_dt.setValue(float(params.get("dt")))
            if "base_rate" in params:
                self.spin_base_rate.setValue(float(params.get("base_rate")))
            if "epsilon" in params:
                self.spin_epsilon.setValue(float(params.get("epsilon")))

            sealed = params.get("sealed_mode", {}) if isinstance(params.get("sealed_mode", {}), dict) else {}
            opt = str(sealed.get("option", "A"))
            self.combo_sealed.setCurrentIndex(0 if opt == "A" else 1)
            if "decay_k" in sealed:
                self.spin_decay_k.setValue(float(sealed.get("decay_k")))

        self.on_structure()
        self.statusBar().showMessage("Loaded", 3000)

    # ---------- save/load ----------
    def on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GapSim Recipe", "", "GapSim Recipe (*.json);;All Files (*)"
        )
        if not path:
            return
        p = Path(path)
        try:
            r = load_recipe_file(p)
        except Exception as e:
            self.statusBar().showMessage(f"Open failed: {e}", 6000)
            return
        self._current_path = p
        self._apply_domain_recipe_to_ui(r)

    def on_save(self) -> None:
        if self._current_path is None:
            self.on_save_as()
            return
        r = self._ui_to_domain_recipe()
        try:
            save_recipe_file(self._current_path, r)
        except Exception as e:
            self.statusBar().showMessage(f"Save failed: {e}", 6000)
            return
        self.statusBar().showMessage(f"Saved: {self._current_path.name}", 3000)

    def on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save GapSim Recipe", "", "GapSim Recipe (*.json);;All Files (*)"
        )
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() != ".json":
            p = p.with_suffix(".json")
        self._current_path = p
        self.on_save()

    # ---------- panel switch ----------
    def on_structure(self) -> None:
        self.view.set_point_radius_px(4)
        base = self.points_model.get_points()
        self.view.set_points_xy(base)
        self.right_stack.setCurrentWidget(self.structure_panel)

    def on_smoothing(self) -> None:
        self.view.set_point_radius_px(1)
        base = self.points_model.get_points()
        self.smoothing_ctrl.set_base_points(base)
        self.view.set_points_xy(base)
        self.smoothing_ctrl.set_params(self.spin_segments.value(), self.spin_iters.value())
        self.smooth_model.set_points([])
        self.right_stack.setCurrentWidget(self.smoothing_panel)

    def on_run_panel(self) -> None:
        pts = self._active_profile_points()
        self.view.set_points_xy(pts)
        self.view.set_point_radius_px(1 if len(pts) > 200 else 4)
        self.right_stack.setCurrentWidget(self.run_panel)

    def on_results_panel(self) -> None:
        self.right_stack.setCurrentWidget(self.results_panel)

    # ---------- smoothing ops ----------
    def on_smoothing_run(self) -> None:
        self.smoothing_ctrl.set_params(self.spin_segments.value(), self.spin_iters.value())
        result = self.smoothing_ctrl.run()
        self.smooth_model.set_points(result)

    def on_smoothing_revert(self) -> None:
        self.smoothing_ctrl.revert()
        self.smooth_model.set_points([])

    def on_smoothing_save_params(self) -> None:
        self.smoothing_ctrl.set_params(self.spin_segments.value(), self.spin_iters.value())
        _ = self.smoothing_ctrl.get_saved_payload()
        self.statusBar().showMessage("Smoothing params captured (in-memory/meta)", 3000)

    # ---------- sealed UI ----------
    def _on_sealed_changed(self) -> None:
        opt = str(self.combo_sealed.currentData())
        self.spin_decay_k.setEnabled(opt == "B")

    # ---------- engine run ----------
    def _write_temp_recipe(self, r: Recipe) -> Path:
        import os
        fd, tmp_path = tempfile.mkstemp(prefix="gapsim_recipe_", suffix=".json")
        try:
            save_recipe_file(tmp_path, r)
        finally:
            try:
                os.close(fd)
            except Exception:
                pass
        return Path(tmp_path)

    def on_engine_run(self) -> None:
        if self._engine_thread is not None and self._engine_thread.isRunning():
            QMessageBox.warning(self, "Engine", "Engine already running.")
            return

        # build Recipe and save to temp json (runner reads recipe json)
        r = self._ui_to_domain_recipe()
        run_pts = self._active_profile_points()
        if len(run_pts) >= 2:
            r.geometry.points = list(run_pts)
        recipe_path = self._write_temp_recipe(r)

        self.lbl_engine_status.setText("Running...")
        self.btn_engine_run.setEnabled(False)
        self.btn_engine_stop.setEnabled(True)
        self._last_run_dir = None
        self.lbl_run_dir.setText("Run dir: -")
        self.btn_open_run_dir.setEnabled(False)

        th = QThread()
        worker = EngineWorker(recipe_path=recipe_path, runs_root="runs")
        worker.moveToThread(th)

        th.started.connect(worker.run)

        worker.progress.connect(self._on_engine_progress)
        worker.message.connect(self._on_engine_message)
        worker.snapshot_saved.connect(self._on_engine_snapshot_saved)
        worker.finished.connect(self._on_engine_finished)
        worker.error.connect(self._on_engine_error)

        # shutdown
        worker.finished.connect(th.quit)
        worker.error.connect(th.quit)

        th.finished.connect(worker.deleteLater)
        th.finished.connect(th.deleteLater)
        th.finished.connect(self._on_engine_thread_finished)

        self._engine_thread = th
        self._engine_worker = worker
        th.start()

    def on_engine_stop(self) -> None:
        if self._engine_worker is not None:
            self._engine_worker.request_cancel()
            self.lbl_engine_status.setText("Cancel requested...")

    def _on_engine_progress(self, k: int, total: int) -> None:
        self.lbl_engine_status.setText(f"Running... {k}/{total}")

    def _on_engine_message(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 3000)

    def _on_engine_snapshot_saved(self, png_path: str) -> None:
        snap = Path(png_path)
        if self._last_run_dir is None:
            self._last_run_dir = snap.parent
            self.lbl_run_dir.setText(f"Run dir: {self._last_run_dir}")
            self.btn_open_run_dir.setEnabled(True)
        if self._last_run_dir == snap.parent and self.right_stack.currentWidget() is self.results_panel:
            self._refresh_snapshot_preview(self._last_run_dir)

    def _on_engine_finished(self, run_dir_str: str) -> None:
        self.btn_engine_run.setEnabled(True)
        self.btn_engine_stop.setEnabled(False)
        self.lbl_engine_status.setText("Idle")

        if not run_dir_str:
            self.statusBar().showMessage("Engine finished (no run dir).", 4000)
            return

        run_dir = Path(run_dir_str)
        self._last_run_dir = run_dir

        self.lbl_run_dir.setText(f"Run dir: {run_dir}")
        self.btn_open_run_dir.setEnabled(True)

        self._refresh_snapshot_preview(run_dir)
        self.right_stack.setCurrentWidget(self.results_panel)
        self.statusBar().showMessage("Run complete.", 5000)

    def _on_engine_error(self, msg: str) -> None:
        self.btn_engine_run.setEnabled(True)
        self.btn_engine_stop.setEnabled(False)
        self.lbl_engine_status.setText("Idle")
        QMessageBox.critical(self, "Engine Error", msg)

    def _on_engine_thread_finished(self) -> None:
        self._engine_thread = None
        self._engine_worker = None

    # ---------- results ----------
    def _refresh_snapshot_preview(self, run_dir: Path) -> None:
        # pick snapshot_000.png if exists else last snapshot_*.png
        snap0 = run_dir / "snapshot_000.png"
        snap = snap0 if snap0.exists() else None

        if snap is None:
            snaps = sorted(run_dir.glob("snapshot_*.png"))
            if snaps:
                snap = snaps[-1]

        if snap is None or not snap.exists():
            self.lbl_snapshot.setText("snapshot not found")
            self.lbl_snapshot.setPixmap(QPixmap())
            return

        px = QPixmap(str(snap))
        if px.isNull():
            self.lbl_snapshot.setText("snapshot (failed to load)")
            self.lbl_snapshot.setPixmap(QPixmap())
            return

        self.lbl_snapshot.setPixmap(
            px.scaled(self.lbl_snapshot.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def on_open_run_dir(self) -> None:
        if self._last_run_dir and self._last_run_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_run_dir)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._last_run_dir:
            self._refresh_snapshot_preview(self._last_run_dir)

    def closeEvent(self, event):
        if self._engine_thread is not None and self._engine_thread.isRunning():
            try:
                if self._engine_worker is not None:
                    self._engine_worker.request_cancel()
                self._engine_thread.quit()
                self._engine_thread.wait(2000)
            except Exception:
                pass
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

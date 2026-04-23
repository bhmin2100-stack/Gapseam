from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMdiArea,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gapsim.ui_qt.main_window import MainWindow
from gapsim.ui_qt.ui_text import tr


class LauncherWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.lang = "ko"
        self._children: List[MainWindow] = []
        self._build_ui()

    def _tr(self, key: str) -> str:
        return tr(key, self.lang)

    def _build_ui(self) -> None:
        self.setWindowTitle(self._tr("app.title"))
        self.resize(1440, 900)

        root = QWidget()
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        title = QLabel(self._tr("app.title"))
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        hint = QLabel(self._tr("launcher.hint"))
        self.btn_new = QPushButton(self._tr("launcher.new"))
        self.btn_open = QPushButton(self._tr("launcher.open"))

        top.addWidget(title)
        top.addSpacing(12)
        top.addWidget(hint, 1)
        top.addWidget(self.btn_new)
        top.addWidget(self.btn_open)
        layout.addLayout(top)

        self.mdi = QMdiArea()
        self.mdi.setViewMode(QMdiArea.ViewMode.SubWindowView)
        self.mdi.setTabsClosable(True)
        self.mdi.setTabsMovable(True)
        self.mdi.setOption(QMdiArea.AreaOption.DontMaximizeSubWindowOnActivation, False)
        layout.addWidget(self.mdi, 1)

        self.setCentralWidget(root)

        self.btn_new.clicked.connect(self._new_project)
        self.btn_open.clicked.connect(self._open_project)

    def _open_in_mdi(
        self,
        *,
        stage: str,
        data: Optional[Dict] = None,
        source_path: Optional[Path] = None,
        run_dir: Optional[Path] = None,
        lang: Optional[str] = None,
    ) -> None:
        win = MainWindow(
            workflow_stage=stage,
            initial_data=data,
            source_path=source_path,
            initial_run_dir=run_dir,
            workflow_spawn=self._spawn_stage_window,
        )
        if lang is not None and lang != "ko":
            win._set_language(lang)
        elif self.lang != "ko":
            win._set_language(self.lang)

        sub = self.mdi.addSubWindow(win)
        sub.setWindowFlags(Qt.WindowType.SubWindow)
        win.show()
        sub.show()
        self._apply_default_subwindow_geometry(sub)
        self.mdi.setActiveSubWindow(sub)
        self._children.append(win)

    def _apply_default_subwindow_geometry(self, sub) -> None:
        rect = self.mdi.viewport().rect()
        vw = max(int(rect.width()), 800)
        vh = max(int(rect.height()), 600)
        w = max(760, int(vw * 0.5))
        h = max(620, int(vh * 0.88))
        w = min(w, max(760, vw - 20))
        h = min(h, max(620, vh - 20))
        offset = 22 * (len(self.mdi.subWindowList()) % 8)
        x = max(0, min(offset, max(0, vw - w - 8)))
        y = max(0, min(offset, max(0, vh - h - 8)))
        sub.resize(w, h)
        sub.move(x, y)

    def _spawn_stage_window(
        self,
        stage: str,
        initial_data: Optional[Dict],
        source_path: Optional[Path],
        initial_run_dir: Optional[Path],
        lang: str,
    ) -> None:
        self._open_in_mdi(
            stage=stage,
            data=initial_data,
            source_path=source_path,
            run_dir=initial_run_dir,
            lang=lang,
        )

    def _new_project(self) -> None:
        self._open_in_mdi(stage="structure", data=None, source_path=None, run_dir=None, lang=self.lang)

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("dialog.open.title"),
            "",
            self._tr("dialog.file_filter"),
        )
        if not path:
            return
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self._tr("dialog.open_error.title"), str(exc))
            return
        stage = MainWindow.project_open_stage_from_data(data, source_path=p)
        self._open_in_mdi(stage=stage, data=data, source_path=p, run_dir=None, lang=self.lang)

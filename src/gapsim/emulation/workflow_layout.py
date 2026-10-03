"""Organization of the process/run pane ONLY; outer workflow stays unchanged."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel, QMessageBox


def _advanced_rows(panel, page, grid, controls, title):
    body = QWidget()
    target = QGridLayout(body)
    target.setContentsMargins(0, 0, 0, 0)
    for target_row, control in enumerate(controls):
        index = grid.indexOf(control)
        row, col, _, _ = grid.getItemPosition(index)
        label_item = grid.itemAtPosition(row, col - 1)
        if label_item is not None:
            target.addWidget(label_item.widget(), target_row, 0)
        target.addWidget(control, target_row, 1)
    fold = panel.fold(title, body)
    panel.layouts[page].insertWidget(max(0, panel.layouts[page].count()-1), fold)
    return fold


def install_workflow_layout(w):
    p = w.process_parameter_panel
    # Common dose inputs are the SAME widgets on all four process pages.
    w.params_group.setTitle('공통 · 증착량 / Step')
    w.lbl_deposition_section.hide()
    p.layout().insertWidget(0, w.params_group)
    p.layout().insertWidget(1, p.dose_label)
    for i, text in enumerate([
        '균일 증착입니다. 위 공통 증착량을 사용합니다.',
        '상부·모서리·바닥 성장 경향을 조절합니다. 실제 공정 미보정 모델입니다.',
        '식각 → 재증착 순서로 설정합니다. 순수 식각은 공통 증착량을 0으로 설정하세요.',
        '증착을 억제합니다. 바닥 성장 보강은 별도 보조 효과입니다.',
    ]):
        note = p.layouts[i].itemAt(0).widget()
        if isinstance(note, QLabel):
            note.setText(text)
    for label in p.findChildren(QLabel):
        if label.text().startswith('새 CVD를 켜면 아래'):
            label.hide()
        if label.text().startswith('ⓘ'):
            label.setText('항목 설명: 마우스 올리기 또는 F1')
    for button in p.buttons:
        button.setText(button.text().lstrip('1234 '))

    # Shared presets and geometry stay INSIDE the process pane.
    w.process_presets_fold = p.fold('내 조건 · 불러오기 / 저장', w.parameter_preset_group)
    w.progress_panel_content.layout().insertWidget(0, w.process_presets_fold)
    p.geometry_group = p.geometry_button.parentWidget()
    p.geometry_group.setTitle('공유 기준 형상')
    w.process_geometry_fold = p.fold('기준 형상 · CVD / 억제 공통', p.geometry_group)
    w.progress_panel_content.layout().insertWidget(2, w.process_geometry_fold)
    p.geometry_group.layout().addWidget(p.geometry_label, 5, 0, 1, 2)
    w.process_notes_fold = p.fold('실행 메모', w.note_group)
    w.progress_panel_content.layout().insertWidget(3, w.process_notes_fold)

    p.advanced_folds = {}
    p.advanced_folds['cvd'] = _advanced_rows(p, 1, p.cvd_fields.layout(),
        [w.cvd_spins['cvd_upper_length_a'], w.cvd_spins['cvd_depth_power']], 'CVD 상세')
    p.advanced_folds['direct'] = _advanced_rows(p, 2, p.grids['direct'],
        [w.spin_sputter_peak_pct, w.spin_sputter_width, w.spin_sputter_smoothing], '식각 상세 · 각도 / 보정 / 평활화')
    p.advanced_folds['redepo'] = _advanced_rows(p, 2, p.grids['redepo'],
        [w.spin_redepo_emit_power, w.spin_redepo_distance_power], '재증착 상세 · 방향 분포')
    p.advanced_folds['inhibition'] = _advanced_rows(p, 3, p.grids['inhibition'],
        [w.spin_inhibition_decay_power, w.spin_inhibition_bottom_boost,
         w.spin_inhibition_recombination, w.spin_inhibition_smoothing], '억제 상세 · 보정 / 성장 보강')
    p.section_containers = {}
    for key, page, title in [('depth', 1, '기존 증착 감쇠 · 호환'), ('ion', 2, '기존 이온 감쇠 · 호환')]:
        fold = p.fold(title, p.sections[key])
        p.section_containers[key] = fold
        p.layouts[page].insertWidget(p.layouts[page].count()-1, fold)

    # Keep curves adjacent to their numeric settings rather than in a second list.
    for group, key in [(w.gaussian_group, 'direct'), (w.redepo_lobe_group, 'redepo'),
                       (w.inhibition_profile_group, 'inhibition')]:
        p.advanced_folds[key].layout().itemAt(0).widget().layout().addWidget(p.curve_folds[group])
    for group, key in [(w.ion_map_group, 'ion'), (w.depth_profile_group, 'depth')]:
        p.section_containers[key].layout().itemAt(0).widget().layout().addWidget(p.curve_folds[group])
    p.layouts[2].insertWidget(p.layouts[2].indexOf(p.sections['redepo'])+1, w.incident_model_group)
    p.advanced_folds['rays'] = _advanced_rows(p, 2, w.incident_model_group.layout(),
        [w.spin_incident_rays], '이온 계산 해상도')
    for label in w.incident_model_group.findChildren(QLabel):
        if label.text().startswith('ON:'):
            label.setText('이온 가림 ON이면 기존 이온 감쇠는 적용하지 않습니다.')
    p.etch_effective = QLabel()
    p.etch_effective.setWordWrap(True)
    p.grids['direct'].addWidget(p.etch_effective, p.grids['direct'].rowCount(), 0, 1, 2)
    w.spin_sputter_strength.valueChanged.connect(p.sync)
    w.spin_sputter_peak_pct.valueChanged.connect(p.sync)

    # Only Run/progress is pinned. Other actions remain in the process pane.
    w.process_execution_bar = QWidget()
    execution = QVBoxLayout(w.process_execution_bar)
    execution.setContentsMargins(0, 0, 0, 0)
    execution.addWidget(w.btn_run)
    execution.addWidget(w.progress_run)
    w.btn_run.setText('시뮬레이션 실행')
    w.btn_run.setMinimumHeight(36)
    w.right_panel.layout().addWidget(w.process_execution_bar)
    w.action_group.setTitle('비교 / 결과 / 초기화')
    w.btn_open_json.setText('결과 불러오기')
    w.btn_split_options.setText('조건 비교 (Split)')
    w.btn_compare_options.setText('모델 비교')
    w.split_group.setTitle('비교할 조건 범위')
    w.compare_group.setTitle('비교할 모델')
    w.process_actions_fold = p.fold('비교 · 결과 · 초기화', w.action_group)
    w.progress_panel_content.layout().insertWidget(4, w.process_actions_fold)
    w.btn_reset.setText('구조 · 공정 초기화')
    w.btn_reset.clicked.disconnect(w.reset_defaults)
    def confirm_reset():
        answer = QMessageBox.question(w, '구조 · 공정 초기화',
            '현재 구조와 공정 조건을 기본값으로 되돌리고 다시 계산할까요?\n저장하지 않은 편집은 사라집니다. 저장한 파일은 유지됩니다.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            w.reset_defaults()
    w.btn_reset.clicked.connect(confirm_reset)
    # Reparenting removes old items and shifts indexes. Set the final order only
    # after all moves so shared secondary tools never precede the process inputs.
    progress = w.progress_panel_content.layout()
    ordered = (w.process_presets_fold, p, w.process_geometry_fold,
               w.process_actions_fold, w.process_notes_fold)
    for widget in ordered:
        progress.removeWidget(widget)
    for index, widget in enumerate(ordered):
        progress.insertWidget(index, widget)
    w.workflow_layout_ready = True
    p.sync()
    sync_workflow_layout(w, w.workflow_tabs.currentIndex())


def sync_workflow_layout(w, index):
    if getattr(w, 'workflow_layout_ready', False):
        w.process_execution_bar.setVisible(index == 2)

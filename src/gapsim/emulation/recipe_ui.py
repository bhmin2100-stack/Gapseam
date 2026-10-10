"""Recipe inputs and visibility rules for the engineer-facing process pane.

Physical recipe duration is independent of the solver's spatial/time resolution.
Old calibrated coefficients remain available only for a calibrated recipe.
"""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel, QPushButton, QSpinBox, QWidget


RECIPE_WIDGETS = {
    "process_type": "cmb_process_type",
    "recipe_model": "cmb_recipe_model",
    "growth_basis": "cmb_growth_basis",
    "cvd_rate_a_per_s": "spin_cvd_rate",
    "cvd_duration_s": "spin_cvd_duration",
    "precursor_sticking": "spin_precursor_sticking",
    "ald_exposure": "spin_ald_exposure",
    "transport_ray_count": "spin_transport_rays",
    "numerical_step_a": "spin_numerical_step",
    "inhibitor_sticking": "spin_inhibitor_sticking",
    "inhibitor_exposure": "spin_inhibitor_exposure",
    "front_scheme": "cmb_front_scheme",
    "ion_growth_fraction": "spin_ion_growth_fraction",
    "redepo_max_distance_a": "spin_redepo_max_distance",
    "inhibition_process_model": "cmb_inhibition_process_model",
}


def init_recipe_controls(w):
    def combo(name, items):
        control = QComboBox()
        control.setObjectName(name)
        for text, value in items:
            control.addItem(text, value)
        setattr(w, name, control)
        return control

    def spin(name, value, low, high, suffix="", decimals=4):
        control = QDoubleSpinBox()
        control.setObjectName(name)
        control.setRange(low, high)
        control.setDecimals(decimals)
        control.setValue(value)
        control.setSuffix(suffix)
        setattr(w, name, control)
        return control

    combo("cmb_process_type", [("ALD", "ald"), ("CVD", "cvd")])
    combo("cmb_recipe_model", [("Conformal · 균일 증착", "ideal_conformal_v1"),
        ("수송·표면 반응", "physical_transport_v1"), ("기존 보정 모델", "legacy_calibrated_v1")])
    combo("cmb_growth_basis", [("기준면 순성장량", "net_planar"), ("식각 전 증착량", "gross")])
    combo("cmb_front_scheme", [("기존 계산", "legacy"), ("SFO3.1 동일 반복", "angular_godunov_v1")])
    combo("cmb_inhibition_process_model", [("ALD", "ald"), ("복합", "hybrid"), ("PEALD", "peald")])
    spin("spin_ion_growth_fraction", 0, 0, 1, "", 15)
    spin("spin_redepo_max_distance", 1800, 1, 1e7, " Å", 15)
    spin("spin_cvd_rate", 1.0, 0, 10000, " Å/s")
    spin("spin_cvd_duration", 100.0, 0, 1e7, " s", 3)
    spin("spin_precursor_sticking", .1, .0001, 1)
    spin("spin_ald_exposure", 10, .0001, 1e5)
    spin("spin_numerical_step", 2, .05, 50, " Å", 2)
    spin("spin_inhibitor_sticking", .3, .0001, 1)
    spin("spin_inhibitor_exposure", 1, 0, 5)
    w.spin_transport_rays = QSpinBox()
    w.spin_transport_rays.setObjectName("spin_transport_rays")
    w.spin_transport_rays.setRange(8, 256)
    w.spin_transport_rays.setSingleStep(2)
    w.spin_transport_rays.setValue(32)
    w.spin_transport_rays.editingFinished.connect(
        lambda: w.spin_transport_rays.setValue(min(256, int(w.spin_transport_rays.value()) + int(w.spin_transport_rays.value()) % 2)))
    w.chk_preset_run_defaults = QCheckBox("저장된 cycle·시간도 불러오기")
    w.chk_preset_run_defaults.setToolTip("끄면 현재 반복 횟수와 시간을 유지하고 공정 계수만 적용합니다. 구조는 항상 유지합니다.")
    w.chk_preset_calculation_settings = QCheckBox("저장된 계산 정확도도 불러오기")
    w.chk_preset_calculation_settings.setToolTip("동일한 계산 결과 재현을 위해 저장된 표면 간격과 방향 수를 함께 적용합니다. 구조는 유지합니다.")


def recipe_values(w):
    values = {key: (widget.currentData() if isinstance(widget, QComboBox) else widget.value())
            for key, name in RECIPE_WIDGETS.items() if (widget := getattr(w, name, None)) is not None}
    # A typed odd value can reach Run before editingFinished on keyboard shortcuts.
    rays = int(values.get("transport_ray_count", 32))
    values["transport_ray_count"] = min(256, rays + rays % 2)
    if values.get("recipe_model") != "legacy_calibrated_v1" or values.get("process_type") != "ald":
        values["front_scheme"] = "legacy"
        values["ion_growth_fraction"] = 0.
    return values


def apply_recipe_values(w, values):
    # Missing fields mean an older calibrated run, never the current UI mode.
    defaults = {"process_type": "ald", "recipe_model": "legacy_calibrated_v1", "growth_basis": "gross",
                "front_scheme": "legacy", "ion_growth_fraction": 0., "redepo_max_distance_a": 1800.,
                "inhibition_process_model": "hybrid"}
    for key, name in RECIPE_WIDGETS.items():
        if key not in values and key not in defaults:
            continue
        widget = getattr(w, name)
        value = values.get(key, defaults.get(key))
        blocker = QSignalBlocker(widget)
        if isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index < 0:
                raise ValueError(f"지원하지 않는 공정 조건: {key}={value}")
            widget.setCurrentIndex(index)
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(value))
        else:
            widget.setValue(float(value))
        del blocker


def _group(title, rows):
    group = QGroupBox(title)
    layout = QGridLayout(group)
    labels = {}
    for index, (name, text, widget) in enumerate(rows):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setBuddy(widget)
        layout.addWidget(label, index, 0)
        layout.addWidget(widget, index, 1)
        labels[name] = label
    return group, labels


def install_recipe_layout(w):
    p = w.process_parameter_panel
    if not hasattr(p, "advanced_folds"):
        return
    p.recipe_layout_ready = True
    w.btn_cancel_run = QPushButton("계산 취소")
    w.btn_cancel_run.setObjectName("btn_cancel_run")
    w.btn_cancel_run.clicked.connect(w.cancel_emulation)
    w.btn_cancel_run.hide()
    w.process_execution_bar.layout().insertWidget(1, w.btn_cancel_run)
    w.params_group.hide()
    w.recipe_group, w.recipe_labels = _group("공정 · 실행 조건", [
        ("process_type", "공정", w.cmb_process_type),
        ("recipe_model", "성장 모델", w.cmb_recipe_model),
        ("gpc", "GPC", w.spin_angstrom_per_cycle),
        ("cycles", "Cycle 수", w.spin_cycles),
        ("rate", "증착속도 D/R", w.spin_cvd_rate),
        ("time", "증착시간", w.spin_cvd_duration),
    ])
    p.layout().insertWidget(0, w.recipe_group)
    w.spin_angstrom_per_cycle.setSuffix(" Å/cycle")
    w.spin_cycles.setSuffix(" cycle")
    w.spin_cycles.setMinimum(0)
    w.parameter_preset_group.layout().insertWidget(1, w.chk_preset_run_defaults)
    w.parameter_preset_group.layout().insertWidget(2, w.chk_preset_calculation_settings)
    w.btn_load_sfo31_reference = QPushButton("SFO3.1 검증 조건 불러오기")
    w.btn_load_sfo31_reference.setObjectName("btn_load_sfo31_reference")
    w.btn_load_sfo31_reference.setToolTip("저장된 SFO3.1 공정과 CD242/R42/H702 구조, cycle 수와 계산 정확도를 함께 불러옵니다. 실행은 별도로 누르세요.")
    w.btn_load_sfo31_reference.clicked.connect(w.load_sfo31_reference)
    w.parameter_preset_group.layout().insertWidget(3, w.btn_load_sfo31_reference)
    p.buttons[0].setText("공정·계산")
    p.buttons[1].setText("성장·수송")
    p.buttons[2].setText("식각·재부착")
    p.buttons[3].setText("억제")
    for page, text in enumerate([
        "ALD는 GPC × cycle, CVD는 D/R × 시간으로 실행합니다. 계산 간격은 공정 반복 횟수와 별개입니다.",
        "Conformal은 열린 표면의 균일 성장입니다. 수송 모델은 실제 구조에서 입자 도달과 표면 반응을 계산합니다.",
        "식각된 물질 중 표면에 다시 도달해 붙은 양을 재부착으로 계산합니다. 이온 가림은 재부착 여부와 독립적입니다.",
        "억제제의 표면 점유율로 성장 가능한 자리가 줄어드는 효과입니다.",
    ]):
        item = p.layouts[page].itemAt(0)
        if item and isinstance(item.widget(), QLabel):
            item.widget().setText(text)

    w.recipe_basis_group, _ = _group("증착량 기준", [("basis", "GPC / D/R 기준", w.cmb_growth_basis)])
    p.layouts[0].insertWidget(1, w.recipe_basis_group)
    p.recipe_note = p.note("")
    p.layouts[0].insertWidget(2, p.recipe_note)
    w.fixed_repeat_group, _ = _group("SFO3.1 반복 계산", [
        ("front", "계산 방식", w.cmb_front_scheme),
        ("growth", "이온 성장 기여율", w.spin_ion_growth_fraction),
    ])
    w.spin_ion_growth_fraction.setToolTip("0은 이온과 무관한 성장, 0.05는 성장의 5%가 이온 도달량에 따라 달라지는 유효 모델입니다. 매 사이클 동일하게 적용합니다.")
    w.redepo_distance_group, _ = _group("재부착 수송 범위", [("distance", "최대 이동 거리", w.spin_redepo_max_distance)])
    p.layouts[2].insertWidget(2, w.redepo_distance_group)
    w.inhibition_law_group, _ = _group("억제 계산", [("law", "억제 모델", w.cmb_inhibition_process_model)])
    p.layouts[3].insertWidget(2, w.inhibition_law_group)
    w.transport_group, w.transport_labels = _group("입자 수송 · 표면 반응", [
        ("sticking", "표면 반응확률", w.spin_precursor_sticking),
        ("exposure", "ALD 노출량", w.spin_ald_exposure),
    ])
    p.layouts[1].insertWidget(1, w.transport_group)
    w.recipe_numerical_group, _ = _group("성장 · 수송 해상도", [
        ("rays", "중성입자 방향 수", w.spin_transport_rays),
        ("step", "최대 성장 간격", w.spin_numerical_step),
    ])
    w.recipe_numerical_fold = p.fold("계산 정확도", w.recipe_numerical_group)
    w.recipe_numerical_fold.layout().itemAt(0).widget().layout().addWidget(w.fixed_repeat_group)
    # Keep one compact numerical section rather than parallel quality panels.
    for index in range(p.layouts[0].count()):
        item = p.layouts[0].itemAt(index)
        old = item.widget() if item else None
        if isinstance(old, QGroupBox) and old.title().startswith("수치 해상도"):
            old.setTitle("표면 해상도")
            w.recipe_numerical_fold.layout().itemAt(0).widget().layout().addWidget(old)
            break
    p.layouts[0].insertWidget(p.layouts[0].count()-1, w.recipe_numerical_fold)
    w.physical_inhibition_group, _ = _group("표면 점유 모델", [
        ("sticking", "억제제 반응확률", w.spin_inhibitor_sticking),
        ("exposure", "억제제 노출량", w.spin_inhibitor_exposure),
    ])
    p.layouts[3].insertWidget(2, w.physical_inhibition_group)
    # A single amplitude controls removal; the legacy percentage is folded into
    # that amplitude on load, while its angular shape stays independently editable.
    w.lbl_sputter_peak_pct.hide()
    w.spin_sputter_peak_pct.hide()
    w.sputter_curve_editor.setEnabled(False)
    p.curve_folds[w.gaussian_group].hide()
    p.conformal_button.setText("순수 Conformal 증착")
    p.conformal_button.setToolTip("균일 증착을 선택하고 식각·재부착·억제를 끕니다. 공정 종류와 GPC/D/R, 구조는 유지합니다.")
    # Reparent the numerical ion resolution once, next to the other solver inputs.
    w.recipe_numerical_fold.layout().itemAt(0).widget().layout().addWidget(p.advanced_folds["rays"])
    for name in RECIPE_WIDGETS.values():
        widget = getattr(w, name)
        signal = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.valueChanged
        signal.connect(lambda *_: _changed(w))
    for control in (w.chk_sputter, w.chk_redepo, w.chk_inhibition_deposition):
        control.toggled.connect(lambda *_: _changed(w))
    p.sync()


def recipe_split_options(w, legacy_options):
    """Only list parameters that this recipe actually consumes."""
    ald = w.cmb_process_type.currentData() == "ald"
    model = w.cmb_recipe_model.currentData()
    amount = [("GPC (Å/cycle)", "angstrom_per_cycle"), ("Cycle 수", "cycles")] if ald else [
        ("증착속도 D/R (Å/s)", "cvd_rate_a_per_s"), ("증착시간 (s)", "cvd_duration_s")]
    if model == "legacy_calibrated_v1":
        obsolete = {"sputter_peak_pct", "angstrom_per_cycle", "cycles"}
        extra = [("이온 성장 기여율", "ion_growth_fraction")] if w.cmb_front_scheme.currentData() != "legacy" else []
        return amount + extra + [(label, key) for label, key in legacy_options if key not in obsolete]
    options = list(amount)
    if model == "physical_transport_v1":
        options.append(("표면 반응확률", "precursor_sticking"))
        if ald:
            options.append(("ALD 노출량", "ald_exposure"))
    if w.chk_sputter.isChecked():
        options.extend([("기준면 식각량" if ald else "기준면 식각속도", "sputter_strength_a_per_cycle"),
            ("최대 식각 각도", "sputter_peak_angle_deg"), ("식각 각도 폭", "sputter_width_deg"),
            ("이온 각도 폭", "redepo_incident_sigma_deg")])
        if w.chk_redepo.isChecked():
            options.append(("도착 후 부착확률 (%)", "redepo_efficiency_pct"))
    if w.chk_inhibition_deposition.isChecked():
        options.extend([("억제제 반응확률", "inhibitor_sticking"), ("억제제 노출량", "inhibitor_exposure")])
    return options


def _changed(w):
    if getattr(w, "_applying_recipe", False):
        return
    w.process_parameter_panel.sync()
    w._invalidate_result_for_input_change()
    if hasattr(w, "cmb_split_parameter"):
        w._populate_split_parameters()


def sync_recipe_layout(w):
    p = getattr(w, "process_parameter_panel", None)
    if not getattr(p, "recipe_layout_ready", False):
        return
    ald = w.cmb_process_type.currentData() == "ald"
    model = w.cmb_recipe_model.currentData()
    legacy = model == "legacy_calibrated_v1"
    w.fixed_repeat_group.setVisible(legacy and ald)
    w.recipe_numerical_fold.setTitle("계산 · SFO3.1 설정" if legacy and ald else "계산 정확도")
    w.redepo_distance_group.setVisible(legacy)
    w.inhibition_law_group.setVisible(legacy)
    transport = model == "physical_transport_v1"
    etch = w.chk_sputter.isChecked()
    inh = w.chk_inhibition_deposition.isChecked()
    for key, widget, visible in [("gpc",w.spin_angstrom_per_cycle,ald), ("cycles",w.spin_cycles,ald),
                               ("rate",w.spin_cvd_rate,not ald), ("time",w.spin_cvd_duration,not ald)]:
        w.recipe_labels[key].setVisible(visible)
        widget.setVisible(visible)
    w.params_group.hide()
    w.transport_group.setVisible(transport)
    w.transport_labels["exposure"].setVisible(ald)
    w.spin_ald_exposure.setVisible(ald)
    w.recipe_numerical_group.setVisible(not legacy)
    p.conformal_button.setVisible(model != "ideal_conformal_v1" or etch or inh)
    w.spin_transport_rays.setEnabled(transport or inh or etch)
    w.cmb_growth_basis.setEnabled(True)
    p.recipe_note.setText(
        "형상 보정용 유효 모델입니다. SFO3.1 동일 반복은 매 cycle 같은 계수를 사용합니다. GPC 기준은 위의 순성장/식각 전 선택을 따릅니다. 실제 재료 물성의 독립 검증은 별도입니다."
        if legacy else
        "기준면 순성장량은 평탄면의 제거량을 반영해 보정합니다. 트랜치의 국소 두께와 재부착은 실제 구조에서 따로 계산합니다."
    )
    # All empirical alternatives are one compatibility family, mutually hidden
    # from the transport/conformal route that does not consume them.
    for widget in [w.chk_typical_cvd, p.cvd_fields, p.advanced_folds["cvd"],
                   w.process_geometry_fold]:
        widget.setVisible(legacy)
    p.section_containers["depth"].setVisible(legacy and not w.chk_typical_cvd.isChecked())
    p.section_containers["ion"].setVisible(legacy and not w.chk_incident_los.isChecked())
    p.advanced_folds["inhibition"].setVisible(legacy)
    for widget in [w.lbl_inhibition_strength, w.spin_inhibition_strength,
                   w.lbl_inhibition_penetration, w.spin_inhibition_penetration,
                   w.lbl_inhibition_min_growth, w.spin_inhibition_min_growth]:
        widget.setVisible(legacy and inh)
    w.physical_inhibition_group.setVisible(not legacy)
    w.physical_inhibition_group.setEnabled(inh)
    p.advanced_folds["redepo"].setVisible(legacy)
    w.lbl_sputter_smoothing.setVisible(legacy and etch)
    w.spin_sputter_smoothing.setVisible(legacy and etch)
    w.lbl_sputter_peak_pct.hide()
    w.spin_sputter_peak_pct.hide()
    p.curve_folds[w.gaussian_group].hide()
    w.chk_incident_los.setVisible(legacy)
    w.incident_model_group.setEnabled(etch)
    w.spin_incident_sigma.setEnabled(etch)
    w.spin_incident_rays.setEnabled(etch)
    w.lbl_sputter_strength.setText(("최대 식각량" if legacy else "기준면 식각량" if ald else "기준면 식각속도") + (" (Å/cycle)" if ald else " (Å/s)"))
    w.lbl_redepo_efficiency.setText("재부착 보정률 (%)" if legacy else "도착 후 부착확률 (%)")
    p.advanced_folds["direct"].setTitle("식각 각도 · 보정" if legacy else "식각 각도 응답")
    amplitude = w.spin_sputter_strength.value() * (w.spin_sputter_peak_pct.value()/100 if legacy else 1)
    p.etch_effective.setText(("최대" if legacy else "기준면") + f" 식각: {amplitude:g} " + ("Å/cycle" if ald else "Å/s"))
    amount = w.spin_cycles.value()*w.spin_angstrom_per_cycle.value() if ald else w.spin_cvd_rate.value()*w.spin_cvd_duration.value()
    basis = "식각 전" if w.cmb_growth_basis.currentData() == "gross" else "기준면 순성장"
    p.dose_label.setText(f"{basis} 증착량 {amount:g} Å ({amount/10:g} nm) · 트랜치 국소 두께는 결과에서 확인")
    p.summary.setText(f"{'ALD' if ald else 'CVD'} · {w.cmb_recipe_model.currentText()} · 식각 {'ON' if etch else 'OFF'} / 재부착 {'ON' if etch and w.chk_redepo.isChecked() else 'OFF'} / 억제 {'ON' if inh else 'OFF'}")
    w.process_geometry_fold.setTitle("기존 보정 모델의 기준 형상")
    for label in w.incident_model_group.findChildren(QLabel):
        if "기존 이온 감쇠" in label.text():
            label.setText("이온 도달량은 현재 형상의 가림으로 계산합니다. 재부착 OFF에서도 식각 가림을 유지합니다.")


def recipe_result_summary(config, result=None):
    meta = result.meta if result else {}
    ald = config.process_type == "ald"
    amount = config.cycles*config.angstrom_per_cycle if ald else config.cvd_rate_a_per_s*config.cvd_duration_s
    model_name = {"ideal_conformal_v1":"Conformal · 균일 증착", "physical_transport_v1":"수송·표면 반응",
                  "legacy_calibrated_v1":"기존 보정 모델"}.get(config.recipe_model, config.recipe_model)
    basis_name = "기준면 순성장량" if config.growth_basis == "net_planar" else "식각 전 증착량"
    lines = [f"공정: {'ALD' if ald else 'CVD'}", f"성장 모델: {model_name}",
             f"GPC {config.angstrom_per_cycle:g} Å/cycle × {config.cycles} cycle" if ald else
             f"증착속도 D/R {config.cvd_rate_a_per_s:g} Å/s × {config.cvd_duration_s:g} s",
             f"기준 증착량: {amount:g} Å", f"증착량 기준: {basis_name}"]
    if config.recipe_model != "legacy_calibrated_v1":
        lines += [f"표면 반응확률: {config.precursor_sticking:g}" if config.recipe_model == "physical_transport_v1" else "열린 표면 균일 성장",
                  f"식각: {'ON' if config.sputter_enabled else 'OFF'} · 재부착: {'ON' if config.redepo_enabled else 'OFF'} · 억제: {'ON' if config.inhibition_enabled else 'OFF'}",
                  f"계산 간격: 최대 {config.numerical_step_a:g} Å / 표면 점 {config.reparam_ds_a:g} Å",
                  "2D 단면 유효 모델 · 재료별 계수 보정 필요"]
        if config.recipe_model == "physical_transport_v1" and ald:
            lines.append(f"ALD 노출량: {config.ald_exposure:g} (무차원)")
        if config.sputter_enabled:
            lines += [f"기준면 식각: {config.sputter_strength_a_per_cycle:g} " + ("Å/cycle" if ald else "Å/s"),
                      f"최대 식각 각도: {config.sputter_peak_angle_deg:g}° · 각도 폭: {config.sputter_width_deg:g}°",
                      f"이온 각도 폭: {config.redepo_incident_sigma_deg:g}° · 이온 방향 수: {config.redepo_incident_ray_count}"]
            if config.redepo_enabled:
                lines.append(f"도착 후 부착확률: {config.redepo_efficiency_pct:g}%")
        if config.inhibition_enabled:
            lines.append(f"억제제 반응확률: {config.inhibitor_sticking:g} · 노출량: {config.inhibitor_exposure:g} (무차원)")
    if config.front_scheme == "angular_godunov_v1":
        lines += ["SFO3.1 동일 반복 · 종료 후 추가 처리 없음",
                  f"이온 성장 기여율: {config.ion_growth_fraction*100:g}%",
                  "형상 보정용 유효 모델 · 실제 물성/다른 구조의 예측력은 별도 검증 필요"]
    if result:
        lines += [f"저장 프레임: {len(result.frame_profiles)}", f"최종 단면 점: {len(result.final_profile)}"]
        for key, label in (("redepo_total_removed_mass", "누적 제거 수송량"),
                           ("redepo_total_mass", "누적 재부착 수송량")):
            if key in meta:
                lines.append(f"{label}: {float(meta[key]):g} Å² (2D 적분값)")
    return "\n".join(lines)

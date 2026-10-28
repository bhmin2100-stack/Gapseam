"""Editable common response parameters; preset names never select an equation."""
from dataclasses import asdict, replace
from copy import deepcopy
import math
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QLabel, QWidget
from .calibrated_response import MODEL, ResponseParameters, load_parameters, sfo310_parameters

# Short names, explicit units, and the actual meaning of every coefficient.
SECTIONS = (
    ('성장 응답', (
        ('growth_enabled','성장 보정 사용','깊이별 성장률에 아래 응답을 매 cycle 적용합니다.'),
        ('depth_reference','깊이 기준','현재 상면은 성장한 field, 최초 상면은 입력 구조의 상면입니다.'),
        ('upper_center_cd','상부 중심 (CD 배수)','현재 기준 폭에 대한 깊이 비율입니다.'),
        ('upper_halfwidth_cd','상부 반폭 (CD 배수)','중심에서 이 거리까지 보정이 부드럽게 0으로 줄어듭니다.'),
        ('upper_gain','상부 성장 증가','낮은 종횡비에서 상부 성장률에 더하는 배율입니다.'),
        ('relief_center_cd','완화 중심 (CD 배수)','성장률을 낮추는 깊이 구간의 중심입니다.'),
        ('relief_halfwidth_cd','완화 반폭 (CD 배수)','성장 완화가 적용되는 깊이 범위입니다.'),
        ('relief_gain','성장 완화량','성장 배율에서 빼는 값입니다. 최종 배율은 0 아래로 내려가지 않습니다.'),
        ('deep_center_cd','심부 중심 (CD 배수)','높은 종횡비에서 적용할 깊이 구간의 중심입니다.'),
        ('deep_halfwidth_cd','심부 반폭 (CD 배수)','심부 성장 응답의 공간 범위입니다.'),
        ('deep_early_gain','초기 심부 변화','초기 증착량 구간의 성장 배율 변화입니다. 음수는 감소입니다.'),
        ('deep_middle_gain','중기 심부 변화','초기 전환 이후, 종료 전환 이전의 배율 변화입니다.'),
    )),
    ('증착량 응답', (
        ('dose_response_enabled','증착량 전환 사용','누적 GPC × cycle에 따라 같은 응답식의 가중치가 달라집니다. 별도 마무리 공정이 아닙니다.'),
        ('dose_start_a','초기 전환량 (Å)','이 증착량 부근에서 초기 응답이 중기 응답으로 바뀝니다.'),
        ('dose_end_a','중기 종료량 (Å)','이 증착량 부근에서 중기 응답이 사라집니다.'),
        ('dose_width_a','전환 폭 (Å)','클수록 증착량에 따른 전환이 완만합니다.'),
    )),
    ('구조 응답', (
        ('aspect_response_enabled','종횡비 응답 사용','기준 깊이 / CD에 따라 상부 및 심부 보정의 가중치를 정합니다.'),
        ('aspect_center','전환 종횡비','상부와 심부 응답의 가중치가 같은 종횡비입니다.'),
        ('aspect_width','종횡비 전환 폭','클수록 종횡비에 따른 전환이 완만합니다.'),
        ('static_aspect_weight','고정 심부 비율','종횡비 응답을 끈 경우에만 사용합니다. 0=상부, 1=심부.'),
    )),
    ('폐쇄 후 충전 · 경험식', (
        ('closure_enabled','깊이별 충전 사용','폐쇄 후 잔류 공간의 충전 한도를 깊이별로 정합니다. 공급 경로가 검증된 물리 모델은 아닙니다.'),
        ('fill_order','충전 순서','깊은 공간 우선 또는 전체 공간에 면적 예산을 배분합니다.'),
        ('include_new_void_budget','새 폐쇄 공간 포함','추가로 닫힌 공간에도 충전 한도를 배정합니다.'),
        ('fill_base','기본 충전 비율','잔류 공간 면적 중 충전할 수 있는 비율의 기준값입니다.'),
        ('fill_shallow','얕은 구간 비율','얕은 쪽 전환이 적용된 충전 비율입니다.'),
        ('fill_deep','깊은 구간 비율','깊은 쪽 전환이 적용된 충전 비율입니다.'),
        ('fill_shallow_depth_nm','얕은 전환 깊이 (nm)','기준 상면에서 아래로 잰 깊이입니다.'),
        ('fill_deep_depth_nm','깊은 전환 깊이 (nm)','기준 상면에서 아래로 잰 깊이입니다.'),
        ('fill_transition_width_nm','깊이 전환 폭 (nm)','충전 비율이 바뀌는 깊이 범위입니다.'),
        ('fill_peak1_depth_nm','추가 구간 1 깊이 (nm)','가우시안 충전 보정의 중심입니다.'),
        ('fill_peak1_width_nm','추가 구간 1 폭 (nm)','가우시안 표준편차입니다.'),
        ('fill_peak1_gain','추가 구간 1 증가','충전 비율에 더하는 양입니다. 합계는 0~1로 제한합니다.'),
        ('fill_peak2_depth_nm','추가 구간 2 깊이 (nm)','두 번째 가우시안 충전 보정의 중심입니다.'),
        ('fill_peak2_width_nm','추가 구간 2 폭 (nm)','두 번째 가우시안 표준편차입니다.'),
        ('fill_peak2_gain','추가 구간 2 증가','충전 비율에 더하는 양입니다. 합계는 0~1로 제한합니다.'),
    )),
    ('고종횡비 응답 · 시험', (
        ('har_enabled','고종횡비 보정 사용','깊은 구조에서 최소 성장과 잔류 충전을 추가 보정합니다. 구조 외삽용 경험식입니다.'),
        ('har_start_ar','시작 종횡비','이하에서는 고종횡비 보정이 0입니다.'),
        ('har_end_ar','전체 적용 종횡비','이상에서는 고종횡비 보정을 전부 적용합니다.'),
        ('har_growth_floor','심부 최소 성장 배율','field 성장률 × 이 값 × 정규화 깊이의 지수승을 최소 성장으로 사용합니다.'),
        ('har_depth_power','심부 깊이 지수','최소 성장이 깊이에 따라 증가하는 모양입니다.'),
        ('har_upper_center_cd','입구 강화 깊이 (CD 배수)','고종횡비 상부 성장 강화의 중심입니다.'),
        ('har_upper_halfwidth_cd','입구 강화 반폭 (CD 배수)','입구 성장 강화 범위입니다.'),
        ('har_upper_gain','입구 성장 증가','해당 구간의 성장 배율에 더하는 값입니다.'),
        ('har_fill_extra','충전 한도 증가','고종횡비에서 충전 가능 면적 비율에 더하는 값입니다.'),
        ('har_fill_rate_gain','충전 속도 증가','1이면 고종횡비 충전 진행 속도가 최대 2배가 됩니다.'),
    )),
)


class CompactSpinBox(QDoubleSpinBox):
    """Retain numerical precision without displaying a column of trailing zeros."""
    def textFromValue(self, value):
        return format(value, '.12f').rstrip('0').rstrip('.') or '0'


def normalized_values(values):
    values = deepcopy(dict(values))
    model = values.get('recipe_model', 'legacy_calibrated_v1')
    if values.get('process_type', 'ald') == 'ald' and model in ('legacy_calibrated_v1', 'sfo310_calibrated_v1', 'sfo310_har_experimental_v1'):
        p = sfo310_parameters() if model != 'legacy_calibrated_v1' else ResponseParameters()
        if model == 'sfo310_har_experimental_v1':
            p = replace(p, har_enabled=True)
        values['empirical_response'] = asdict(p)
        values['recipe_model'] = MODEL
    if values.get('empirical_response') is not None:
        values['empirical_response'] = asdict(load_parameters(values['empirical_response']))
    return values


def init_response_controls(w):
    w.response_controls = {}
    defaults = asdict(ResponseParameters())
    for _, rows in SECTIONS:
        for key, label, tip in rows:
            value = defaults[key]
            if isinstance(value, bool):
                c = QCheckBox(label)
                c.setChecked(value)
            elif isinstance(value, str):
                c = QComboBox()
                items = [('현재 상면','current_top'),('최초 상면','initial_top')] if key=='depth_reference' else [('깊은 공간 우선','deep_first'),('균일 배분','uniform')]
                for text, data in items: c.addItem(text, data)
            else:
                c = CompactSpinBox()
                c.setDecimals(12)
                c.setRange(-1e6, 1e7)
                c.setValue(value)
                c.setSingleStep(.1 if abs(value)<10 else 10)
            c.setObjectName('response_'+key)
            c.setToolTip(tip)
            w.response_controls[key] = c
    w._response_raw = defaults
    w._response_display = _control_values(w)


def _control_values(w):
    return {k: c.isChecked() if isinstance(c,QCheckBox) else c.currentData() if isinstance(c,QComboBox) else c.value()
            for k,c in w.response_controls.items()}


def response_values(w):
    values = _control_values(w)
    return {'version':1, **{k: w._response_raw[k] if value==w._response_display[k] else value for k,value in values.items()}}


def apply_response_values(w, values):
    raw = asdict(load_parameters(values.get('empirical_response')))
    for k,c in w.response_controls.items():
        blocker = QSignalBlocker(c)
        if isinstance(c,QCheckBox): c.setChecked(raw[k])
        elif isinstance(c,QComboBox): c.setCurrentIndex(c.findData(raw[k]))
        else: c.setValue(raw[k])
        del blocker
    w._response_raw = raw
    w._response_display = _control_values(w)


def install_response_layout(w):
    from .recipe_ui import _changed, _group
    p = w.process_parameter_panel
    # Move existing controls; do not duplicate their values or signals.
    def move_rows(title, page, entries):
        rows=[]
        for key,label,c in entries:
            old=c.parentWidget().layout() if c.parentWidget() else None
            if isinstance(old,QGridLayout):
                index=old.indexOf(c)
                if index>=0:
                    row,col,_,_=old.getItemPosition(index)
                    item=old.itemAtPosition(row,col-1)
                    if item and isinstance(item.widget(),QLabel): item.widget().hide()
            rows.append((key,label,c))
        group,_=_group(title,rows)
        p.layouts[page].insertWidget(max(0,p.layouts[page].count()-1),group)
        return group
    w.common_ion_growth_group=move_rows('이온 성장',1,[('ion','이온 성장 기여율',w.spin_ion_growth_fraction)])
    w.common_smoothing_group=move_rows('평활화 · 보정값 유지',5,[
        ('etch','식각률 평활화 (Å)',w.spin_sputter_smoothing),
        ('growth','성장률 평활화 (Å)',w.spin_inhibition_smoothing)])
    w.common_fill_group=move_rows('기본 잔류 충전 · 경험식',4,[
        ('threshold','폐쇄 판정 간격 (Å)',w.spin_depth_closure_threshold),
        ('hole','Hole 충전 한도 (%)',w.spin_depth_post_fill_hole_pct),
        ('line','Trench 충전 한도 (%)',w.spin_depth_post_fill_line_pct),
        ('path','Trench 공급 보정',w.spin_depth_line_open_path),
        ('decay','잔류 충전 감쇠 길이 (Å)',w.spin_depth_residual_decay),
        ('distribution','충전 분포',w.cmb_residual_distribution)])
    w.common_growth_boost_group=move_rows('바닥 성장 보강 · 경험식',1,[
        ('bottom','바닥 성장 증가 (%)',w.spin_inhibition_bottom_boost),
        ('radical','재결합 보정 (%)',w.spin_inhibition_recombination)])
    p.layouts[4].addWidget(p.note('추가 응답은 모든 보정 레시피가 공유합니다. 프리셋 적용 후 값을 바꿔 파생 레시피로 저장할 수 있습니다. 깊이·증착량 응답은 동일 반복식 안에서 적용됩니다.'))
    w.response_folds = []
    for title, rows in SECTIONS:
        body = QWidget(); form = QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        for key,label,tip in rows:
            c = w.response_controls[key]
            text = QLabel(label); text.setToolTip(tip); text.setWordWrap(True); text.setBuddy(c)
            if isinstance(c,QCheckBox): form.addRow(c)
            else: form.addRow(text,c)
            signal = c.toggled if isinstance(c,QCheckBox) else c.currentIndexChanged if isinstance(c,QComboBox) else c.valueChanged
            signal.connect(lambda *_: _changed(w))
        fold = p.fold(title,body)
        w.response_folds.append(fold)
        p.layouts[4].addWidget(fold)
    p.layouts[4].addStretch()
    # One numerical page, independent of physical recipe groups.
    p.layouts[5].addWidget(p.note('해상도는 계산 비용과 수치 오차를 바꿉니다. 보정에 사용된 평활화 길이도 재현을 위해 프리셋과 함께 저장합니다.'))
    p.layouts[5].addWidget(w.recipe_numerical_fold)
    w.recipe_numerical_fold.setChecked(True)
    p.layouts[5].addWidget(w.chk_symmetry)
    p.layouts[5].addStretch()


def sync_response_layout(w):
    enabled = w.cmb_recipe_model.currentData()==MODEL and w.cmb_process_type.currentData()=='ald'
    calibrated = w.cmb_recipe_model.currentData() in (MODEL,'legacy_calibrated_v1','sfo310_calibrated_v1')
    w.common_fill_group.setEnabled(calibrated and w.chk_depth_deposition.isChecked())
    w.common_ion_growth_group.setVisible(calibrated and w.cmb_process_type.currentData()=='ald')
    w.common_smoothing_group.setVisible(calibrated)
    w.common_growth_boost_group.setVisible(calibrated)
    w.common_growth_boost_group.setEnabled(w.chk_inhibition_deposition.isChecked())
    w.lbl_sputter_smoothing.hide()
    w.lbl_inhibition_smoothing.hide()
    w.spin_sputter_smoothing.setVisible(True)
    w.spin_sputter_smoothing.setEnabled(calibrated and w.chk_sputter.isChecked())
    w.spin_inhibition_smoothing.setEnabled(calibrated and w.chk_inhibition_deposition.isChecked())
    for fold in w.response_folds: fold.setEnabled(enabled)
    v = _control_values(w)
    for key,c in w.response_controls.items():
        active = True
        if key.startswith(('upper_','relief_','deep_')) or key=='depth_reference': active = v['growth_enabled'] or (key=='depth_reference' and v['closure_enabled'])
        elif key.startswith('dose_') and key!='dose_response_enabled': active = v['growth_enabled'] and v['dose_response_enabled']
        elif key.startswith('aspect_') and key!='aspect_response_enabled': active = v['growth_enabled'] and v['aspect_response_enabled']
        elif key=='static_aspect_weight': active = v['growth_enabled'] and not v['aspect_response_enabled']
        elif key.startswith('fill_') or key=='include_new_void_budget': active = v['closure_enabled']
        elif key.startswith('har_') and key!='har_enabled': active = v['har_enabled'] and (v['closure_enabled'] if key.startswith('har_fill') else v['growth_enabled'])
        c.setEnabled(enabled and active)


def remember_precision(w, values):
    """Keep loaded coefficients bit-exact until their visible control changes."""
    w._recipe_exact_cache = {}
    shown = asdict(w.current_config())
    from .parameter_library import GEOMETRY_PARAMETER_FIELDS
    for key,value in values.items():
        if key in GEOMETRY_PARAMETER_FIELDS or key not in shown: continue
        if isinstance(value,float) and isinstance(shown[key],(float,int)) and math.isclose(value, shown[key], rel_tol=0, abs_tol=1e-9):
            w._recipe_exact_cache[key]=(shown[key],value)


def exact_config(w, cfg):
    changes = {k: raw for k,(shown,raw) in getattr(w,'_recipe_exact_cache',{}).items() if getattr(cfg,k)==shown}
    return replace(cfg,**changes) if changes else cfg

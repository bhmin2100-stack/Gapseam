"""Editable equation controls, separate from the calibrated response family."""
from dataclasses import asdict
import math
from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel
from .depth_formula import MODEL, Parameters, LAW_NAMES, load_parameters, description

ROWS = (
    ('decay_per_nm', '감쇠계수 (1/nm)', 'exponential'),
    ('linear_slope', '선형 계수 a', 'linear_exp'),
    ('linear_constant', '상수 b', 'linear_exp'),
    ('linear_exp_gain', '지수 계수 c', 'linear_exp'),
    ('linear_length', '지수 길이 L', 'linear_exp'),
    ('cubic_a', '3차 계수 a', 'cubic'),
    ('cubic_b', '2차 계수 b', 'cubic'),
    ('cubic_c', '1차 계수 c', 'cubic'),
    ('cubic_d', '상수 d', 'cubic'),
)


class CoefficientSpin(QDoubleSpinBox):
    def textFromValue(self, value):
        return f'{value:.12g}'

    def valueFromText(self, text):
        return float(text)

    def validate(self, text, position):
        try:
            value = float(text)
            state = QValidator.State.Acceptable if math.isfinite(value) and self.minimum() <= value <= self.maximum() else QValidator.State.Invalid
        except ValueError:
            state = QValidator.State.Intermediate if text.strip().lower().endswith(('e', 'e-', 'e+', '.', '-', '+')) or not text.strip() else QValidator.State.Invalid
        return state, text, position


def init_controls(w):
    defaults = asdict(Parameters())
    w.depth_formula_controls = {}
    for key, choices in (
        ('law', [(name, key) for key, name in LAW_NAMES.items()]),
        ('depth_unit', [('nm', 'nm'), ('Å', 'A')]),
        ('reference', [('실행 시작 상면', 'initial_top'), ('현재 상면', 'current_field')]),
    ):
        c = QComboBox()
        for label, data in choices: c.addItem(label, data)
        w.depth_formula_controls[key] = c
    for key, label, law in ROWS:
        c = CoefficientSpin()
        c.setDecimals(15)
        c.setStepType(QDoubleSpinBox.StepType.AdaptiveDecimalStepType)
        c.setRange(0 if key == 'decay_per_nm' else 1e-9 if key == 'linear_length' else -1e9, 1e9)
        c.setValue(defaults[key])
        c.setToolTip('성장식에 표시된 경험식 계수입니다. 과학적 표기(예: -6e-10)로 입력할 수 있습니다.')
        w.depth_formula_controls[key] = c
    for key, c in w.depth_formula_controls.items(): c.setObjectName('depth_formula_'+key)
    w._depth_formula_exact = {}


def values(w):
    result = {'version': 1}
    for key, c in w.depth_formula_controls.items():
        v = c.currentData() if isinstance(c, QComboBox) else c.value()
        shown, raw = getattr(w, '_depth_formula_exact', {}).get(key, (None, None))
        result[key] = raw if v == shown else v
    return result


def apply_values(w, raw):
    p = asdict(load_parameters(raw))
    w._depth_formula_exact = {}
    for key, c in w.depth_formula_controls.items():
        blocker = QSignalBlocker(c)
        if isinstance(c, QComboBox): c.setCurrentIndex(c.findData(p[key]))
        else: c.setValue(p[key])
        del blocker
    shown = values(w)
    w._depth_formula_exact = {key: (shown[key], p[key]) for key in w.depth_formula_controls}


def install_layout(w):
    from .recipe_ui import _changed
    w.depth_formula_group = QGroupBox('깊이별 성장식 · 경험식')
    layout = QFormLayout(w.depth_formula_group)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    w.depth_formula_labels = {}
    for key, label in [('law', '성장식'), ('depth_unit', 'z 단위'), ('reference', '깊이 기준')]+[(key,label) for key,label,law in ROWS]:
        text = QLabel(label)
        text.setBuddy(w.depth_formula_controls[key])
        w.depth_formula_labels[key] = text
        layout.addRow(text, w.depth_formula_controls[key])
    w.depth_formula_equation = QLabel()
    w.depth_formula_equation.setWordWrap(True)
    w.depth_formula_note = QLabel()
    w.depth_formula_note.setWordWrap(True)
    layout.addRow(w.depth_formula_equation)
    layout.addRow(w.depth_formula_note)
    w.process_parameter_panel.layouts[1].insertWidget(1, w.depth_formula_group)
    for c in w.depth_formula_controls.values():
        signal = c.currentIndexChanged if isinstance(c, QComboBox) else c.valueChanged
        signal.connect(lambda *_: _changed(w))


def sync_layout(w):
    w.depth_formula_group.setVisible(w.cmb_recipe_model.currentData() == MODEL)
    p = Parameters(**values(w))
    for key, label, law in ROWS:
        w.depth_formula_labels[key].setVisible(law == p.law)
        w.depth_formula_controls[key].setVisible(law == p.law)
    for c in (w.depth_formula_labels['depth_unit'],w.depth_formula_controls['depth_unit']):
        c.setVisible(p.law != 'exponential')
    w.depth_formula_equation.setText(description(p))
    unit_note = ('지수식은 d_nm을 사용하며 exp(−0.0000829 × d_Å)와 같습니다.'
                 if p.law == 'exponential' else
                 f'z는 음수 깊이 ({"Å" if p.depth_unit == "A" else "nm"})입니다. 단위를 바꿔도 계수는 자동 변환하지 않습니다.')
    w.depth_formula_note.setText('r=f(z)/f(0) · GPC/D/R은 평탄부 값으로 별도 지정합니다. ' + unit_note)

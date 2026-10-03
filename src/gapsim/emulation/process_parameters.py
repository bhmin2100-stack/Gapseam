"""Engineer-facing organization; existing widgets/signals remain authoritative."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QLabel, QCheckBox, QDoubleSpinBox, QPushButton,
                              QVBoxLayout, QGridLayout, QGroupBox, QSizePolicy)
from gapsim.engine.typical_cvd import DEFAULTS
from gapsim.engine.typical_cvd import reference_geometry


def init_cvd_controls(w):
    w.chk_typical_cvd = QCheckBox('Typical CVD 사용 · 경험식 형상 모델')
    w.cvd_spins = {}
    for name, high, suffix in [('cvd_overhang_pct',200,' %'),('cvd_cusping_pct',200,' %'),
                               ('cvd_bottom_ratio_pct',100,' %'),('cvd_upper_length_a',10000,' Å'),
                               ('cvd_depth_power',6,'')]:
        spin = QDoubleSpinBox()
        spin.setObjectName(name)
        spin.setRange(.5 if name=='cvd_upper_length_a' else .2 if name=='cvd_depth_power' else 0, high)
        spin.setDecimals(2)
        spin.setValue(DEFAULTS[name])
        spin.setSuffix(suffix)
        w.cvd_spins[name] = spin


def cvd_values(w):
    return dict(cvd_enabled=w.chk_typical_cvd.isChecked(),
                **{name:spin.value() for name,spin in w.cvd_spins.items()})


def apply_cvd_values(w, values):
    for name,spin in w.cvd_spins.items():
        spin.setValue(float(values.get(name,DEFAULTS[name])))
    w.chk_typical_cvd.setChecked(bool(values.get('cvd_enabled',False)))


class ProcessPageStack(QWidget):
    """Hidden process pages must not reserve their full height in the scroll pane."""

    def __init__(self):
        super().__init__()
        self._pages = []
        self._current_index = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    def addWidget(self, page):
        self._pages.append(page)
        self.layout().addWidget(page)
        page.setVisible(len(self._pages) - 1 == self._current_index)

    def setCurrentIndex(self, index):
        self._current_index = index
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)
        self.updateGeometry()

    def currentIndex(self):
        return self._current_index


class ProcessParameterPanel(QWidget):
    TITLES = ('1  Conformal depo', '2  Typical CVD', '3  Etch + redeposition', '4  Inhibition')

    def __init__(self,w,base_group,parent_layout):
        super().__init__()
        self.w=w
        root=QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        nav=QGridLayout()
        self.buttons=[]
        self.stack=ProcessPageStack()
        self.pages=[]
        self.layouts=[]
        self.sections={}
        self.grids={}
        self.curve_folds={}
        for i,title in enumerate(self.TITLES):
            button=QPushButton(title)
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
            button.clicked.connect(lambda checked=False,n=i:self.select(n))
            nav.addWidget(button,i//2,i%2)
            self.buttons.append(button)
            page=QWidget()
            layout=QVBoxLayout(page)
            layout.setContentsMargins(0,0,0,0)
            self.pages.append(page)
            self.layouts.append(layout)
            self.stack.addWidget(page)
        self.summary=QLabel()
        self.summary.setWordWrap(True)
        root.addLayout(nav)
        root.addWidget(self.summary)
        root.addWidget(self.stack)
        base_group.setTitle('Conformal · 기본 증착량')
        self.layouts[0].addWidget(self.note('기본은 표면 법선 방향 균일 증착입니다. CVD·Etch·Inhibition은 독립적으로 조합합니다. Step은 계산 단위이며 실제 ALD cycle 또는 시간이 아닙니다.'))
        self.layouts[0].addWidget(base_group)
        for label in base_group.findChildren(QLabel):
            if label.text()=='Cycles':label.setText('계산 Step 수')
        numerical=QWidget()
        ng=QGridLayout(numerical)
        ng.setContentsMargins(0,0,0,0)
        for row,(label,spin) in enumerate([(w.lbl_quality_mode,w.cmb_quality_mode),(w.lbl_reparam_ds,w.spin_reparam_ds)]):
            ng.addWidget(label,row,0)
            ng.addWidget(spin,row,1)
        self.layouts[0].addWidget(self.fold('수치 해상도 · 공정 효과 아님',numerical))
        self.dose_label=QLabel()
        self.dose_label.setWordWrap(True)
        self.layouts[0].addWidget(self.dose_label)
        w.lbl_depo_rate.setText('기본 증착량 Å/step')
        w.lbl_reparam_ds.setText('표면 점 간격 (수치)')
        w.lbl_deposition_section.setText('공통 증착 · 수치 적분')
        self.conformal_button=QPushButton('순수 Conformal만 사용')
        self.conformal_button.setToolTip('CVD·기존 depth depletion·Etch·Inhibition을 끕니다. 입력 수치와 구조는 보존합니다.')
        self.conformal_button.clicked.connect(self.conformal_only)
        self.layouts[0].addWidget(self.conformal_button)

        self.layouts[1].addWidget(self.note('Overhang: 상부 측벽 성장 강화 / Cusping: 모서리 성장 집중 / Bottom: 기준 깊이의 기본 성장률. 형상 경향 계수이며 실제 온도·압력·sticking의 보정값은 아닙니다.'))
        self.layouts[1].addWidget(w.chk_typical_cvd)
        self.cvd_fields=QWidget()
        cg=QGridLayout(self.cvd_fields)
        cg.setContentsMargins(0,0,0,0)
        definitions=[('cvd_overhang_pct','Overhang 강화','0=추가 강화 없음. 100=상부 수직벽의 기본 성장 성분을 최대 2배로 강화.'),
                     ('cvd_cusping_pct','Cusping 집중','0=추가 집중 없음. 경사진 모서리 주변의 국소 성장 강화. 최종 뾰족함의 직접 측정값은 아닙니다.'),
                     ('cvd_bottom_ratio_pct','Bottom 성장률','기준 깊이에서 평탄부 대비 기본 성장률. 100=depletion 없음, 0=바닥 기본 성장 없음. 억제/상부 강화 이전 값.'),
                     ('cvd_upper_length_a','상부 영향 길이','입구 부근 효과의 공간 범위. 단일 중심 트랜치 근사입니다.'),
                     ('cvd_depth_power','Depletion 곡선 지수','상부에서 바닥으로 성장률이 감소하는 모양.')]
        for i,(name,label,tip) in enumerate(definitions):
            text=QLabel(label)
            text.setToolTip(tip)
            w.cvd_spins[name].setToolTip(tip)
            cg.addWidget(text,i,0)
            cg.addWidget(w.cvd_spins[name],i,1)
        self.layouts[1].addWidget(self.cvd_fields)
        self.geometry_label=QLabel()
        self.geometry_label.setWordWrap(True)
        self.layouts[1].addWidget(self.geometry_label)
        self.layouts[1].addWidget(self.note('새 CVD를 켜면 아래 기존 depth depletion은 이중 적용하지 않습니다. 기존 값은 보존됩니다. 닫힌 내부 void에는 추가 CVD 공급을 하지 않습니다.'))
        self.layouts[2].addWidget(self.note('Etch → 이온 공급/가림 → redep 순으로 설정합니다. 순수 Etch는 기본 증착량=0. 입사 가림을 유지한 무재증착 비교는 Redepo ON + 효율 0%. LF 전력·에너지 해석은 아닙니다.'))
        self.layouts[3].addWidget(self.note('증착 성장률에 적용되는 억제입니다. CVD와 함께 켜면 CVD 성장률 × inhibition 비율로 계산합니다. Bottom boost는 억제가 아니라 별도의 성장 보강 경험항입니다.'))
        # Reparent existing controls, never duplicate them or bypass their signals.
        destinations={'depth':1,'inhibition':3}
        for key,rows in w._model_parameter_section_rows.items():
            section=QWidget()
            grid=QGridLayout(section)
            grid.setContentsMargins(0,0,0,0)
            row=0
            for widget,col,span in rows:
                w.params_grid.removeWidget(widget)
                grid.addWidget(widget,row,col,1,span)
                if span>1 or col>0:row+=1
            self.sections[key]=section
            self.grids[key]=grid
            self.layouts[destinations.get(key,2)].addWidget(section)
        # Inactive legacy models stay hidden as before, but are retained for compatibility.
        for key in ('lf','closure','reflected'):
            self.sections[key].hide()
        geometry=QGroupBox('공유 기준 형상 · CVD / Inhibition')
        gg=QGridLayout(geometry)
        self.geometry_widgets=[]
        for row,(label,spin) in enumerate([(w.lbl_depth_feature_type,w.cmb_depth_feature_type),
                                          (w.lbl_depth_feature_width,w.spin_depth_feature_width),
                                          (w.lbl_depth_feature_depth,w.spin_depth_feature_depth),
                                          (w.lbl_depth_feature_length,w.spin_depth_feature_length)]):
            gg.addWidget(label,row,0)
            gg.addWidget(spin,row,1)
            self.geometry_widgets.extend((label,spin))
        self.geometry_button=QPushButton('현재 구조에서 폭·깊이 가져오기')
        self.geometry_button.clicked.connect(self.infer_geometry)
        gg.addWidget(self.geometry_button,4,0,1,2)
        self.layouts[1].insertWidget(4,geometry)
        for widget,page in [(w.incident_model_group,2),
                            (w.gaussian_group,2),(w.ion_map_group,2),(w.redepo_lobe_group,2),
                            (w.depth_profile_group,1),(w.inhibition_profile_group,3)]:
            parent_layout.removeWidget(widget)
            if widget in (w.gaussian_group,w.ion_map_group,w.redepo_lobe_group,w.depth_profile_group,w.inhibition_profile_group):
                fold=self.fold(widget.title()+' · 곡선 편집',widget)
                self.curve_folds[widget]=fold
                self.layouts[page].addWidget(fold)
            else:
                self.layouts[page].addWidget(widget)
        w.lbl_depth_depo_section.setText('기존 Depth depletion · 호환 모델')
        w.chk_depth_deposition.setText('기존 깊이 감쇠 사용 (호환)')
        w.chk_depth_deposition.setToolTip('새 Typical CVD OFF일 때만 적용합니다. 기존 수치는 보존됩니다.')
        w.chk_ion_transmission.setText('기존 이온 깊이 감쇠 (호환)')
        w.chk_ion_transmission.setToolTip('입사 이온 가림 OFF일 때만 적용됩니다. 새 모델과 중복 적용하지 않습니다.')
        # Numerical regularization is labeled separately from physical process inputs.
        w.lbl_sputter_smoothing.setText('수치 평활화 Å')
        w.lbl_inhibition_smoothing.setText('성장률 평활화 Å')
        w.spin_sputter_smoothing.setToolTip('수치 요철 억제 길이입니다. 물리적 표면 확산이나 공정 레시피가 아닙니다.')
        for layout in self.layouts:layout.addStretch(1)
        w.chk_typical_cvd.toggled.connect(self.changed)
        for spin in w.cvd_spins.values():spin.valueChanged.connect(self.changed)
        for check in (w.chk_depth_deposition,w.chk_sputter,w.chk_redepo,w.chk_inhibition_deposition,w.chk_incident_los):
            check.toggled.connect(self.sync)
        w.spin_cycles.valueChanged.connect(self.sync)
        w.spin_angstrom_per_cycle.valueChanged.connect(self.sync)
        w.spin_depth_feature_width.valueChanged.connect(self.sync)
        w.spin_depth_feature_depth.valueChanged.connect(self.sync)
        self.select(0)
        self.sync()
        from gapsim.emulation.parameter_help import install_parameter_help
        install_parameter_help(w,self)
        hint=self.note('ⓘ 항목 이름이나 입력값에 마우스를 올리면 움직이는 설명이 나옵니다. 키보드: F1')
        root.insertWidget(2,hint)
        self.help_hint = hint
        self.help_manager.preferences.enabledChanged.connect(self.update_help_hint)
        self.update_help_hint(self.help_manager.enabled)

    def update_help_hint(self, enabled):
        self.help_hint.setText('항목 설명: 마우스 올리기 또는 F1' if enabled else
                               '설명 말풍선 꺼짐 · 상단 설정에서 켤 수 있습니다.')

    @staticmethod
    def fold(title,widget):
        group=QGroupBox(title)
        group.setCheckable(True)
        group.setChecked(False)
        layout=QVBoxLayout(group)
        body=QWidget()
        inner=QVBoxLayout(body)
        inner.setContentsMargins(0,0,0,0)
        inner.addWidget(widget)
        layout.addWidget(body)
        body.hide()
        group.toggled.connect(body.setVisible)
        return group

    @staticmethod
    def note(text):
        label=QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet('color:#475569; padding:5px;')
        return label

    def select(self,n):
        self.stack.setCurrentIndex(n)
        for i,button in enumerate(self.buttons):button.setChecked(i==n)
        # Only the selected page contributes to the outer scroll area height.
        from PySide6.QtWidgets import QSizePolicy
        for i,page in enumerate(self.pages):
            page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred if i==n else QSizePolicy.Ignored)
        self.stack.adjustSize()

    def changed(self,*_):
        self.sync()
        self.w._invalidate_result_for_input_change()

    def conformal_only(self):
        for check in (self.w.chk_typical_cvd,self.w.chk_depth_deposition,self.w.chk_sputter,self.w.chk_inhibition_deposition):
            check.setChecked(False)
        self.w._invalidate_result_for_input_change()
        self.sync()

    def infer_geometry(self):
        try:
            width,depth=reference_geometry(self.w._current_geometry_points())
        except ValueError as exc:
            self.w.statusBar().showMessage(str(exc),6000)
            return
        self.w.spin_depth_feature_width.setValue(width)
        self.w.spin_depth_feature_depth.setValue(depth)
        self.w._invalidate_result_for_input_change()
        self.sync()

    def sync(self,*_):
        w=self.w
        cvd=w.chk_typical_cvd.isChecked()
        etch=w.chk_sputter.isChecked()
        inh=w.chk_inhibition_deposition.isChecked()
        self.cvd_fields.setEnabled(cvd)
        self.geometry_label.setText(f'계산 기준: 폭 {w.spin_depth_feature_width.value():g} Å / 깊이 {w.spin_depth_feature_depth.value():g} Å\n폭은 아래 설정값, 깊이는 구조 입력에서 갱신됩니다. 실제 단면과 다르면 가져오기로 맞추세요.')
        for widget in self.geometry_widgets:
            widget.setVisible(True)
            widget.setEnabled(True)
        line=str(w.cmb_depth_feature_type.currentData())=='line'
        w.spin_depth_feature_length.setVisible(line)
        w.lbl_depth_feature_length.setVisible(line)
        w.cmb_depth_feature_type.setEnabled(not cvd)
        w.spin_depth_feature_length.setEnabled(not cvd and line)
        w.lbl_depth_depo_section.setText('기존 Depth depletion · 호환 모델')
        w.chk_depth_deposition.setText('기존 깊이 감쇠 사용 (호환)')
        w.chk_ion_transmission.setText('기존 이온 깊이 감쇠 (호환)')
        w.lbl_sputter_smoothing.setText('수치 평활화 Å')
        self.summary.setText(f'적용: {"Typical CVD" if cvd else "기존 depth depletion" if w.chk_depth_deposition.isChecked() else "Conformal"}'
                             f' + Etch {"ON" if etch else "OFF"} / redep {"ON" if etch and w.chk_redepo.isChecked() else "OFF"}'
                             f' / Inhibition {"ON" if inh else "OFF"}')
        dose=w.spin_cycles.value()*w.spin_angstrom_per_cycle.value()
        self.dose_label.setText(f'누적 명목 증착량: {dose:g} Å ({dose/10:g} nm)\n실제 순 막 두께는 식각·재증착·CVD·억제에 따라 달라집니다.')
        self.sections['depth'].setEnabled(not cvd)
        w.depth_profile_group.setEnabled(not cvd and w.chk_depth_deposition.isChecked())
        # A read-only geometry summary remains available with either deposition model.
        los=etch and w.chk_redepo.isChecked() and w.chk_incident_los.isChecked()
        self.sections['ion'].setEnabled(not los)
        w.ion_map_group.setEnabled(not los and etch and w.chk_ion_transmission.isChecked())
        from gapsim.emulation.parameter_help import apply_simple_names
        apply_simple_names(w,self)
        if hasattr(self,'advanced_folds'):
            self.advanced_folds['cvd'].setEnabled(cvd)
            for key in ('direct','redepo','rays'):
                self.advanced_folds[key].setEnabled(etch if key=='direct' else etch and w.chk_redepo.isChecked())
            self.advanced_folds['inhibition'].setEnabled(inh)
            self.section_containers['depth'].setVisible(not cvd)
            self.section_containers['ion'].setVisible(not los)
            self.etch_effective.setText(f'각도 곡선 최대 식각량: {w.spin_sputter_strength.value()*w.spin_sputter_peak_pct.value()/100:g} Å/step (가림 적용 전)')
            self.etch_effective.setVisible(etch)
            self.dose_label.setText(f'누적 명목 증착량 {dose:g} Å ({dose/10:g} nm) · 식각/보정 전')

    def reorder(self,order):
        # Reordering remains available within each physical category; it cannot
        # silently move a deposition model under etch.
        for key in order:
            if key in ('depth','inhibition') or key not in self.sections:continue
            container=getattr(self,'section_containers',{}).get(key,self.sections[key])
            self.layouts[2].removeWidget(container)
            self.layouts[2].insertWidget(self.layouts[2].count()-1,container)

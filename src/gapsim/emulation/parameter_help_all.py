"""Coverage for settings outside the four process pages and curve handles."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import (QWidget, QLabel, QAbstractSpinBox, QComboBox, QCheckBox,
    QSlider, QLineEdit, QPlainTextEdit, QAbstractButton, QGroupBox, QGridLayout, QLayout)
from .parameter_help import HELP, ParameterHelp, spec

DISPLAY='화면 표시만 바뀝니다. 계산된 형상이나 공정 조건은 바뀌지 않습니다.'
LEGACY='현재 기본 통합 모델에서는 사용하지 않는 호환용 항목입니다. 값을 바꿔도 현재 계산에는 적용되지 않습니다.'

EXTRA = {
 'cmb_split_parameter':spec('비교할 항목','Split에서 하나씩 바꿔 계산할 파라미터를 선택합니다.','한 항목의 작은 값 조건','같은 항목의 큰 값 조건','split','선택한 항목에 따라 단위와 효과가 달라집니다. Split 실행 시 여러 조건을 계산합니다.'),
 'spin_split_start':spec('시작값','Split 조건 범위의 첫 값입니다.','더 작은 값부터 비교','더 큰 값부터 비교','split','선택한 파라미터의 단위를 사용합니다. 시작·끝·간격을 함께 확인하세요.'),
 'spin_split_end':spec('끝값','Split 조건 범위의 마지막 한계값입니다.','비교 범위의 상한 감소','비교 범위의 상한 증가','split','간격에 따라 끝값 자체가 포함되지 않을 수 있습니다. 실행 전 생성 조건을 확인하세요.'),
 'spin_split_step':spec('비교 간격','인접한 Split 조건 사이의 값 차이입니다.','촘촘한 비교: 조건 수와 시간이 증가','성긴 비교: 조건 수와 시간이 감소','sampling','0은 사용할 수 없습니다. 한 번의 증착 Step 크기가 아닙니다.'),
 'cmb_compare_target':spec('비교 모델','현재 설정과 나란히 계산할 비교 모델을 고릅니다.','현재 모델 결과','선택한 비교 모델 결과','split','모델 선택이므로 크고 작음의 의미는 없습니다. 조건별 지원 파라미터가 다를 수 있습니다.'),
 'spin_smooth_segments':spec('분할 수','입력 구조를 스무딩하기 전에 나누는 조각 수입니다.','성긴 점으로 구조 표현','촘촘한 점으로 구조 표현','quality','스무딩 적용 후 스무딩 사용을 선택해야 계산 입력이 바뀝니다. 공정 중 표면 점 간격과 별개입니다.'),
 'spin_smooth_iterations':spec('스무딩 횟수','입력 구조의 모서리를 부드럽게 만드는 반복 횟수입니다.','원래 모서리를 더 유지','모서리가 더 둥글어짐','smooth','스무딩 적용 후 스무딩 사용을 선택하면 초기 구조가 달라져 결과에도 영향을 줍니다.'),
 'slider_frame':spec('결과 단계','이미 계산된 결과 중 표시할 프레임을 선택합니다.','이전 계산 단계 표시','이후 계산 단계 표시','frames',DISPLAY),
 'slider_overlay_opacity':spec('이미지 불투명도','겹쳐 보여주는 이미지의 진하기입니다.','더 투명하게 표시','더 진하게 표시','opacity',DISPLAY),
 'chk_show_etch_overlay':spec('식각 표시','제거된 영역의 파란 표시를 켜거나 끕니다.','파란 표시 숨김','파란 표시 보임','opacity',DISPLAY),
 'chk_show_redepo_overlay':spec('재증착 표시','재부착 영역의 빨간 표시를 켜거나 끕니다.','빨간 표시 숨김','빨간 표시 보임','opacity',DISPLAY),
 'chk_symmetric_structure_edit':spec('좌우대칭 편집','구조 점을 옮길 때 반대편 점도 대칭으로 움직입니다.','선택한 점만 이동','반대편 점도 함께 이동','coordinates','초기 구조를 편집하는 기능입니다. 이후 계산 결과가 달라질 수 있습니다.'),
 'cmb_structure_library':spec('구조 선택','저장한 구조를 불러와 초기 단면으로 사용합니다.','현재 구조','선택한 저장 구조','coordinates','구조가 바뀌므로 이후 시뮬레이션 결과도 달라집니다.'),
 'edit_structure_name':spec('구조 이름','저장할 구조의 이름입니다.','짧은 이름','조건을 구분할 이름','display','이름 자체는 물리 계산에 영향이 없습니다. 저장 버튼을 눌러 반영합니다.'),
 'edit_parameter_preset_name':spec('프리셋 이름','현재 공정 조건을 저장할 이름입니다.','짧은 이름','조건을 구분할 이름','display','이름 자체는 결과를 바꾸지 않습니다. 같은 이름 저장 시 기존 항목을 확인하세요.'),
 'edit_request_note':spec('공정 메모','관찰 내용이나 조건 설명을 기록합니다.','간단한 기록','상세한 기록','display','메모는 물리 계산에 사용하지 않습니다. 결과 파일명과 요약에 포함됩니다.'),
 'cmb_parameter_preset':spec('공정 프리셋','저장한 공정 조건 묶음을 선택합니다.','현재 조건 유지','선택 조건을 적용해 비교','split','적용 버튼으로 반영합니다. 구조는 유지되지만 여러 공정값이 함께 바뀝니다.'),
 'cmb_emulator_default_preset':spec('기본 프리셋','기본 모델의 시작 조건을 선택합니다.','현재 입력 조건','선택한 기본 조건','split','기본 조건을 적용하면 관련 파라미터가 바뀔 수 있습니다.'),
 'cmb_incident_preset':spec('검증 프리셋','이온 가림·재증착 연구에 사용한 조건 묶음입니다.','현재 조건','선택한 검증 조건','split','적용 버튼으로 반영합니다. 실제 장비에서 보정한 레시피라는 뜻은 아닙니다.'),
 'chk_incident_preset_geometry':spec('프리셋 구조 적용','검증 조건을 적용할 때 보고서의 트랜치 구조도 가져옵니다.','현재 구조 유지','보고서 구조로 변경','coordinates','체크만으로는 바뀌지 않습니다. 프리셋 적용 시 구조까지 변경됩니다.'),
 'btn_move_overlay':spec('이미지 이동','겹쳐진 이미지를 움직여 단면과 정렬합니다.','이미지 이동 잠금','마우스로 이미지 이동','coordinates',DISPLAY),
 'btn_overlay_compare':spec('결과 겹쳐보기','두 계산 결과를 같은 좌표에 겹쳐 비교합니다.','나란히 보기','겹쳐 보기','opacity',DISPLAY),
 'btn_split_options':spec('Split 설정','파라미터를 여러 값으로 바꾸는 비교 설정을 펼칩니다.','설정 숨김','설정 펼침','split','설정을 펼치는 것만으로 계산이나 조건 변경이 일어나지 않습니다.'),
 'btn_compare_options':spec('Compare 설정','다른 모델과 비교하는 설정을 펼칩니다.','설정 숨김','설정 펼침','split','Compare 실행 전까지 새 비교 계산을 하지 않습니다.'),
 'btn_depth_advanced':spec('고급 설정','기존 증착 감쇠의 닫힘 이후 설정을 펼칩니다.','고급 항목 숨김','고급 항목 표시','display','펼치기만으로 값은 바뀌지 않습니다. 새 CVD에는 잔류 채움 항을 적용하지 않습니다.'),
 'structure_points_table':spec('구조 좌표','X는 좌우 위치, Y는 높이입니다. 좌표의 단위는 Å입니다.','작은 X: 왼쪽 / 작은 Y: 아래','큰 X: 오른쪽 / 큰 Y: 위','coordinates','셀 편집으로 초기 구조를 변경합니다. 축척과 점 순서, 교차 여부를 확인하세요.'),
 'smoothed_points_table':spec('스무딩 좌표','스무딩된 구조 좌표를 확인합니다.','스무딩 전 구조','스무딩 후 구조','smooth','이 표는 읽기 전용입니다. 스무딩 횟수 또는 그림의 점을 통해 조절하세요.'),
 'structure_view':spec('구조 점 편집','구조 점을 끌어서 초기 단면을 바꿉니다.','왼쪽·아래로 이동','오른쪽·위로 이동','coordinates','입구 폭·깊이가 달라지면 공급과 닫힘 결과도 달라집니다. 드래그 중에는 도움말을 띄우지 않습니다.'),
 'smoothing_view':spec('스무딩 구조 편집','스무딩한 단면의 점 위치를 조절합니다.','원래 형상 쪽으로 수정','원하는 곡선 쪽으로 수정','smooth','스무딩 사용을 선택해야 계산 입력으로 쓰입니다.'),
 'addon_list':spec('애드온 사용','목록의 체크 표시로 설치된 애드온을 켜거나 끕니다.','해당 애드온 OFF','해당 애드온 ON','display','영향은 각 애드온 구현에 따릅니다. 공통으로 막이 두꺼워지거나 얇아진다고 해석하지 마세요.'),
 'cmb_redepo_source_model':spec('재증착 원료 모델','재증착에 공급할 식각 원료 모델입니다.','기존 원료 모델','선택 원료 모델','display',LEGACY),
 'spin_redepo_soft_los':spec('가림 경계 보정','과거 수송 경로의 가림 경계 보정 단계입니다.','보정 없음','보정 단계 증가','display',LEGACY),
}

# Retained fields must have honest help, even if a future compatibility UI exposes them.
for key,title in {
 'chk_reflected_ion':'반사 이온', 'spin_reflected_strength':'반사 세기',
 'spin_reflected_bowing':'측벽 확장', 'spin_reflected_microtrench':'바닥 모서리 식각',
 'spin_reflected_range':'반사 영향 거리', 'chk_lf_overhang':'LF 형상 보정',
 'spin_lf_overhang_dose':'LF 보정량', 'spin_lf_overhang_sputter_gain':'식각 배율',
 'spin_lf_overhang_redepo_fraction':'재증착 비율', 'spin_lf_overhang_survival':'잔류 비율',
 'spin_lf_overhang_width':'보정 폭', 'chk_closure_redepo':'닫힘 재증착 보정',
 'spin_closure_redepo_efficiency':'닫힘 재증착률', 'spin_closure_redepo_shadow_gain':'가림 포집 배율',
 'spin_closure_redepo_width':'포집 폭', 'spin_closure_redepo_survival':'잔류 비율',
 'spin_closure_redepo_smoothing':'포집 평활화',
}.items():EXTRA[key]=spec(title,'과거 모델과 파일 호환을 위해 남겨둔 설정입니다.','현재 계산 변화 없음','현재 계산 변화 없음','display',LEGACY)

HANDLES = {
 'sputter_curve_editor':{'peak':'spin_sputter_peak','left_width':'spin_sputter_width','right_width':'spin_sputter_width'},
 'ion_transmission_editor':{'start':'spin_ion_start_depth','strength':'spin_ion_decay_strength','curve':'spin_ion_curve_power'},
 'depth_deposition_editor':{'attenuation':'spin_depth_decay_k','power':'spin_depth_decay_power','floor':'spin_depth_min_ratio_pct','closure':'spin_depth_closure_threshold'},
 'inhibition_profile_editor':{'strength':'spin_inhibition_strength','penetration':'spin_inhibition_penetration',
    'power':'spin_inhibition_decay_power','floor':'spin_inhibition_min_growth','boost':'spin_inhibition_bottom_boost','recombination':'spin_inhibition_recombination'},
 'redepo_lobe_editor':{'efficiency':'spin_redepo_efficiency','emit_left':'spin_redepo_emit_power','emit_right':'spin_redepo_emit_power','distance':'spin_redepo_distance_power'},
}


def bind_grid_labels(root,manager):
    # Recurse layouts as well as widgets: smoothing uses nested grids. Match only
    # the closest preceding label in the same row (there may be several fields).
    # QObject traversal includes nested layouts without walking QMainWindow's
    # private layout items (their wrappers are not stable in PySide).
    for layout in root.findChildren(QGridLayout):
            labels=[]
            fields=[]
            for i in range(layout.count()):
                widget=layout.itemAt(i).widget()
                row,col,_,_=layout.getItemPosition(i)
                if isinstance(widget,QLabel):labels.append((row,col,widget))
                elif widget in manager.bindings:fields.append((row,col,widget))
            for row,col,control in fields:
                candidates=[(c,label) for r,c,label in labels if r==row and c<col]
                if candidates:
                    _,label=max(candidates,key=lambda pair:pair[0])
                    entry,actual=manager.bindings[control]
                    manager.bind(label,entry,actual)


def install_extended_help(owner,manager=None):
    manager=manager or ParameterHelp(owner)
    for key,entry in EXTRA.items():
        widget=getattr(owner,key,None)
        if widget is not None:
            widget.setProperty('helpParameterKey',key)
            manager.bind(widget,entry)
    for name,mapping in HANDLES.items():
        editor=getattr(owner,name,None)
        if editor is None:continue
        def resolve(pos,editor=editor,mapping=mapping):
            handle=editor._hit_handle(QPointF(pos))
            if handle in mapping:
                key=mapping[handle]
                return HELP[key],getattr(owner,key)
            entry=spec('곡선 편집','조절점 위에 마우스를 올리면 해당 값의 설명이 나옵니다. 점을 끌면 연결된 입력값도 바뀝니다.',
                       '조절점을 한쪽으로 이동','반대쪽으로 이동','display','선택한 조절점에 따라 효과가 다릅니다. 드래그 중에는 도움말이 나타나지 않습니다.')
            return entry,editor
        manager.resolvers[editor]=resolve
    # Explicit overview for multi-axis peak: one handle edits angle AND height.
    editor=getattr(owner,'sputter_curve_editor',None)
    if editor is not None:
        previous=manager.resolvers[editor]
        def sputter_resolve(pos):
            if editor._hit_handle(QPointF(pos))=='peak':
                return spec('최대 식각 각도 · 식각 세기','꼭짓점을 좌우로 움직이면 최대 식각 각도, 위아래로 움직이면 식각 세기가 바뀝니다.',
                            '왼쪽: 작은 각도 / 아래: 약한 식각','오른쪽: 큰 각도 / 위: 강한 식각','angle'),editor
            return previous(pos)
        manager.resolvers[editor]=sputter_resolve
    table=getattr(owner,'structure_points_table',None)
    if table is not None:
        def coordinate_help(pos):
            index=table.indexAt(table.viewport().mapFrom(table,pos.toPoint() if isinstance(pos,QPointF) else pos))
            if not index.isValid():return EXTRA['structure_points_table'],table
            axis='X' if index.column()==0 else 'Y'
            table.setProperty('helpCurrentValue',f'{index.row()+1}행 {axis}: {index.data()} Å')
            return spec(axis+' 좌표','X는 좌우 위치, Y는 높이입니다. 셀을 편집하면 초기 단면이 바뀝니다.',
                        '왼쪽 이동' if axis=='X' else '아래로 이동 (깊어짐)',
                        '오른쪽 이동' if axis=='X' else '위로 이동 (얕아짐)',
                        'coordinate_x' if axis=='X' else 'coordinate_y','좌표 단위는 Å입니다. 점 순서와 자기 교차를 확인하세요.'),table
        manager.resolvers[table]=coordinate_help
    panel=getattr(owner,'process_parameter_panel',None)
    if panel is not None:
        for button in panel.buttons:
            manager.bind(button,spec('공정 항목 보기',button.text()+' 설정 페이지로 이동합니다.',
                                    '현재 페이지','선택한 페이지','display','페이지 선택만으로 공정을 켜거나 끄지 않습니다.'))
    for button in getattr(owner, 'workflow_buttons', []):
        manager.bind(button,spec('작업 단계',button.text()+' 화면으로 이동합니다.',
                                '현재 화면','선택한 화면','display','단계 이동만으로 입력 조건이나 결과를 바꾸지 않습니다.'))
    for widget in owner.findChildren(QWidget):
        if manager.bubble.isAncestorOf(widget):continue
        if isinstance(widget,QGroupBox) and widget.isCheckable():
            manager.bind(widget,spec('상세 설정 보기',widget.title()+' 항목을 펼치거나 접습니다.','상세 항목 숨김','상세 항목 표시','display','펼치기만으로 계산 조건은 바뀌지 않습니다.'))
        # Attach unknown future/addon controls honestly; do not invent physics.
        if is_value_control(widget) and manager.lookup(widget) is None:
            manager.bind_fallback(widget)
    bind_grid_labels(owner,manager)
    owner.parameter_help=manager
    return manager


def is_value_control(widget):
    # Qt's toolbar overflow chevron is window chrome, not an editable setting.
    if widget.objectName()=='qt_toolbar_ext_button':return False
    return (isinstance(widget,(QAbstractSpinBox,QComboBox,QSlider,QCheckBox))
            or isinstance(widget,(QLineEdit,QPlainTextEdit)) and not widget.isReadOnly()
            or isinstance(widget,QAbstractButton) and widget.isCheckable())

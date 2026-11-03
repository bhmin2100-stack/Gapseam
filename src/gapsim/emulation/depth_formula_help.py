"""Read-only depth-rate plots from the exact equation used by the solver."""
from dataclasses import replace
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from .depth_formula import load_parameters, growth_ratios


def install(owner, manager):
    from .parameter_help import spec
    notes = {
        'law': ('성장식', '깊이별 성장률을 정하는 경험식을 고릅니다. 세 식은 서로 다른 대안입니다.'),
        'depth_unit': ('z 단위', '음수 깊이 z를 nm 또는 Å 숫자로 식에 넣습니다. 변경 시 계수는 자동 변환하지 않습니다.'),
        'reference': ('깊이 기준', '실행 시작 상면을 고정하거나 이동한 현재 최고 상면에서 깊이를 잽니다. 기준면 위쪽은 깊이 0입니다.'),
        'decay_per_nm': ('감쇠계수', 'exp(−k×깊이_nm)의 k입니다. 클수록 깊은 곳의 성장률이 더 빨리 감소합니다.'),
        'linear_slope': ('선형 계수 a', 'f(z)의 a×z 항입니다. z≤0이므로 a를 높이면 깊은 곳의 원식 출력이 작아집니다.'),
        'linear_constant': ('상수 b', '원식 전체를 위아래로 이동합니다. f(0)도 변하므로 정규화 후의 영향은 다른 항과 함께 결정됩니다.'),
        'linear_exp_gain': ('지수 계수 c', '(1−z/L)exp(z/L)의 크기입니다. f(0)도 함께 바뀌며 국소 성장률은 그 비율로 정해집니다.'),
        'linear_length': ('지수 길이 L', '지수항이 깊이에 따라 변하는 길이 척도입니다. z와 같은 단위이며 0보다 커야 합니다.'),
        'cubic_a': ('3차 계수 a', 'a×z³ 항입니다. z≤0이므로 a를 더 음수로 만들면 깊은 곳의 출력이 증가합니다.'),
        'cubic_b': ('2차 계수 b', 'b×z² 항입니다. b를 높이면 깊이에 따른 출력이 증가합니다. 다른 차수 항과 합산됩니다.'),
        'cubic_c': ('1차 계수 c', 'c×z 항입니다. z≤0이므로 c를 높이면 깊은 곳의 출력이 감소합니다.'),
        'cubic_d': ('상수 d', '3차식의 f(0)입니다. 다른 계수를 고정하고 d를 바꾸면 정규화 비율도 함께 바뀝니다.'),
    }
    for key, control in owner.depth_formula_controls.items():
        title, meaning = notes[key]
        categorical = key in ('law','depth_unit','reference')
        entry = spec(title, meaning, '선택한 식·단위·기준으로 계산' if categorical else '계수만 작은 값으로 비교',
            '선택한 식·단위·기준으로 계산' if categorical else '계수만 큰 값으로 비교', 'depth_formula',
            '경험식 성장률 비교입니다. 최종 단면 예측이 아닙니다. 음수·과도한 외삽 조건은 실행이 중단됩니다. 원식의 단위와 적용 범위를 확인하세요.')
        control.setProperty('helpParameterKey', 'depth_formula_'+key)
        manager.bind(control, entry)
        label = getattr(owner, 'depth_formula_labels', {}).get(key)
        if label is not None: manager.bind(label, entry, control)


def curves(config, key):
    p = load_parameters(config.depth_formula)
    depth = max(y for x,y in config.points)-min(y for x,y in config.points)
    depths = np.linspace(0, max(depth, 1.), 201)
    field = key.removeprefix('depth_formula_')
    value = getattr(p, field, None)
    choices = [('현재', p)]
    if isinstance(value, (int,float)) and field != 'version':
        delta = abs(value)*.2 if value else .0001
        lower = max(0., value-delta) if field=='decay_per_nm' else max(1e-9,value-delta) if field=='linear_length' else value-delta
        choices = [(f'{lower:.4g}', replace(p, **{field:lower})), ('현재',p),
                   (f'{value+delta:.4g}', replace(p, **{field:value+delta}))]
    lines, errors = [], []
    for label, candidate in choices:
        try: values = growth_ratios(depths, load_parameters(candidate))
        except ValueError: errors.append(label+' 범위 밖'); continue
        lines.append((label, values))
    return depths/10., lines, errors


def draw(animation, painter):
    title = '현재 식의 성장률' if animation.key in ('depth_formula_law','depth_formula_depth_unit','depth_formula_reference') else '현재 식의 성장률 · 계수 하나만 ±20% 비교'
    animation.label(painter, title, 0, size=13)
    config = getattr(animation, 'formula_config', None)
    if config is None:
        animation.label(painter, '깊이식을 선택한 뒤 계수를 확인하세요.', 40)
        return
    try: depths, lines, errors = curves(config, animation.key)
    except (ValueError, TypeError):
        animation.label(painter, '입력한 식과 계수·깊이 범위를 확인하세요.', 40)
        return
    rect = QRectF(62,56,410,232)
    painter.setPen(QPen(QColor('#94a3b8'),1))
    painter.drawLine(rect.topLeft(),rect.bottomLeft())
    painter.drawLine(rect.topLeft(),rect.topRight())
    xmax = max([float(v.max()) for _,v in lines]+[1.])
    colors = ('#008694','#6c58b5','#db790c')
    for index,(label,values) in enumerate(lines):
        points = [QPointF(rect.left()+float(v)/xmax*rect.width(),rect.top()+float(d)/depths[-1]*rect.height()) for d,v in zip(depths,values)]
        curve=QPainterPath(points[0])
        for point in points[1:]:curve.lineTo(point)
        color=QColor(colors[index]);painter.setPen(QPen(color,2));painter.setBrush(Qt.NoBrush);painter.drawPath(curve)
        painter.drawText(QRectF(70+index*133,30,130,22), Qt.AlignLeft, label)
        point=points[int(animation.phase*(len(points)-1))]
        painter.setBrush(color);painter.drawEllipse(point,3,3)
    animation.label(painter, f'→ 성장률 / 평탄부 (0 ~ {xmax:.3g})   ↓ 깊이 (0 ~ {depths[-1]:g} nm)', 292, size=11)
    animation.label(painter, ' · '.join(errors) or '곡선은 실제 깊이식 계산값입니다. 최종 형상은 별도 실행하세요.', 315, size=11)

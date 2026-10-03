"""Local, read-only animated explanations for the process controls.

Packaged movies contain actual engine-simulated example trench profiles.
Hover only reads these local assets; it never runs or modifies the user's job.
"""
from dataclasses import dataclass

from PySide6.QtCore import QObject, QEvent, QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QWidget, QFrame, QLabel, QPushButton,
                              QVBoxLayout, QHBoxLayout, QScrollArea, QAbstractSpinBox,
                              QComboBox, QCheckBox, QSlider, QGridLayout)
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QAbstractButton, QGroupBox
from PySide6.QtWidgets import QButtonGroup


@dataclass(frozen=True)
class HelpSpec:
    title: str
    meaning: str
    low: str
    high: str
    kind: str = 'growth'
    caution: str = '다른 조건을 고정한 정성적 설명입니다. 실제 결과는 구조·공정 조합에 따라 달라집니다.'


def spec(title, meaning, low, high, kind='growth', caution=''):
    return HelpSpec(title, meaning, low, high, kind, caution or HelpSpec.__dataclass_fields__['caution'].default)


# Keys are the existing authoritative widget attributes; no duplicate parameters.
HELP = {
 'spin_cycles': spec('계산 Step 수', '증착과 식각 계산을 몇 번 반복할지 정합니다.', '계산 반복 감소', '계산 반복 증가', 'growth', '실제 시간이나 ALD cycle 수가 아닙니다. 식각·닫힘 때문에 Step이 늘어도 순 막두께가 계속 증가하지는 않습니다.'),
 'spin_angstrom_per_cycle': spec('기본 증착량 · Å/step', '한 Step에 더하는 기본 막 두께입니다. 10 Å = 1 nm입니다.', '한 번에 얇게 증착', '한 번에 두껍게 증착', 'growth', '0이면 증착은 없고 켜진 식각만 진행합니다. 실제 순 두께는 CVD·식각·억제에 따라 달라집니다.'),
 'spin_reparam_ds': spec('표면 점 간격 · 계산 해상도', '단면 곡선을 얼마나 촘촘한 점으로 나눌지 정합니다.', '촘촘한 점: 정밀하지만 느림', '성긴 점: 빠르지만 세부 형상 손실', 'mesh', '막질을 바꾸는 공정 조건이 아닙니다. 그림의 점 개수만 비교하세요.'),
 'cmb_quality_mode': spec('계산 품질', '표면 점 간격을 묶어서 선택하는 설정입니다.', '빠른 모드: 성긴 표면 점', '정밀 모드: 촘촘한 표면 점', 'quality', '공정 효과가 아닌 수치 설정입니다. 정밀도를 올려도 실측 정확도가 보장되지는 않습니다.'),
 'chk_typical_cvd': spec('Typical CVD 켜기', '상부 측벽·모서리 성장 강화와 깊이에 따른 성장 감소를 조합합니다.', 'OFF: 다른 활성 증착 모델 사용', 'ON: CVD 형상 계수 적용', 'overhang', '실제 온도·압력으로 보정된 해석이 아닌 경험식입니다. 기존 깊이 감쇠와 중복 적용하지 않습니다.'),
 'cvd_overhang_pct': spec('Overhang · 입구 측벽 성장', '트랜치 입구 근처 측벽에 막이 더 자라도록 합니다.', '추가 강화가 작아 입구가 덜 좁아짐', '상부 측벽 성장이 커져 입구가 더 좁아짐', 'overhang'),
 'cvd_cusping_pct': spec('Cusping · 어깨 성장 집중', '평탄부와 벽이 만나는 경사진 모서리 주변의 성장을 강화합니다.', '모서리의 추가 성장이 적음', '모서리 부근에 성장이 더 집중', 'cusp', '최종 뾰족함이나 패임 깊이를 직접 지정하는 값은 아닙니다.'),
 'cvd_bottom_ratio_pct': spec('Bottom 성장률', '기준 깊이에서 평탄부 대비 기본 성장률을 정합니다.', '바닥 성장이 작아 depletion 증가', '바닥 성장이 커져 depletion 감소', 'bottom', '100%는 기본 깊이 감쇠 없음. 0%는 기준 깊이의 기본 성장 없음. 억제·상부 강화 적용 전 값입니다.'),
 'cvd_upper_length_a': spec('상부 영향 길이', 'Overhang과 Cusping 강화의 깊이 범위, Cusping의 좌우 범위를 함께 정합니다.', '입구·모서리 가까이에 집중', '입구 아래와 모서리 주변 더 넓게 영향', 'length', 'Å 단위입니다. 강화 계수가 0이면 이 길이를 바꿔도 강화 효과는 없습니다.'),
 'cvd_depth_power': spec('Depletion 곡선 지수', '입구에서 바닥까지 성장률이 감소하는 곡선 모양입니다.', '입구부터 비교적 빨리 감소', '상부 성장을 유지하다 깊은 곳에서 감소', 'power', '기준 깊이의 Bottom 비율 자체는 바꾸지 않습니다. Bottom 100%이면 영향이 없습니다.'),
 'chk_sputter': spec('Etch · 식각 켜기', '입사 각도에 따른 수율로 표면의 물질을 제거합니다.', 'OFF: 직접 식각과 재증착 원료 없음', 'ON: 식각 및 재증착 원료 생성 가능', 'etch'),
 'spin_sputter_strength': spec('식각량 · Å/step', '한 Step의 식각 기준 크기입니다. 각도 응답과 가림이 이를 조절합니다.', '덜 깎임, 재증착 원료도 줄 수 있음', '더 깎임, 재증착 원료도 늘 수 있음', 'etch', 'Etch ON에서 적용. 많이 깎는다고 모든 위치의 최종 막이 얇아지는 것은 아닙니다.'),
 'spin_sputter_peak_pct': spec('식각 수율 높이 · Peak %', '각도별 식각 응답 곡선의 전체 높이를 바꿉니다.', '모든 각도의 식각 응답 감소', '모든 각도의 식각 응답 증가', 'amplitude'),
 'spin_sputter_peak': spec('최대 식각 각도 · Peak', '표면 법선과 입사 방향 사이에서 식각이 가장 강한 각도입니다.', '법선에 가까운 입사에서 최대', '더 비스듬한 입사에서 최대', 'angle', '각도를 옮기는 설정입니다. 전체 식각량이 무조건 증가하는 것은 아닙니다.'),
 'spin_sputter_width': spec('식각 각도 폭 · Width', '최대 수율 주위에서 식각이 유효한 각도 범위입니다.', '좁은 각도 범위에 집중', '넓은 각도 범위에서 식각', 'spread'),
 'spin_sputter_smoothing': spec('식각 수치 평활화', '표면 법선을 평균화해 식각 각도와 이동·방출 방향을 바꿉니다. 통합 재증착 경로에서는 결과 단면의 짧은 요철도 완화합니다.', '법선과 국소 형상을 더 유지', '더 넓은 이웃을 평균화', 'smooth', '물리적 확산이 아닙니다. 이온 가림 OFF 경로에서는 식각량 분포도 평활화합니다. 모든 패임이 사라지거나 식각 총량이 보존된다는 뜻은 아닙니다.'),
 'chk_incident_los': spec('입사 이온 가림', '입구에서 표면까지 실제로 열린 방향만 식각 원료 계산에 포함합니다.', 'OFF: 이 기하학적 가림 미적용', 'ON: 다른 벽에 막힌 방향 제외', 'shadow', '현재 통합 모델에서 Etch와 Redepo가 켜져야 적용됩니다. LF 전력 자체가 가려지는 해석은 아닙니다.'),
 'spin_incident_sigma': spec('입사 이온 각도 퍼짐 · σ', '수직 입사를 중심으로 이온 방향이 퍼지는 폭입니다.', '수직 부근에 집중', '비스듬한 입사 방향도 증가', 'spread', '깊은 곳의 도달량은 가림·각도 수율과 함께 결정됩니다. σ 증가가 깊은 redep 증가를 보장하지 않습니다.'),
 'spin_incident_rays': spec('입사 이온 방향 수', '±4σ의 각도 분포를 홀수 개 방향으로 나누어 적분합니다. 방향별 가중치 합은 항상 1입니다.', '적은 방향으로 근사', '더 많은 방향으로 세밀하게 근사', 'rays', '물리적인 이온 수나 플라즈마 세기가 아닙니다. 방향 수를 늘려도 총 입사량을 늘리는 설정은 아닙니다.'),
 'chk_redepo': spec('Redeposition · 재증착', '식각 원료 중 방출 축이 맞은편 측벽에 도달한 원료를 도착점 주변에 분배합니다.', 'OFF: 재부착과 새 이온 가림 경로 OFF', 'ON: 유효한 원료를 맞은편 벽에 재분배', 'redepo', '현재 구현에서는 재증착 OFF 시 새 이온 가림도 꺼져 식각량까지 달라질 수 있습니다. 재부착만 0으로 비교하려면 재증착·이온 가림 ON에서 재증착률을 0%로 두세요.'),
 'spin_redepo_efficiency': spec('재증착 효율', '맞은편 벽에 유효하게 도달한 원료량에 곱하는 비율입니다. 탈출한 원료는 제외합니다.', '도달 원료 중 되붙는 비율 감소', '도달 원료 중 되붙는 비율 증가', 'redepo', '전체 식각량의 이 비율이 반드시 붙는 것은 아닙니다. 0%에서는 재부착량이 0이며, 이온 가림이 ON이면 가림 계산은 유지됩니다.'),
 'spin_redepo_emit_power': spec('재증착 분포 폭 · Angular spread', '현재 엔진은 원료마다 방출 축 하나로 도착점을 찾고, 그 주변 측벽을 따라 가우시안 분배합니다. 이 각도는 분배 폭을 정합니다.', '도착점 가까이에 집중', '도착점 주변 더 넓은 구간에 분배', 'spread', '여러 방출 광선을 추가하는 값이 아닙니다. 폭 = 거리 × tan(각도), 최소 1.5×점 간격·최대 수송 거리 제한. 총량은 정규화하며 각 분배점의 가림을 다시 추적하지는 않습니다.'),
 'spin_redepo_distance_power': spec('재증착 방향 편향 · Specular bias', '표면 법선과 수직 입사를 가정한 반사 방향을 혼합해 방출 축을 정합니다.', '음수: 법선에서 반사축의 반대쪽으로 편향', '양수: 반사 방향 쪽으로 편향', 'angle', '0%는 법선, 100%는 반사축 기준입니다. 거리 감쇠 지수가 아닙니다. 실제 법선에 따라 달라지므로 깊은 곳이나 얕은 곳으로 이동한다고 단정할 수 없습니다.'),
 'chk_inhibition_deposition': spec('Inhibition · 증착 억제', '표면이 자라는 비율에 억제 계수를 곱합니다.', 'OFF: 이 억제 없음', 'ON: 주로 상부 성장 억제', 'inhibit', '식각이 아니라 성장 감소입니다. Bottom boost는 별도 성장 보강 항입니다.'),
 'spin_inhibition_strength': spec('억제 강도', '억제제가 있는 곳의 증착을 얼마나 줄일지 정합니다.', '억제제 피복에 의한 성장 감소가 약해짐', '피복이 큰 곳의 성장 감소가 강해짐', 'inhibit', '0%여도 바닥 성장 보강과 재결합 손실은 남습니다. 억제 모델 전체를 끄려면 증착 억제 OFF를 선택하세요.'),
 'spin_inhibition_penetration': spec('억제 침투 깊이', '억제 효과가 입구에서 얼마나 깊이까지 유지될지 정합니다.', '입구 근처만 주로 억제', '더 깊은 측벽까지 억제', 'penetration'),
 'spin_inhibition_decay_power': spec('억제 감쇠 지수', '깊이에 따라 억제제 피복이 줄어드는 곡선 모양입니다.', '침투 길이 주변에서 완만하게 전환', '침투 길이 주변에서 급격하게 전환', 'inhibit_power', '침투 길이보다 얕은 곳과 깊은 곳의 변화 방향이 다릅니다. 전체 억제 증가 값이 아닙니다.'),
 'spin_inhibition_min_growth': spec('최소 성장률', '억제 모델이 만드는 성장 배율의 하한입니다.', '더 낮은 배율 허용', '하한에 걸린 구간의 배율 증가', 'floor', 'CVD 배율을 곱하기 전 하한입니다. 바닥 보강 때문에 100%로 두어도 배율이 1보다 클 수 있습니다. 억제 배율의 상한은 2입니다.'),
 'spin_inhibition_bottom_boost': spec('Bottom boost · 바닥 성장 보강', '억제가 약해진 깊은 부분의 성장률을 추가로 올립니다.', '깊은 곳의 추가 성장 적음', '깊은 곳의 추가 성장 증가', 'bottom', '경험적 보강 항이며 원료 수송 보존 해석이나 억제 자체가 아닙니다.'),
 'spin_inhibition_recombination': spec('재결합 손실 가중치', '기존 깊이 감쇠식으로 구한 공급 손실에 가중치를 곱합니다. 현재 Hybrid 모델은 그 절반을 성장 손실로 반영합니다.', '추가 성장 손실 감소', '공급 손실이 있는 곳의 성장 손실 증가', 'depletion', '기준 형상·폭·길이, 기존 감쇠 강도·지수·최소 비율도 이 항에 영향을 줍니다. CVD ON 또는 기존 증착 감쇠 OFF여도 억제 ON이면 이 의존성이 남습니다.'),
 'spin_inhibition_smoothing': spec('성장률 평활화', '이웃한 위치의 성장률 변화를 완만하게 합니다.', '국소 성장률 차이를 유지', '짧은 구간의 성장률 차이를 완화', 'smooth', '그림은 성장률 곡선이며 실제 단면 평활화를 보장하지 않습니다.'),
 'chk_depth_deposition': spec('기존 깊이 감쇠 모델', '깊이와 폭의 비로 증착 공급 감소를 근사하는 호환 모델입니다.', 'OFF: 기존 감쇠 없음', 'ON: 깊은 곳의 증착 감소', 'depletion', '새 Typical CVD ON이면 중복 적용되지 않습니다.'),
 'cmb_depth_feature_type': spec('기준 형상 · Hole / Line', '기존 감쇠와 억제 재결합의 유효 종횡비 계산 방식입니다.', 'Hole: 깊이 / 폭', '긴 Line: 깊이 / (2×폭)', 'geometry', '구조 좌표 자체를 바꾸지 않습니다. CVD 성장식 자체에는 없지만 함께 켠 억제 재결합에는 적용됩니다.'),
 'spin_depth_feature_width': spec('기준 입구 폭', 'CVD 모서리 위치와 호환 수송 모델의 기준 폭입니다.', '좁은 기준 입구', '넓은 기준 입구', 'geometry', '실제 구조를 늘리는 값이 아닙니다. 현재 구조에서 가져오기 또는 실측 기준으로 맞추세요.'),
 'spin_depth_feature_depth': spec('기준 깊이', 'CVD의 Bottom 성장률 위치와 그래프 깊이 기준입니다.', '얕은 기준 위치에서 Bottom 비율 도달', '더 깊은 기준 위치에서 Bottom 비율 도달', 'retention', '실제 구조 깊이를 바꾸지 않습니다. 구조를 수정하면 기준값이 갱신됩니다.'),
 'spin_depth_feature_length': spec('Line 기준 길이', 'Line 유효 종횡비는 깊이×(폭+길이)/(2×폭×길이)입니다.', '양수 범위에서 짧을수록 공급 감소', '길수록 긴 Line 근사에 접근', 'geometry', '0은 무한 길이 근사이며 가장 짧다는 뜻이 아닙니다. Hole에는 영향 없음. CVD와 함께 켠 억제 재결합에도 사용되며 구조 좌표는 바뀌지 않습니다.'),
 'spin_depth_decay_k': spec('기존 감쇠 강도 · K', '유효 종횡비에 따른 성장률 감소 강도입니다.', '깊은 곳에도 더 많은 성장', '깊은 곳의 성장 감소', 'depletion'),
 'spin_depth_decay_power': spec('기존 감쇠 지수', '유효 종횡비에 따른 감쇠 곡선의 모양입니다.', '종횡비에 대한 완만한 전환', '종횡비 1 주변에서 더 급한 전환', 'inhibit_power', '종횡비가 1보다 작은지 큰지에 따라 변화 방향이 다릅니다.'),
 'spin_depth_min_ratio_pct': spec('기존 최소 증착 비율', '성장 배율 = 최소 비율 + (1−최소 비율)×감쇠 응답입니다.', '입구 아래의 성장 배율 감소', '입구 아래의 성장 배율 증가', 'floor', '곡선 바닥만 잘라내는 max 하한이 아니라 전체 감쇠 곡선을 끌어올립니다. 억제 재결합의 공급 손실 계산에도 사용합니다.'),
 'spin_depth_closure_threshold': spec('닫힘 진단 간격', '기존 모델이 남은 틈을 검사해 진단 기록에 닫힘 여부를 표시하는 기준입니다.', '더 작은 틈에서 닫힘 기록', '더 큰 틈에서도 닫힘 기록', 'display', '현재 계산에서 실제 접촉이나 잔류 채움 시작을 앞당기는 값은 아닙니다. 잔류 채움은 실제 폐공간 생성으로 시작합니다.'),
 'spin_depth_post_fill_hole_pct': spec('Hole 닫힌 뒤 잔류 fill', 'Hole 모드에서 최초 폐공간 면적 중 추가로 채울 총 예산 비율입니다.', '총 채움 예산 감소', '총 채움 예산 증가', 'bottom', '매 Step 채움 비율이 아닙니다. 실제 채움량은 후보 공급량에도 제한됩니다. 기존 감쇠/억제 ON·CVD OFF에서만 적용하는 경험항입니다.'),
 'spin_depth_post_fill_line_pct': spec('Line 닫힌 뒤 잔류 fill', 'Line 모드의 총 채움 예산 = 최초 폐공간 면적 × 이 비율 × 잔류 공급입니다.', '총 채움 예산 감소', '총 채움 예산 증가', 'bottom', '매 Step 비율이나 3D 끝단 공급 해석이 아닙니다. 기존 감쇠/억제 ON·CVD OFF에서만 적용하는 경험항입니다.'),
 'spin_depth_line_open_path': spec('Line 열린 공급 경로', '호환 Line 모델의 닫힘 후 공급 가능성을 조절합니다.', '추가 공급을 더 제한', '추가 공급을 더 허용', 'bottom', '새 CVD에는 적용하지 않는 경험적 보정입니다.'),
 'spin_depth_residual_decay': spec('잔류 공급 감쇠 길이', '닫힌 위치 아래 깊이 차 Δz에 exp(−Δz/길이)를 곱해 후보 채움 면적을 적분합니다.', '깊은 구간의 채움량 기여 감소', '깊은 구간의 채움량 기여 증가', 'retention', '시간이나 지속 Step 수가 아닙니다. 이 가중치는 후보 총량 계산용이며, 실제 채움은 예산 내 폐공간 균일 축소입니다. 깊이별 막두께 분포를 직접 지정하지 않으며 새 CVD에는 미적용입니다.'),
 'chk_ion_transmission': spec('기존 이온 감쇠', '깊이와 기하학적 가중치로 직접 식각량을 줄이는 호환 모델입니다.', 'OFF: 기존 감쇠 없음', 'ON: 깊이에 따른 식각 감소', 'shadow', '새 입사 이온 가림이 활성화되면 중복 적용하지 않습니다. 증착량 감쇠가 아닙니다.'),
 'spin_ion_start_depth': spec('이온 감쇠 시작 깊이 %', '전체 깊이 중 감쇠가 시작되는 위치입니다.', '얕은 곳부터 감소 시작', '더 깊은 곳에서 감소 시작', 'power'),
 'spin_ion_end_depth': spec('이온 감쇠 끝 깊이 %', '감쇠 구간이 끝나는 위치입니다.', '짧은 깊이 구간에서 감소', '긴 깊이 구간에 걸쳐 감소', 'power'),
 'spin_ion_decay_strength': spec('이온 감쇠 크기 %', '감쇠 구간에서 이온 전달을 얼마나 줄일지 정합니다.', '전달량 감소가 작음', '전달량 감소가 큼', 'depletion'),
 'spin_ion_floor': spec('이온 전달 하한 %', '기존 모델에서 깊이 감쇠와 기하학적 보정을 곱한 뒤 적용하는 전달 배율 하한입니다.', '더 낮은 전달 배율 허용', '하한에 걸린 곳의 전달 배율 증가', 'floor', '기존 전달 배율은 이 하한 아래로 내려가지 않습니다. 새 이온 가림에는 미적용이며, 최종 식각량은 수율·식각 제한에 따라 별도로 결정됩니다.'),
 'spin_ion_curve_power': spec('이온 감쇠 곡선', '감쇠 구간에서 전달량이 떨어지는 모양입니다.', '앞쪽부터 비교적 빠르게 감소', '앞쪽을 유지하다 뒤쪽에서 감소', 'power'),
 'slider_ion_aperture_shadow': spec('입구 가림 가중치', '입구가 좁아질 때 공급 제한을 얼마나 반영할지 정합니다.', '입구 제한 반영 약함', '입구 제한 반영 강함', 'shadow'),
 'slider_ion_lateral_shadow': spec('숨은 면 가림 가중치', '옆벽에 가려진 영역의 공급 감소를 반영합니다.', '숨은 면 감쇠가 작음', '숨은 면 감쇠가 큼', 'shadow'),
 'slider_ion_edge_shadow': spec('모서리 가림 가중치', '모서리 부근의 기존 가림 보정을 조절합니다.', '모서리 보정 약함', '모서리 보정 강함', 'shadow'),
 'cmb_depth_display_mode': spec('깊이 그래프 표시', '그래프에 그리는 축의 표현을 바꿉니다.', '한 가지 축 표현', '다른 축 표현', 'display', '표시만 바뀝니다. 저장된 공정값과 시뮬레이션 결과는 바뀌지 않습니다.'),
}

# Keep the visible names short; technical terms belong in the explanation.
SHORT_NAMES = {
 'spin_cycles':'Step 수', 'spin_angstrom_per_cycle':'증착량 (Å/step)',
 'cmb_quality_mode':'계산 품질', 'spin_reparam_ds':'점 간격',
 'cvd_overhang_pct':'상부 성장', 'cvd_cusping_pct':'모서리 성장',
 'cvd_bottom_ratio_pct':'바닥 성장률', 'cvd_upper_length_a':'상부 영향 길이',
 'cvd_depth_power':'깊이 감쇠 지수',
 'spin_sputter_strength':'식각량 (Å/step)', 'spin_sputter_peak_pct':'식각 세기 (%)',
 'spin_sputter_peak':'최대 식각 각도 (°)', 'spin_sputter_width':'식각 각도 폭 (°)',
 'spin_sputter_smoothing':'식각 평활화 (Å)',
 'spin_incident_sigma':'이온 각도 폭', 'spin_incident_rays':'계산 방향 수',
 'spin_redepo_efficiency':'재증착률 (%)', 'spin_redepo_emit_power':'재증착 분포 폭 (°)',
 'spin_redepo_distance_power':'재증착 방향 (%)',
 'spin_inhibition_strength':'억제 강도 (%)', 'spin_inhibition_penetration':'억제 깊이 (Å)',
 'spin_inhibition_decay_power':'억제 감쇠 지수', 'spin_inhibition_min_growth':'최소 성장률 (%)',
 'spin_inhibition_bottom_boost':'바닥 성장 보강 (%)', 'spin_inhibition_recombination':'재결합 손실 (%)',
 'spin_inhibition_smoothing':'성장률 평활화 (Å)',
 'cmb_depth_feature_type':'기준 형상', 'spin_depth_feature_width':'기준 폭 (Å)',
 'spin_depth_feature_depth':'기준 깊이 (Å)', 'spin_depth_feature_length':'기준 길이 (Å)',
 'spin_depth_decay_k':'감쇠 강도', 'spin_depth_decay_power':'감쇠 지수',
 'spin_depth_min_ratio_pct':'최소 증착률 (%)', 'spin_depth_closure_threshold':'닫힘 진단 간격 (Å)',
 'spin_depth_post_fill_hole_pct':'잔류 채움 (%)', 'spin_depth_post_fill_line_pct':'잔류 채움 (%)',
 'spin_depth_line_open_path':'잔류 공급', 'spin_depth_residual_decay':'잔류 감쇠 길이 (Å)',
 'spin_ion_start_depth':'감쇠 시작 깊이 (%)', 'spin_ion_end_depth':'감쇠 끝 깊이 (%)',
 'spin_ion_decay_strength':'감쇠 강도 (%)', 'spin_ion_floor':'최소 이온 전달 (%)',
 'spin_ion_curve_power':'감쇠 지수', 'slider_ion_aperture_shadow':'입구 가림',
 'slider_ion_lateral_shadow':'벽 가림', 'slider_ion_edge_shadow':'모서리 가림',
 'cmb_depth_display_mode':'그래프 표시',
}


def apply_simple_names(owner,panel):
    if owner.active_emulator_number()!=0:return
    for attr,title in {
        'chk_typical_cvd':'CVD 사용', 'chk_sputter':'식각 사용', 'chk_redepo':'재증착 사용',
        'chk_incident_los':'이온 가림 사용', 'chk_inhibition_deposition':'증착 억제 사용',
        'chk_depth_deposition':'기존 증착 감쇠', 'chk_ion_transmission':'기존 이온 감쇠',
        'lbl_etch_section':'식각 · 통합 모델', 'lbl_sputter_section':'식각 각도',
        'lbl_redepo_section':'재증착', 'lbl_depth_depo_section':'기존 증착 감쇠',
        'lbl_inhibition_section':'증착 억제', 'lbl_ion_depth_section':'기존 이온 감쇠',
        'lbl_ion_geometry_section':'기존 가림 보정',
    }.items():getattr(owner,attr).setText(title)
    manager=getattr(panel,'help_manager',None)
    if manager is None:return
    controls={}
    for key,name in SHORT_NAMES.items():
        control=owner.cvd_spins.get(key) if key.startswith('cvd_') else getattr(owner,key,None)
        if control is not None:
            control.setProperty('helpShortName',name)
            controls[control]=name
    for widget,(_,control) in manager.bindings.items():
        if isinstance(widget,QLabel) and control in controls:widget.setText(controls[control])


from .parameter_help_visuals import TrenchAnimation as EffectAnimation


class HelpBubble(QFrame):
    def __init__(self, owner):
        # Native Qt tooltips dismiss themselves on mouse presses, before their
        # child buttons can be used. This owned, non-activating tool window keeps
        # the view/pause controls interactive without stealing editor focus.
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setObjectName('parameterHelpBubble')
        self.setStyleSheet('#parameterHelpBubble {background:#ffffff;border:1px solid #a8c5d3;border-radius:12px;} QLabel {color:#1e293b;} QPushButton {padding:4px 9px;}')
        root=QVBoxLayout(self)
        root.setContentsMargins(12,10,12,10)
        head=QHBoxLayout()
        self.title=QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet('font-weight:700; font-size:14px; color:#086a76;')
        self.pause=QPushButton('일시정지')
        self.pause.setCheckable(True)
        self.pause.setFocusPolicy(Qt.NoFocus)
        close=QPushButton('×')
        close.setAccessibleName('도움말 닫기')
        close.setFocusPolicy(Qt.NoFocus)
        close.clicked.connect(self.hide)
        head.addWidget(self.title,1)
        head.addWidget(self.pause)
        head.addWidget(close)
        root.addLayout(head)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body=QWidget()
        layout=QVBoxLayout(body)
        layout.setContentsMargins(0,0,2,0)
        self.current=QLabel()
        self.meaning=QLabel()
        self.animation=EffectAnimation()
        self.views=QWidget()
        view_layout=QHBoxLayout(self.views)
        view_layout.setContentsMargins(0,0,0,0)
        self.view_group=QButtonGroup(self)
        self.view_buttons={}
        for name,title in [('auto','자동 재생'),('shape','단면 비교'),('zoom','변화 확대'),('meaning','물리 의미')]:
            button=QPushButton(title)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda checked=False,mode=name:self.animation.set_view(mode))
            self.view_group.addButton(button)
            self.view_buttons[name]=button
            view_layout.addWidget(button)
        self.view_buttons['auto'].setChecked(True)
        self.plot_note=QLabel()
        self.low=QLabel()
        self.high=QLabel()
        self.caution=QLabel()
        self.foot=QLabel('예시 시뮬레이션/설명 이미지 · 현재 구조의 계산 결과가 아닙니다.\n마우스를 말풍선 안으로 옮겨 읽기 · F1 도움말 · Esc 닫기')
        for label in (self.current,self.meaning,self.plot_note,self.low,self.high,self.caution,self.foot):
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
        self.current.setStyleSheet('background:#e8f4f5;padding:6px;border-radius:5px;')
        self.caution.setStyleSheet('color:#87530d;background:#fff6e6;padding:6px;')
        self.foot.setStyleSheet('color:#64748b;font-size:11px;')
        self.plot_note.setStyleSheet('color:#475569;font-size:11px;')
        for widget in (self.current,self.meaning,self.views,self.animation,self.plot_note,self.low,self.high,self.caution,self.foot):layout.addWidget(widget)
        scroll.setWidget(body)
        root.addWidget(scroll)
        self.pause.toggled.connect(self.set_paused)

    def set_paused(self,paused):
        self.pause.setText('재생' if paused else '일시정지')
        if paused:self.animation.timer.stop()
        elif self.isVisible():self.animation.timer.start()

    def hideEvent(self,event):
        self.animation.timer.stop()
        super().hideEvent(event)


class ParameterHelp(QObject):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner=owner
        self.bindings={}
        self.resolvers={}
        self.fallback_controls=set()
        self.bubble=HelpBubble(owner)
        self.anchor=None
        self.pending=None
        self.delay=QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.setInterval(650)
        self.delay.timeout.connect(self.show_pending)
        self.dismiss=QTimer(self)
        self.dismiss.setSingleShot(True)
        self.dismiss.setInterval(350)
        self.dismiss.timeout.connect(self.dismiss_if_outside)
        from .help_preferences import help_preferences
        self.preferences = help_preferences()
        self.enabled = self.preferences.enabled
        self.preferences.enabledChanged.connect(self.set_enabled)
        owner.installEventFilter(self)
        QApplication.instance().installEventFilter(self)

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.hide()

    def bind(self,widget,entry,control=None):
        if widget is None:return
        if widget not in self.bindings:
            widget.destroyed.connect(lambda _=None,w=widget:self.forget(w))
        self.bindings[widget]=(entry,control or widget)
        widget.setMouseTracking(True)
        widget.setToolTip('마우스를 잠시 올리거나 F1: 움직이는 파라미터 설명')
        widget.setAccessibleDescription(entry.meaning+' 낮추면: '+entry.low+' 높이면: '+entry.high)

    def forget(self,widget):
        self.bindings.pop(widget,None)
        self.resolvers.pop(widget,None)
        self.fallback_controls.discard(widget)
        if self.anchor is widget:self.anchor=None
        if self.pending is widget:self.pending=None

    def bind_fallback(self,widget):
        title=widget.accessibleName() or widget.objectName() or '추가 설정'
        text=widget.toolTip() or '추가된 입력 항목입니다. 항목별 영향은 해당 기능의 설명을 확인하세요.'
        entry=spec(title,text,'값 또는 선택 변경','변경된 값 또는 선택','display',
                   '이 항목의 물리적 영향은 자동으로 추정하지 않습니다. 애드온 등 추가 기능의 설명을 확인하세요.')
        self.bind(widget,entry)
        self.fallback_controls.add(widget)

    def resolve_at(self,anchor,pos):
        if anchor in self.resolvers:
            value=self.resolvers[anchor](pos)
            if self.bindings.get(anchor)!=value:
                self.bindings[anchor]=value
                self.anchor=None
                self.pending=None
        return self.bindings.get(anchor)

    def lookup(self,widget):
        while isinstance(widget,QWidget):
            if widget in self.bindings:return widget
            widget=widget.parentWidget()
        return None

    def hide(self):
        self.delay.stop()
        self.dismiss.stop()
        self.pending=None
        self.anchor=None
        self.bubble.hide()

    def dismiss_if_outside(self):
        # Child Enter/Leave events can arrive in either order when crossing the
        # gap to this top-level bubble. Keep it open while the pointer is inside.
        if self.bubble.isVisible() and self.bubble.rect().contains(self.bubble.mapFromGlobal(QCursor.pos())):
            return
        self.hide()

    def dismiss_if_inactive(self):
        # Some Qt platforms briefly deactivate the owner when the owned tool
        # window appears. Resolve the active window after that transition.
        active=QApplication.activeWindow()
        if active is self.owner or active is self.bubble:
            return
        self.hide()

    def show_pending(self):
        if self.pending is not None and self.pending.isVisible():self.show_for(self.pending)

    def show_for(self,anchor):
        if not self.enabled:
            self.hide()
            return
        self.delay.stop()
        self.dismiss.stop()
        entry,control=self.bindings[anchor]
        # The same legacy fields have different semantics in older emulator modes.
        mode=getattr(self.owner,'active_emulator_number',lambda:0)()
        if control is getattr(self.owner,'spin_redepo_emit_power',None) and mode not in (0,6):
            entry=spec('방출 지수 · Emit power','표면 법선 방향의 방출 집중도를 조절합니다.','넓은 방출 분포','법선 방향에 집중','narrowing')
        if control is getattr(self.owner,'spin_redepo_distance_power',None) and mode not in (0,6):
            entry=spec('거리 감쇠 지수','먼 표면으로 가는 재증착 가중치입니다.','먼 거리 기여를 더 유지','먼 거리 기여를 더 줄임','depletion')
        self.anchor=anchor
        b=self.bubble
        short=control.property('helpShortName') if mode==0 else None
        b.title.setText(short or entry.title)
        if isinstance(control,QAbstractSpinBox):value=control.text()
        elif isinstance(control,QComboBox):value=control.currentText()
        elif isinstance(control,(QAbstractButton,QGroupBox)) and control.isCheckable():value='ON' if control.isChecked() else 'OFF'
        elif isinstance(control,QSlider):value=str(control.value())+(' %' if '불투명도' in entry.title or '가림' in entry.title else '')
        elif isinstance(control,QLineEdit):value=control.text() or '(입력 전)'
        elif isinstance(control,QPlainTextEdit):value=control.toPlainText()[:100] or '(입력 전)'
        else:value=control.property('helpCurrentValue') or '표/그림 직접 조절'
        b.current.setText('현재 설정: '+value+('  · 비활성: 이 입력은 현재 편집할 수 없음' if not control.isEnabled() else ''))
        b.meaning.setText(entry.title+'\n'+entry.meaning if short else entry.meaning)
        toggle=isinstance(control,(QAbstractButton,QGroupBox)) and control.isCheckable()
        b.low.setText(('OFF   ' if toggle else '↓ 낮추면 / 이전   ')+entry.low)
        b.high.setText(('ON   ' if toggle else '↑ 높이면 / 이후   ')+entry.high)
        from .parameter_help_response import application_note
        from .parameter_help_trench import load_movie, recipe_note
        key=control.property('helpParameterKey') or ''
        status=''
        movie=None
        try:
            if hasattr(self.owner,'current_config'):
                status=application_note(key,self.owner.current_config())
            if mode in (0,6):
                movie=load_movie(key)
        except (OSError, ValueError, KeyError) as error:
            status='예시 단면 자료를 읽을 수 없습니다: '+str(error)
        b.caution.setText((status+'\n' if status else '')+entry.caution)
        b.animation.configure(movie,key,entry.kind,getattr(self.owner,'_result',None))
        b.animation.set_view('auto')
        b.view_buttons['auto'].setChecked(True)
        b.views.setVisible(movie is not None)
        b.plot_note.setText(recipe_note(movie) if movie else '설정의 공간적 의미를 보여주는 설명용 이미지입니다. 물리적 막 형상 변화로 해석하지 마세요.')
        screen=anchor.screen().availableGeometry()
        b.resize(min(568,screen.width()-16),min(760,screen.height()-24))
        pos=anchor.mapToGlobal(QPoint(0,0))
        x=pos.x()-b.width()-10
        if x<screen.left():x=pos.x()+anchor.width()+10
        target=clamped_rect(QRect(x,pos.y()-28,b.width(),b.height()),screen)
        b.move(target.topLeft())
        b.show()
        if not b.pause.isChecked():b.animation.timer.start()

    def eventFilter(self,obj,event):
        et=event.type()
        # Closed test/dialog windows can remain alive in Qt. Do not leave their
        # application-wide filters processing events for every subsequent window.
        if obj is self.owner and et==QEvent.Show:
            QApplication.instance().installEventFilter(self)
        if et==QEvent.Show and isinstance(obj,QWidget) and self.owner.isAncestorOf(obj) and not self.bubble.isAncestorOf(obj):
            from .parameter_help_all import is_value_control
            if is_value_control(obj) and self.lookup(obj) is None:self.bind_fallback(obj)
        if obj is self.owner and et in (QEvent.Close,QEvent.Hide):
            self.hide()
            QApplication.instance().removeEventFilter(self)
            return False
        if et not in (QEvent.KeyPress,QEvent.ToolTip,QEvent.Enter,QEvent.MouseMove,
                      QEvent.Leave,QEvent.MouseButtonPress,QEvent.Wheel,
                      QEvent.Hide,QEvent.WindowDeactivate):return False
        if not isinstance(obj,QWidget):return False
        inside=obj is self.bubble or self.bubble.isAncestorOf(obj)
        anchor=self.lookup(obj)
        if not self.enabled:
            # Suppress the Qt tooltip fallback too, but never block editing,
            # scrolling or normal keyboard input while explanations are off.
            return anchor is not None and (et == QEvent.ToolTip or
                et == QEvent.KeyPress and event.key() == Qt.Key_F1)
        if et==QEvent.MouseMove and event.buttons()!=Qt.NoButton and not inside:
            self.hide()
            return False
        if anchor in self.resolvers and et in (QEvent.MouseMove,QEvent.ToolTip):
            pos=event.position().toPoint() if hasattr(event,'position') else event.pos()
            self.resolve_at(anchor,anchor.mapFrom(obj,pos))
        if et==QEvent.KeyPress:
            if event.key()==Qt.Key_Escape and self.bubble.isVisible():
                self.hide()
                return True
            if event.key()==Qt.Key_F1 and anchor is not None:
                self.show_for(anchor)
                return True
            if not inside:self.hide()
        if et==QEvent.ToolTip and anchor is not None:
            self.show_for(anchor)
            return True
        if et in (QEvent.Enter,QEvent.MouseMove):
            if inside:self.dismiss.stop()
            elif anchor is not None:
                self.dismiss.stop()
                if anchor is not self.anchor and anchor is not self.pending:
                    self.pending=anchor
                    self.delay.start()
            elif self.bubble.isVisible():self.dismiss.start()
        elif et==QEvent.Leave and (anchor is not None or inside):
            self.delay.stop()
            self.pending=None
            self.dismiss.start()
        elif et in (QEvent.MouseButtonPress,QEvent.Wheel) and not inside:
            self.hide()
        elif et==QEvent.Hide and (obj is self.owner or obj is self.anchor):self.hide()
        elif et==QEvent.WindowDeactivate and obj is self.owner:
            QTimer.singleShot(0,self.dismiss_if_inactive)
        return False


def clamped_rect(rect,screen):
    """Keep the bubble inside the selected monitor, including negative origins."""
    w,h=min(rect.width(),screen.width()),min(rect.height(),screen.height())
    return QRect(max(screen.left(),min(rect.x(),screen.right()-w+1)),
                 max(screen.top(),min(rect.y(),screen.bottom()-h+1)),w,h)


def install_parameter_help(owner,panel):
    manager=ParameterHelp(owner)
    controls={}
    for key,entry in HELP.items():
        widget=owner.cvd_spins.get(key) if key.startswith('cvd_') else getattr(owner,key,None)
        if widget is not None:
            widget.setProperty('helpParameterKey',key)
            controls[widget]=entry
            manager.bind(widget,entry)
    # Match labels to the actual grid row, not translated label strings.
    for parent in panel.findChildren(QWidget):
        grid=parent.layout()
        if not isinstance(grid,QGridLayout):continue
        for i in range(grid.count()):
            item=grid.itemAt(i)
            widget=item.widget()
            control=widget if widget in controls else next((w for w in controls if widget and widget.isAncestorOf(w)),None)
            if control is None:continue
            row,col,rs,cs=grid.getItemPosition(i)
            for j in range(grid.count()):
                r,c,_,_=grid.getItemPosition(j)
                label=grid.itemAt(j).widget()
                if r==row and isinstance(label,QLabel):manager.bind(label,controls[control],control)
    for attr,key in [('sputter_curve_editor','spin_sputter_peak'),('ion_transmission_editor','spin_ion_curve_power'),
                     ('depth_deposition_editor','spin_depth_decay_k'),('inhibition_profile_editor','spin_inhibition_strength'),
                     ('redepo_lobe_editor','spin_redepo_emit_power')]:
        manager.bind(getattr(owner,attr),HELP[key],getattr(owner,key))
    panel.help_manager=manager
    apply_simple_names(owner,panel)
    return manager

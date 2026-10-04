"""Read-only help samples, evaluated by the same local kernels as the engine.

Never advance a surface here. A fixed, clearly labelled example separates a
local response from a final deposited profile. The caller's config is immutable.
"""
from dataclasses import dataclass, replace
import math

from gapsim.emulation import trench_depo as engine
from gapsim.engine import typical_cvd
from gapsim.engine.incident_ions import source_integral


# Attribute -> config field, UI-to-config factor, unit, useful comparison range.
FIELDS = {
    'spin_cycles': ('cycles', 1, 'cycle', 10, 50),
    'spin_angstrom_per_cycle': ('angstrom_per_cycle', 1, 'Å/cycle', 0, 20),
    'spin_sputter_strength': ('sputter_strength_a_per_cycle', 1, 'Å/cycle', 0, 10),
    'spin_sputter_peak_pct': ('sputter_peak_pct', 1, '%', 0, 100),
    'spin_sputter_peak': ('sputter_peak_angle_deg', 1, '°', 20, 75),
    'spin_sputter_width': ('sputter_width_deg', 1, '°', 5, 40),
    'spin_incident_sigma': ('redepo_incident_sigma_deg', 1, '°', 2, 20),
    'spin_incident_rays': ('redepo_incident_ray_count', 1, '방향', 9, 51),
    'spin_redepo_efficiency': ('redepo_efficiency_pct', 1, '%', 0, 100),
    'spin_redepo_distance_power': ('redepo_distance_power', 1, '%', -100, 100),
    'spin_depth_feature_width': ('deposition_feature_width_a', 1, 'Å', 100, 800),
    'spin_depth_feature_depth': ('deposition_feature_depth_a', 1, 'Å', 500, 2000),
    'spin_depth_feature_length': ('deposition_feature_length_a', 1, 'Å', 0, 3000),
    'spin_depth_decay_k': ('deposition_depth_decay_k', 1, '', 0, 2),
    'spin_depth_decay_power': ('deposition_depth_decay_power', 1, '', .5, 3),
    'spin_depth_min_ratio_pct': ('deposition_min_ratio', .01, '%', 0, 50),
    'spin_depth_post_fill_hole_pct': ('deposition_post_closure_fill_pct_hole', .01, '%', 0, 100),
    'spin_depth_post_fill_line_pct': ('deposition_post_closure_fill_pct_line', .01, '%', 0, 100),
    'spin_depth_line_open_path': ('deposition_line_open_path_factor', 1, '', 0, 1),
    'spin_inhibition_strength': ('inhibition_strength_pct', 1, '%', 0, 100),
    'spin_inhibition_penetration': ('inhibition_penetration_depth_a', 1, 'Å', 100, 1600),
    'spin_inhibition_decay_power': ('inhibition_decay_power', 1, '', .5, 3),
    'spin_inhibition_min_growth': ('inhibition_min_growth_ratio', .01, '%', 0, 100),
    'spin_inhibition_bottom_boost': ('inhibition_bottom_boost_pct', 1, '%', 0, 100),
    'spin_inhibition_recombination': ('inhibition_peald_recombination_pct', 1, '%', 0, 100),
    'spin_inhibition_smoothing': ('inhibition_smoothing_a', 1, 'Å', 0, 150),
    'spin_ion_start_depth': ('ion_transmission_start_depth_pct', 1, '%', 0, 60),
    'spin_ion_end_depth': ('ion_transmission_end_depth_pct', 1, '%', 40, 100),
    'spin_ion_decay_strength': ('ion_transmission_decay_strength_pct', 1, '%', 0, 100),
    'spin_ion_floor': ('ion_transmission_floor_pct', 1, '%', 0, 80),
    'spin_ion_curve_power': ('ion_transmission_curve_power', 1, '', .2, 6),
    'slider_ion_aperture_shadow': ('ion_transmission_aperture_shadow_pct', 1, '%', 0, 100),
    'slider_ion_lateral_shadow': ('ion_transmission_lateral_shadow_pct', 1, '%', 0, 100),
    'slider_ion_edge_shadow': ('ion_transmission_edge_shadow_pct', 1, '%', 0, 100),
}
for name, unit, low, high in [
    ('cvd_overhang_pct', '%', 0, 100), ('cvd_cusping_pct', '%', 0, 100),
    ('cvd_bottom_ratio_pct', '%', 0, 100), ('cvd_upper_length_a', 'Å', 50, 600),
    ('cvd_depth_power', '', .2, 4),
]:
    FIELDS[name] = (name, 1, unit, low, high)


@dataclass(frozen=True)
class ResponsePlot:
    title: str
    xlabel: str
    note: str
    labels: tuple
    x: tuple
    curves: tuple


def example_points():
    # Fixed geometry even when reference width/depth controls change. Shoulder
    # slopes and a recessed wall expose orientation/occlusion dependencies.
    return engine.equal_arc_resample([
        (-750., 0.), (-250., 0.), (-180., -70.), (-180., -220.),
        (-280., -420.), (-250., -1120.), (-170., -1200.),
        (170., -1200.), (250., -1120.), (280., -420.),
        (180., -220.), (180., -70.), (250., 0.), (750., 0.),
    ], 20.)


def depth_args(c):
    return dict(feature_type=c.deposition_feature_type,
                feature_width_a=c.deposition_feature_width_a,
                feature_length_a=c.deposition_feature_length_a,
                attenuation_model=c.deposition_attenuation_model,
                depth_decay_k=c.deposition_depth_decay_k,
                depth_decay_power=c.deposition_depth_decay_power,
                min_depo_ratio=c.deposition_min_ratio,
                use_equivalent_aspect_ratio=c.deposition_use_equivalent_ar)


def inhibition_response(points, c):
    return engine.compute_inhibition_deposition_factors(
        points, **depth_args(c), process_model=c.inhibition_process_model,
        **{name: getattr(c, name) for name in (
            'inhibition_strength_pct', 'inhibition_penetration_depth_a',
            'inhibition_decay_power', 'inhibition_min_growth_ratio',
            'inhibition_bottom_boost_pct', 'inhibition_peald_recombination_pct',
            'inhibition_smoothing_a')}, reparam_ds_a=20.)


def growth_response(points, c):
    """Pre-motion combined deposition multiplier, matching branch precedence."""
    if c.angstrom_per_cycle <= 0:
        return [0.] * len(points)
    if c.cvd_enabled:
        base = typical_cvd.growth_ratios(points, c)
    elif c.deposition_depth_enabled:
        base = engine.compute_depth_deposition_factors(points, **depth_args(c))
    else:
        base = [1.] * len(points)
    if c.inhibition_enabled:
        base = [a*b for a, b in zip(base, inhibition_response(points, c))]
    return base


def los_active(c):
    if getattr(c, 'recipe_model', 'legacy_calibrated_v1') != 'legacy_calibrated_v1':
        return c.sputter_enabled and c.sputter_strength_a_per_cycle > 0
    return (c.sputter_enabled and c.sputter_strength_a_per_cycle > 0
            and c.redepo_enabled and c.redepo_incident_los_enabled)


def ion_response(points, c):
    if los_active(c) or not c.sputter_enabled or c.sputter_strength_a_per_cycle <= 0:
        return [1.] * len(points)
    names = ('start_depth_pct', 'end_depth_pct', 'decay_strength_pct', 'floor_pct',
             'curve_power', 'aperture_shadow_pct', 'lateral_shadow_pct', 'edge_shadow_pct')
    return engine.compute_ion_transmission_factors(
        points, enabled=c.ion_transmission_enabled, override=c.ion_transmission_override,
        **{name: getattr(c, 'ion_transmission_'+name) for name in names}, reparam_ds_a=20.)


def application_note(key, c):
    """Semantic gates: a collapsed/disabled editor is not a disabled process."""
    etch = c.sputter_enabled and c.sputter_strength_a_per_cycle > 0
    model = getattr(c, 'recipe_model', 'legacy_calibrated_v1')
    process = getattr(c, 'process_type', 'ald')
    if key in ('spin_cycles', 'spin_angstrom_per_cycle', 'spin_ald_exposure'):
        if process != 'ald':
            return '현재 미적용: ALD 전용 입력 · CVD는 D/R과 시간 사용'
        if key == 'spin_ald_exposure' and model != 'physical_transport_v1':
            return '현재 미적용: 수송·표면 반응 모델에서 ALD 포화 계산에 사용'
        return '현재 적용: ALD cycle 수와 GPC 기준'
    if key in ('spin_cvd_rate', 'spin_cvd_duration'):
        return '현재 적용: CVD D/R × 시간' if process == 'cvd' else '현재 미적용: CVD 전용 입력 · ALD는 GPC와 cycle 수 사용'
    if key == 'spin_precursor_sticking':
        return '현재 적용: 중성 전구체 수송·반응' if model == 'physical_transport_v1' else '현재 미적용: 수송·표면 반응 모델에서 사용'
    if key in ('spin_inhibitor_sticking', 'spin_inhibitor_exposure'):
        return '현재 적용: 억제제 수송·흡착 피복' if model != 'legacy_calibrated_v1' and c.inhibition_enabled else '현재 미적용: Conformal/수송 모델에서 증착 억제 ON 필요'
    if key == 'spin_numerical_step':
        return '계산 정확도 설정 · 실제 공정 cycle/시간과 별개' if model != 'legacy_calibrated_v1' else '현재 미적용: 기존 보정 모델은 저장된 계산 순서 유지'
    if key == 'spin_transport_rays':
        active = model == 'physical_transport_v1' or model == 'ideal_conformal_v1' and (c.inhibition_enabled or etch and c.redepo_enabled)
        return '현재 적용: 방향 적분 정확도' if active else '현재 미적용: 중성 수송·억제 또는 재부착 수송 경로 없음'
    if model != 'legacy_calibrated_v1':
        if key.startswith(('cvd_', 'spin_inhibition_', 'spin_depth_', 'cmb_depth_', 'spin_ion_', 'slider_ion_')) or key in ('chk_typical_cvd', 'chk_depth_deposition', 'chk_ion_transmission', 'spin_sputter_smoothing', 'spin_sputter_peak_pct', 'spin_redepo_emit_power', 'spin_redepo_distance_power', 'spin_redepo_max_distance', 'spin_redepo_soft_los'):
            return '현재 미적용: 기존 보정 모델 전용 설정'
        if key.startswith(('spin_incident_', 'chk_incident_')):
            return '현재 적용: 식각의 기하학적 이온 가림 · 재부착 OFF에서도 유지' if etch else '현재 미적용: 식각 OFF 또는 식각량 0'
    if key == 'spin_redepo_soft_los':
        return ''  # Retained compatibility input: its own help says ignored.
    if key.startswith('cvd_'):
        return '적용 조건: CVD ON · 증착량 > 0' if c.cvd_enabled and c.angstrom_per_cycle > 0 else '현재 미적용: CVD OFF 또는 증착량 0'
    if key.startswith('spin_inhibition_'):
        return '적용 조건: 증착 억제 ON · 증착량 > 0' if c.inhibition_enabled and c.angstrom_per_cycle > 0 else '현재 미적용: 증착 억제 OFF 또는 증착량 0'
    if key.startswith(('spin_incident_', 'chk_incident_')):
        return '현재 적용: 식각·재증착·이온 가림 ON' if los_active(c) else '현재 미적용: 식각량 > 0 및 식각·재증착·이온 가림 ON 필요'
    if key.startswith(('spin_ion_', 'slider_ion_', 'chk_ion_')):
        if los_active(c):
            return '현재 미적용: 새 이온 가림이 기존 이온 감쇠를 대체함'
        return '현재 적용: 기존 이온 전달 배율' if etch and c.ion_transmission_enabled else '현재 미적용: 식각 또는 기존 이온 감쇠 OFF'
    if key.startswith('spin_redepo_'):
        if not etch or not c.redepo_enabled:
            return '현재 미적용: 식각량 > 0 및 식각·재증착 ON 필요'
        return '적용 조건 충족 · 실제 포집량은 도달 원료에 따름'
    if key.startswith('spin_sputter_'):
        return '적용 조건: 식각 ON (식각량·수율이 0이면 제거 없음)' if c.sputter_enabled else '현재 미적용: 식각 OFF'
    if key.startswith(('spin_depth_post_', 'spin_depth_line_open', 'spin_depth_residual')):
        if c.cvd_enabled or not (c.deposition_depth_enabled or c.inhibition_enabled) or c.angstrom_per_cycle <= 0:
            return '현재 미적용: CVD OFF · 기존 감쇠/억제 ON · 증착량 > 0 필요'
        return '실제 폐공간 생성 후에만 적용 · 아래는 채움 예산 비교'
    if key == 'spin_depth_closure_threshold':
        return '진단 기록용 · 실제 접촉/채움 시작 조건 아님'
    if key.startswith(('spin_depth_decay', 'spin_depth_min', 'spin_depth_feature', 'cmb_depth_feature')):
        if key == 'spin_depth_feature_length' and c.deposition_feature_type != 'line':
            return '현재 미적용: Hole은 Line 기준 길이를 사용하지 않음'
        if key == 'spin_depth_feature_depth':
            return '현재 적용: CVD의 바닥 성장률 기준 깊이' if c.cvd_enabled and c.angstrom_per_cycle > 0 else '현재 CVD 기준 깊이 미적용 (CVD OFF 또는 증착량 0)'
        active = c.angstrom_per_cycle > 0 and (
            c.deposition_depth_enabled and not c.cvd_enabled or c.inhibition_enabled or
            key == 'spin_depth_feature_width' and c.cvd_enabled)
        return ('적용 경로 있음 · ' if active else '현재 증착 경로에서 미적용 · ') + '기존 감쇠는 CVD OFF · 억제 재결합은 CVD ON에서도 이 기준 사용'
    return ''


def build_response(key, c, values):
    """Evaluate exactly the listed values, never interpolate a pretend result."""
    if key not in FIELDS or c.emulator_number not in (0, 6) or getattr(c, 'recipe_model', 'legacy_calibrated_v1') != 'legacy_calibrated_v1':
        return None
    field, scale, unit, _, _ = FIELDS[key]
    configs = []
    for value in values:
        v = value * scale
        if field in ('cycles', 'redepo_incident_ray_count'):
            v = int(v)
        if field == 'deposition_feature_length_a' and v <= 0:
            v = None
        configs.append(replace(c, **{field: v}))
    points = example_points()
    x = tuple(engine._model6_arc_coordinates(points))
    xlabel = '표면 거리 Å (왼쪽 평탄부 → 바닥 → 오른쪽)'
    note = '예시 단면: 입구 500 Å · 깊이 1200 Å · 점 간격 20 Å. 다른 공정값은 현재 설정. 구조는 고정하며 최종 막 형상을 계산하지 않습니다.'
    if key.startswith(('cvd_', 'spin_inhibition_', 'spin_depth_feature', 'spin_depth_decay', 'spin_depth_min')):
        title = '증착 배율 · CVD/기존 감쇠 × 억제'
        curves = [growth_response(points, v) for v in configs]
    elif key.startswith(('spin_ion_', 'slider_ion_')):
        title = '기존 이온 전달 배율 (새 가림과 별개)'
        curves = [ion_response(points, v) for v in configs]
    elif key.startswith('spin_sputter_'):
        title = '제한 전 각도별 식각 기준량 ('+('Å/s' if c.process_type=='cvd' else 'Å/cycle')+')'
        x = tuple(float(i) for i in range(91))
        xlabel = '법선과 입사 방향 사이 각도 (°)'
        note = '실제 각도 수율 함수 × 식각량. 투영·가림·평활화·제거량 제한 전 응답이며, 최종 제거량이나 막두께가 아닙니다.'
        curves = [[engine.direct_sputter_angle_response(
            angle, peak_angle_deg=v.sputter_peak_angle_deg, width_deg=v.sputter_width_deg,
            peak_pct=v.sputter_peak_pct) * v.sputter_strength_a_per_cycle
            if v.sputter_enabled else 0. for angle in x] for v in configs]
    elif key.startswith('spin_incident_'):
        title = '가림 후 이온 식각 원료 응답 ('+('Å/s' if c.process_type=='cvd' else 'Å/cycle')+')'
        normals = engine._smooth_unit_vectors(engine.vertex_air_normals(points),
                    int(round(c.sputter_smoothing_a/20.)))
        curves = []
        for v in configs:
            response = source_integral(points, normals, sigma=v.redepo_incident_sigma_deg,
                rays=v.redepo_incident_ray_count, peak=v.sputter_peak_angle_deg,
                width=v.sputter_width_deg, amplitude=v.sputter_peak_pct/100.)[1]
            curves.append(response * v.sputter_strength_a_per_cycle if los_active(v) else response*0.)
        note += ' 입사 가중치 합은 1. 식각량 제한과 단면 이동 전 값입니다.'
    elif key in ('spin_cycles', 'spin_angstrom_per_cycle'):
        title = '명목 증착량 (Å) · 순 막두께 아님'
        # Bound help work independently of a user's very large step count.
        end = max(v.cycles for v in configs)
        x = tuple(end*i/100 for i in range(101))
        curves = [[min(step, v.cycles)*v.angstrom_per_cycle for step in x] for v in configs]
        xlabel = 'ALD cycle'
        note = '기준 누적량 = cycle × GPC. 억제·식각·재부착·닫힘은 미포함. 실제 국소 두께가 계속 증가한다는 뜻은 아닙니다.'
    elif key == 'spin_redepo_efficiency':
        title = '도달 원료 1에 대한 재부착 예산'
        x = (0., 1.)
        curves = [[v.redepo_efficiency_pct/100.]*2 if v.sputter_enabled and v.sputter_strength_a_per_cycle > 0 and v.redepo_enabled else [0., 0.] for v in configs]
        xlabel = '유효 도달 원료량을 1로 고정한 비교'
        note = '예산 = 재증착률 × 유효 도달 원료. 전체 제거량이 아닙니다. 실제 도달량은 방출 방향·가림·거리 제한에 따라 달라집니다.'
    elif key == 'spin_redepo_distance_power':
        title = '고정 예시 법선에서 방출 축 각도 (°)'
        x = (0., 1.)
        curves = []
        for v in configs:
            nx, ny = engine._model6_blended_emission_axis((.8, .6), v.redepo_distance_power/100.)
            curves.append([math.degrees(math.atan2(ny, nx))]*2)
        xlabel = '법선 (0.8, 0.6) 고정 · +X축 기준 각도'
        note = '실제 방향 혼합 함수의 예시. 음수는 법선에서 반사 방향의 반대쪽으로 외삽합니다. 실제 부착 위치·깊이·총량을 예측하는 그림은 아닙니다.'
    elif key.startswith(('spin_depth_post_', 'spin_depth_line_open')):
        title = '폐공간 최초 면적에 대한 총 채움 예산'
        x = (0., 1.)
        curves = []
        for v in configs:
            active = not v.cvd_enabled and (v.deposition_depth_enabled or v.inhibition_enabled) and v.angstrom_per_cycle > 0
            fraction = engine._post_closure_allowed_fill_fraction(
                feature_type=v.deposition_feature_type,
                post_closure_fill_pct_hole=v.deposition_post_closure_fill_pct_hole,
                post_closure_fill_pct_line=v.deposition_post_closure_fill_pct_line,
                line_open_path_factor=v.deposition_line_open_path_factor) if active else 0.
            curves.append([fraction]*2)
        xlabel = '최초 폐공간 면적 = 1 · 누적 예산 비율'
        note = '실제 폐공간 생성 후 최초 면적×비율만큼을 총 예산으로 설정합니다. 매 Step 그 비율만큼 채우는 설정이 아니며, Hole/Line 선택에 맞는 값만 사용합니다.'
    else:
        return None
    labels = tuple(f'{label}: {value:g} {unit}'.strip() for label, value in zip(('작은 값', '현재 값', '큰 값'), values))
    return ResponsePlot(title, xlabel, note, labels, x, tuple(tuple(float(y) for y in ys) for ys in curves))


def for_control(owner, control, key):
    """UI adapter; does not touch widget values, geometry, result or settings."""
    if not hasattr(owner, 'current_config'):
        return None, ''
    c = owner.current_config()
    if c.emulator_number not in (0, 6):
        return None, '호환 모델: 통합 모델용 응답 그림은 표시하지 않습니다.'
    status = application_note(key, c)
    if key not in FIELDS or not hasattr(control, 'value'):
        return None, status
    _, _, _, low, high = FIELDS[key]
    current = float(control.value())
    low = max(control.minimum(), min(low, current))
    high = min(control.maximum(), max(high, current))
    if key == 'spin_incident_rays':
        # Widget correction uses odd quadrature counts. Keep comparison valid.
        low, high = max(3, int(low)//2*2+1), min(101, int(high)//2*2+1)
        if int(current) % 2 == 0:
            return None, status+' · 홀수 방향 수 입력 후 비교 가능'
    return build_response(key, c, (low, current, high)), status


def operation_steps(key, kind):
    """No invented profile for settings that do not predict a local response."""
    exact = {
        'spin_redepo_emit_power': ('방출 축 하나로 도착점 찾기', '거리 × tan(각도)로 분배 폭 계산', '도착점 주변 분배 · 포집 총량 정규화'),
        'spin_sputter_smoothing': ('표면 법선 평균화', '각도 수율·이동·방출 방향에 반영', '통합 재증착 경로: 단면 요철 완화'),
        'spin_depth_residual_decay': ('닫힌 위치 아래 깊이 차 구하기', 'exp(−깊이 차/길이)로 후보 채움량 적분', '총 예산 안에서 폐공간 균일 축소'),
        'spin_depth_closure_threshold': ('단면의 남은 틈 검사', '기준 이하인지 진단 기록', '실제 접촉·채움 시작과는 별개'),
        'chk_redepo': ('식각 원료 계산 (이온 가림 경로 연동)', '방출 축이 맞은편 측벽에 도달하는지 검사', '도달 원료 × 재증착률을 주변에 분배'),
        'chk_incident_los': ('식각·재증착 ON 및 식각량 확인', '방향별 가림·투영·각도 수율 적분', '가림 후 원료 계산 · 기존 이온 감쇠 대체'),
        'spin_reparam_ds': ('단면 길이를 점 간격으로 나누기', '작을수록 촘촘한 표면 점', '해상도·시간 변경 · 실제 막질 보장 아님'),
        'cmb_quality_mode': ('빠름 20 Å / 보통 10 Å', '정밀 5 Å / 최정밀 2.5 Å', '공정은 유지 · 점 간격만 선택'),
        'chk_symmetric_structure_edit': ('좌우대칭 편집 ON/OFF', '구조 점 이동', 'ON이면 반대편 점도 대칭 이동'),
        'chk_incident_preset_geometry': ('구조 포함 여부 선택', '검증 프리셋 적용 버튼', 'ON이면 보고서 구조도 함께 적용'),
        'btn_move_overlay': ('이미지 이동 모드 ON/OFF', '마우스로 이미지 정렬', '계산 형상·공정 조건은 유지'),
        'spin_smooth_segments': ('입력 구조 분할 수 지정', '스무딩 적용', '스무딩 사용 시 계산 입력 변경'),
        'spin_smooth_iterations': ('모서리 완화 반복 횟수 지정', '스무딩 적용', '스무딩 사용 시 계산 입력 변경'),
        'chk_typical_cvd': ('CVD ON/OFF', '깊이 기본 배율 × 상부/모서리 강화', '억제 ON이면 추가 곱셈 · 기존 감쇠 대체'),
        'chk_inhibition_deposition': ('증착 억제 ON/OFF', '피복 억제 × 재결합 손실 × 바닥 보강', '다른 증착 배율과 곱셈 · 식각 아님'),
        'chk_depth_deposition': ('기존 증착 감쇠 ON/OFF', 'CVD OFF일 때만 증착 감쇠 적용', '억제 재결합의 감쇠 계수 사용은 별개'),
        'chk_ion_transmission': ('기존 이온 감쇠 ON/OFF', '새 이온 가림이 켜지면 기존식 대체', '식각 수율에 전달 배율 반영'),
        'cmb_depth_feature_type': ('Hole 또는 Line 기준 선택', '기존 감쇠·억제 재결합 EAR 계산', '구조 좌표는 바꾸지 않음'),
    }
    if key in exact:
        return exact[key]
    if kind == 'frames':
        return ('표시할 결과 Step 선택', '이미 계산된 프레임 읽기', '화면만 갱신 · 재계산 없음')
    if kind == 'opacity':
        return ('겹친 표시의 켜짐·진하기 조절', '화면 표시만 변경', '계산 형상·공정 조건 유지')
    if kind in ('split', 'sampling'):
        return ('비교할 항목과 조건 지정', '실행 전에 생성 조건 확인', '실행 시 각 조건을 별도로 계산')
    if kind == 'coordinates':
        return ('초기 구조 좌표 선택/편집', '점 순서·교차·축척 확인', '다음 계산의 입력 구조로 사용')
    if kind in ('smooth', 'quality'):
        return ('구조 편집 설정', '적용 전후 구조 확인', '선택한 입력 구조로 계산')
    if kind == 'etch':
        return ('식각 ON/OFF', '수율·가림·제거량 제한 반영', '물질 제거 · 재증착 원료 생성 가능')
    return ('선택한 항목의 동작 확인', '아래 설명의 적용 조건 확인', '단순 표시를 물리 변화로 해석하지 않기')

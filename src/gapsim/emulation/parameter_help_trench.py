"""Reproducible single-field SVT trench examples for parameter help.

The packaged movies contain actual run_trench_depo frames, not interpolated
response curves. Recipes are deliberately independent of the user's settings.
"""
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib.resources import files
import gzip
import json

from .trench_depo import TrenchDepoConfig
from .parameter_help_response import FIELDS

ASSET = 'help_trench_examples.json.gz'
VERSION = 3
TRENCH = ((-700., 0.), (-260., 0.), (-210., -50.), (-210., -900.),
          (210., -900.), (210., -50.), (260., 0.), (700., 0.))
NECK = ((-700., 0.), (-100., 0.), (-100., -100.), (-220., -250.),
        (-220., -900.), (220., -900.), (220., -250.), (100., -100.),
        (100., 0.), (700., 0.))
RECESSED = ((-700., 0.), (-190., 0.), (-150., -60.), (-150., -220.),
            (-250., -380.), (-250., -900.), (250., -900.), (250., -380.),
            (150., -220.), (150., -60.), (190., 0.), (700., 0.))
# Bounded sensitivity search in the 72-control SVT (2026-10-03). These are
# shared comparison backgrounds, never changes to the user's process recipe.
SVT_CONTEXTS = {
    'spin_redepo_emit_power': ('강한 식각·재증착', dict(cycles=36,
        angstrom_per_cycle=2., sputter_strength_a_per_cycle=12., redepo_efficiency_pct=100.)),
    'slider_ion_aperture_shadow': ('강한 식각·재증착', dict(cycles=36,
        angstrom_per_cycle=2., sputter_strength_a_per_cycle=12., redepo_efficiency_pct=100.)),
    'spin_incident_rays': ('넓은 이온 입사 분포', dict(points=RECESSED, cycles=32,
        sputter_width_deg=45., redepo_incident_sigma_deg=20.)),
    'spin_inhibition_smoothing': ('억제·CVD 복합 성장', dict(cycles=36,
        angstrom_per_cycle=9., cvd_enabled=True, cvd_overhang_pct=80., cvd_bottom_ratio_pct=65.)),
}


@dataclass(frozen=True)
class Example:
    key: str
    field: str
    values: tuple
    labels: tuple
    family: str
    config: TrenchDepoConfig

    def configs(self):
        # Strict single-field split, including switches. The engine handles
        # inactive dependencies; changing extra inputs would confound the SVT.
        return tuple(replace(self.config, **{self.field: v}) for v in self.values)


def examples(svt=True):
    base = TrenchDepoConfig(points=TRENCH, cycles=20, angstrom_per_cycle=6., reparam_ds_a=10.,
        deposition_feature_width_a=520., deposition_feature_depth_a=900.,
        cvd_upper_length_a=180., inhibition_penetration_depth_a=250.,
        inhibition_smoothing_a=30., deposition_residual_fill_decay_length_a=300.)
    cvd = replace(base, cvd_enabled=True)
    etch = replace(base, cycles=24, angstrom_per_cycle=3., sputter_enabled=True,
        sputter_strength_a_per_cycle=8., sputter_width_deg=40., sputter_smoothing_a=20.,
        redepo_enabled=True, redepo_incident_los_enabled=True, redepo_efficiency_pct=70.,
        redepo_emit_power=10., redepo_distance_power=50.)
    inhibit = replace(base, inhibition_enabled=True)
    depth = replace(base, deposition_depth_enabled=True)
    ion = replace(etch, redepo_incident_los_enabled=False, ion_transmission_enabled=True)
    fill = replace(depth, points=NECK, cycles=36, deposition_feature_width_a=200.,
                   deposition_depth_decay_k=.15, deposition_depth_decay_power=1.,
                   deposition_post_closure_fill_pct_hole=.5,
                   deposition_post_closure_fill_pct_line=.5)
    result = {}

    def add(key, field, values, family, recipe, unit='', labels=None):
        result[key] = Example(key, field, tuple(values), tuple(labels or (
            f'{value:g} {unit}'.strip() for value in values)), family, recipe)

    for key, (field, scale, unit, lo, hi) in FIELDS.items():
        if key.startswith('cvd_'):
            recipe, family = cvd, 'growth'
        elif key.startswith('spin_sputter_'):
            recipe, family = etch, 'etch'
        elif key.startswith('spin_incident_'):
            recipe, family = etch, 'ions'
        elif key.startswith('spin_redepo_'):
            recipe, family = etch, 'redepo'
        elif key.startswith('spin_inhibition_'):
            recipe, family = inhibit, 'inhibition'
        elif key.startswith(('spin_ion_', 'slider_ion_')):
            recipe, family = ion, 'transmission'
        elif key.startswith(('spin_depth_post_', 'spin_depth_line_open')):
            recipe, family = fill, 'closure'
            if key != 'spin_depth_post_fill_hole_pct':
                recipe = replace(recipe, deposition_feature_type='line')
        elif key.startswith('spin_depth_feature'):
            recipe, family = depth, 'reference'
            if key == 'spin_depth_feature_depth':
                recipe = cvd
            if key == 'spin_depth_feature_length':
                recipe = replace(depth, deposition_feature_type='line')
        elif key.startswith('spin_depth_'):
            recipe, family = depth, 'depletion'
        else:
            recipe, family = base, 'growth'
        # Keep explanatory cases small and visible, not user's huge run ranges.
        overrides = {'spin_cycles': (8, 28), 'spin_angstrom_per_cycle': (2, 8),
                     'spin_sputter_strength': (2, 10), 'spin_sputter_peak': (20, 70),
                     'spin_depth_feature_width': (200, 800),
                     'cvd_cusping_pct': (0, 160)}
        lo, hi = overrides.get(key, (lo, hi))
        values = [value*scale for value in (lo, hi)]
        if field in ('cycles', 'redepo_incident_ray_count'):
            values = [int(v) for v in values]
        if field == 'deposition_feature_length_a':
            values = [None if v <= 0 else v for v in values]
        add(key, field, values, family, recipe, labels=(f'{lo:g} {unit}'.strip(), f'{hi:g} {unit}'.strip()))

    add('spin_redepo_emit_power', 'redepo_emit_power', (3., 35.), 'redepo', etch, '°')
    add('spin_sputter_smoothing', 'sputter_smoothing_a', (0., 80.), 'smoothing', etch, 'Å')
    add('spin_depth_residual_decay', 'deposition_residual_fill_decay_length_a', (80., 1200.), 'closure', fill, 'Å')
    add('spin_reparam_ds', 'reparam_ds_a', (5., 20.), 'mesh', cvd, 'Å')
    add('cmb_quality_mode', 'reparam_ds_a', (20., 5.), 'mesh', cvd,
        labels=('빠름 · 20 Å', '정밀 · 5 Å'))
    add('cmb_depth_feature_type', 'deposition_feature_type', ('hole', 'line'), 'reference', depth,
        labels=('Hole', 'Line'))
    add('chk_symmetry', 'symmetry_mode', ('off', 'auto'), 'mesh', base,
        labels=('일반 경계', '대칭 입력 보존'))
    add('cmb_front_scheme', 'front_scheme', ('legacy', 'angular_godunov_v1'), 'mesh', etch,
        labels=('기존 전진법', '방향별 전진법'))
    add('spin_ion_growth_fraction', 'ion_growth_fraction', (0., .6), 'growth',
        replace(etch, front_scheme='angular_godunov_v1'))
    add('spin_redepo_max_distance', 'redepo_max_distance_a', (100., 1800.), 'redepo', etch, 'Å')
    add('cmb_inhibition_process_model', 'inhibition_process_model', ('ald','peald'), 'inhibition',
        replace(inhibit, inhibition_peald_recombination_pct=60.), labels=('ALD 법칙','PEALD 법칙'))
    for key, field, family, recipe in [
        ('chk_typical_cvd', 'cvd_enabled', 'growth', cvd),
        ('chk_sputter', 'sputter_enabled', 'etch', etch),
        ('chk_redepo', 'redepo_enabled', 'redepo', etch),
        ('chk_incident_los', 'redepo_incident_los_enabled', 'ions', etch),
        ('chk_inhibition_deposition', 'inhibition_enabled', 'inhibition', inhibit),
        ('chk_depth_deposition', 'deposition_depth_enabled', 'depletion', depth),
        ('chk_ion_transmission', 'ion_transmission_enabled', 'transmission', ion),
    ]:
        add(key, field, (False, True), family, recipe, labels=('OFF', 'ON'))
    # The research sweep keeps its original baseline and independently searches
    # contexts. Help playback uses the reviewed SVT selections below.
    if not svt:
        return result
    for key, example in list(result.items()):
        lo, hi = example.values
        if (isinstance(lo, (bool, str)) or lo is None or hi is None):
            continue
        mid = getattr(example.config, example.field)
        if not min(lo, hi) < mid < max(lo, hi):
            mid = (lo + hi)/2
        if example.field in ('cycles', 'redepo_incident_ray_count'):
            mid = int(round(mid))
            if example.field == 'redepo_incident_ray_count' and mid % 2 == 0:
                mid += 1
        assert min(lo, hi) < mid < max(lo, hi), key
        if key in FIELDS:
            _, scale, unit, _, _ = FIELDS[key]
            middle_label = f'{mid/scale:g} {unit}'.strip()
        else:
            unit = '°' if key == 'spin_redepo_emit_power' else '' if key == 'spin_ion_growth_fraction' else 'Å'
            middle_label = f'{mid:g} {unit}'
        context = SVT_CONTEXTS.get(key, ('기본 비교 조건', {}))[1]
        result[key] = replace(example, values=(lo, mid, hi),
            labels=(example.labels[0], middle_label, example.labels[1]),
            config=replace(example.config, **context))
    if hasattr(TrenchDepoConfig, 'recipe_model'):
        result.update(recipe_examples())
    return result


def recipe_examples():
    """Model-specific, single-input splits for the actual ALD/CVD recipe path."""
    result = {}
    for model in ('ideal_conformal_v1', 'physical_transport_v1'):
        base = TrenchDepoConfig(points=TRENCH, recipe_model=model, process_type='ald',
            cycles=12, angstrom_per_cycle=5., reparam_ds_a=20., numerical_step_a=3.,
            precursor_sticking=.1, ald_exposure=3., transport_ray_count=16,
            cvd_rate_a_per_s=2., cvd_duration_s=30.,
            sputter_strength_a_per_cycle=1., sputter_peak_angle_deg=45., sputter_width_deg=40.,
            redepo_incident_sigma_deg=10., redepo_incident_ray_count=15,
            redepo_efficiency_pct=70., inhibitor_sticking=.3, inhibitor_exposure=1.)
        etch = replace(base, sputter_enabled=True, redepo_enabled=True)
        cvd = replace(base, process_type='cvd')
        inhibit = replace(base, inhibition_enabled=True)

        def add(key, field, values, config, labels, family='physical_growth'):
            qualified = movie_key(key, model)
            result[qualified] = Example(qualified, field, tuple(values), tuple(labels), family, config)

        add('spin_cycles', 'cycles', (4, 12, 24), base, ('4 cycle', '12 cycle', '24 cycle'))
        add('spin_angstrom_per_cycle', 'angstrom_per_cycle', (2., 5., 8.), base,
            ('2 Å/cycle', '5 Å/cycle', '8 Å/cycle'))
        add('spin_cvd_rate', 'cvd_rate_a_per_s', (.5, 2., 4.), cvd, ('.5 Å/s', '2 Å/s', '4 Å/s'))
        add('spin_cvd_duration', 'cvd_duration_s', (10., 30., 60.), cvd, ('10 s', '30 s', '60 s'))
        resolution = replace(base, cycles=4)
        add('spin_reparam_ds', 'reparam_ds_a', (10., 20., 40.), resolution,
            ('10 Å', '20 Å', '40 Å'), 'mesh')
        add('cmb_quality_mode', 'reparam_ds_a', (20., 10., 5.), resolution,
            ('빠름 · 20 Å', '보통 · 10 Å', '정밀 · 5 Å'), 'mesh')
        add('spin_numerical_step', 'numerical_step_a', (1., 3., 10.), etch,
            ('1 Å', '3 Å', '10 Å'), 'mesh')
        add('spin_transport_rays', 'transport_ray_count', (8, 16, 32), etch,
            ('8 방향', '16 방향', '32 방향'), 'physical_growth')
        add('spin_sputter_strength', 'sputter_strength_a_per_cycle', (0., 1., 3.), etch,
            ('0 Å/cycle', '1 Å/cycle', '3 Å/cycle'), 'etch')
        cvd_etch_key = movie_key('spin_sputter_strength', model, 'cvd')
        result[cvd_etch_key] = Example(cvd_etch_key, 'sputter_strength_a_per_cycle',
            (0., 1., 3.), ('0 Å/s', '1 Å/s', '3 Å/s'), 'etch', replace(etch, process_type='cvd'))
        add('spin_sputter_peak', 'sputter_peak_angle_deg', (20., 45., 65.), etch,
            ('20 °', '45 °', '65 °'), 'etch')
        add('spin_sputter_width', 'sputter_width_deg', (20., 40., 60.), etch,
            ('20 °', '40 °', '60 °'), 'etch')
        add('spin_incident_sigma', 'redepo_incident_sigma_deg', (2., 10., 20.), etch,
            ('2 °', '10 °', '20 °'), 'ions')
        add('spin_incident_rays', 'redepo_incident_ray_count', (9, 15, 31), etch,
            ('9 방향', '15 방향', '31 방향'), 'ions')
        add('spin_redepo_efficiency', 'redepo_efficiency_pct', (0., 70., 100.), etch,
            ('0 %', '70 %', '100 %'), 'redepo')
        add('spin_inhibitor_sticking', 'inhibitor_sticking', (.05, .3, .8), inhibit,
            ('.05', '.3', '.8'), 'physical_growth')
        add('spin_inhibitor_exposure', 'inhibitor_exposure', (.1, 1., 3.), inhibit,
            ('.1', '1', '3'), 'physical_growth')
        for key, field, config, family in (
                ('chk_sputter', 'sputter_enabled', etch, 'etch'),
                ('chk_redepo', 'redepo_enabled', etch, 'redepo'),
                ('chk_inhibition_deposition', 'inhibition_enabled', inhibit, 'physical_growth')):
            add(key, field, (False, True), config, ('OFF', 'ON'), family)
        if model == 'physical_transport_v1':
            add('spin_precursor_sticking', 'precursor_sticking', (.02, .1, .7), base,
                ('.02', '.1', '.7'))
            add('spin_ald_exposure', 'ald_exposure', (.3, 3., 12.), base,
                ('.3', '3', '12'))
    return result


def movie_key(key, model='legacy_calibrated_v1', process='ald'):
    base = key if model == 'legacy_calibrated_v1' else key+'@'+model
    return base+'@cvd' if key=='spin_sputter_strength' and process=='cvd' and model != 'legacy_calibrated_v1' else base


@lru_cache(maxsize=1)
def movie_catalog():
    with files('gapsim.emulation').joinpath(ASSET).open('rb') as handle:
        data = json.loads(gzip.decompress(handle.read()))
    if data.get('version') != VERSION:
        raise ValueError('도움말 형상 자료 버전이 맞지 않습니다.')
    return data


def load_movie(key, model='legacy_calibrated_v1', process='ald'):
    data = movie_catalog()
    case = data['cases'].get(movie_key(key, model, process))
    if not case:
        return None
    return {**case, 'runs': [data['runs'][run_id] for run_id in case['runs']]}


def recipe_note(movie):
    c = movie['runs'][1 if len(movie['runs']) == 3 else 0]['config']
    active = [name for name, field in [('CVD 형상 보정', 'cvd_enabled'), ('식각', 'sputter_enabled'),
              ('재증착', 'redepo_enabled'), ('이온 가림', 'redepo_incident_los_enabled'),
              ('억제', 'inhibition_enabled'), ('기존 감쇠', 'deposition_depth_enabled'),
              ('기존 이온 감쇠', 'ion_transmission_enabled')] if c[field]]
    process = c.get('process_type', 'ald')
    dose = (f"{c['cvd_duration_s']:g} s, D/R {c['cvd_rate_a_per_s']:g} Å/s" if process == 'cvd'
            else f"{c['cycles']} cycle, GPC {c['angstrom_per_cycle']:g} Å/cycle")
    model = {'legacy_calibrated_v1': '기존 보정', 'ideal_conformal_v1': 'Conformal',
             'physical_transport_v1': '수송·표면 반응'}[c.get('recipe_model', 'legacy_calibrated_v1')]
    return ('실제 엔진으로 미리 계산한 예시 트랜치입니다. 현재 입력으로 실행한 결과가 아닙니다. '
            f"기준: {dose}, 점 간격 {c['reparam_ds_a']:g} Å. 모델: {model}. "
            '예시 배경: '+movie.get('context', '기본 비교 조건')+'. '
            '예시 기준의 기능: '+(' + '.join(active) or '추가 식각·억제 없음')+'. 비교 대상 하나만 변경하고 나머지 입력은 동일합니다.')

"""Reproducible two-value trench examples for parameter help.

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
VERSION = 1
TRENCH = ((-700., 0.), (-260., 0.), (-210., -50.), (-210., -900.),
          (210., -900.), (210., -50.), (260., 0.), (700., 0.))
NECK = ((-700., 0.), (-100., 0.), (-100., -100.), (-220., -250.),
        (-220., -900.), (220., -900.), (220., -250.), (100., -100.),
        (100., 0.), (700., 0.))


@dataclass(frozen=True)
class Example:
    key: str
    field: str
    values: tuple
    labels: tuple
    family: str
    config: TrenchDepoConfig

    def configs(self):
        out = []
        for value in self.values:
            c = replace(self.config, **{self.field: value})
            # Same enable dependencies as the main UI; these are not new knobs.
            if not c.sputter_enabled:
                c = replace(c, redepo_enabled=False, redepo_incident_los_enabled=False,
                            ion_transmission_enabled=False)
            elif not c.redepo_enabled:
                c = replace(c, redepo_incident_los_enabled=False)
            out.append(c)
        return tuple(out)


def examples():
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
    return result


@lru_cache(maxsize=1)
def movie_catalog():
    with files('gapsim.emulation').joinpath(ASSET).open('rb') as handle:
        data = json.loads(gzip.decompress(handle.read()))
    if data.get('version') != VERSION:
        raise ValueError('도움말 형상 자료 버전이 맞지 않습니다.')
    return data


def load_movie(key):
    data = movie_catalog()
    case = data['cases'].get(key)
    if not case:
        return None
    return {**case, 'runs': [data['runs'][run_id] for run_id in case['runs']]}


def recipe_note(movie):
    c = movie['runs'][0]['config']
    active = [name for name, field in [('CVD', 'cvd_enabled'), ('식각', 'sputter_enabled'),
              ('재증착', 'redepo_enabled'), ('이온 가림', 'redepo_incident_los_enabled'),
              ('억제', 'inhibition_enabled'), ('기존 감쇠', 'deposition_depth_enabled'),
              ('기존 이온 감쇠', 'ion_transmission_enabled')] if c[field]]
    return ('실제 엔진으로 미리 계산한 예시 트랜치입니다. 현재 입력으로 실행한 결과가 아닙니다. '
            f"기준: {c['cycles']} Step, 증착 {c['angstrom_per_cycle']:g} Å/step, 점 간격 {c['reparam_ds_a']:g} Å. "
            '첫 조건의 기능: '+(' + '.join(active) or 'Conformal')+'. 비교 대상 외 입력은 동일하며 연동 ON/OFF는 함께 전환됩니다.')

from dataclasses import asdict, replace
from unittest.mock import patch
import math

import numpy as np
import pytest

from gapsim.emulation.depth_formula import (
    MODEL, Parameters, PRESET_LAWS, growth_ratios, load_parameters, validate_config,
)
from gapsim.emulation.builtin_presets import recipe_config
from gapsim.emulation.trench_depo import TrenchDepoConfig, run_trench_depo
from gapsim.emulation.trench_depo_export import result_to_payload, payload_to_trench_run

POINTS = [(-1500., 0.), (-500., 0.), (-500., -1000.), (500., -1000.), (500., 0.), (1500., 0.)]


def config(law='exponential', **kw):
    return replace(TrenchDepoConfig(points=POINTS, recipe_model=MODEL,
        depth_formula=asdict(Parameters(law=law)), cycles=4, angstrom_per_cycle=1.,
        reparam_ds_a=20., numerical_step_a=2., process_type='cvd',
        cvd_rate_a_per_s=1., cvd_duration_s=4.), **kw)


@pytest.mark.parametrize('law', ['exponential', 'linear_exp', 'cubic'])
@pytest.mark.parametrize('unit', ['nm', 'A'])
def test_original_equations_with_explicit_units(law, unit):
    depths = np.linspace(0, 2000, 111)
    z = -depths/(10 if unit=='nm' else 1)
    expected = {
        'exponential': 2.416*np.exp(-.0000829*depths)/2.416,
        'linear_exp': (.0001*z+.2134+.0282*(1-z/100)*np.exp(z/100))/.2416,
        'cubic': (-6e-10*z**3-6e-7*z**2-.0002*z+.423)/.423,
    }[law]
    np.testing.assert_allclose(growth_ratios(depths, Parameters(law=law,depth_unit=unit)), expected, atol=1e-14)


def test_negative_and_excessive_extrapolation_are_errors_not_clipped():
    with pytest.raises(ValueError, match='음수'):
        validate_config(config('linear_exp',points=[(-100.,0.),(0.,-50000.),(100.,0.)]))
    with pytest.raises(ValueError, match='1000배'):
        growth_ratios([50000.], Parameters(law='cubic',depth_unit='A'))
    assert growth_ratios([50000.], Parameters(law='cubic'))[0] == pytest.approx(145.2080378250591)


@pytest.mark.parametrize('parameters,depth', [
    (Parameters(law='cubic',cubic_a=0.,cubic_b=.001,cubic_c=.1,cubic_d=1.),1000.),
    (Parameters(law='linear_exp',linear_slope=-.0001,linear_constant=-.09,linear_exp_gain=.1),10000.),
])
def test_validation_detects_negative_growth_between_vertices(parameters, depth):
    assert np.all(growth_ratios([0., depth], parameters) > 0)
    with pytest.raises(ValueError, match='음수'):
        validate_config(config(depth_formula=asdict(parameters),points=[(-100.,0.),(0.,-depth),(100.,0.)]))


@pytest.mark.parametrize('values', [dict(version=2),dict(law='eval'),dict(depth_unit='um'),
    dict(reference='unknown'),dict(cubic_d=math.nan),dict(linear_length=0),
    dict(decay_per_nm=-1),dict(law='cubic',cubic_d=0),dict(extra='bad')])
def test_invalid_parameters_fail_clearly(values):
    with pytest.raises(ValueError):load_parameters(values)


@pytest.mark.parametrize('name', PRESET_LAWS)
@pytest.mark.parametrize('process', ['ald','cvd'])
def test_planar_dose_uses_editable_gpc_or_rate(name,process):
    c=replace(recipe_config(name),points=[(-100.,0.),(100.,0.)],process_type=process,
        angstrom_per_cycle=1.25,cycles=4,cvd_rate_a_per_s=.5,cvd_duration_s=10.,reparam_ds_a=5.)
    r=run_trench_depo(c)
    assert np.array(r.final_profile)[:,1]==pytest.approx(5.,abs=.01)
    assert r.meta['depth_formula_evaluation']=='every_internal_step'
    assert r.meta['nominal_dose_a']==5.


@pytest.mark.parametrize('law', ['exponential','linear_exp','cubic'])
@pytest.mark.parametrize('reference', ['initial_top','current_field'])
def test_production_matches_independent_report_injector(law, reference):
    c=config(law,cvd_duration_s=20.,depth_formula=asdict(Parameters(law=law,reference=reference)))
    result=run_trench_depo(c)
    def original_formula(points,config,**kwargs):
        origin=max(y for x,y in points) if reference=='current_field' else 0.
        z=np.minimum(0,np.array(points)[:,1]-origin)/10
        if law=='exponential': ratios=np.exp(.000829*z)
        elif law=='linear_exp': ratios=(.0001*z+.2134+.0282*(1-z/100)*np.exp(z/100))/.2416
        else: ratios=(-6e-10*z**3-6e-7*z**2-.0002*z+.423)/.423
        return ratios,{}
    with patch('gapsim.emulation.process_recipe._growth_ratios', original_formula):
        reference=run_trench_depo(replace(c,recipe_model='ideal_conformal_v1',depth_formula=None))
    np.testing.assert_allclose(result.final_profile,reference.final_profile,atol=1e-9)
    assert result.frame_voids==reference.frame_voids


def test_translating_geometry_preserves_original_top_and_profile():
    c=config('cubic')
    r=run_trench_depo(c)
    shifted=run_trench_depo(replace(c,points=[(x+130,y+700) for x,y in c.points]))
    np.testing.assert_allclose(np.array(shifted.final_profile)-[130,700],r.final_profile,atol=.01)


def test_formula_and_results_survive_replay_and_old_defaults():
    c=config('linear_exp')
    payload=result_to_payload(c,run_trench_depo(c),request_note='depth formula replay')
    restored,replay,_=payload_to_trench_run(payload)
    assert asdict(restored)==asdict(c)
    assert replay.meta['depth_formula']==c.depth_formula
    payload['config'].pop('depth_formula')
    payload['config']['recipe_model']='ideal_conformal_v1'
    assert payload_to_trench_run(payload)[0].depth_formula is None


def test_existing_sealed_void_is_not_filled_by_depth_law():
    cavity=[(-20.,-30.),(20.,-30.),(20.,-10.),(-20.,-10.)]
    c=config('cubic',points=[(-100.,0.),(100.,0.)],initial_voids=[cavity],reparam_ds_a=2.)
    r=run_trench_depo(c)
    assert r.frame_voids[0]==r.frame_voids[-1]


@pytest.mark.parametrize('name', PRESET_LAWS)
def test_shipped_presets_use_angstrom_without_reinterpreting_saved_nm(name):
    new = recipe_config(name)
    assert new.depth_formula['depth_unit'] == 'A'
    old = replace(new, points=POINTS, cycles=4,
                  depth_formula=asdict(Parameters(law=PRESET_LAWS[name], depth_unit='nm')))
    result = run_trench_depo(old)
    restored, replay, _ = payload_to_trench_run(result_to_payload(old, result, request_note='unit preservation'))
    assert restored.depth_formula['depth_unit'] == 'nm'
    assert asdict(restored) == asdict(old)
    assert replay.final_profile == result.final_profile
    # Legacy dictionaries that omitted a unit retain the previous interpretation.
    assert load_parameters({'law': PRESET_LAWS[name]}).depth_unit == 'nm'


def test_angstrom_formula_range_is_not_silently_clamped():
    linear = recipe_config('깊이 선형·지수식 (시험)')
    assert growth_ratios([2000.], load_parameters(linear.depth_formula))[0] == pytest.approx(.0554635812111555)
    with pytest.raises(ValueError, match='음수'):
        validate_config(replace(linear, points=[(-100.,0.),(0.,-4000.),(100.,0.)]))
    cubic = load_parameters(recipe_config('깊이 3차식 (시험)').depth_formula)
    assert growth_ratios([4000.], cubic)[0] == pytest.approx(30.023/.423)
    with pytest.raises(ValueError, match='1000배'):
        growth_ratios([10000.], cubic)

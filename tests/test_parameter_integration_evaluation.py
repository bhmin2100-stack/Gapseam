"""Behavioral gates for the candidate common-parameter integration."""
from dataclasses import asdict, replace
import json
from copy import deepcopy
from types import SimpleNamespace
import pytest

from gapsim.emulation.calibrated_response import (
    ResponseParameters, load_parameters, sfo310_parameters, growth_response,
    fill_fraction, nominal_gpc,
)
from gapsim.emulation.process_parameter_schema import to_parameter_tree,from_parameter_tree
from gapsim.emulation.sfo31_verified import verified_sfo31_config,sfo310_config
from gapsim.emulation.trench_depo import run_trench_depo


@pytest.mark.parametrize('factory',[verified_sfo31_config,sfo310_config])
def test_tree_preserves_all_original_numbers_and_ignores_preset_name(factory):
    original=factory()
    tree=json.loads(json.dumps(to_parameter_tree(original,name='not-an-sfo-name')))
    actual=asdict(from_parameter_tree(tree));expected=asdict(original)
    for key in expected.keys()-{'recipe_model','empirical_response'}:
        assert actual[key]==expected[key],key
    renamed=deepcopy(tree);renamed['name']='another-user-variant'
    assert from_parameter_tree(renamed)==from_parameter_tree(tree)
    assert actual['recipe_model']=='calibrated_response_v1'
    assert actual['empirical_response']['growth_enabled']==(factory==sfo310_config)


def test_tree_rejects_lost_or_duplicated_fields():
    tree=to_parameter_tree(verified_sfo31_config())
    del tree['groups']['process']['cycles']
    with pytest.raises(ValueError,match='Missing'):from_parameter_tree(tree)
    tree=to_parameter_tree(verified_sfo31_config())
    tree['groups']['growth']['cycles']=4
    with pytest.raises(ValueError):from_parameter_tree(tree)


def test_display_group_does_not_change_preset_application_policy(tmp_path):
    from gapsim.emulation.parameter_library import save_parameter_preset,read_parameter_preset,parameter_preset_application_values
    cfg=from_parameter_tree(to_parameter_tree(sfo310_config()))
    path=tmp_path/'presets.json'
    save_parameter_preset(path,'unrelated-name',cfg,emulator_number=0)
    current=replace(cfg,cycles=7,reparam_ds_a=30.,sputter_smoothing_a=99.,inhibition_smoothing_a=88.,points=((-10.,0.),(10.,0.)))
    values=parameter_preset_application_values(read_parameter_preset(path,'unrelated-name'),current)
    assert values['cycles']==7 and values['reparam_ds_a']==30.
    assert values['points']==current.points
    assert values['sputter_smoothing_a']==cfg.sputter_smoothing_a
    assert values['inhibition_smoothing_a']==cfg.inhibition_smoothing_a
    assert values['empirical_response']==cfg.empirical_response


def test_explicit_response_survives_saved_result(tmp_path):
    from gapsim.emulation.trench_depo_export import save_trench_depo_result_json,load_trench_depo_run
    cfg=from_parameter_tree(to_parameter_tree(replace(sfo310_config(),cycles=2,reparam_ds_a=40.)))
    result=run_trench_depo(cfg)
    path=save_trench_depo_result_json(cfg,result,results_root=tmp_path)
    restored,replayed,_=load_trench_depo_run(path)
    assert restored.empirical_response==cfg.empirical_response
    assert run_trench_depo(restored).frame_profiles==result.frame_profiles
    assert replayed.frame_voids==result.frame_voids


@pytest.mark.parametrize('change',[{'dose_width_a':0},{'fill_peak1_width_nm':-1},{'upper_gain':float('nan')},{'growth_enabled':1},{'fill_order':'invalid'},{'version':2},{'missing_parameter':3}])
def test_invalid_response_inputs_are_not_silently_ignored(change):
    with pytest.raises(ValueError):load_parameters({**asdict(sfo310_parameters()),**change})


def test_growth_parameter_changes_are_active_and_do_not_leak():
    cfg=from_parameter_tree(to_parameter_tree(sfo310_config()))
    pts=[(0.,0.),(0.,-.26*2420),(0.,-.55*2420),(0.,-2.2*2420)]
    state=SimpleNamespace(surface=SimpleNamespace(points=pts),meta={})
    cfg=replace(cfg,deposition_feature_depth_a=5*2420.)
    a=growth_response(state,cfg,[1.]*4,cycle_index=500)
    changed=replace(cfg,empirical_response={**cfg.empirical_response,'upper_gain':.8})
    b=growth_response(state,changed,[1.]*4,cycle_index=500)
    assert b[1]>a[1] and b[0]==a[0]
    assert growth_response(state,cfg,[1.]*4,cycle_index=500)==a
    assert nominal_gpc.get() is None
    assert fill_fraction(442.,replace(sfo310_parameters(),fill_peak2_gain=0.))<fill_fraction(442.)


def test_unsupported_process_rejected_before_silent_fallback():
    cfg=from_parameter_tree(to_parameter_tree(sfo310_config()))
    with pytest.raises(ValueError):run_trench_depo(replace(cfg,process_type='cvd',front_scheme='legacy'))

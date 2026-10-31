from dataclasses import asdict, replace
import pytest
from test_incident_preset_ui import window
from gapsim.emulation.builtin_presets import RECIPE_NAMES, STRUCTURE_NAMES, recipe_config, structure_config
from gapsim.emulation.parameter_library import GEOMETRY_PARAMETER_FIELDS
from gapsim.emulation.calibrated_response import MODEL, ResponseParameters
from gapsim.emulation.response_ui import normalized_values


@pytest.mark.parametrize('structure', STRUCTURE_NAMES)
@pytest.mark.parametrize('recipe', RECIPE_NAMES)
def test_all_builtins_apply_exactly(window, structure, recipe):
    window.cmb_structure_library.setCurrentIndex(window.cmb_structure_library.findData(structure))
    window.load_selected_structure_from_library()
    before=asdict(window.current_config())
    expected=asdict(recipe_config(recipe))
    window.chk_preset_run_defaults.setChecked(True)
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData(recipe))
    window.btn_apply_parameter_preset.click()
    actual=asdict(window.current_config())
    for key in GEOMETRY_PARAMETER_FIELDS: expected[key]=before[key]
    assert {k:(v,actual[k]) for k,v in expected.items() if actual[k]!=v}=={}
    assert window.spin_cycles.isEnabled()
    window.spin_cycles.setValue(17)
    after=asdict(window.current_config())
    assert after=={**actual,'cycles':17}


def test_every_response_is_editable_and_saved(window):
    from gapsim.emulation.response_ui import SECTIONS
    assert {key for _,rows in SECTIONS for key,_,_ in rows} == set(ResponseParameters.__dataclass_fields__)-{'version'}
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData(RECIPE_NAMES[2]))
    window.btn_apply_parameter_preset.click()
    window.response_controls['upper_gain'].setValue(.731234567891)
    window.response_controls['har_growth_floor'].setValue(3.75)
    expected=asdict(window.current_config())
    window.edit_parameter_preset_name.setText('내 파생 레시피')
    window.btn_save_parameter_preset.click()
    window.response_controls['upper_gain'].setValue(0)
    window.btn_apply_parameter_preset.click()
    assert asdict(window.current_config())==expected
    assert expected['recipe_model']==MODEL
    assert expected['empirical_response']['upper_gain']==.731234567891


def test_legacy_migrates_and_preserves_exact_coefficients(window):
    from gapsim.emulation.sfo31_verified import verified_sfo31_config, sfo310_config
    for factory in (verified_sfo31_config,sfo310_config):
        original=asdict(factory())
        window._apply_parameter_config_values(original)
        actual=asdict(window.current_config())
        expected=normalized_values(original)
        for key in GEOMETRY_PARAMETER_FIELDS: expected[key]=actual[key]
        assert actual==expected


def test_common_editor_geometry_portable_and_cvd_default(window):
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData(RECIPE_NAMES[2]))
    window.btn_apply_parameter_preset.click()
    window.cmb_process_type.setCurrentIndex(window.cmb_process_type.findData('cvd'))
    assert window.current_config().recipe_model=='ideal_conformal_v1'
    assert len(window.process_parameter_panel.buttons)==6


def test_response_history_restores_real_run(window, tmp_path):
    from gapsim.emulation.trench_depo_export import save_trench_depo_result_json
    from unittest.mock import patch
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData(RECIPE_NAMES[2]))
    window.btn_apply_parameter_preset.click()
    window.spin_cycles.setValue(2)
    window.spin_reparam_ds.setValue(20)
    window.response_controls['fill_peak2_gain'].setValue(.41)
    before=asdict(window.current_config())
    with patch('gapsim.emulation.trench_depo_ui.QMessageBox.critical') as error:
        window.run_emulation(save_artifacts=False)
    error.assert_not_called()
    assert window._result is not None
    file=save_trench_depo_result_json(window.current_config(),window._result,results_root=tmp_path)
    window.response_controls['fill_peak2_gain'].setValue(0)
    window.load_replay_json(file)
    actual=asdict(window.current_config())
    assert actual['empirical_response']==before['empirical_response']
    assert actual['deposition_residual_fill_distribution']==before['deposition_residual_fill_distribution']
    assert actual['sputter_strength_a_per_cycle']==before['sputter_strength_a_per_cycle']


def test_builtin_structure_save_creates_user_copy(window):
    name=STRUCTURE_NAMES[0]
    window.cmb_structure_library.setCurrentIndex(window.cmb_structure_library.findData(name))
    window.load_selected_structure_from_library()
    original=window.current_config().points
    changed=tuple((x*1.2,y) for x,y in original)
    window._set_structure_points(changed,preserve_on_emulator_switch=True)
    window.edit_structure_name.setText(name)
    window.save_current_structure_to_library()
    assert window.cmb_structure_library.currentData()!=name
    assert window.current_config().points==changed
    window.cmb_structure_library.setCurrentIndex(window.cmb_structure_library.findData(name))
    window.load_selected_structure_from_library()
    assert window.current_config().points==original


def test_har_gate_and_invalid_ranges():
    from gapsim.emulation.calibrated_response import aspect_extension_weight, load_parameters
    p=ResponseParameters(har_enabled=True)
    base=recipe_config(RECIPE_NAMES[2])
    for ar,w in [(2,0),(7,0),(8.5,.5),(10,1),(20,1)]:
        c=replace(base,deposition_feature_depth_a=ar*base.deposition_feature_width_a)
        assert aspect_extension_weight(c,p)==w
    with pytest.raises(ValueError):load_parameters({'har_start_ar':10.,'har_end_ar':7.})
    with pytest.raises(ValueError):load_parameters(replace(p,har_upper_halfwidth_cd=0))


def test_sfo311_apply_keeps_geometry_duration_and_blocks_post_fill(window):
    window.spin_cycles.setValue(73)
    window.chk_preset_run_defaults.setChecked(False)
    before=asdict(window.current_config())
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData('SFO3.11'))
    window.btn_apply_parameter_preset.click()
    cfg=window.current_config()
    assert cfg.cycles==73
    assert all(asdict(cfg)[k]==before[k] for k in GEOMETRY_PARAMETER_FIELDS)
    assert cfg.sputter_enabled and cfg.redepo_enabled and cfg.inhibition_enabled
    assert not cfg.empirical_response['closure_enabled']
    assert cfg.deposition_post_closure_fill_pct_hole==cfg.deposition_post_closure_fill_pct_line==0.
    from gapsim.emulation.calibrated_response import aspect_extension_weight, load_parameters
    p=load_parameters(cfg.empirical_response)
    assert aspect_extension_weight(replace(cfg,deposition_feature_width_a=2420.,deposition_feature_depth_a=7020.),p)==0.
    assert aspect_extension_weight(replace(cfg,deposition_feature_width_a=2300.,deposition_feature_depth_a=50000.),p)==1.

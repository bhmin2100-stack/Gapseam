import os
from dataclasses import replace
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from gapsim.emulation.trench_depo_ui import TrenchDepoWindow
from gapsim.emulation.incident_presets import incident_study_preset, INCIDENT_PRESET_DOSES
from gapsim.emulation.parameter_library import read_parameter_preset
from gapsim.emulation.trench_depo_export import save_trench_depo_result_json, load_trench_depo_run


@pytest.fixture
def window(tmp_path, monkeypatch):
    for key, rel in [('GAPSIM_DATA_ROOT','data'),('GAPSIM_STRUCTURE_LIBRARY','structures.xlsx'),
                     ('GAPSIM_PARAMETER_LIBRARY','presets.json'),('GAPSIM_ADDON_ROOT','addons'),
                     ('GAPSIM_ADDON_STATE','addons.json')]:
        monkeypatch.setenv(key,str(tmp_path/rel))
    app=QApplication.instance() or QApplication([])
    with mock.patch('gapsim.emulation.trench_depo_ui.QTimer.singleShot'):
        w=TrenchDepoWindow()
    w._set_workflow_step('progress')
    w.process_presets_fold.setChecked(True)
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def apply_sfo(window):
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData('SFO3.1'))
    window.btn_apply_parameter_preset.click()


def test_single_sfo_preset_applies_without_changing_geometry(window):
    assert window.windowTitle() == 'GFE'
    points=window._current_geometry_points()
    cycles=window.spin_cycles.value()
    assert window.cmb_parameter_preset.count()==1
    assert window.cmb_parameter_preset.currentText()=='SFO3.1'
    assert not hasattr(window,'cmb_incident_preset')
    window.btn_split_options.setChecked(True)
    apply_sfo(window)
    assert window.windowTitle() == 'GFE'
    assert not window.btn_split_options.isChecked()
    cfg=window.current_config()
    assert cfg.cycles==cycles and cfg.angstrom_per_cycle==2
    assert cfg.process_type=='ald' and cfg.recipe_model=='legacy_calibrated_v1'
    assert cfg.redepo_incident_los_enabled
    assert cfg.sputter_strength_a_per_cycle==pytest.approx(8/3,abs=1e-11)
    assert cfg.sputter_width_deg==40 and cfg.sputter_smoothing_a==20
    assert cfg.redepo_emit_power==5 and cfg.redepo_distance_power==50
    assert cfg.points==points
    assert window._active_parameter_preset_name=='SFO3.1'


def test_saved_preset_roundtrip(window):
    apply_sfo(window)
    window.spin_incident_sigma.setValue(8)
    window.spin_incident_rays.setValue(49)
    window.edit_parameter_preset_name.setText('가림 roundtrip')
    window.btn_save_parameter_preset.click()
    record=read_parameter_preset(window._parameter_library_path,'가림 roundtrip')
    saved=record['config']
    assert saved['redepo_incident_los_enabled'] and record['calculation_settings']['redepo_incident_ray_count']==49
    assert 'points' not in saved
    window.chk_incident_los.setChecked(False)
    window.spin_incident_sigma.setValue(15)
    window.btn_apply_parameter_preset.click()
    assert window.current_config().redepo_incident_los_enabled
    assert window.current_config().redepo_incident_sigma_deg==8
    assert window.current_config().redepo_incident_ray_count==49


def test_old_preset_disables_new_mode_and_cache_tracks_settings(window):
    apply_sfo(window)
    cfg=window.current_config()
    key=window._preview_cache_key(cfg)
    assert key!=window._preview_cache_key(replace(cfg,redepo_incident_los_enabled=False))
    assert key!=window._preview_cache_key(replace(cfg,redepo_incident_sigma_deg=8))
    assert key!=window._preview_cache_key(replace(cfg,redepo_incident_ray_count=49))
    window._apply_parameter_config_values({'cycles':20})
    assert not window.current_config().redepo_incident_los_enabled


def test_actual_ui_run_and_result_json_roundtrip(window,tmp_path):
    apply_sfo(window)
    window._set_structure_points(incident_study_preset().points,preserve_on_emulator_switch=True)
    # Real engine and real result application; only shorten dose for fast CI.
    window.spin_cycles.setValue(3)
    with mock.patch('gapsim.emulation.trench_depo_ui.QMessageBox.critical') as error:
        window.run_emulation(save_artifacts=False)
    error.assert_not_called()
    assert window._result is not None
    assert window._result.meta['redepo_incident_los_enabled']
    assert len(window._result.frame_profiles)==4
    path=save_trench_depo_result_json(window.current_config(),window._result,results_root=tmp_path)
    cfg, result, note=load_trench_depo_run(path)
    assert cfg.redepo_incident_los_enabled and cfg.redepo_incident_ray_count==25
    window.chk_incident_los.setChecked(False)
    window.load_replay_json(path)
    assert window.current_config().redepo_incident_los_enabled
    assert window._result.final_profile==result.final_profile
    assert '입사 이온 가림 연구 모델' in window.edit_result_parameters.toPlainText()


def test_source_controls_gated_and_rays_odd(window):
    assert not window.spin_incident_sigma.isEnabled()
    apply_sfo(window)
    assert window.spin_incident_sigma.isEnabled()
    window.spin_incident_rays.setValue(24)
    assert window.spin_incident_rays.value()==25
    window.chk_redepo.setChecked(False)
    assert window.current_config().redepo_incident_los_enabled
    assert window.spin_incident_sigma.isEnabled()


def test_sfo_user_edit_survives_reseed_and_other_presets_are_preserved(window):
    from gapsim.emulation.incident_presets import ensure_sfo31_preset
    from gapsim.emulation.parameter_library import list_parameter_presets
    apply_sfo(window)
    window.spin_angstrom_per_cycle.setValue(4)
    window.edit_parameter_preset_name.setText('SFO3.1')
    window.btn_save_parameter_preset.click()
    window.edit_parameter_preset_name.setText('다른 조건')
    window.btn_save_parameter_preset.click()
    ensure_sfo31_preset(window._parameter_library_path)
    saved=read_parameter_preset(window._parameter_library_path,'SFO3.1')['config']
    assert saved['angstrom_per_cycle']==4
    assert 'points' not in saved
    assert list_parameter_presets(window._parameter_library_path)==['SFO3.1','다른 조건']

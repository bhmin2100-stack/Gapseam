from dataclasses import replace
from unittest import mock
import time

import pytest
from PySide6.QtWidgets import QApplication

from tests.test_process_parameters import window
from gapsim.emulation.trench_depo_export import save_trench_depo_result_json


def select(w, name, value):
    control=getattr(w,name)
    control.setCurrentIndex(control.findData(value))
    QApplication.processEvents()


def test_ald_and_cvd_offer_conformal_without_sfo(window):
    assert window.current_config().recipe_model=='ideal_conformal_v1'
    assert window.current_config().process_type=='ald'
    assert window.spin_cycles.isVisible() and window.spin_angstrom_per_cycle.isVisible()
    assert not window.spin_cvd_duration.isVisible()
    select(window,'cmb_process_type','cvd')
    assert window.spin_cvd_rate.isVisible() and window.spin_cvd_duration.isVisible()
    assert not window.spin_cycles.isVisible() and not window.spin_angstrom_per_cycle.isVisible()
    window.spin_cvd_rate.setValue(2.5)
    window.spin_cvd_duration.setValue(20)
    assert '50 Å' in window.process_parameter_panel.dose_label.text()
    window.chk_sputter.setChecked(True)
    window.chk_redepo.setChecked(True)
    window.chk_inhibition_deposition.setChecked(True)
    window.process_parameter_panel.conformal_only()
    cfg=window.current_config()
    assert cfg.process_type=='cvd' and cfg.recipe_model=='ideal_conformal_v1'
    assert cfg.cvd_rate_a_per_s==2.5 and cfg.cvd_duration_s==20
    assert not cfg.sputter_enabled and not cfg.redepo_enabled and not cfg.inhibition_enabled


def test_transport_controls_and_split_list_follow_physics(window):
    p=window.process_parameter_panel
    p.select(1)
    assert not window.transport_group.isVisible()
    select(window,'cmb_recipe_model','physical_transport_v1')
    assert window.spin_precursor_sticking.isVisible() and window.spin_ald_exposure.isVisible()
    select(window,'cmb_process_type','cvd')
    assert not window.spin_ald_exposure.isVisible()
    keys=[window.cmb_split_parameter.itemData(i) for i in range(window.cmb_split_parameter.count())]
    assert 'cvd_rate_a_per_s' in keys and 'precursor_sticking' in keys
    assert not {'cycles','angstrom_per_cycle','sputter_peak_pct','cvd_overhang_pct'} & set(keys)
    assert p.section_containers['depth'].isHidden()
    assert window.process_geometry_fold.isHidden()


def test_sfo_preset_is_ald_and_preserves_target_geometry_and_runtime(window):
    points=((-500.,0.),(-100.,0.),(-100.,-300.),(100.,-300.),(100.,0.),(500.,0.))
    window._set_structure_points(points,preserve_on_emulator_switch=True)
    window.spin_cycles.setValue(47)
    window.spin_cvd_duration.setValue(123)
    select(window,'cmb_process_type','cvd')
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData('SFO3.1'))
    window.apply_selected_parameter_preset()
    cfg=window.current_config()
    assert tuple(cfg.points)==points
    assert cfg.process_type=='ald' and cfg.recipe_model=='legacy_calibrated_v1'
    assert cfg.cycles==47 and cfg.cvd_duration_s==123
    assert cfg.angstrom_per_cycle==2 and cfg.redepo_enabled
    window.chk_preset_run_defaults.setChecked(True)
    window.chk_preset_calculation_settings.setChecked(True)
    window.spin_reparam_ds.setValue(20)
    window.apply_selected_parameter_preset()
    assert window.current_config().cycles==150
    assert window.current_config().reparam_ds_a==5
    assert tuple(window.current_config().points)==points


def test_cvd_actual_run_save_reload_and_time_playback(window,tmp_path):
    window._set_structure_points(((-100.,0.),(100.,0.)),preserve_on_emulator_switch=True)
    select(window,'cmb_process_type','cvd')
    window.spin_cvd_rate.setValue(.5)
    window.spin_cvd_duration.setValue(6)
    window.spin_numerical_step.setValue(.5)
    with mock.patch('gapsim.emulation.trench_depo_ui.QMessageBox.critical') as error:
        window.run_emulation(save_artifacts=False)
    error.assert_not_called()
    result=window._result
    assert result is not None
    assert min(y for _,y in result.final_profile)==pytest.approx(3,abs=.02)
    path=save_trench_depo_result_json(window.current_config(),result,results_root=tmp_path)
    select(window,'cmb_process_type','ald')
    window.load_replay_json(path)
    assert window.current_config().process_type=='cvd'
    assert window.current_config().cvd_rate_a_per_s==.5
    window.show_frame(len(result.frame_profiles)-1)
    assert '6/6s' in window.lbl_status.text().replace(' ', '')
    assert '증착속도 D/R' in window.edit_result_parameters.toPlainText()


def test_recipe_cache_and_merged_etch_amplitude(window):
    cfg=window.current_config()
    for key,value in [('process_type','cvd'),('recipe_model','physical_transport_v1'),
                      ('cvd_duration_s',12),('precursor_sticking',.7),('inhibitor_exposure',3)]:
        assert window._preview_cache_key(cfg)!=window._preview_cache_key(replace(cfg,**{key:value}))
    window._apply_parameter_config_values({'sputter_enabled':True,
        'sputter_strength_a_per_cycle':4,'sputter_peak_pct':50})
    assert window.current_config().sputter_strength_a_per_cycle==2
    assert window.current_config().sputter_peak_pct==100
    assert window.spin_sputter_peak_pct.isHidden()


def test_physical_etch_has_no_hidden_gain_and_odd_ray_input_is_safe(window):
    window._apply_parameter_config_values({'recipe_model':'physical_transport_v1',
        'sputter_enabled':True, 'redepo_enabled':False,
        'sputter_strength_a_per_cycle':4,'sputter_peak_pct':50})
    assert window.current_config().sputter_strength_a_per_cycle==4
    window.recipe_numerical_fold.setChecked(True)
    assert window.process_parameter_panel.advanced_folds['rays'].isEnabled()
    window.spin_transport_rays.setValue(9)
    assert window.current_config().transport_ray_count==10
    window.spin_transport_rays.editingFinished.emit()
    assert window.spin_transport_rays.value()==10
    keys=lambda: {window.cmb_split_parameter.itemData(i) for i in range(window.cmb_split_parameter.count())}
    assert 'redepo_efficiency_pct' not in keys()
    window.chk_redepo.setChecked(True)
    assert 'redepo_efficiency_pct' in keys()


def test_async_cancel_stops_worker_without_error_or_export(window):
    window._set_structure_points(((-100.,0.),(100.,0.)),preserve_on_emulator_switch=True)
    window.spin_cycles.setValue(100000)
    with mock.patch('gapsim.emulation.trench_depo_ui.QMessageBox.critical') as error, \
         mock.patch('gapsim.emulation.trench_depo_ui.export_trench_depo_run') as export:
        window.run_emulation()
        assert window._emulation_thread is not None
        window.cancel_emulation()
        deadline=time.monotonic()+10
        while window._emulation_thread is not None and time.monotonic()<deadline:
            QApplication.processEvents()
            time.sleep(.005)
        assert window._emulation_thread is None
    error.assert_not_called()
    export.assert_not_called()
    assert window.btn_run.isEnabled() and window.btn_cancel_run.isHidden()
    assert '취소' in window.lbl_status.text()

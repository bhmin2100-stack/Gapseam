import os
from dataclasses import replace
from unittest import mock
import math
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QPoint
from gapsim.emulation.trench_depo import TrenchDepoConfig, run_trench_depo, _replace_sweep_config
from gapsim.emulation.trench_depo_ui import TrenchDepoWindow
from gapsim.emulation.trench_depo_export import save_trench_depo_result_json, load_trench_depo_run
from gapsim.emulation.incident_presets import incident_study_preset
from gapsim.engine import typical_cvd
from gapsim.engine.deposition_pipeline import equal_arc_resample, normalize_surface_order

POINTS=((-700.,0.),(-250.,0.),(-250.,-500.),(250.,-500.),(250.,0.),(700.,0.))


def config(**kw):
    return replace(TrenchDepoConfig(points=POINTS,cycles=3,angstrom_per_cycle=4,reparam_ds_a=10,
                    deposition_feature_width_a=500,deposition_feature_depth_a=500,cvd_enabled=True),**kw)


def test_cvd_controls_separate_positive_growth_and_mirror_symmetry():
    pts=equal_arc_resample(POINTS,10)
    base=config(cvd_overhang_pct=0,cvd_cusping_pct=0,cvd_bottom_ratio_pct=100)
    assert typical_cvd.growth_ratios(pts,base)==pytest.approx([1]*len(pts))
    for key in ('cvd_overhang_pct','cvd_cusping_pct'):
        flux=typical_cvd.growth_ratios(pts,replace(base,**{key:100}))
        assert max(flux)>1.2
        assert min(flux)>=1
        assert flux==pytest.approx(list(reversed(flux)),abs=1e-9)
    depleted=typical_cvd.growth_ratios(pts,replace(base,cvd_bottom_ratio_pct=20))
    assert min(depleted)==pytest.approx(.2)
    assert max(depleted)==pytest.approx(1)


@pytest.mark.parametrize('key,value',[('cvd_overhang_pct',float('nan')),('cvd_cusping_pct',201),
 ('cvd_bottom_ratio_pct',-1),('cvd_upper_length_a',0),('cvd_depth_power',7)])
def test_invalid_cvd_parameters_rejected(key,value):
    with pytest.raises(ValueError):run_trench_depo(config(**{key:value}))


@pytest.mark.parametrize('key,low,high',[('cvd_overhang_pct',0,100),('cvd_cusping_pct',0,100),('cvd_bottom_ratio_pct',20,100)])
def test_actual_engine_split_changes_profile(key,low,high):
    a=run_trench_depo(config(**{key:low}))
    b=run_trench_depo(config(**{key:high}))
    assert a.final_profile!=b.final_profile
    assert all(math.isfinite(v) for p in b.final_profile for v in p)
    assert b.meta['cvd_enabled'] and b.meta['cvd_model'].startswith('empirical')
    # Deposition-only cannot lower the central original floor.
    assert min(y for x,y in b.final_profile)>=-500.0001


def test_existing_preset_and_split_compatibility():
    cfg=replace(incident_study_preset(),cycles=2,reparam_ds_a=10)
    old=run_trench_depo(cfg)
    changed=run_trench_depo(replace(cfg,cvd_overhang_pct=200,cvd_cusping_pct=200))
    assert old.frame_profiles==changed.frame_profiles
    split=_replace_sweep_config(cfg,'cvd_overhang_pct',50)
    assert split.cvd_enabled and split.redepo_enabled and split.sputter_enabled


def test_combined_cvd_inhibition_etch_and_redeposition():
    cfg=replace(incident_study_preset(),cycles=3,reparam_ds_a=10,cvd_enabled=True,
                inhibition_enabled=True,inhibition_strength_pct=20)
    result=run_trench_depo(cfg)
    assert result.meta['cvd_enabled'] and result.meta['inhibition_enabled']
    assert result.meta['redepo_enabled']
    assert result.frame_profiles[-1]!=result.frame_profiles[0]
    assert all(math.isfinite(v) for p in result.final_profile for v in p)


@pytest.fixture
def window(tmp_path,monkeypatch):
    for key,rel in [('GAPSIM_DATA_ROOT','data'),('GAPSIM_STRUCTURE_LIBRARY','structures.xlsx'),
                    ('GAPSIM_PARAMETER_LIBRARY','presets.json'),('GAPSIM_ADDON_ROOT','addons'),('GAPSIM_ADDON_STATE','addons.json')]:
        monkeypatch.setenv(key,str(tmp_path/rel))
    app=QApplication.instance() or QApplication([])
    # UI preference tests never read or modify the user's real saved choice.
    from PySide6.QtCore import QSettings
    from gapsim.emulation.help_preferences import HelpPreferences
    preferences = HelpPreferences(QSettings(str(tmp_path/'help.ini'), QSettings.IniFormat), parent=app)
    monkeypatch.setattr(app, '_gfe_help_preferences', preferences, raising=False)
    with mock.patch('gapsim.emulation.trench_depo_ui.QTimer.singleShot'):
        w=TrenchDepoWindow()
    w._set_workflow_step('progress')
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def test_four_group_navigation_and_dependencies(window):
    p=window.process_parameter_panel
    assert len(p.buttons)==4
    for i,button in enumerate(p.buttons):
        QTest.mouseClick(button,Qt.LeftButton)
        assert p.stack.currentIndex()==i and button.isChecked()
    p.select(1)
    assert not window.cvd_spins['cvd_overhang_pct'].isEnabled()
    QTest.mouseClick(window.chk_typical_cvd,Qt.LeftButton,pos=QPoint(8,window.chk_typical_cvd.height()//2))
    assert window.cvd_spins['cvd_overhang_pct'].isEnabled()
    assert not window.chk_depth_deposition.isEnabled()
    window.process_geometry_fold.setChecked(True)
    p.geometry_button.click()
    assert window.current_config().deposition_feature_width_a==500
    assert window.current_config().deposition_feature_depth_a==4000
    window.chk_sputter.setChecked(True)
    window.chk_redepo.setChecked(True)
    window.chk_incident_los.setChecked(True)
    assert not window.chk_ion_transmission.isEnabled()
    window.chk_inhibition_deposition.setChecked(True)
    p.conformal_only()
    c=window.current_config()
    assert not any((c.cvd_enabled,c.sputter_enabled,c.inhibition_enabled,c.deposition_depth_enabled))


def test_cvd_ui_preset_cache_and_replay_roundtrip(window,tmp_path):
    window.cmb_recipe_model.setCurrentIndex(window.cmb_recipe_model.findData('legacy_calibrated_v1'))
    window.process_presets_fold.setChecked(True)
    window.chk_typical_cvd.setChecked(True)
    window.cvd_spins['cvd_overhang_pct'].setValue(65)
    window.cvd_spins['cvd_cusping_pct'].setValue(42)
    window.cvd_spins['cvd_bottom_ratio_pct'].setValue(25)
    window.spin_cycles.setValue(2)
    window.edit_parameter_preset_name.setText('CVD engineer')
    window.btn_save_parameter_preset.click()
    before=window.current_config()
    for key in typical_cvd.DEFAULTS:
        change=False if key=='cvd_enabled' else getattr(before,key)+1
        assert window._preview_cache_key(before)!=window._preview_cache_key(replace(before,**{key:change}))
    window.chk_typical_cvd.setChecked(False)
    window.btn_apply_parameter_preset.click()
    assert typical_cvd.config_values(window.current_config())==typical_cvd.config_values(before)
    with mock.patch('gapsim.emulation.trench_depo_ui.QMessageBox.critical') as error:
        window.run_emulation(save_artifacts=False)
    error.assert_not_called()
    assert window._result.meta['cvd_enabled']
    path=save_trench_depo_result_json(window.current_config(),window._result,results_root=tmp_path)
    loaded,result,_=load_trench_depo_run(path)
    assert typical_cvd.config_values(loaded)==typical_cvd.config_values(before)
    window.chk_typical_cvd.setChecked(False)
    window.load_replay_json(path)
    assert window.current_config().cvd_enabled
    assert 'Typical CVD (경험식): ON' in window.edit_result_parameters.toPlainText()
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData('SFO3.1'))
    window.btn_apply_parameter_preset.click()
    assert not window.current_config().cvd_enabled
    assert window.current_config().redepo_incident_los_enabled

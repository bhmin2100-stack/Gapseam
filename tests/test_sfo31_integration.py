"""Production integration must reproduce the unchanged research sequence."""
from dataclasses import asdict, replace
from pathlib import Path
import sys
import numpy as np
import pytest

from gapsim.emulation.sfo31_verified import verified_sfo31_config, register_verified_sfo31, STRUCTURE_NAME
from gapsim.emulation.trench_depo import run_trench_depo
from gapsim.emulation.parameter_library import read_parameter_preset
from gapsim.emulation.structure_library import read_structure_points


def test_research_equivalence():
    research=Path(__file__).resolve().parents[1]/'experiments'
    if not all((research/name).exists() for name in ('angular_front.py','directed_growth.py','sfo31_shadow_model.py')):
        pytest.skip('Optional local research cross-check; production solver tests do not require research files')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'))
    import angular_front
    import directed_growth
    import sfo31_shadow_model
    cfg = replace(verified_sfo31_config(), cycles=8, reparam_ds_a=20.)
    actual = run_trench_depo(cfg)
    legacy = replace(cfg, front_scheme='legacy', ion_growth_fraction=0.)
    with sfo31_shadow_model.shadow_model(), angular_front.angular_front(enabled=True, fair_scale=0), directed_growth.directed_growth(.05, cfg.redepo_incident_sigma_deg):
        expected = run_trench_depo(legacy)
    assert actual.frame_steps == expected.frame_steps
    for a,b in zip(actual.frame_profiles, expected.frame_profiles):
        np.testing.assert_allclose(a,b,rtol=0,atol=1e-8)
    assert actual.frame_voids == expected.frame_voids


def test_register_backs_up_and_preserves_other_presets(tmp_path):
    from gapsim.emulation.parameter_library import save_parameter_preset
    p,s=tmp_path/'p.json',tmp_path/'s.xlsx'
    cfg=verified_sfo31_config()
    save_parameter_preset(p,'mine',replace(cfg,cycles=7),emulator_number=0)
    backups=register_verified_sfo31(p,s,replace_existing=True)
    assert backups and Path(backups[0]).exists()
    assert read_parameter_preset(p,'mine')['run_defaults']['cycles']==7
    record=read_parameter_preset(p,'SFO3.1')
    assert record['config']['front_scheme']=='angular_godunov_v1'
    assert record['run_defaults']['cycles']==1045
    np.testing.assert_allclose(read_structure_points(s,STRUCTURE_NAME),cfg.points,atol=1e-10)
    assert register_verified_sfo31(p,s)==[]


def test_invalid_solver_not_silently_ignored():
    cfg=verified_sfo31_config()
    with pytest.raises(ValueError):
        run_trench_depo(replace(cfg,recipe_model='ideal_conformal_v1'))


@pytest.mark.parametrize('changes', [
    {'sputter_enabled':False, 'redepo_enabled':False, 'redepo_incident_los_enabled':False},
    {'redepo_enabled':False},
    {'inhibition_enabled':False, 'deposition_depth_enabled':False},
    {'sputter_enabled':False, 'redepo_enabled':False, 'redepo_incident_los_enabled':False,
     'inhibition_enabled':False, 'deposition_depth_enabled':False},
])
def test_fixed_recipe_physics_switches(changes):
    cfg=replace(verified_sfo31_config(),cycles=2,reparam_ds_a=20.,**changes)
    result=run_trench_depo(cfg)
    assert result.frame_steps==[0,1,2]
    assert np.isfinite(result.final_profile).all()
    if changes.get('redepo_enabled') is False:
        assert not result.meta['redepo_enabled']


def test_front_does_not_leak_to_conformal_or_legacy():
    from gapsim.emulation.trench_depo import TrenchDepoConfig
    base=TrenchDepoConfig(points=((-100.,0.),(100.,0.)),cycles=2,angstrom_per_cycle=.56)
    before=run_trench_depo(base)
    run_trench_depo(replace(verified_sfo31_config(),cycles=2,reparam_ds_a=20.))
    after=run_trench_depo(base)
    assert before.final_profile==after.final_profile


def test_ui_roundtrip(tmp_path, monkeypatch):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication
    from gapsim.emulation.trench_depo_ui import TrenchDepoWindow
    for key,rel in [('GAPSIM_DATA_ROOT','data'),('GAPSIM_STRUCTURE_LIBRARY','s.xlsx'),('GAPSIM_PARAMETER_LIBRARY','p.json'),('GAPSIM_ADDON_ROOT','addons'),('GAPSIM_ADDON_STATE','addons.json')]:
        monkeypatch.setenv(key,str(tmp_path/rel))
    app=QApplication.instance() or QApplication([])
    with patch('gapsim.emulation.trench_depo_ui.QTimer.singleShot'):
        w=TrenchDepoWindow()
    try:
        w.load_sfo31_reference()
        actual=asdict(w.current_config());expected=asdict(verified_sfo31_config())
        ignored={'points','initial_voids','inhibition_process_model'}
        diffs={k:(expected[k],actual[k]) for k in expected if k not in ignored and expected[k]!=actual[k] and not (isinstance(expected[k],float) and isinstance(actual[k],float) and abs(expected[k]-actual[k])<1e-12)}
        assert not diffs, diffs
        assert actual['inhibition_process_model']=='ald'
        summary=w._format_result_parameters(w.current_config(),None)
        assert 'SFO3.1 동일 반복' in summary
        assert '누적 기준량 (기준면 순성장): 585.2 A' in summary
        np.testing.assert_allclose(actual['points'],expected['points'],atol=1e-10,rtol=0)
        old=w._preview_cache_key(w.current_config())
        w.spin_ion_growth_fraction.setValue(.06)
        assert old!=w._preview_cache_key(w.current_config())
        from gapsim.emulation.trench_depo import build_trench_depo_sweep_configs
        cases=build_trench_depo_sweep_configs(w.current_config(),'ion_growth_fraction',0,.1,.05)
        assert [c.config.ion_growth_fraction for c in cases]==[0,.05,.1]
        cases=build_trench_depo_sweep_configs(w.current_config(),'inhibition_strength_pct',50,60,5)
        assert all(c.config.sputter_enabled and c.config.redepo_enabled for c in cases)
        # The run JSON is a complete recipe, unlike the geometry-independent
        # process preset. Both new controls and the inhibition law must survive.
        from gapsim.emulation.trench_depo_export import save_trench_depo_result_json
        cfg=replace(w.current_config(),cycles=2,reparam_ds_a=20.)
        result=run_trench_depo(cfg)
        path=save_trench_depo_result_json(cfg,result,results_root=tmp_path)
        w.load_replay_json(path)
        assert w.current_config().front_scheme==cfg.front_scheme
        assert w.current_config().ion_growth_fraction==cfg.ion_growth_fraction
        assert w.current_config().inhibition_process_model=='ald'
        assert w.current_config().redepo_max_distance_a==5000.
        assert w.current_config().cycles==2
        assert w.current_config().reparam_ds_a==20.
        # Exercise the real button -> QThread -> engine -> export -> result path.
        # Only the output location and modal error reporting are intercepted.
        import time
        w._runs_root=tmp_path/'button-run'
        with patch('gapsim.emulation.trench_depo_ui.QMessageBox.critical') as error:
            w.btn_run.click()
            deadline=time.monotonic()+30
            while w._emulation_thread is not None and time.monotonic()<deadline:
                app.processEvents();time.sleep(.005)
            assert w._emulation_thread is None
        error.assert_not_called()
        np.testing.assert_allclose(w._result.final_profile,result.final_profile,rtol=0,atol=1e-8)
        assert list(w._runs_root.rglob('*.gif'))
        assert list(w._runs_root.rglob('*.json'))
    finally:
        if w._emulation_thread is not None:
            w.cancel_emulation()
            import time
            while w._emulation_thread is not None:
                app.processEvents();time.sleep(.005)
        w.close();app.processEvents()

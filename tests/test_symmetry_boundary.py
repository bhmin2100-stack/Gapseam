from dataclasses import replace
import numpy as np
import pytest
from gapsim.emulation.trench_depo import TrenchDepoConfig, run_trench_depo
from gapsim.emulation.incident_presets import sfo31_preset
from gapsim.engine.deposition_pipeline import init_simulation_state
from gapsim.engine.symmetry import configure

POINTS = [(-100.,0.),(-25.,0.),(-25.,-100.),(25.,-100.),(25.,0.),(100.,0.)]


@pytest.mark.parametrize('shift',[0.,17.])
@pytest.mark.parametrize('reverse',[False,True])
def test_detection_independent_of_point_density_and_order(shift,reverse):
    points = POINTS[:1]+[(-60.,0.)]+POINTS[1:]
    points = [(x+shift,y) for x,y in points]
    if reverse: points.reverse()
    state = init_simulation_state(points)
    assert configure(state,'auto')['active']
    assert state.meta['symmetry']['axis_a'] == shift


@pytest.mark.parametrize('model',['legacy_calibrated_v1','ideal_conformal_v1','physical_transport_v1'])
@pytest.mark.parametrize('process',['ald','cvd'])
def test_all_saved_frames_symmetric(model,process):
    cfg = TrenchDepoConfig(points=POINTS, cycles=3, angstrom_per_cycle=1.,
        reparam_ds_a=5., recipe_model=model, process_type=process,
        cvd_rate_a_per_s=1., cvd_duration_s=3., transport_ray_count=16)
    result = run_trench_depo(cfg)
    assert result.meta['symmetry']['active']
    for frame in result.frame_profiles:
        a = np.asarray(frame); b = a[::-1].copy(); b[:,0] *= -1
        assert np.max(abs(a-b)) < 1e-10


def test_asymmetric_input_and_void_are_not_repaired():
    points = list(POINTS); points[1] = (-30.,0.)
    assert not configure(init_simulation_state(points),'auto')['active']
    cfg = TrenchDepoConfig(points=POINTS,cycles=1,initial_voids=(
        ((50.,-30.),(60.,-30.),(60.,-40.),(50.,-40.)),))
    result = run_trench_depo(cfg)
    assert not result.meta['symmetry']['active']


def test_original_sfo_can_replay_without_boundary():
    assert sfo31_preset().symmetry_mode == 'off'
    result = run_trench_depo(replace(sfo31_preset(),cycles=2,reparam_ds_a=20.))
    assert not result.meta['symmetry']['active']


def test_redeposition_remains_active():
    cfg = replace(sfo31_preset(),points=POINTS,cycles=3,reparam_ds_a=5.,
                  symmetry_mode='auto',redepo_max_distance_a=300.)
    result = run_trench_depo(cfg)
    assert result.meta['symmetry']['active']
    assert result.meta['redepo_active']
    assert any(result.meta['frame_redepo_overlays'])


def test_unknown_mode_rejected():
    with pytest.raises(ValueError,match='symmetry_mode'):
        run_trench_depo(TrenchDepoConfig(cycles=0,symmetry_mode='force'))


def test_asymmetric_auto_has_identical_geometry_to_off():
    points = list(POINTS); points[1] = (-30.,0.)
    config = TrenchDepoConfig(points=points,cycles=3,angstrom_per_cycle=1.,
                             reparam_ds_a=5.)
    auto = run_trench_depo(config)
    off = run_trench_depo(replace(config,symmetry_mode='off'))
    assert not auto.meta['symmetry']['active']
    assert auto.frame_profiles == off.frame_profiles
    assert auto.frame_voids == off.frame_voids


def test_parallel_runs_do_not_share_boundary_state():
    from concurrent.futures import ThreadPoolExecutor
    configs = [TrenchDepoConfig(points=[(x+shift,y) for x,y in POINTS],
        cycles=2,angstrom_per_cycle=1.,reparam_ds_a=5.,symmetry_mode=mode)
        for shift,mode in [(0.,'auto'),(17.,'auto'),(0.,'off')]]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run_trench_depo,configs))
    assert [r.meta['symmetry']['active'] for r in results] == [True,True,False]
    assert [r.meta['symmetry']['axis_a'] for r in results] == [0.,17.,0.]
    assert results[0].meta['symmetry'] is not results[1].meta['symmetry']

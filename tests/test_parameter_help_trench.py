from dataclasses import asdict
import math
from pathlib import Path
import importlib.util

import pytest

from gapsim.emulation.parameter_help import HELP
from gapsim.emulation.parameter_help_trench import examples, movie_catalog, load_movie
from gapsim.emulation.parameter_help_visuals import fit_transform, frame_at, incoming_paths
from gapsim.emulation.trench_depo import TrenchDepoConfig, run_trench_depo
from PySide6.QtCore import QRectF


def test_all_physical_parameters_have_actual_trench_movies():
    nonphysical = {'spin_depth_closure_threshold', 'cmb_depth_display_mode'}
    assert set(HELP)-nonphysical == set(movie_catalog()['cases'])
    assert set(examples())==set(movie_catalog()['cases'])


def test_asset_fingerprint_matches_current_engine():
    builder=Path(__file__).resolve().parents[1]/'experiments/build_help_trench_movies.py'
    spec=importlib.util.spec_from_file_location('help_movie_builder',builder)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert movie_catalog()['engine_sha256']==module.engine_fingerprint()


def test_engine_fingerprint_ignores_git_checkout_line_endings(monkeypatch):
    builder=Path(__file__).resolve().parents[1]/'experiments/build_help_trench_movies.py'
    spec=importlib.util.spec_from_file_location('help_movie_newline_check',builder)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected=module.engine_fingerprint()
    read=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda p:read(p).replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))
    assert module.engine_fingerprint()==expected


@pytest.mark.parametrize('key', list(examples()))
def test_movies_have_exact_recipes_and_calculated_frame_sequences(key):
    movie=load_movie(key)
    configs=examples()[key].configs()
    for c,run in zip(configs,movie['runs']):
        stored=TrenchDepoConfig(**{**run['config'],'points':tuple(tuple(p) for p in run['config']['points'])})
        assert c==stored
        frames=run['frames']
        assert frames[0]['step']==0 and frames[-1]['step']==c.cycles
        assert [f['step'] for f in frames]==sorted(set(f['step'] for f in frames))
        assert all(len(f['profile'])>2 for f in frames)
        assert all(math.isfinite(v) for f in frames for p in f['profile'] for v in p)
    differences={k for k,v in asdict(configs[0]).items() if v!=asdict(configs[1])[k]}
    allowed={examples()[key].field}
    if key in ('chk_sputter','chk_redepo'):
        allowed.update(('redepo_enabled','redepo_incident_los_enabled','ion_transmission_enabled'))
    assert differences<=allowed
    assert movie['difference_a']>=0


@pytest.mark.parametrize('key', ['cvd_overhang_pct','cvd_cusping_pct','spin_redepo_emit_power',
                                'spin_incident_sigma','spin_inhibition_strength',
                                'spin_depth_post_fill_hole_pct','spin_ion_floor'])
def test_packaged_coordinates_and_voids_match_fresh_actual_simulation(key):
    movie=load_movie(key)
    for config,run in zip(examples()[key].configs(),movie['runs']):
        actual=run_trench_depo(config)
        for f in run['frames']:
            assert f['profile']==[list(p) for p in actual.frame_profiles[f['step']]]
            assert f['voids']==[[list(p) for p in loop] for loop in actual.frame_voids[f['step']]]
        # Python 3.11/3.13 and CPU reductions differ in the last floating-point bit.
        assert run['captured_mass']==pytest.approx(actual.meta.get('redepo_total_mass_last',0.),rel=1e-12,abs=1e-10)


def test_redirection_data_really_contains_sources_targets_and_small_geometry_difference():
    movie=load_movie('spin_redepo_emit_power')
    assert 0<movie['difference_a']<15
    assert all(run['captured_mass']>0 for run in movie['runs'])
    assert any(f['transport'] and f['redepo'] for run in movie['runs'] for f in run['frames'])
    assert movie['runs'][0]['frames'][-1]['profile']!=movie['runs'][1]['frames'][-1]['profile']


def test_reference_dimensions_do_not_modify_initial_coordinates():
    for key in ('spin_depth_feature_width','spin_depth_feature_depth','spin_depth_feature_length'):
        movie=load_movie(key)
        assert movie['runs'][0]['config']['points']==movie['runs'][1]['config']['points']


def test_closure_movie_contains_actual_trapped_void_and_budget_difference():
    movie=load_movie('spin_depth_post_fill_hole_pct')
    a,b=movie['runs']
    assert a['frames'][-1]['voids'] and b['frames'][-1]['voids']
    assert a['frames'][-1]['voids']!=b['frames'][-1]['voids']


def test_frames_are_selected_without_morphing_or_inventing_intermediate_shapes():
    run=load_movie('cvd_overhang_pct')['runs'][0]
    for t in (0,.1,.37,.61,1):
        assert any(frame_at(run,t) is f for f in run['frames'])


def test_isotropic_common_view_transform():
    transform,scale=fit_transform((-700,-900,700,100),QRectF(0,0,240,220))
    a,b,c=transform(0,0),transform(100,0),transform(0,100)
    assert b.x()-a.x()==pytest.approx(a.y()-c.y())
    assert b.x()-a.x()==pytest.approx(100*scale)


def test_ion_illustration_paths_stop_at_first_surface_intersection():
    # Flat plane blocks every displayed ray, so no dot can enter the substrate.
    paths=incoming_paths([(-10000.,0.),(10000.,0.)],20.,51)
    assert len(paths)==15
    assert all(y>0 and abs(end[1])<1e-8 for (_,y),end in paths)

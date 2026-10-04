from dataclasses import asdict
import math
from pathlib import Path
import importlib.util

import pytest

from gapsim.emulation.parameter_help import HELP
from gapsim.emulation.parameter_help_trench import examples, movie_catalog, load_movie, movie_key, recipe_note
from gapsim.emulation.parameter_help_visuals import fit_transform, frame_at, incoming_paths
from gapsim.emulation.trench_depo import TrenchDepoConfig, run_trench_depo
from PySide6.QtCore import QRectF


def test_all_physical_parameters_have_actual_trench_movies():
    nonphysical = {'spin_depth_closure_threshold', 'cmb_depth_display_mode',
                  'cmb_process_type', 'cmb_recipe_model', 'cmb_growth_basis'}
    covered = {key.split('@')[0] for key in movie_catalog()['cases']}
    assert set(HELP)-nonphysical <= covered
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
    key_parts = key.split('@')
    movie=load_movie(*key_parts)
    configs=examples()[key].configs()
    assert len(configs)==len(movie['runs'])==len(movie['labels'])
    for c,run in zip(configs,movie['runs']):
        stored=TrenchDepoConfig(**{**run['config'],
            'points':tuple(tuple(p) for p in run['config']['points']),
            'initial_voids':tuple(tuple(tuple(p) for p in loop) for loop in run['config'].get('initial_voids',()))})
        assert c==stored
        frames=run['frames']
        assert frames[0]['step']==0
        if c.process_type == 'cvd':
            assert frames[-1]['time_s'] == pytest.approx(c.cvd_duration_s)
            assert all(a['time_s'] <= b['time_s'] for a,b in zip(frames, frames[1:]))
        else:
            assert frames[-1]['step']==c.cycles
        assert [f['step'] for f in frames]==sorted(set(f['step'] for f in frames))
        assert all(len(f['profile'])>2 for f in frames)
        assert all(math.isfinite(v) for f in frames for p in f['profile'] for v in p)
    for config in configs[1:]:
        differences={k for k,v in asdict(configs[0]).items() if v!=asdict(config)[k]}
        assert differences=={examples()[key].field}
    assert movie['difference_a']>=0


@pytest.mark.parametrize('key', ['cvd_overhang_pct','cvd_bottom_ratio_pct','cvd_cusping_pct','spin_redepo_emit_power',
                                'spin_incident_sigma','spin_inhibition_strength',
                                'spin_depth_post_fill_hole_pct','spin_ion_floor',
                                'spin_incident_rays','spin_inhibition_smoothing',
                                'slider_ion_aperture_shadow'])
def test_packaged_coordinates_and_voids_match_fresh_actual_simulation(key):
    movie=load_movie(key)
    for config,run in zip(examples()[key].configs(),movie['runs']):
        actual=run_trench_depo(config)
        for f in run['frames']:
            assert f['profile']==[list(p) for p in actual.frame_profiles[f['step']]]
            assert f['voids']==[[list(p) for p in loop] for loop in actual.frame_voids[f['step']]]
        # Python 3.11/3.13 and CPU reductions differ in the last floating-point bit.
        assert run['captured_mass']==pytest.approx(actual.meta.get('redepo_total_mass_last',0.),rel=1e-12,abs=1e-10)


def test_redirection_svt_uses_visible_context_and_actual_transport():
    movie=load_movie('spin_redepo_emit_power')
    assert movie['difference_a']>75
    assert movie['context']=='강한 식각·재증착'
    assert movie['labels']==['3 °','10 °','35 °']
    assert all(run['captured_mass']>0 for run in movie['runs'])
    assert any(f['transport'] and f['redepo'] for run in movie['runs'] for f in run['frames'])
    assert movie['runs'][0]['frames'][-1]['profile']!=movie['runs'][1]['frames'][-1]['profile']


def test_reference_dimensions_do_not_modify_initial_coordinates():
    for key in ('spin_depth_feature_width','spin_depth_feature_depth','spin_depth_feature_length'):
        movie=load_movie(key)
        assert movie['runs'][0]['config']['points']==movie['runs'][1]['config']['points']


def test_closure_movie_contains_actual_trapped_void_and_budget_difference():
    movie=load_movie('spin_depth_post_fill_hole_pct')
    a,b=movie['runs'][0],movie['runs'][-1]
    assert a['frames'][-1]['voids'] and b['frames'][-1]['voids']
    assert a['frames'][-1]['voids']!=b['frames'][-1]['voids']


def test_frames_are_selected_without_morphing_or_inventing_intermediate_shapes():
    run=load_movie('cvd_overhang_pct')['runs'][0]
    for t in (0,.1,.37,.61,1):
        assert any(frame_at(run,t) is f for f in run['frames'])


def test_svt_backgrounds_and_units_are_reproducible():
    from gapsim.emulation.parameter_help_trench import SVT_CONTEXTS, recipe_note
    for key in SVT_CONTEXTS:
        movie=load_movie(key)
        assert movie['context']==SVT_CONTEXTS[key][0]
        assert '현재 입력으로 실행한 결과가 아닙니다' in recipe_note(movie)
        assert '하나만 변경' in recipe_note(movie)
        assert len(movie['runs'])==3
    for example in examples().values():
        assert len(example.values)==(2 if isinstance(example.values[0],(bool,str)) or None in example.values else 3)
    baseline=examples(svt=False)['spin_redepo_emit_power']
    assert baseline.values==(3.,35.) and baseline.config.cycles==24


def test_recipe_note_describes_middle_example_not_low_endpoint():
    assert '기준: 20 cycle' in recipe_note(load_movie('spin_cycles'))


@pytest.mark.parametrize('model', ['ideal_conformal_v1', 'physical_transport_v1'])
def test_recipe_movie_never_substitutes_another_models_result(model):
    movie = load_movie('spin_angstrom_per_cycle', model)
    assert movie['key'] == movie_key('spin_angstrom_per_cycle', model)
    assert {run['config']['recipe_model'] for run in movie['runs']} == {model}
    assert load_movie('cvd_overhang_pct', model) is None
    assert 'GPC' in recipe_note(movie)
    cvd = load_movie('spin_cvd_rate', model)
    assert all(run['config']['process_type']=='cvd' for run in cvd['runs'])
    assert 'D/R' in recipe_note(cvd)


@pytest.mark.parametrize('key,model', [
    ('spin_angstrom_per_cycle', 'ideal_conformal_v1'),
    ('spin_precursor_sticking', 'physical_transport_v1'),
    ('spin_ald_exposure', 'physical_transport_v1'),
    ('spin_cvd_duration', 'physical_transport_v1'),
    ('spin_redepo_efficiency', 'physical_transport_v1'),
    ('spin_inhibitor_exposure', 'physical_transport_v1'),
])
def test_new_recipe_movies_match_recomputed_final_geometry(key, model):
    movie = load_movie(key, model)
    for c, run in zip(examples()[movie_key(key, model)].configs(), movie['runs']):
        actual = run_trench_depo(c)
        assert run['frames'][-1]['profile'] == [list(point) for point in actual.frame_profiles[-1]]
        assert run['frames'][-1]['voids'] == [[list(point) for point in loop] for loop in actual.frame_voids[-1]]


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

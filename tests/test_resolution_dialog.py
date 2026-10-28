from dataclasses import asdict, replace
import time
from unittest import mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from tests.test_process_parameters import window
from gapsim.emulation.resolution_dialog import (
    POINT_WARNING_THRESHOLD, ResolutionDialog, estimate_resolution, resolution_choices,
)
from gapsim.emulation.sfo31_verified import verified_sfo31_config
from gapsim.emulation.trench_depo import run_trench_depo
from gapsim.emulation.trench_depo_export import load_trench_depo_run
from gapsim.emulation.trench_depo_ui import _EmulationRunWorker
from gapsim.engine.deposition_pipeline import equal_arc_resample


DEEP = ((-5000., 0.), (-1150., 0.), (-1150., -50000.),
        (1150., -50000.), (1150., 0.), (5000., 0.))


@pytest.mark.parametrize('points', [DEEP, DEEP[::-1], ((0., 0.), (100., -50.), (200., 0.))])
@pytest.mark.parametrize('spacing', [4., 20., 40.])
def test_estimate_matches_uniform_resampling_without_running_simulation(points, spacing):
    estimate = estimate_resolution(points)
    assert estimate.points_at(spacing) == len(equal_arc_resample(points, spacing))


def test_deep_structure_proposes_bounded_coarser_choices():
    estimate = estimate_resolution(DEEP)
    assert estimate.depth_a == 50000
    assert estimate.points_at(4.) == 27501
    assert resolution_choices(estimate, 4.) == [('현재 유지', 4.), ('권장', 20.), ('더 빠르게', 40.)]
    assert estimate.points_at(20.) == 5501
    assert estimate.points_at(40.) == 2751
    enormous = estimate_resolution(((0., 0.), (1., -1e7), (2., 0.)))
    assert all(spacing <= 200 for _, spacing in resolution_choices(enormous, 100.))
    assert resolution_choices(enormous, 200.) == [('현재 유지', 200.)]


@pytest.mark.parametrize('spacing', [0., -1., float('nan'), float('inf')])
def test_invalid_spacing_rejected(spacing):
    with pytest.raises(ValueError):
        estimate_resolution(DEEP).points_at(spacing)


def test_standard_preset_is_below_warning_threshold(window):
    config = verified_sfo31_config()
    assert estimate_resolution(config.points).points_at(config.reparam_ds_a) <= POINT_WARNING_THRESHOLD
    with mock.patch.object(ResolutionDialog, 'exec', side_effect=AssertionError('unnecessary popup')):
        assert window._choose_run_resolution(config) is config


def test_dialog_default_and_mouse_selection(window):
    dialog = ResolutionDialog(estimate_resolution(DEEP), 4., window)
    try:
        dialog.show()
        QApplication.processEvents()
        assert dialog.selected_spacing_a() == 20.
        QTest.mouseClick(dialog.radios[0], Qt.MouseButton.LeftButton)
        assert dialog.selected_spacing_a() == 4.
        QTest.mouseClick(dialog.radios[2], Qt.MouseButton.LeftButton)
        assert dialog.selected_spacing_a() == 40.
    finally:
        dialog.close()


@pytest.mark.parametrize('choice', [0, 1, 2])
def test_only_spacing_changes_after_explicit_acceptance(window, choice):
    config = replace(verified_sfo31_config(), points=DEEP)
    original = asdict(config)
    def choose(dialog):
        dialog.radios[choice].setChecked(True)
        return QDialog.DialogCode.Accepted
    with mock.patch.object(ResolutionDialog, 'exec', choose):
        selected = window._choose_run_resolution(config)
    expected = [4., 20., 40.][choice]
    assert asdict(config) == original
    assert asdict(selected) == dict(original, reparam_ds_a=expected)
    if choice:
        assert window.spin_reparam_ds.value() == expected
    else:
        assert selected is config


@pytest.mark.parametrize('split', [False, True])
def test_cancel_does_not_start_run_or_change_controls_and_results(window, split):
    window._set_structure_points(DEEP)
    window._set_quality_mode_for_ds(4.)
    before = asdict(window.current_config())
    result = window._result
    status = window.lbl_progress_view_status.text()
    enabled = (window.btn_run.isEnabled(), window.btn_run_split.isEnabled())
    with mock.patch.object(ResolutionDialog, 'exec', return_value=QDialog.DialogCode.Rejected), \
         mock.patch('gapsim.emulation.trench_depo_ui.run_trench_depo', side_effect=AssertionError('run canceled')), \
         mock.patch('gapsim.emulation.trench_depo_ui.run_trench_depo_sweep', side_effect=AssertionError('split canceled')):
        (window.run_split_test if split else window.run_emulation)()
    assert window._emulation_thread is None
    assert asdict(window.current_config()) == before
    assert window._result is result
    assert window.lbl_progress_view_status.text() == status
    assert (window.btn_run.isEnabled(), window.btn_run_split.isEnabled()) == enabled


def test_automatic_preview_does_not_silently_run_or_lower_resolution(window):
    window._set_structure_points(DEEP)
    window._set_quality_mode_for_ds(4.)
    with mock.patch.object(ResolutionDialog, 'exec', side_effect=AssertionError('no automatic popup')), \
         mock.patch('gapsim.emulation.trench_depo_ui.run_trench_depo', side_effect=AssertionError('no expensive preview')):
        window.run_emulation(save_artifacts=False, use_preview_cache=True)
    assert window.spin_reparam_ds.value() == 4.
    assert '해상도를 선택' in window.statusBar().currentMessage()


def test_split_uses_one_selected_resolution_for_all_cases(window):
    window._set_structure_points(DEEP)
    window._set_quality_mode_for_ds(4.)
    with mock.patch.object(ResolutionDialog, 'exec', return_value=QDialog.DialogCode.Accepted) as dialog, \
         mock.patch('gapsim.emulation.trench_depo_ui.run_trench_depo_sweep', return_value=[]) as sweep, \
         mock.patch('gapsim.emulation.trench_depo_ui.export_trench_depo_sweep_runs', return_value=[]):
        window.run_split_test()
    assert dialog.call_count == 1
    assert sweep.call_args.args[0].reparam_ds_a == 20.
    assert window.spin_reparam_ds.value() == 20.


def test_real_button_selected_spacing_reaches_engine_and_saved_history(window, tmp_path):
    window._set_structure_points(DEEP)
    window._apply_parameter_config_values(asdict(replace(verified_sfo31_config(), cycles=1)))
    window.spin_cycles.setValue(1)
    window._set_quality_mode_for_ds(4.)
    original = window.current_config()
    assert original.points == DEEP
    window._runs_root = tmp_path / 'runs'
    with mock.patch.object(ResolutionDialog, 'exec', return_value=QDialog.DialogCode.Accepted), \
         mock.patch('gapsim.emulation.trench_depo_ui.QMessageBox.critical') as error:
        QTest.mouseClick(window.btn_run, Qt.MouseButton.LeftButton)
        deadline = time.monotonic() + 30
        while window._emulation_thread is not None and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(.005)
        assert window._emulation_thread is None
    error.assert_not_called()
    expected_config = replace(original, reparam_ds_a=20.)
    assert asdict(window._result_config) == asdict(expected_config)
    expected = run_trench_depo(expected_config)
    assert window._result.frame_profiles == expected.frame_profiles
    files = list(window._runs_root.rglob('에뮬레이터재생_*.json'))
    assert len(files) == 1
    saved_config, saved_result, _ = load_trench_depo_run(files[0])
    assert saved_config.reparam_ds_a == 20.
    assert saved_result.frame_profiles == expected.frame_profiles


def test_worker_progress_shows_internal_points_between_cycles():
    worker = _EmulationRunWorker(config=verified_sfo31_config(), cache_key=(), request_note='',
                                 save_artifacts=True, use_preview_cache=False)
    updates = []
    worker.progress.connect(lambda a, b, text: updates.append((a, b, text)))
    worker._emit_detail_progress({'kind': 'cycle', 'step': 245, 'total': 1045, 'points': 27501})
    worker._emit_detail_progress({'step': 245, 'total': 1045, 'substep': 1, 'substeps': 1, 'phase': 'start'})
    assert all('내부 점 27,501개' in row[2] for row in updates)
    assert updates[0][:2] == (245, 1045)

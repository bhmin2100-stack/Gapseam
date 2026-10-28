import json
import math
import time
from dataclasses import asdict
from unittest import mock

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from tests.test_process_parameters import window
from gapsim.emulation import trench_depo_export as ex
from gapsim.emulation.gif_export_dialog import GifExportDialog
from gapsim.emulation.trench_depo import TrenchDepoConfig, TrenchDepoResult


def result_fixture(count=7):
    profiles = [[(-30., float(i)), (-10., -20. + i), (10., -20. + i), (30., float(i))]
                for i in range(count)]
    return TrenchDepoResult(list(range(count)), profiles, [[] for _ in profiles], profiles[-1],
                            {'cycles': count - 1, 'process_type': 'ald', 'angstrom_per_cycle': 1.})


@pytest.mark.parametrize('count', [0, 1, 2, 99, 100, 101, 124, 1046, 1000000])
@pytest.mark.parametrize('interval', [1, 3, 10, 100, 10000000])
def test_indices_are_bounded_ordered_and_include_both_endpoints(count, interval):
    indices = ex.gif_frame_indices(count, interval)
    assert len(indices) <= 100
    assert indices == sorted(set(indices))
    if not count:
        assert indices == []
        return
    assert indices[0] == 0 and indices[-1] == count - 1
    step = max(interval, math.ceil((count - 1) / 99), 1)
    assert ex.minimum_gif_interval(count) == max(1, math.ceil((count - 1) / 99))
    assert all(b - a == step for a, b in zip(indices[:-2], indices[1:-1]))
    if len(indices) > 1:
        assert 0 < indices[-1] - indices[-2] <= step


@pytest.mark.parametrize('interval', [0, -1, True, 1.5, '2'])
def test_bad_interval_is_rejected(interval):
    with pytest.raises(ValueError):
        ex.gif_frame_indices(10, interval)


def test_dialog_clamps_to_limit_and_updates_count(window):
    dialog = GifExportDialog(1046, 1, window)
    try:
        assert dialog.interval.minimum() == 11
        assert dialog.interval.value() == 11
        assert '96장' in dialog.summary.text()
        dialog.interval.setValue(100)
        assert '12장' in dialog.summary.text()
    finally:
        dialog.close()


def test_sampled_images_are_identical_to_the_same_original_frames(window, tmp_path):
    config = TrenchDepoConfig(cycles=6, angstrom_per_cycle=1.)
    result = result_fixture()
    before = json.dumps(asdict(result), sort_keys=True)
    all_images = ex._render_gif_frames(result, config, request_note='', frame_interval=1)
    with mock.patch.object(ex, '_frame_progress_label', wraps=ex._frame_progress_label) as labels:
        sampled = ex._render_gif_frames(result, config, request_note='', frame_interval=4)
    try:
        assert [call.args[2] for call in labels.call_args_list] == [0, 0, 4, 4, 6, 6]
        assert len(sampled) == 3
        for image, index in zip(sampled, [0, 4, 6]):
            assert image.tobytes() == all_images[index].tobytes()
    finally:
        for image in all_images + sampled:
            image.close()
    path = ex.export_trench_depo_gif(config, result, tmp_path / 'manual.gif', frame_interval=4)
    with Image.open(path) as gif:
        assert gif.n_frames == 3
        assert gif.size == (1820, 1040)
    assert json.dumps(asdict(result), sort_keys=True) == before


def test_renderer_reports_the_capped_plan_before_starting_work(window):
    result = result_fixture(101)
    class StopProbe(Exception):
        pass
    updates = []
    def progress(done, total):
        updates.append((done, total))
        raise StopProbe()
    with pytest.raises(StopProbe):
        ex._render_gif_frames(result, TrenchDepoConfig(), request_note='', progress_cb=progress)
    assert updates == [(0, 51)]


def test_failed_gif_replace_preserves_existing_file_and_closes_images(tmp_path):
    target = tmp_path / 'keep.gif'
    target.write_bytes(b'previous GIF')
    frame = Image.new('RGB', (2, 2), 'white')
    with mock.patch.object(ex, '_render_gif_frames', return_value=[frame]), \
         mock.patch.object(ex.os, 'replace', side_effect=OSError('write failed')):
        with pytest.raises(OSError):
            ex.export_trench_depo_gif(TrenchDepoConfig(), result_fixture(1), target)
    assert target.read_bytes() == b'previous GIF'
    assert list(tmp_path.iterdir()) == [target]
    with pytest.raises(ValueError):
        frame.getpixel((0, 0))


def test_cancel_leaves_no_output_and_preserves_existing_gif(window, tmp_path):
    target = tmp_path / 'output' / 'keep.gif'
    target.parent.mkdir()
    target.write_bytes(b'previous GIF')
    def progress(done, total):
        if done == 1:
            raise ex.GifExportCanceled()
    with pytest.raises(ex.GifExportCanceled):
        ex.export_trench_depo_gif(TrenchDepoConfig(), result_fixture(3), target, progress_cb=progress)
    assert target.read_bytes() == b'previous GIF'
    assert list(target.parent.iterdir()) == [target]


def test_actual_run_button_displays_result_before_json_export_and_never_renders_gif(window, tmp_path):
    window._runs_root = tmp_path
    window._set_structure_points([(-50., 0.), (-20., 0.), (-20., -40.), (20., -40.), (20., 0.), (50., 0.)])
    window.cmb_recipe_model.setCurrentIndex(window.cmb_recipe_model.findData('ideal_conformal_v1'))
    window.spin_cycles.setValue(3)
    window.spin_angstrom_per_cycle.setValue(1.)
    calls = []
    def save(config, result, **kwargs):
        assert window._result is result
        assert window.btn_save_gif.isEnabled()
        assert kwargs['include_gif'] is False
        calls.append(result)
        return ex.export_trench_depo_run(config, result, **kwargs)
    with mock.patch('gapsim.emulation.trench_depo_ui.export_trench_depo_run', side_effect=save), \
         mock.patch.object(ex, '_render_gif_frames', side_effect=AssertionError('automatic GIF forbidden')):
        QTest.mouseClick(window.btn_run, Qt.MouseButton.LeftButton)
        deadline = time.monotonic() + 10
        while window._emulation_thread is not None and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(.005)
    assert window._emulation_thread is None
    assert len(calls) == 1
    assert len(window._result.frame_profiles) == 4
    assert list(tmp_path.rglob('*.json'))
    assert not list(tmp_path.rglob('*.gif'))
    assert window.btn_run.isEnabled()


def test_manual_gif_button_uses_executed_config_and_requested_interval(window, tmp_path):
    config = window.current_config()
    result = result_fixture()
    window._apply_emulation_result(config, result, None, use_preview_cache=False)
    window.spin_angstrom_per_cycle.setValue(99)
    path = tmp_path / 'chosen.gif'
    def choose(dialog):
        dialog.interval.setValue(4)
        return QDialog.DialogCode.Accepted
    with mock.patch.object(GifExportDialog, 'exec', choose), \
         mock.patch('gapsim.emulation.trench_depo_ui.QFileDialog.getSaveFileName', return_value=(str(path), '')), \
         mock.patch('gapsim.emulation.trench_depo_ui.export_trench_depo_gif', wraps=ex.export_trench_depo_gif) as exporter:
        QTest.mouseClick(window.btn_save_gif, Qt.MouseButton.LeftButton)
    assert exporter.call_args.args[:2] == (config, result)
    assert exporter.call_args.kwargs['frame_interval'] == 4
    with Image.open(path) as gif:
        assert gif.n_frames == 3
    assert '3장' in window.statusBar().currentMessage()

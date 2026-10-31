import json
import time
from dataclasses import asdict, replace
from unittest import mock

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_process_parameters import window
from gapsim.emulation.trench_depo import TrenchDepoConfig, TrenchDepoResult, run_trench_depo
from gapsim.emulation.trench_depo_export import (
    load_trench_depo_history, load_trench_depo_run, result_to_payload,
    save_trench_depo_result_json,
)
from gapsim.emulation.trench_depo_ui import TrenchDepoWindow


def small_result():
    frames = [[(-20., float(i)), (20., float(i))] for i in range(4)]
    return TrenchDepoResult(frame_steps=[0, 2, 4, 6], frame_profiles=frames,
        frame_voids=[[], [[(-2., -5.), (2., -5.), (0., -2.)]], [], []],
        final_profile=frames[-1], meta={"frame_doses_a": [0., 1.12, 2.24, 3.36],
        "frame_etch_overlays": [[], [[0., 1., .2]], [], []], "cycles": 6})


def test_explicit_path_full_data_and_display_state_roundtrip(tmp_path):
    config = TrenchDepoConfig(cycles=6, angstrom_per_cycle=.56,
        points=[(-20., 0.), (20., 0.)], initial_voids=(((-2., -5.), (2., -5.), (0., -2.)),))
    result = small_result()
    before = json.dumps(asdict(result), sort_keys=True)
    state = {"frame_index": 2, "frame_interval": 100, "show_etch": False,
             "show_redepo": True, "viewport": {"matrix": [2., 0., 0., 0., 2., 0., 0., 0., 1.], "center": [0., -3.]}}
    path = tmp_path / "다른 폴더" / "공정 이력.json"
    saved = save_trench_depo_result_json(config, result, path=path, view_state=state, request_note="내 이력")
    restored, replay, note, restored_state = load_trench_depo_history(saved)
    assert saved == path
    assert asdict(restored) == asdict(config)
    assert asdict(replay) == asdict(result)
    assert restored_state == state
    assert note == "내 이력"
    assert load_trench_depo_run(saved)[1] == replay
    assert json.dumps(asdict(result), sort_keys=True) == before


def test_atomic_save_failure_preserves_existing_file_and_cleans_temporary_file(tmp_path):
    path = tmp_path / "history.json"
    path.write_bytes(b"existing history")
    with mock.patch("gapsim.emulation.trench_depo_export.os.replace", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError):
            save_trench_depo_result_json(TrenchDepoConfig(), small_result(), path=path)
    assert path.read_bytes() == b"existing history"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("state", [None, {}])
def test_old_result_files_remain_loadable_without_view_state(tmp_path, state):
    path = save_trench_depo_result_json(TrenchDepoConfig(), small_result(), results_root=tmp_path, view_state=state)
    assert load_trench_depo_history(path)[3] == {}


@pytest.mark.parametrize("bad_state", [[], {"frame_interval": 0}, {"frame_index": "1"},
                                       {"show_etch": "false"}, {"viewport": {"matrix": [], "center": []}}])
def test_bad_file_does_not_clear_the_current_result_or_controls(window, tmp_path, bad_state):
    config = window.current_config()
    result = small_result()
    window._apply_emulation_result(config, result, None, use_preview_cache=False)
    before = asdict(window.current_config())
    window.slider_frame.setValue(1)
    payload = result_to_payload(TrenchDepoConfig(angstrom_per_cycle=999), result, request_note="bad")
    payload["view_state"] = bad_state
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        window.load_replay_json(path)
    assert window._result is result
    assert asdict(window.current_config()) == before
    assert window.slider_frame.value() == 1


def test_save_cancel_and_no_result_do_not_create_files(window, tmp_path):
    assert not window.action_save_history.isEnabled()
    config = window.current_config()
    window._apply_emulation_result(config, small_result(), None, use_preview_cache=False)
    window.slider_frame.setValue(2)
    with mock.patch("gapsim.emulation.trench_depo_ui.QFileDialog.getSaveFileName", return_value=("", "")):
        window.action_save_history.trigger()
    assert window._history_path is None
    assert window.slider_frame.value() == 2


@pytest.mark.parametrize("process", ["ald", "cvd", "calibrated"])
def test_save_and_open_buttons_restore_a_real_run_in_a_fresh_window(window, tmp_path, process):
    window._set_structure_points([(-200., 0.), (-80., 0.), (-80., -200.), (80., -200.), (80., 0.), (200., 0.)])
    window.cmb_recipe_model.setCurrentIndex(window.cmb_recipe_model.findData("ideal_conformal_v1"))
    window.cmb_process_type.setCurrentIndex(window.cmb_process_type.findData(process))
    window.spin_cycles.setValue(6)
    window.spin_angstrom_per_cycle.setValue(.56)
    window.spin_cvd_rate.setValue(2.4)
    window.spin_cvd_duration.setValue(3.)
    if process == "calibrated":
        window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData("SFO3.1"))
        window.apply_selected_parameter_preset()
        window.spin_cycles.setValue(2)
    config = window.current_config()
    result = run_trench_depo(config)
    window._apply_emulation_result(config, result, None, use_preview_cache=False)
    QApplication.processEvents()
    index = min(2, len(result.frame_profiles) - 1)
    window.slider_frame.setValue(index)
    window.result_navigation.interval.setValue(37)
    window.chk_show_etch_overlay.setChecked(False)
    window.chk_show_redepo_overlay.setChecked(True)
    window.view.scale(2, 2)
    window.view.centerOn(QPointF(15., 80.))
    view_state = window._history_view_state()
    dose = window.lbl_result_dose.text()
    path = tmp_path / f"{process} 이력.json"
    # Edits after running must not replace the recipe used to produce the result.
    window.spin_angstrom_per_cycle.setValue(77)
    real_strftime = time.strftime
    def ascii_locale_strftime(fmt, *args):
        fmt.encode('ascii')
        return real_strftime(fmt, *args)
    with mock.patch('gapsim.emulation.trench_depo_ui.time.strftime', side_effect=ascii_locale_strftime), \
         mock.patch("gapsim.emulation.trench_depo_ui.QFileDialog.getSaveFileName", return_value=(str(path), "")):
        QTest.mouseClick(window.btn_save_result_json, Qt.MouseButton.LeftButton)
    assert path.is_file()
    assert json.dumps(asdict(load_trench_depo_run(path)[0]), sort_keys=True) == json.dumps(asdict(config), sort_keys=True)
    with mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"):
        fresh = TrenchDepoWindow()
    try:
        fresh.show()
        QApplication.processEvents()
        with mock.patch("gapsim.emulation.trench_depo_ui.QFileDialog.getOpenFileName", return_value=(str(path), "")), \
             mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", side_effect=AssertionError("must not resimulate")):
            fresh.action_open_history.trigger()
            QApplication.processEvents()
        assert json.dumps(asdict(fresh._result), sort_keys=True) == json.dumps(asdict(result), sort_keys=True)
        assert json.dumps(asdict(fresh._result_config), sort_keys=True) == json.dumps(asdict(config), sort_keys=True)
        actual = asdict(fresh.current_config())
        differences = {key: (actual[key], value) for key, value in asdict(config).items() if actual[key] != value}
        assert not differences
        assert fresh.slider_frame.value() == index
        assert fresh.lbl_result_dose.text() == dose
        assert fresh.result_navigation.step() == 37
        assert not fresh.chk_show_etch_overlay.isChecked()
        assert fresh.chk_show_redepo_overlay.isChecked()
        restored_view = fresh._history_view_state()
        assert restored_view["viewport"]["matrix"] == pytest.approx(view_state["viewport"]["matrix"])
        assert restored_view["viewport"]["center"] == pytest.approx(view_state["viewport"]["center"], abs=2.)
        assert not fresh._result_playback_timer.isActive()
        assert fresh.action_save_history.isEnabled()
    finally:
        fresh.close()
        QApplication.processEvents()

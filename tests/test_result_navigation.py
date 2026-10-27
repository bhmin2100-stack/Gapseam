import json
import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_process_parameters import window
from gapsim.emulation.result_navigation import FRAME_INTERVALS, frame_deposition_label
from gapsim.emulation.trench_depo import TrenchDepoConfig, TrenchDepoResult, TrenchSweepResult, run_trench_depo
from gapsim.emulation.trench_depo_export import save_trench_depo_result_json
from gapsim.emulation.trench_depo_ui import SplitTestWindow, merge_continued_trench_result


def sample(steps=None, **meta):
    steps = list(range(108)) if steps is None else steps
    frames = [[(-10., i / 10), (10., i / 10)] for i in range(len(steps))]
    return TrenchDepoResult(frame_steps=steps, frame_profiles=frames,
        frame_voids=[[] for _ in frames], final_profile=frames[-1],
        meta={"cycles": steps[-1], "angstrom_per_cycle": .56, **meta})


def test_recorded_dose_and_legacy_sparse_frames_use_physical_progress():
    config = TrenchDepoConfig(angstrom_per_cycle=10)
    result = sample([0, 5, 17])
    assert frame_deposition_label(result, config, 2) == "누적 증착량 9.520 Å"
    result.meta["frame_doses_a"] = [0., 2.1234, 7.6543]
    assert frame_deposition_label(result, config, 2) == "누적 증착량 7.654 Å"
    result.meta["growth_basis"] = "net_planar"
    assert frame_deposition_label(result, config, 2) == "누적 증착량 7.654 Å"


def test_cvd_uses_actual_frame_times_not_image_index():
    config = TrenchDepoConfig(process_type="cvd", cvd_rate_a_per_s=999)
    result = sample([0, 3, 10], process_type="cvd", cvd_rate_a_per_s=2.5,
                    frame_times_s=[0., .15, .65])
    assert frame_deposition_label(result, config, 2) == "누적 증착량 1.625 Å"
    result.meta.pop("frame_times_s")
    assert frame_deposition_label(result, config, 2) == "누적 증착량 — (기록 없음)"


def test_incomplete_history_does_not_apply_last_recipe_to_earlier_stages():
    config = TrenchDepoConfig(angstrom_per_cycle=99)
    result = sample([0, 1, 2], history_self_contained=True, stage_count=2)
    assert frame_deposition_label(result, config, 2) == "누적 증착량 — (기록 없음)"
    result.meta["frame_stage_progress"] = [{"dose_a": 0.}, {"dose_a": 1.}, {"dose_a": 3.}]
    assert frame_deposition_label(result, config, 2) == "현재 단계 증착량 3.000 Å · 누적 정보 없음"
    result.meta["frame_doses_a"] = [0., 1., 4.]
    assert frame_deposition_label(result, config, 2) == "누적 증착량 4.000 Å"


@pytest.mark.parametrize("interval", FRAME_INTERVALS)
def test_buttons_keyboard_playback_and_endpoints_share_interval(window, interval):
    config = TrenchDepoConfig(angstrom_per_cycle=.56, cycles=107)
    result = sample()
    before = json.dumps(vars(result), sort_keys=True)
    window._apply_emulation_result(config, result, None, use_preview_cache=False)
    nav = window.result_navigation
    nav.interval.setCurrentIndex(nav.interval.findData(interval))
    window.slider_frame.setValue(0)
    assert not nav.previous.isEnabled()
    QTest.mouseClick(nav.next, Qt.MouseButton.LeftButton)
    assert window.slider_frame.value() == interval
    assert window.lbl_result_dose.text() == f"누적 증착량 {interval * .56:,.3f} Å"
    QTest.mouseClick(nav.previous, Qt.MouseButton.LeftButton)
    assert window.slider_frame.value() == 0
    window.slider_frame.setFocus()
    QTest.keyClick(window.slider_frame, Qt.Key.Key_Right)
    assert window.slider_frame.value() == interval
    QTest.keyClick(window.slider_frame, Qt.Key.Key_Left)
    assert window.slider_frame.value() == 0
    window.toggle_result_playback()
    assert window._result_playback_timer.isActive()
    window._advance_result_playback()
    assert window.slider_frame.value() == interval
    QTest.mouseClick(nav.next, Qt.MouseButton.LeftButton)
    assert not window._result_playback_timer.isActive()
    window.slider_frame.setValue(106)
    window._advance_result_playback()
    assert window.slider_frame.value() == 107
    assert not nav.next.isEnabled()
    assert window.lbl_result_dose.text() == "누적 증착량 59.920 Å"
    window._advance_result_playback()
    assert window.slider_frame.value() == 0
    assert json.dumps(vars(result), sort_keys=True) == before


def test_loading_saved_result_keeps_interval_and_original_dose(window, tmp_path):
    config = TrenchDepoConfig(angstrom_per_cycle=.56, cycles=17)
    path = save_trench_depo_result_json(config, sample([0, 5, 17]), results_root=tmp_path)
    window.load_replay_json(path)
    nav = window.result_navigation
    nav.interval.setCurrentIndex(nav.interval.findData(100))
    window.spin_angstrom_per_cycle.setValue(10)
    window.slider_frame.setValue(1)
    assert window.lbl_result_dose.text() == "누적 증착량 2.800 Å"
    QTest.mouseClick(nav.next, Qt.MouseButton.LeftButton)
    assert window.slider_frame.value() == 2
    assert window.lbl_result_dose.text() == "누적 증착량 9.520 Å"
    window.load_replay_json(path)
    assert nav.step() == 100


def test_actual_ald_cvd_continuation_dose_survives_reload_and_split(window, tmp_path):
    config = TrenchDepoConfig(points=((-20., 0.), (20., 0.)),
        recipe_model="ideal_conformal_v1", cycles=2, angstrom_per_cycle=.56, reparam_ds_a=2.)
    first = run_trench_depo(config)
    next_config = replace(config, points=first.final_profile, process_type="cvd",
                          cvd_rate_a_per_s=2., cvd_duration_s=1.5)
    second = run_trench_depo(next_config)
    joined = merge_continued_trench_result(first, second, stage_index=2, continued_from_run=None)
    path = save_trench_depo_result_json(next_config, joined, results_root=tmp_path)
    window.load_replay_json(path)
    assert window.lbl_result_dose.text() == "누적 증착량 4.120 Å"
    window.slider_frame.setValue(2)
    assert window.lbl_result_dose.text() == "누적 증착량 1.120 Å"
    cases = [TrenchSweepResult(parameter="cycles", label="사이클", value=2,
                              config=config, result=first),
             TrenchSweepResult(parameter="cycles", label="연속", value=3,
                              config=next_config, result=joined)]
    split = SplitTestWindow(cases)
    try:
        split.show()
        split.result_navigation.interval.setCurrentIndex(5)
        QTest.mouseClick(split.result_navigation.next, Qt.MouseButton.LeftButton)
        assert not split._timer.isActive()
        assert split.slider_frame.value() == len(joined.frame_profiles) - 1
        assert "누적 증착량 1.120 Å" in split._case_status_labels[0].text()
        assert "누적 증착량 4.120 Å" in split._case_status_labels[1].text()
        split.slider_frame.setValue(0)
        split._advance_frame()
        assert split.slider_frame.value() == len(joined.frame_profiles) - 1
    finally:
        split.close()
        QApplication.processEvents()


def test_result_controls_disabled_without_a_result(window):
    assert not window.result_navigation.isEnabled()
    assert window.lbl_result_dose.text() == "누적 증착량 —"

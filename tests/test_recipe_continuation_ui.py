"""Replay and continuation preserve buried geometry and physical progress labels."""
from dataclasses import replace

from PySide6.QtWidgets import QApplication

from tests.test_process_parameters import window
from gapsim.emulation.trench_depo import TrenchDepoConfig, TrenchSweepResult, run_trench_depo
from gapsim.emulation.trench_depo_ui import SplitTestWindow, merge_continued_trench_result
from gapsim.emulation.trench_depo_export import save_trench_depo_result_json


VOID = (((-3., -6.), (3., -6.), (3., -3.), (-3., -3.)),)
POINTS = ((-20., 0.), (20., 0.))


def test_geometry_void_context_is_preserved_by_presets_cleared_by_new_structure_and_undoable(window):
    window._set_structure_points(POINTS, initial_voids=VOID, preserve_on_emulator_switch=True)
    config = window.current_config()
    assert config.initial_voids == VOID
    assert window._preview_cache_key(config) != window._preview_cache_key(replace(config, initial_voids=()))
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData("SFO3.1"))
    window.apply_selected_parameter_preset()
    assert window.current_config().initial_voids == VOID
    window._clear_structure_undo_stack()
    window._record_structure_undo_before_change()
    window._set_structure_points(((-30., 0.), (30., 0.)))
    assert window.current_config().initial_voids == ()
    window._set_workflow_step("structure")
    window._undo_structure_edit()
    assert window.current_config().initial_voids == VOID
    assert tuple(window.current_config().points) == POINTS


def test_load_replay_and_start_next_stage_keep_actual_cavities(window, tmp_path):
    config = TrenchDepoConfig(points=POINTS, initial_voids=VOID, cycles=1,
        angstrom_per_cycle=1., recipe_model="ideal_conformal_v1", reparam_ds_a=2.)
    result = run_trench_depo(config)
    path = save_trench_depo_result_json(config, result, results_root=tmp_path)
    window.load_replay_json(path)
    assert window.current_config().initial_voids == VOID
    window.start_next_depo_stage()
    assert window.current_config().initial_voids == tuple(tuple(poly) for poly in result.frame_voids[-1])
    assert tuple(window.current_config().points) == tuple(result.final_profile)
    continued = run_trench_depo(window.current_config())
    assert continued.frame_voids[-1] == result.frame_voids[-1]


def test_main_and_split_playback_show_mixed_stage_units(window, tmp_path):
    first_config = TrenchDepoConfig(points=POINTS, recipe_model="ideal_conformal_v1", cycles=1,
                                   angstrom_per_cycle=1., reparam_ds_a=2., numerical_step_a=1.)
    first = run_trench_depo(first_config)
    second_config = replace(first_config, points=first.final_profile, process_type="cvd", cvd_rate_a_per_s=2., cvd_duration_s=1.)
    second = run_trench_depo(second_config)
    joined = merge_continued_trench_result(first, second, stage_index=2, continued_from_run=None)
    path = save_trench_depo_result_json(second_config, joined, results_root=tmp_path)
    window.load_replay_json(path)
    window.show_frame(1)
    assert "1차 ALD · Cycle 1 / 1" in window.lbl_status.text()
    window.show_frame(len(joined.frame_profiles) - 1)
    assert "2차 CVD · 시간 1 / 1 s" in window.lbl_status.text()
    case = TrenchSweepResult(parameter="cvd_duration_s", label="시간", value=1., config=second_config, result=joined)
    split = SplitTestWindow([case])
    try:
        split.show_frame(len(joined.frame_profiles) - 1)
        assert "2차 CVD · 시간 1 / 1 s" in split._case_status_labels[0].text()
        split.show_frame(1)
        assert "1차 ALD · Cycle 1 / 1" in split._case_status_labels[0].text()
    finally:
        split.close()
        QApplication.processEvents()

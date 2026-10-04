"""A continued history keeps physical units and each stage's recipe."""
from dataclasses import replace

import pytest

from gapsim.emulation.trench_depo import TrenchDepoConfig, run_trench_depo
from gapsim.emulation.trench_depo_ui import merge_continued_trench_result
from gapsim.emulation.trench_depo_export import (
    _frame_progress_label, _gif_panel_lines, save_trench_depo_result_json, load_trench_depo_run,
)
from gapsim.emulation.parameter_library import (
    save_parameter_preset, read_parameter_preset, parameter_preset_application_values,
)


def recipe(**kwargs):
    return replace(TrenchDepoConfig(
        points=[(-20., 0.), (20., 0.)], recipe_model="ideal_conformal_v1",
        cycles=2, angstrom_per_cycle=1., numerical_step_a=1., reparam_ds_a=2.,
    ), **kwargs)


def merge(base, next_result, stage=2):
    return merge_continued_trench_result(base, next_result, stage_index=stage, continued_from_run=None)


def test_mixed_ald_cvd_continuation_never_calls_ald_cycles_seconds(tmp_path):
    first_config = recipe()
    first = run_trench_depo(first_config)
    second_config = recipe(points=first.final_profile, process_type="cvd", cvd_rate_a_per_s=2., cvd_duration_s=1.5)
    second = run_trench_depo(second_config)
    joined = merge(first, second)
    meta = joined.meta
    assert meta["history_process_type"] == "mixed"
    assert meta["frame_times_s"] == [] and meta["frame_cycle_counts"] == []
    assert meta["frame_doses_a"] == pytest.approx([0., 1., 2., 3., 4., 5.])
    assert len(meta["frame_stage_progress"]) == len(joined.frame_profiles)
    assert [p["process_type"] for p in meta["frame_stage_progress"]] == ["ald"] * 3 + ["cvd"] * 3
    assert _frame_progress_label(joined, second_config, 2) == "1차 ALD · Cycle 2 / 2"
    assert _frame_progress_label(joined, second_config, 3) == "2차 CVD · 시간 0.5 / 1.5 s"
    assert _frame_progress_label(joined, second_config, 5) == "2차 CVD · 시간 1.5 / 1.5 s"
    first_panel = "\n".join(_gif_panel_lines(joined, second_config, request_note="", frame_index=1))
    second_panel = "\n".join(_gif_panel_lines(joined, second_config, request_note="", frame_index=4))
    assert "공정: ALD" in first_panel and "GPC: 1 Å/cycle" in first_panel
    assert "공정: CVD" in second_panel and "D/R: 2 Å/s" in second_panel
    path = save_trench_depo_result_json(second_config, joined, results_root=tmp_path)
    _, restored, _ = load_trench_depo_run(path)
    assert restored.meta["frame_stage_progress"] == meta["frame_stage_progress"]


def test_homogeneous_cvd_time_accumulates_but_each_stage_keeps_its_own_rate():
    first = run_trench_depo(recipe(process_type="cvd", cvd_rate_a_per_s=2., cvd_duration_s=1.5))
    second = run_trench_depo(recipe(points=first.final_profile, process_type="cvd", cvd_rate_a_per_s=1., cvd_duration_s=2.))
    joined = merge(first, second)
    assert joined.meta["frame_times_s"] == pytest.approx([0., .5, 1., 1.5, 2.5, 3.5])
    assert joined.meta["frame_doses_a"] == pytest.approx([0., 1., 2., 3., 4., 5.])
    assert joined.meta["stage_history"][0]["recipe_config"]["cvd_rate_a_per_s"] == 2.
    assert joined.meta["stage_history"][1]["recipe_config"]["cvd_rate_a_per_s"] == 1.
    third = run_trench_depo(recipe(points=joined.final_profile, cycles=1, angstrom_per_cycle=2.))
    final = merge(joined, third, stage=3)
    assert final.meta["frame_times_s"] == []
    assert final.meta["frame_doses_a"] == pytest.approx([0., 1., 2., 3., 4., 5., 7.])
    assert final.meta["frame_stage_progress"][:-1] == joined.meta["frame_stage_progress"]
    assert final.meta["frame_stage_progress"][-1]["cycle"] == 1


def test_ald_counts_accumulate_and_mixed_growth_bases_do_not_add():
    first = run_trench_depo(recipe())
    second = run_trench_depo(recipe(points=first.final_profile, cycles=3, growth_basis="net_planar"))
    joined = merge(first, second)
    assert joined.meta["frame_cycle_counts"] == [0, 1, 2, 3, 4, 5]
    assert joined.meta["frame_doses_a"] == []
    assert "nominal_dose_a" not in joined.meta
    assert joined.meta["frame_stage_progress"][-1]["dose_a"] == 3.
    assert joined.meta["stage_history"][-1]["growth_basis"] == "net_planar"


def test_closed_void_survives_continuation_and_replay_but_does_not_transfer_with_preset(tmp_path):
    initial_voids = (((-3., -6.), (3., -6.), (3., -3.), (-3., -3.)),)
    first_config = recipe(initial_voids=initial_voids, cycles=1)
    first = run_trench_depo(first_config)
    assert first.frame_voids[-1]
    second_config = recipe(points=first.final_profile, initial_voids=first.frame_voids[-1], cycles=1)
    second = run_trench_depo(second_config)
    joined = merge(first, second)
    assert all(len(voids) == 1 for voids in joined.frame_voids)
    assert joined.frame_voids[-1] == first.frame_voids[-1]
    path = save_trench_depo_result_json(first_config, first, results_root=tmp_path)
    restored, replay, _ = load_trench_depo_run(path)
    assert restored.initial_voids == initial_voids
    assert replay.frame_voids == first.frame_voids
    library = tmp_path / "presets.json"
    save_parameter_preset(library, "recipe", first_config, emulator_number=0)
    record = read_parameter_preset(library, "recipe")
    target = recipe(initial_voids=())
    applied = parameter_preset_application_values(record, target)
    assert applied["initial_voids"] == ()
    assert "initial_voids" not in record["config"]
    assert record["source_structure"]["initial_voids"]

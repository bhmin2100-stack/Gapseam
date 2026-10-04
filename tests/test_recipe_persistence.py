"""Cross-structure presets and exact run replay are different operations."""
from dataclasses import asdict, replace

import pytest

from gapsim.emulation.incident_presets import ensure_sfo31_preset, sfo31_preset
from gapsim.emulation.parameter_library import (
    parameter_preset_application_values, read_parameter_preset, save_parameter_preset,
)
from gapsim.emulation.trench_depo import TrenchDepoConfig, TrenchDepoResult
from gapsim.emulation.trench_depo_export import (
    _frame_progress_label, _recipe_run_lines, payload_to_trench_run,
    result_to_payload, save_trench_depo_result_json, load_trench_depo_run,
    export_trench_depo_run,
)


def _small_result():
    initial = [(-20.0, 0.0), (20.0, 0.0)]
    final = [(-20.0, 2.0), (20.0, 2.0)]
    return TrenchDepoResult(
        frame_steps=[0, 1], frame_profiles=[initial, final],
        frame_voids=[[], []], final_profile=final,
        meta={"frame_times_s": [0.0, 1.5], "frame_cycle_counts": [0, 1]},
    )


@pytest.mark.parametrize("process", ["ald", "cvd"])
@pytest.mark.parametrize("model", ["legacy_calibrated_v1", "physical_transport_v1", "ideal_conformal_v1"])
def test_full_result_json_roundtrip_every_config_field(tmp_path, process, model):
    original = TrenchDepoConfig(
        points=[(-20.0, 0.0), (20.0, 0.0)],
        recipe_model=model, process_type=process, growth_basis="net_planar",
        cycles=3, angstrom_per_cycle=1.7, cvd_rate_a_per_s=2.4,
        cvd_duration_s=11.3, precursor_sticking=0.04, ald_exposure=9.0,
        transport_ray_count=48, numerical_step_a=0.75,
        closure_redepo_enabled=True, closure_redepo_efficiency_pct=17.0,
        closure_redepo_smoothing_a=73.0, inhibition_enabled=True,
        inhibitor_sticking=0.12, inhibitor_exposure=2.2,
    )
    result = _small_result()
    path = save_trench_depo_result_json(original, result, results_root=tmp_path, request_note="roundtrip")
    restored, replay, note = load_trench_depo_run(path)
    assert asdict(restored) == asdict(original)
    assert asdict(replay) == asdict(result)
    assert note == "roundtrip"


def test_old_replay_defaults_to_original_model_and_cycle_semantics():
    payload = result_to_payload(TrenchDepoConfig(), _small_result(), request_note="old")
    fields = ("recipe_model", "process_type", "growth_basis", "cvd_rate_a_per_s",
              "cvd_duration_s", "ald_exposure", "precursor_sticking", "numerical_step_a",
              "transport_ray_count", "inhibitor_sticking", "inhibitor_exposure")
    for name in fields:
        payload["config"].pop(name)
    restored, _, _ = payload_to_trench_run(payload)
    assert restored.recipe_model == "legacy_calibrated_v1"
    assert restored.process_type == "ald"
    assert restored.growth_basis == "gross"


def test_cvd_process_preset_moves_rate_but_not_time_or_structure(tmp_path):
    path = tmp_path / "presets.json"
    source = TrenchDepoConfig(
        recipe_model="physical_transport_v1", process_type="cvd", growth_basis="net_planar",
        cvd_rate_a_per_s=1.75, cvd_duration_s=60.0, precursor_sticking=0.03,
        transport_ray_count=64, numerical_step_a=0.5,
        deposition_feature_width_a=500.0, deposition_feature_depth_a=2200.0,
    )
    save_parameter_preset(path, "CVD", source, emulator_number=0)
    record = read_parameter_preset(path, "CVD")
    target = TrenchDepoConfig(cvd_duration_s=120.0, deposition_feature_width_a=900.0,
                             deposition_feature_depth_a=4000.0, transport_ray_count=32,
                             numerical_step_a=2.0)
    applied = TrenchDepoConfig(**parameter_preset_application_values(record, target))
    assert applied.cvd_rate_a_per_s == 1.75
    assert applied.cvd_duration_s == 120.0
    assert applied.deposition_feature_width_a == 900.0
    assert applied.deposition_feature_depth_a == 4000.0
    assert applied.transport_ray_count == 32 and applied.numerical_step_a == 2.0
    assert applied.process_type == "cvd" and applied.recipe_model == "physical_transport_v1"
    assert applied.growth_basis == "net_planar" and applied.precursor_sticking == 0.03


def test_sfo_is_ald_and_opt_in_reference_settings_restore_exact_config(tmp_path):
    path = tmp_path / "presets.json"
    ensure_sfo31_preset(path)
    record = read_parameter_preset(path, "SFO3.1")
    expected = sfo31_preset()
    current = replace(expected, process_type="cvd", recipe_model="physical_transport_v1",
                      growth_basis="net_planar", cycles=700, reparam_ds_a=20.0,
                      redepo_incident_ray_count=49, sputter_smoothing_a=80.0)
    applied = parameter_preset_application_values(
        record, current, include_run_defaults=True, include_calculation_settings=True,
    )
    assert applied == asdict(expected)
    # Applying a preset is not a data migration or an automatic overwrite.
    bytes_before = path.read_bytes()
    ensure_sfo31_preset(path)
    assert path.read_bytes() == bytes_before


def test_legacy_sfo_does_not_inherit_new_cvd_or_net_growth_selection():
    legacy = asdict(sfo31_preset())
    for name in ("recipe_model", "process_type", "growth_basis"):
        legacy.pop(name)
    target = TrenchDepoConfig(recipe_model="physical_transport_v1", process_type="cvd",
                             growth_basis="net_planar")
    applied = parameter_preset_application_values({"config": legacy}, target)
    assert applied["recipe_model"] == "legacy_calibrated_v1"
    assert applied["process_type"] == "ald" and applied["growth_basis"] == "gross"


def test_exported_cvd_labels_show_actual_time_not_computational_cycles():
    config = TrenchDepoConfig(process_type="cvd", cvd_rate_a_per_s=2.0, cvd_duration_s=1.5)
    assert _frame_progress_label(_small_result(), config, 1) == "시간 1.5 / 1.5 s"
    lines = "\n".join(_recipe_run_lines(config))
    assert "D/R: 2 Å/s" in lines
    assert "3 Å" in lines
    assert "cycle" not in lines and "GPC" not in lines


def test_replay_rejects_string_false_instead_of_silently_enabling_sputter():
    payload = result_to_payload(TrenchDepoConfig(), _small_result(), request_note="")
    payload["config"]["sputter_enabled"] = "false"
    with pytest.raises(ValueError, match="sputter_enabled must be a boolean"):
        payload_to_trench_run(payload)


def test_actual_cvd_gif_and_replay_export(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    config = TrenchDepoConfig(process_type="cvd", recipe_model="ideal_conformal_v1",
                             cvd_rate_a_per_s=2.0, cvd_duration_s=1.5)
    folder = export_trench_depo_run(config, _small_result(), runs_root=tmp_path, request_note="CVD export")
    assert "CVD_1.5초_2A초" in folder.name
    replay_path = next(folder.glob("에뮬레이터재생_*.json"))
    restored, replay, _ = load_trench_depo_run(replay_path)
    assert restored.process_type == "cvd" and restored.cvd_duration_s == 1.5
    assert replay.meta["frame_times_s"] == [0.0, 1.5]
    with Image.open(next(folder.glob("*.gif"))) as gif:
        assert gif.n_frames == 2
        assert gif.size == (1820, 1040)
    summary = next(folder.glob("요청사항요약_*.txt")).read_text(encoding="utf-8")
    assert "D/R: 2 Å/s" in summary and "증착 시간: 1.5 s" in summary
    assert "A/CYC" not in summary

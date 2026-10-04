from dataclasses import replace
import math

import numpy as np
import pytest

from gapsim.emulation import trench_depo as engine
from gapsim.emulation.parameter_help import HELP
from gapsim.emulation.parameter_help_response import (
    FIELDS, application_note, build_response, example_points, growth_response,
    inhibition_response, ion_response, operation_steps,
)
from gapsim.engine import typical_cvd
from gapsim.engine.incident_ions import source_integral


def config(**kwargs):
    return replace(engine.TrenchDepoConfig(), cvd_enabled=True,
                   deposition_feature_width_a=500., deposition_feature_depth_a=1200.,
                   **kwargs)


@pytest.mark.parametrize('key', FIELDS)
def test_each_numeric_comparison_is_finite_bounded_and_read_only(key):
    c = config(sputter_enabled=True, redepo_enabled=True, redepo_incident_los_enabled=True,
               inhibition_enabled=True)
    field, scale, _, lo, hi = FIELDS[key]
    current = (getattr(c, field) or 0)/scale
    plot = build_response(key, c, (lo, current, hi))
    assert plot is not None
    assert len(plot.labels) == len(plot.curves) == 3
    assert 2 <= len(plot.x) < 1000
    assert all(len(ys) == len(plot.x) for ys in plot.curves)
    assert all(math.isfinite(y) for ys in plot.curves for y in ys)
    assert c == config(sputter_enabled=True, redepo_enabled=True, redepo_incident_los_enabled=True,
                       inhibition_enabled=True)


def test_cvd_plot_equals_actual_engine_function_at_all_three_values():
    c = config()
    points = example_points()
    values = (0, 30, 100)
    plot = build_response('cvd_overhang_pct', c, values)
    for value, ys in zip(values, plot.curves):
        assert ys == pytest.approx(typical_cvd.growth_ratios(points, replace(c, cvd_overhang_pct=value)))


def test_cvd_off_bottom_100_and_zero_deposition_do_not_invent_effects():
    c = config()
    for c in (replace(c, cvd_enabled=False), replace(c, cvd_bottom_ratio_pct=100.),
              replace(c, angstrom_per_cycle=0.)):
        plot = build_response('cvd_depth_power', c, (.2, 1.2, 6))
        assert plot.curves[0] == plot.curves[1] == plot.curves[2]


def test_reference_dimensions_never_change_example_geometry():
    before = example_points()
    c = config()
    for key in ('spin_depth_feature_width', 'spin_depth_feature_depth', 'spin_depth_feature_length'):
        assert build_response(key, c, (100, 500, 2000)).x == tuple(engine._model6_arc_coordinates(before))
    assert example_points() == before


def test_depth_minimum_is_affine_not_a_clipped_floor():
    c = replace(config(), cvd_enabled=False, deposition_depth_enabled=True)
    points = example_points()
    plot = build_response('spin_depth_min_ratio_pct', c, (0, 25, 50))
    idx = min(range(len(points)), key=lambda i: abs(points[i][1]+400))
    z = -points[idx][1]
    raw = math.exp(-c.deposition_depth_decay_k*(z/c.deposition_feature_width_a)**c.deposition_depth_decay_power)
    assert plot.curves[1][idx] == pytest.approx(.25+.75*raw)
    assert plot.curves[1][idx] != pytest.approx(max(.25, raw))


def test_inhibition_cvd_combination_and_hidden_legacy_dependency():
    points = example_points()
    c = config(inhibition_enabled=True, deposition_depth_enabled=False)
    expected = [a*b for a, b in zip(typical_cvd.growth_ratios(points, c), inhibition_response(points, c))]
    assert growth_response(points, c) == pytest.approx(expected)
    plot = build_response('spin_depth_decay_k', c, (0, .8, 2))
    assert plot.curves[0] != plot.curves[2]
    assert 'CVD ON' in application_note('spin_depth_decay_k', c)
    off = replace(c, inhibition_enabled=False)
    plot = build_response('spin_depth_decay_k', off, (0, .8, 2))
    assert plot.curves[0] == plot.curves[2]


def test_inhibition_zero_strength_is_not_whole_model_off():
    c = config(inhibition_enabled=True, inhibition_strength_pct=0.)
    assert inhibition_response(example_points(), c) != [1.]*len(example_points())
    c = replace(c, inhibition_min_growth_ratio=1., inhibition_bottom_boost_pct=100.)
    assert max(inhibition_response(example_points(), c)) > 1.


def test_legacy_ion_floor_applies_after_geometry_but_not_to_new_los():
    c = config(sputter_enabled=True, ion_transmission_enabled=True,
               ion_transmission_floor_pct=45.)
    ys = ion_response(example_points(), c)
    assert min(ys) >= .45
    assert min(ys) == pytest.approx(.45)
    c = replace(c, redepo_enabled=True, redepo_incident_los_enabled=True)
    plot = build_response('spin_ion_floor', c, (0, 45, 90))
    assert plot.curves[0] == plot.curves[1] == plot.curves[2]
    assert '대체' in application_note('spin_ion_floor', c)


def test_sputter_gaussian_width_preserves_peak_and_matches_engine():
    c = config(sputter_enabled=True, sputter_peak_angle_deg=55.)
    plot = build_response('spin_sputter_width', c, (5, 14, 40))
    for width, ys in zip((5, 14, 40), plot.curves):
        assert ys == pytest.approx([c.sputter_strength_a_per_cycle * engine.direct_sputter_angle_response(
            angle, peak_angle_deg=55, width_deg=width, peak_pct=c.sputter_peak_pct) for angle in plot.x])
        assert ys[55] == pytest.approx(c.sputter_strength_a_per_cycle)
    assert plot.curves[0][30] < plot.curves[2][30]


def test_incident_response_is_actual_normalized_integral_even_at_zero_redepo():
    c = config(sputter_enabled=True, redepo_enabled=True, redepo_incident_los_enabled=True,
               redepo_efficiency_pct=0.)
    points = example_points()
    normals = engine._smooth_unit_vectors(engine.vertex_air_normals(points), int(round(c.sputter_smoothing_a/20.)))
    plot = build_response('spin_incident_rays', c, (9, 25, 51))
    for rays, ys in zip((9, 25, 51), plot.curves):
        expected = source_integral(points, normals, sigma=c.redepo_incident_sigma_deg, rays=rays,
            peak=c.sputter_peak_angle_deg, width=c.sputter_width_deg, amplitude=c.sputter_peak_pct/100.)[1]
        assert ys == pytest.approx(expected*c.sputter_strength_a_per_cycle)
    assert max(plot.curves[1]) > 0
    assert '현재 적용' in application_note('spin_incident_rays', c)
    off = build_response('spin_incident_rays', replace(c, redepo_enabled=False), (9, 25, 51))
    assert not np.any(off.curves)


def test_recipe_application_help_matches_active_process_and_transport_model():
    c = config(recipe_model='ideal_conformal_v1', process_type='ald')
    assert '현재 적용' in application_note('spin_angstrom_per_cycle', c)
    assert '현재 미적용' in application_note('spin_cvd_rate', c)
    assert '현재 미적용' in application_note('spin_precursor_sticking', c)
    assert '기존 보정 모델 전용' in application_note('cvd_overhang_pct', c)
    c = replace(c, recipe_model='physical_transport_v1', process_type='cvd', sputter_enabled=True,
                redepo_enabled=False, redepo_incident_los_enabled=False)
    assert '현재 적용' in application_note('spin_cvd_rate', c)
    assert '현재 미적용' in application_note('spin_angstrom_per_cycle', c)
    assert '현재 적용' in application_note('spin_precursor_sticking', c)
    assert '재부착 OFF에서도 유지' in application_note('spin_incident_sigma', c)
    assert '현재 미적용' in application_note('spin_inhibitor_sticking', c)
    assert '현재 적용' in application_note('spin_inhibitor_sticking', replace(c, inhibition_enabled=True))


def test_recipe_help_resolves_physical_units_and_redeposition_semantics():
    from gapsim.emulation.parameter_help import effective_help
    c = config(recipe_model='ideal_conformal_v1', process_type='ald')
    ald = effective_help('spin_sputter_strength', HELP['spin_sputter_strength'], c)
    assert 'Å/cycle' in ald.title and '기준 평탄면' in ald.meaning
    cvd = effective_help('spin_sputter_strength', HELP['spin_sputter_strength'], replace(c, process_type='cvd'))
    assert 'Å/s' in cvd.title
    old = effective_help('spin_sputter_strength', HELP['spin_sputter_strength'], replace(c, recipe_model='legacy_calibrated_v1'))
    assert '최대 제거량' in old.meaning
    toggle = effective_help('chk_redepo', HELP['chk_redepo'], c)
    assert '꺼도 직접 식각과 이온 가림은 유지' in toggle.caution
    conformal = effective_help('spin_angstrom_per_cycle', HELP['spin_angstrom_per_cycle'], c)
    assert '노출면 전체' in conformal.meaning


def test_post_fill_is_total_budget_and_uses_only_selected_feature_type():
    c = replace(config(), cvd_enabled=False, deposition_depth_enabled=True,
                deposition_feature_type='line', deposition_line_open_path_factor=.4)
    plot = build_response('spin_depth_post_fill_line_pct', c, (0, 50, 100))
    assert [ys[0] for ys in plot.curves] == pytest.approx([0, .2, .4])
    hole = build_response('spin_depth_post_fill_hole_pct', c, (0, 50, 100))
    assert hole.curves[0] == hole.curves[1] == hole.curves[2]
    ignored = build_response('spin_depth_post_fill_line_pct', replace(c, cvd_enabled=True), (0, 50, 100))
    assert not np.any(ignored.curves)


def test_large_step_help_is_bounded_and_nominal_not_net_growth():
    c = config(cycles=100000000)
    plot = build_response('spin_cycles', c, (10, c.cycles, c.cycles))
    assert len(plot.x) == 101
    assert '순 막두께 아님' in plot.title


def test_key_explanations_describe_implementation_not_old_cartoons():
    assert '분배' in HELP['spin_redepo_emit_power'].meaning
    assert '여러 방출 광선을 추가하는 값이 아닙니다' in HELP['spin_redepo_emit_power'].caution
    assert '이온 가림도 꺼져' in HELP['chk_redepo'].caution
    assert '균일 축소' in HELP['spin_depth_residual_decay'].caution
    assert '진단' in HELP['spin_depth_closure_threshold'].title
    assert '정규화' in operation_steps('spin_redepo_emit_power', 'spread')[2]


def test_no_unified_response_claim_for_other_emulator_modes():
    assert build_response('spin_redepo_distance_power', replace(config(), emulator_number=2), (-1, 0, 1)) is None

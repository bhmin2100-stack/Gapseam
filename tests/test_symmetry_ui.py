from tests.test_process_parameters import window
from gapsim.emulation.incident_presets import sfo31_preset
from dataclasses import asdict
import pytest


def test_toggle_and_original_preset_roundtrip(window):
    window.process_parameter_panel.select(0)
    assert window.chk_symmetry.isVisible()
    window.chk_symmetry.setChecked(True)
    auto = window.current_config()
    assert auto.symmetry_mode == 'auto'
    window.chk_symmetry.setChecked(False)
    off = window.current_config()
    assert off.symmetry_mode == 'off'
    assert window._preview_cache_key(auto) != window._preview_cache_key(off)
    window._apply_parameter_config_values(asdict(sfo31_preset()))
    assert window.current_config().symmetry_mode == 'off'


@pytest.mark.parametrize('axis', [0., 170.])
def test_structure_edit_uses_actual_axis(window, axis):
    window._structure_points = [(axis-100., 0.), (axis-25., 0.),
        (axis-25., -50000.), (axis+25., -50000.), (axis+25., 0.), (axis+100., 0.)]
    window.chk_symmetric_structure_edit.setChecked(True)
    points, partner = window._structure_points_with_symmetric_move(1, axis-30., -4.)
    assert partner == 4
    assert points[4] == (axis+30., -4.)
    assert points[2] == (axis-25., -50000.)


def test_deep_trench_does_not_match_unrelated_point(window):
    window._structure_points = [(-100., 0.), (-25., 0.), (-25., -50000.),
                               (25., -50000.), (30., -10.), (100., 0.)]
    window.chk_symmetric_structure_edit.setChecked(True)
    points, partner = window._structure_points_with_symmetric_move(1, -35., -5.)
    assert partner is None
    assert points[4] == (30., -10.)


def test_center_point_stays_on_axis_and_toggle_off_is_free(window):
    window._structure_points = [(70., 0.), (170., -100.), (270., 0.)]
    window.chk_symmetric_structure_edit.setChecked(True)
    points, partner = window._structure_points_with_symmetric_move(1, 180., -120.)
    assert points[1] == (170., -120.)
    assert partner is None
    window.chk_symmetric_structure_edit.setChecked(False)
    points, partner = window._structure_points_with_symmetric_move(1, 180., -120.)
    assert points[1] == (180., -120.)

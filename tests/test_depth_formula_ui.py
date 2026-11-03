from dataclasses import asdict
from unittest.mock import patch
import pytest
from test_incident_preset_ui import window
from gapsim.emulation.depth_formula import PRESET_LAWS, MODEL
from gapsim.emulation.builtin_presets import STRUCTURE_NAMES


def apply(window, name):
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData(name))
    window.btn_apply_parameter_preset.click()


@pytest.mark.parametrize('name', PRESET_LAWS)
def test_preset_exposes_equation_controls_and_preserves_structure(window,name):
    before=window.current_config().points
    window.spin_cycles.setValue(73)
    apply(window,name)
    window.process_parameter_panel.select(1)
    c=window.current_config()
    assert c.recipe_model==MODEL and c.depth_formula['law']==PRESET_LAWS[name]
    assert c.points==before and c.cycles==73
    assert window.depth_formula_group.isVisible()
    assert not window.transport_group.isVisible()
    assert not c.sputter_enabled and not c.redepo_enabled and not c.inhibition_enabled


def test_equation_coefficient_edit_save_reload_and_cache_invalidation(window):
    apply(window,'깊이 3차식 (시험)')
    oldkey=window._preview_cache_key(window.current_config())
    window.depth_formula_controls['cubic_a'].setValue(-4.25e-10)
    window.depth_formula_controls['depth_unit'].setCurrentIndex(1)
    expected=asdict(window.current_config())
    assert window._preview_cache_key(window.current_config())!=oldkey
    window.edit_parameter_preset_name.setText('내 깊이식')
    window.btn_save_parameter_preset.click()
    window.depth_formula_controls['cubic_a'].setValue(-1e-10)
    window.btn_apply_parameter_preset.click()
    assert asdict(window.current_config())==expected


def test_invalid_depth_is_rejected_before_worker_or_resolution_dialog(window):
    window.cmb_structure_library.setCurrentIndex(window.cmb_structure_library.findData(STRUCTURE_NAMES[-1]))
    window.load_selected_structure_from_library()
    apply(window,'깊이 선형·지수식 (시험)')
    with patch('gapsim.emulation.trench_depo_ui.QMessageBox.critical') as error, patch('gapsim.emulation.trench_depo_ui._EmulationRunWorker') as worker:
        window.run_emulation()
    assert error.called and '음수' in str(error.call_args)
    assert not worker.called and window.btn_run.isEnabled()


def test_switching_to_conformal_clears_formula_from_active_config(window):
    apply(window,'깊이 지수식 (시험)')
    window.cmb_recipe_model.setCurrentIndex(window.cmb_recipe_model.findData('ideal_conformal_v1'))
    assert window.current_config().depth_formula is None
    assert not window.depth_formula_group.isVisible()


def test_scientific_coefficient_input_accepts_small_signed_numbers(window):
    spin=window.depth_formula_controls['cubic_a']
    spin.lineEdit().setText('-3.125e-10')
    spin.interpretText()
    assert spin.value()==-3.125e-10


def test_formula_help_draws_actual_rate_without_running_or_mutating(window):
    apply(window,'깊이 3차식 (시험)')
    before=window.current_config()
    manager=window.parameter_help
    manager.set_enabled(True)
    with patch('gapsim.emulation.trench_depo.run_trench_depo',side_effect=AssertionError('No hover simulation')):
        manager.show_for(window.depth_formula_controls['cubic_a'])
        animation=manager.bubble.animation
        animation.timer.stop()
        assert animation.kind=='depth_formula' and animation.movie is None
        assert animation.formula_config==before
        animation.phase=0.
        first=animation.grab().toImage()
        animation.phase=.6
        last=animation.grab().toImage()
        assert not first.isNull() and first!=last
        assert '경험식의 성장률' in manager.bubble.plot_note.text()
    assert window.current_config()==before

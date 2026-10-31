"""Process preset application is independent from structure selection and dose."""
from dataclasses import asdict
import pytest
from test_incident_preset_ui import window
from gapsim.emulation.parameter_library import (
    parameter_preset_application_values, read_parameter_preset,
)


def test_apply_all_process_fields_and_edit_cycle(window):
    before = window.current_config()
    record = read_parameter_preset(window._parameter_library_path, 'SFO3.1')
    assert window.chk_preset_calculation_settings.isChecked()
    assert not window.chk_preset_run_defaults.isChecked()
    assert not hasattr(window, 'btn_load_sfo31_reference')
    from gapsim.emulation.response_ui import normalized_values
    expected = normalized_values(parameter_preset_application_values(record, before, include_calculation_settings=True))
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData('SFO3.1'))
    window.btn_apply_parameter_preset.click()
    actual = asdict(window.current_config())
    differences = {k: (v, actual.get(k)) for k, v in expected.items()
                   if k != 'emulator_number' and actual.get(k) != v
                   and not (isinstance(v, float) and isinstance(actual.get(k), float)
                            and actual[k] == pytest.approx(v, abs=1e-10))}
    assert not differences, differences
    assert '적용된 프리셋: SFO3.1' in window.lbl_parameter_preset_active.text()
    assert 'GPC 0.56' in window.lbl_parameter_preset_active.text()
    assert window.spin_cycles.isEnabled()
    window.spin_cycles.setValue(47)
    after = asdict(window.current_config())
    assert after['cycles'] == 47
    assert {k:v for k,v in actual.items() if k!='cycles'} == {k:v for k,v in after.items() if k!='cycles'}


def test_structure_is_separate_and_apply_keeps_edited_cycle(window):
    from gapsim.emulation.sfo31_verified import STRUCTURE_NAME, verified_sfo31_config
    from gapsim.emulation.parameter_library import GEOMETRY_PARAMETER_FIELDS
    custom = ((-1000.,0.),(-150.,0.),(-120.,-700.),(210.,-700.),(250.,0.),(1000.,0.))
    window._set_structure_points(custom, preserve_on_emulator_switch=True)
    window.spin_cycles.setValue(123)
    geometry = {key: asdict(window.current_config())[key] for key in GEOMETRY_PARAMETER_FIELDS}
    window.btn_apply_parameter_preset.click()
    cfg = window.current_config()
    assert cfg.cycles == 123
    assert {key:asdict(cfg)[key] for key in GEOMETRY_PARAMETER_FIELDS} == geometry
    window.spin_cycles.setValue(9)
    window.btn_apply_parameter_preset.click()
    assert window.current_config().cycles == 9
    window.chk_preset_run_defaults.setChecked(True)
    window.btn_apply_parameter_preset.click()
    assert window.current_config().cycles == 1045
    assert window.current_config().points == custom
    window.spin_cycles.setValue(17)
    assert window.current_config().cycles == 17
    # Loading the reference structure is an independent step-1 action.
    window.cmb_structure_library.setCurrentIndex(window.cmb_structure_library.findData(STRUCTURE_NAME))
    window.load_selected_structure_from_library()
    import numpy as np
    # Excel round-trips decimal coordinates at about 1e-12 Å.
    np.testing.assert_allclose(window.current_config().points, verified_sfo31_config().points, rtol=0, atol=1e-10)
    assert window.current_config().cycles == 17


def test_builtin_sfo_ignores_stale_same_name_recipe(window):
    from gapsim.emulation.parameter_library import save_parameter_preset
    from gapsim.emulation.trench_depo import TrenchDepoConfig
    # An existing PC can contain defaults saved under the SFO3.1 name.
    save_parameter_preset(window._parameter_library_path, 'SFO3.1',
                          TrenchDepoConfig(), emulator_number=0)
    saved_bytes = window._parameter_library_path.read_bytes()
    window.refresh_parameter_presets(show_status=False)
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData('SFO3.1'))
    window.btn_apply_parameter_preset.click()
    cfg = window.current_config()
    assert cfg.angstrom_per_cycle == .56
    assert cfg.front_scheme == 'angular_godunov_v1'
    assert cfg.sputter_enabled and cfg.redepo_enabled and cfg.inhibition_enabled
    assert window._parameter_library_path.read_bytes() == saved_bytes


@pytest.mark.parametrize('contents', ['{"version":2,"presets":{}}', '{broken json'])
def test_builtin_sfo_does_not_depend_on_writable_library(window, contents):
    window._parameter_library_path.write_text(contents, encoding='utf-8')
    window.refresh_parameter_presets(show_status=False)
    index = window.cmb_parameter_preset.findData('SFO3.1')
    assert index >= 0
    window.cmb_parameter_preset.setCurrentIndex(index)
    window.btn_apply_parameter_preset.click()
    assert window.current_config().angstrom_per_cycle == .56
    assert window._parameter_library_path.read_text(encoding='utf-8') == contents


def test_saved_same_name_remains_accessible_and_builtin_cannot_be_deleted(window):
    from gapsim.emulation.sfo31_verified import SAVED_PRESET_KEY
    window.btn_apply_parameter_preset.click()
    window.spin_angstrom_per_cycle.setValue(4)
    window.edit_parameter_preset_name.setText('SFO3.1')
    window.btn_save_parameter_preset.click()
    assert window.cmb_parameter_preset.currentText() == 'SFO3.1 (저장본)'
    assert window.cmb_parameter_preset.findData(SAVED_PRESET_KEY) >= 0
    window.spin_angstrom_per_cycle.setValue(10)
    window.btn_apply_parameter_preset.click()
    assert window.current_config().angstrom_per_cycle == 4
    assert window.btn_delete_parameter_preset.isEnabled()
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData('SFO3.1'))
    assert not window.btn_delete_parameter_preset.isEnabled()
    window.btn_apply_parameter_preset.click()
    assert window.current_config().angstrom_per_cycle == .56

    # Removing a user copy keeps the built-in entry and clears its active label.
    from unittest.mock import patch
    from PySide6.QtWidgets import QMessageBox
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData(SAVED_PRESET_KEY))
    window.btn_apply_parameter_preset.click()
    with patch('gapsim.emulation.trench_depo_ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        window.btn_delete_parameter_preset.click()
    assert window.cmb_parameter_preset.findData('SFO3.1') >= 0
    assert window._active_parameter_preset_name == ''


def test_failed_application_cannot_claim_success(window, monkeypatch):
    from unittest.mock import patch
    monkeypatch.setattr(window, '_apply_parameter_config_values', lambda values: None)
    with patch('gapsim.emulation.trench_depo_ui.QMessageBox.warning') as warning:
        window.btn_apply_parameter_preset.click()
    warning.assert_called_once()
    assert window._active_parameter_preset_name == ''
    assert '적용된 프리셋: 없음' in window.lbl_parameter_preset_active.text()


def test_sfo310_builtin_preserves_geometry_and_legacy_preset(window):
    from gapsim.emulation.sfo31_verified import sfo310_config
    from gapsim.emulation.parameter_library import GEOMETRY_PARAMETER_FIELDS
    before = asdict(window.current_config())
    window.spin_cycles.setValue(23)
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData('SFO3.10'))
    assert not window.btn_delete_parameter_preset.isEnabled()
    window.btn_apply_parameter_preset.click()
    cfg = window.current_config()
    expected = sfo310_config()
    assert cfg.recipe_model == 'calibrated_response_v1'
    assert cfg.deposition_residual_fill_distribution == 'uniform_below_closure'
    assert cfg.angstrom_per_cycle == expected.angstrom_per_cycle
    assert cfg.sputter_strength_a_per_cycle == pytest.approx(expected.sputter_strength_a_per_cycle, abs=1e-12)
    assert cfg.deposition_depth_decay_k == pytest.approx(expected.deposition_depth_decay_k, abs=1e-12)
    assert cfg.cycles == 23
    assert {key: asdict(cfg)[key] for key in GEOMETRY_PARAMETER_FIELDS} == {key: before[key] for key in GEOMETRY_PARAMETER_FIELDS}
    assert 'SFO3.10' in window.lbl_parameter_preset_active.text()
    assert 'SFO3.1 동일 반복' not in window.lbl_parameter_preset_active.text()
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData('SFO3.1'))
    window.btn_apply_parameter_preset.click()
    assert window.current_config().recipe_model == 'calibrated_response_v1'


@pytest.mark.parametrize('name', ('SFO3.10', 'SFO3.11'))
def test_calibrated_user_copy_is_separate_and_replayable(window, name):
    from gapsim.emulation.sfo31_verified import SAVED_PRESET_KEY_310
    from gapsim.emulation.builtin_presets import SAVED_RECIPE_KEYS
    saved_key = SAVED_PRESET_KEY_310 if name == 'SFO3.10' else SAVED_RECIPE_KEYS[name]
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData(name))
    window.btn_apply_parameter_preset.click()
    window.spin_angstrom_per_cycle.setValue(1.5)
    window.edit_parameter_preset_name.setText(name)
    window.btn_save_parameter_preset.click()
    assert window.cmb_parameter_preset.findData(saved_key) >= 0
    assert window.cmb_parameter_preset.currentText() == f'{name} (저장본)'
    window.spin_angstrom_per_cycle.setValue(3.0)
    window.btn_apply_parameter_preset.click()
    cfg = window.current_config()
    assert cfg.recipe_model == 'calibrated_response_v1'
    assert cfg.deposition_residual_fill_distribution == 'uniform_below_closure'
    assert cfg.angstrom_per_cycle == 1.5

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
    expected = parameter_preset_application_values(record, before, include_calculation_settings=True)
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

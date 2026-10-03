from unittest import mock
from PySide6.QtWidgets import QApplication, QMessageBox
from tests.test_process_parameters import window
from gapsim.emulation.trench_depo_ui import TrenchDepoWindow
from gapsim.emulation.incident_presets import incident_study_preset
from dataclasses import asdict
import pytest


def test_outer_workflow_is_unchanged(window):
    assert not window.view_tabs.tabBar().isHidden()
    assert not window.workflow_tabs.tabBar().isHidden()
    assert not hasattr(window, 'workflow_buttons')
    assert [window.workflow_tabs.tabText(i) for i in range(5)] == ['1 구조','2 스무딩','3 진행','4 결과','5 옵션']
    assert window.btn_structure_panel_next.text() == '다음: 스무딩'
    assert window.btn_use_raw_geometry.text() == 'Raw 사용'
    assert window.result_summary_group.title() == '4 결과 / 보기'
    assert window.result_summary_group.isAncestorOf(window.btn_save_result_json)
    assert not window.result_summary_group.isAncestorOf(window.btn_open_json)
    assert window.addon_group.parent() is window.options_panel_content
    for index in range(5):
        window._set_workflow_index(index)
        assert window.process_execution_bar.isHidden() == (index != 2)


def test_common_parameters_and_fixed_run(window):
    p = window.process_parameter_panel
    window.resize(1080,852)
    for i in range(4):
        p.select(i)
        QApplication.processEvents()
        assert window.spin_cycles.isVisible()
        assert window.spin_angstrom_per_cycle.isVisible()
    assert window.params_group.parent() is p
    assert not window.progress_scroll_area.isAncestorOf(window.btn_run)
    window.progress_scroll_area.verticalScrollBar().setValue(99999)
    QApplication.processEvents()
    assert window.btn_run.isVisible()
    assert window.right_panel.rect().contains(window.btn_run.mapTo(window.right_panel, window.btn_run.rect().bottomRight()))


def test_secondary_actions_and_presets_remain_in_process(window):
    layout = window.progress_panel_content.layout()
    assert [layout.itemAt(i).widget() for i in range(5)] == [
        window.process_presets_fold, window.process_parameter_panel,
        window.process_geometry_fold, window.process_actions_fold,
        window.process_notes_fold]
    for control in (window.btn_open_json,window.btn_reset,window.btn_open_run_dir):
        assert window.progress_panel_content.isAncestorOf(control)
    before = window.current_config()
    for fold in (window.process_presets_fold,window.process_geometry_fold,window.process_notes_fold,window.process_actions_fold):
        fold.setChecked(True)
    assert window.current_config() == before
    assert window.process_presets_fold.isAncestorOf(window.parameter_preset_group)
    assert not hasattr(window,'preset_tabs')
    assert not hasattr(window,'incident_preset_group')
    assert window.btn_save_parameter_preset.isEnabled()


def test_hidden_long_pages_do_not_create_blank_scroll_space(window):
    p = window.process_parameter_panel
    p.select(0)
    QApplication.processEvents()
    assert p.stack.sizeHint().height() == p.pages[0].sizeHint().height()
    assert window.process_geometry_fold.y() < window.progress_scroll_area.viewport().height()
    p.select(1)
    window.chk_typical_cvd.setChecked(True)
    before = p.stack.sizeHint().height()
    p.advanced_folds['cvd'].setChecked(True)
    QApplication.processEvents()
    assert p.stack.sizeHint().height() > before


def test_advanced_and_compatibility_settings_are_preserved(window):
    p = window.process_parameter_panel
    window.chk_sputter.setChecked(True)
    window.chk_redepo.setChecked(True)
    window.chk_incident_los.setChecked(True)
    window.chk_typical_cvd.setChecked(True)
    window.chk_inhibition_deposition.setChecked(True)
    before = window.current_config()
    for fold in p.advanced_folds.values():fold.setChecked(True)
    assert window.current_config() == before
    assert p.section_containers['depth'].isHidden()
    assert p.section_containers['ion'].isHidden()
    window.chk_incident_los.setChecked(False)
    window.chk_typical_cvd.setChecked(False)
    assert not p.section_containers['depth'].isHidden()
    assert not p.section_containers['ion'].isHidden()
    assert p.advanced_folds['direct'].isAncestorOf(window.spin_sputter_peak_pct)
    assert p.advanced_folds['direct'].isAncestorOf(window.sputter_curve_editor)
    window.spin_sputter_strength.setValue(4)
    window.spin_sputter_peak_pct.setValue(50)
    assert '2 Å/step' in p.etch_effective.text()


def test_reset_requires_confirmation(window):
    window.process_actions_fold.setChecked(True)
    before = window.current_config()
    with mock.patch('gapsim.emulation.workflow_layout.QMessageBox.question', return_value=QMessageBox.No):
        window.btn_reset.click()
    assert window.current_config() == before
    with mock.patch('gapsim.emulation.workflow_layout.QMessageBox.question', return_value=QMessageBox.Yes), mock.patch.object(window,'reset_defaults') as reset:
        window.btn_reset.click()
    reset.assert_called_once()


@pytest.mark.parametrize('settings', [
    {'cvd_enabled':True,'cvd_overhang_pct':65,'cvd_bottom_ratio_pct':25},
    asdict(incident_study_preset()),
    {'inhibition_enabled':True,'inhibition_strength_pct':60},
])
def test_layout_does_not_change_preset_config(window, settings):
    with mock.patch('gapsim.emulation.trench_depo_ui.QTimer.singleShot'), mock.patch('gapsim.emulation.workflow_layout.install_workflow_layout'):
        original = TrenchDepoWindow()
    try:
        original._apply_parameter_config_values(settings)
        window._apply_parameter_config_values(settings)
        assert window.current_config() == original.current_config()
    finally:
        original.close()

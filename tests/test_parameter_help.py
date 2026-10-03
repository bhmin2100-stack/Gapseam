import pytest
from unittest import mock
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QHelpEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget, QAbstractSpinBox, QComboBox, QCheckBox, QSlider
from PySide6.QtTest import QTest
from test_process_parameters import window
from gapsim.emulation.parameter_help import HELP, clamped_rect
from gapsim.emulation.parameter_help_all import EXTRA, HANDLES, is_value_control


def test_help_catalog_covers_all_primary_parameters(window):
    manager=window.process_parameter_panel.help_manager
    assert len(HELP)>=50
    for key in HELP:
        control=window.cvd_spins[key] if key.startswith('cvd_') else getattr(window,key)
        assert control in manager.bindings
        assert manager.lookup(control)==control
        if isinstance(control,QAbstractSpinBox):assert manager.lookup(control.lineEdit())==control
    for page in window.process_parameter_panel.pages:
        for control in page.findChildren(QWidget):
            if not isinstance(control,(QAbstractSpinBox,QComboBox,QCheckBox,QSlider)):continue
            # Preset pickers, unsupported legacy fields, and hidden compatibility
            # inputs are outside the editable process field surface.
            if control.isVisible() and control.isEnabled():
                assert manager.lookup(control) is not None, control.objectName() or repr(control)


def test_disabled_cvd_label_and_input_help_are_read_only(window):
    panel=window.process_parameter_panel
    panel.select(1)
    QApplication.processEvents()
    manager=panel.help_manager
    control=window.cvd_spins['cvd_overhang_pct']
    assert not control.isEnabled()
    before=window.current_config()
    labels=[w for w,(s,c) in manager.bindings.items() if c is control and w is not control]
    assert labels
    event=QHelpEvent(QEvent.ToolTip,QPoint(2,2),control.mapToGlobal(QPoint(2,2)))
    QApplication.sendEvent(control,event)
    assert manager.bubble.isVisible()
    assert manager.bubble.title.text()=='상부 성장'
    assert 'Overhang' in manager.bubble.meaning.text()
    assert '30.00' in manager.bubble.current.text()
    assert '비활성' in manager.bubble.current.text()
    assert '계산 결과가 아닙니다' in manager.bubble.foot.text()
    assert window.current_config()==before
    manager.hide()
    assert not manager.bubble.animation.timer.isActive()


def test_timer_pause_resume_escape_and_hide(window):
    manager=window.process_parameter_panel.help_manager
    control=window.spin_cycles
    QApplication.sendEvent(control,QKeyEvent(QEvent.KeyPress,Qt.Key_F1,Qt.NoModifier))
    assert manager.bubble.isVisible()
    animation=manager.bubble.animation
    QTest.qWait(110)
    assert animation.phase>0
    manager.bubble.pause.click()
    phase=animation.phase
    QTest.qWait(110)
    assert animation.phase==phase and not animation.timer.isActive()
    manager.bubble.pause.click()
    assert animation.timer.isActive()
    QApplication.sendEvent(control,QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier))
    assert not manager.bubble.isVisible() and not animation.timer.isActive()
    manager.show_for(control)
    window.hide()
    assert not manager.bubble.isVisible() and not animation.timer.isActive()


def test_hover_delay_leave_and_current_value(window):
    manager=window.process_parameter_panel.help_manager
    control=window.spin_cycles
    # Enter path used by label and spinbox hover; do not change focus or value.
    manager.eventFilter(control,QEvent(QEvent.Enter))
    assert manager.delay.isActive() and not manager.bubble.isVisible()
    QTest.qWait(710)
    assert manager.bubble.isVisible()
    manager.eventFilter(control,QEvent(QEvent.Leave))
    manager.eventFilter(manager.bubble,QEvent(QEvent.Enter))
    assert not manager.dismiss.isActive()
    manager.eventFilter(manager.bubble,QEvent(QEvent.Leave))
    QTest.qWait(400)
    assert not manager.bubble.isVisible()
    control.setValue(37)
    manager.show_for(control)
    assert '37' in manager.bubble.current.text()


@pytest.mark.parametrize('screen',[QRect(0,0,800,600),QRect(-1920,0,1920,1080),QRect(0,0,360,480)])
def test_popup_clamped_on_small_and_secondary_screens(screen):
    for x,y in [(screen.left()-500,-90),(screen.right(),screen.bottom())]:
        rect=clamped_rect(QRect(x,y,448,548),screen)
        assert screen.contains(rect)


def test_all_illustrations_render_and_animate_without_changing_config(window,tmp_path):
    manager=window.process_parameter_panel.help_manager
    before=window.current_config()
    manager.show_for(window.spin_cycles)
    animation=manager.bubble.animation
    animation.timer.stop()
    for key, entry in HELP.items():
        control=window.cvd_spins[key] if key.startswith('cvd_') else getattr(window,key)
        manager.show_for(control)
        animation.timer.stop()
        animation.phase=0
        first=animation.grab().toImage()
        animation.phase=.5
        last=animation.grab().toImage()
        assert not first.isNull() and not last.isNull()
        assert first!=last,key
    assert before==window.current_config()
    assert manager.bubble.grab().save(str(tmp_path/'parameter-help.png'))


def test_help_reports_model_state_not_collapsed_editor_state(window):
    window.chk_typical_cvd.setChecked(True)
    control=window.cvd_spins['cvd_cusping_pct']
    manager=window.parameter_help
    control.setEnabled(False)  # A collapsed parent/readonly editor is not CVD OFF.
    manager.show_for(control)
    assert '적용 조건: CVD ON' in manager.bubble.caution.text()
    assert '현재 미적용' not in manager.bubble.caution.text()
    assert manager.bubble.animation.movie is not None
    window.chk_typical_cvd.setChecked(False)
    manager.show_for(control)
    assert '현재 미적용' in manager.bubble.caution.text()


def test_redeposition_uses_actual_profiles_not_a_response_curve_or_flow_boxes(window):
    manager=window.parameter_help
    manager.show_for(window.spin_redepo_emit_power)
    movie=manager.bubble.animation.movie
    assert movie['family']=='redepo'
    assert len(movie['runs'])==2
    assert all(len(run['frames'])>2 for run in movie['runs'])
    assert any(frame['transport'] for run in movie['runs'] for frame in run['frames'])
    manager.show_for(window.slider_frame)
    assert manager.bubble.animation.movie is None
    assert manager.bubble.animation.recorded_result is getattr(window,'_result',None)


def test_example_values_are_not_misrepresented_as_current_values(window):
    window.chk_typical_cvd.setChecked(True)
    control=window.cvd_spins['cvd_overhang_pct']
    manager=window.parameter_help
    control.setValue(80)
    before=window.current_config()
    manager.show_for(control)
    movie=manager.bubble.animation.movie
    assert movie['labels']==['0 %','100 %']
    assert '80.00' in manager.bubble.current.text()
    assert '현재 입력으로 실행한 결과가 아닙니다' in manager.bubble.plot_note.text()
    assert window.current_config() == before


def test_views_change_only_illustration_not_recipe(window):
    manager=window.parameter_help
    manager.show_for(window.spin_redepo_emit_power)
    before=window.current_config()
    movie=manager.bubble.animation.movie
    pictures=[]
    for view in ('shape','zoom','meaning'):
        manager.bubble.view_buttons[view].click()
        assert manager.bubble.animation.view==view
        manager.bubble.animation.phase=.9
        pictures.append(manager.bubble.animation.grab().toImage())
        assert manager.bubble.animation.movie is movie
    assert all(not picture.isNull() for picture in pictures)
    assert pictures[0]!=pictures[1]!=pictures[2]
    assert window.current_config()==before


def test_bubble_view_buttons_accept_mouse_clicks_without_dismissing(window):
    manager=window.parameter_help
    manager.show_for(window.spin_cycles)
    bubble=manager.bubble
    assert bubble.windowType()==Qt.Tool
    assert bubble.windowFlags() & Qt.WindowDoesNotAcceptFocus
    for view in ('zoom','meaning','shape'):
        QTest.mouseClick(bubble.view_buttons[view],Qt.LeftButton)
        QApplication.processEvents()
        assert bubble.isVisible()
        assert bubble.animation.view==view
    QTest.mouseClick(bubble.pause,Qt.LeftButton)
    assert bubble.isVisible() and not bubble.animation.timer.isActive()
    QTest.mouseClick(bubble.pause,Qt.LeftButton)
    assert bubble.isVisible() and bubble.animation.timer.isActive()


def test_every_movie_and_mechanism_renders_without_running_user_simulation(window):
    from gapsim.emulation.parameter_help_trench import examples
    manager=window.parameter_help
    before=window.current_config()
    with mock.patch('gapsim.emulation.trench_depo.run_trench_depo',side_effect=AssertionError('No hover simulation')):
        for key in examples():
            control=window.cvd_spins[key] if key.startswith('cvd_') else getattr(window,key)
            manager.show_for(control)
            animation=manager.bubble.animation
            animation.timer.stop()
            for view in ('shape','zoom','meaning'):
                animation.set_view(view)
                for phase in (.1,.9):
                    animation.phase=phase
                    assert not animation.grab().isNull(),(key,view,phase)
    assert window.current_config()==before


def test_mode_sensitive_redeposition_labels(window):
    manager=window.process_parameter_panel.help_manager
    manager.show_for(window.spin_redepo_distance_power)
    assert 'Specular bias' in manager.bubble.meaning.text()
    with mock.patch.object(window,'active_emulator_number',return_value=2):
        manager.show_for(window.spin_redepo_distance_power)
        assert '거리 감쇠' in manager.bubble.title.text()


def test_all_window_settings_have_explicit_help_including_hidden_controls(window):
    manager=window.parameter_help
    # Scan all widget states, not just the one currently visible page.
    missing=[]
    for widget in window.findChildren(QWidget):
        if manager.bubble.isAncestorOf(widget) or not is_value_control(widget):continue
        anchor=manager.lookup(widget)
        if anchor is None or anchor in manager.fallback_controls:missing.append(widget.objectName() or str(type(widget)))
    assert not missing,missing
    assert window.structure_points_table in manager.resolvers
    for attr in EXTRA:
        if hasattr(window,attr):assert getattr(window,attr) in manager.bindings,attr


def test_nested_multi_field_grid_labels_match_the_correct_control(window):
    manager=window.parameter_help
    window._set_workflow_step('smoothing')
    from PySide6.QtWidgets import QLabel
    found={w.text():c for w,(entry,c) in manager.bindings.items() if isinstance(w,QLabel) and w.text() in ('분할','반복')}
    assert found['분할'] is window.spin_smooth_segments
    assert found['반복'] is window.spin_smooth_iterations


def test_each_curve_handle_uses_its_own_parameter_help(window):
    manager=window.parameter_help
    for attr,mapping in HANDLES.items():
        editor=getattr(window,attr)
        for handle,key in mapping.items():
            with mock.patch.object(editor,'_hit_handle',return_value=handle):
                entry,control=manager.resolve_at(editor,QPoint(50,50))
            if attr=='sputter_curve_editor' and handle=='peak':
                assert '식각 세기' in entry.title
            else:assert control is getattr(window,key),(attr,handle)


def test_dragging_does_not_open_help_or_block_editor(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    manager=window.parameter_help
    editor=window.sputter_curve_editor
    event=QMouseEvent(QEvent.MouseMove,QPointF(40,40),QPointF(40,40),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
    assert not manager.eventFilter(editor,event)
    assert not manager.delay.isActive() and not manager.bubble.isVisible()


def test_nonphysical_animation_and_slider_units(window):
    manager=window.parameter_help
    manager.show_for(window.slider_frame)
    assert '%' not in manager.bubble.current.text()
    assert '계산된 형상' in manager.bubble.caution.text()
    for kind in {entry.kind for entry in EXTRA.values()}:
        manager.bubble.animation.kind=kind
        manager.bubble.animation.phase=.25
        assert not manager.bubble.animation.grab().isNull()


def test_future_control_gets_safe_help_without_inventing_physics(window):
    from PySide6.QtWidgets import QDoubleSpinBox
    control=QDoubleSpinBox(window)
    control.setObjectName('extension-setting')
    control.setToolTip('확장 기능의 세기')
    control.show()
    QApplication.processEvents()
    manager=window.parameter_help
    assert manager.lookup(control) is control
    assert control in manager.fallback_controls
    manager.show_for(control)
    assert '자동으로 추정하지 않습니다' in manager.bubble.caution.text()
    manager.hide()
    control.close()


def test_separate_split_window_has_help(window):
    from gapsim.emulation.trench_depo_ui import SplitTestWindow
    with mock.patch('gapsim.emulation.trench_depo_ui.QTimer.singleShot'):
        split=SplitTestWindow([])
    try:
        split.show()
        QApplication.processEvents()
        manager=split.parameter_help
        for control in (split.slider_frame,split.slider_overlay_opacity,split.btn_overlay_compare):
            assert manager.lookup(control) is control
            manager.show_for(control)
            assert manager.bubble.isVisible()
        assert not manager.fallback_controls
    finally:split.close()


def test_coordinate_cells_have_axis_specific_help(window):
    window._set_workflow_step('structure')
    QApplication.processEvents()
    table=window.structure_points_table
    for col,axis in enumerate(('X','Y')):
        index=table.model().index(0,col)
        pos=table.viewport().mapTo(table,table.visualRect(index).center())
        entry,control=window.parameter_help.resolve_at(table,pos)
        assert entry.title==axis+' 좌표'
        assert 'Å' in table.property('helpCurrentValue')


def test_toolbar_settings_is_next_to_update_check(window):
    from PySide6.QtWidgets import QToolBar
    toolbar = next(t for t in window.findChildren(QToolBar)
                   if window.action_check_updates in t.actions())
    actions = toolbar.actions()
    assert toolbar.widgetForAction(actions[actions.index(window.action_check_updates)+1]) is window.settings_button
    assert window.settings_button.text() == '설정'
    assert window.action_help_bubbles in window.help_settings_menu.actions()
    assert window.action_help_bubbles.isChecked()


def test_setting_closes_bubble_and_blocks_hover_tooltip_and_f1(window):
    manager = window.parameter_help
    control = window.spin_cycles
    before = window.current_config()
    manager.show_for(control)
    assert manager.bubble.isVisible() and manager.bubble.animation.timer.isActive()
    window.action_help_bubbles.trigger()
    assert not manager.enabled
    assert not manager.bubble.isVisible() and not manager.bubble.animation.timer.isActive()
    assert '꺼짐' in window.process_parameter_panel.help_hint.text()
    manager.eventFilter(control, QEvent(QEvent.Enter))
    assert not manager.delay.isActive()
    QApplication.sendEvent(control, QHelpEvent(QEvent.ToolTip, QPoint(2,2), control.mapToGlobal(QPoint(2,2))))
    QApplication.sendEvent(control, QKeyEvent(QEvent.KeyPress, Qt.Key_F1, Qt.NoModifier))
    manager.show_for(control)
    QTest.qWait(710)
    assert not manager.bubble.isVisible()
    assert not manager.eventFilter(control, QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier))
    assert window.current_config() == before
    window.action_help_bubbles.trigger()
    QApplication.sendEvent(control, QKeyEvent(QEvent.KeyPress, Qt.Key_F1, Qt.NoModifier))
    assert manager.enabled and manager.bubble.isVisible()
    assert window.current_config() == before


def test_disabling_cancels_pending_hover(window):
    manager = window.parameter_help
    manager.eventFilter(window.spin_cycles, QEvent(QEvent.Enter))
    assert manager.delay.isActive()
    window.action_help_bubbles.setChecked(False)
    assert manager.pending is None and not manager.delay.isActive() and not manager.dismiss.isActive()
    QTest.qWait(710)
    assert not manager.bubble.isVisible()


def test_help_preference_persists_and_new_windows_inherit_it(window):
    from PySide6.QtCore import QSettings
    from gapsim.emulation.help_preferences import HelpPreferences
    from gapsim.emulation.trench_depo_ui import SplitTestWindow
    preferences = window.parameter_help.preferences
    window.action_help_bubbles.setChecked(False)
    restarted = HelpPreferences(QSettings(preferences.settings.fileName(), QSettings.IniFormat))
    assert restarted.enabled is False
    with mock.patch('gapsim.emulation.trench_depo_ui.QTimer.singleShot'):
        split = SplitTestWindow([])
    try:
        split.show()
        QApplication.processEvents()
        manager = split.parameter_help
        manager.show_for(split.slider_frame)
        assert not manager.enabled and not manager.bubble.isVisible()
        window.action_help_bubbles.setChecked(True)
        manager.show_for(split.slider_frame)
        assert manager.enabled and manager.bubble.isVisible()
        window.action_help_bubbles.setChecked(False)
        assert not manager.bubble.isVisible() and not manager.bubble.animation.timer.isActive()
    finally:
        split.close()

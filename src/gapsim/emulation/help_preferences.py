"""Application-wide, local-only preference for animated explanation bubbles."""
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QToolButton


class HelpPreferences(QObject):
    enabledChanged = Signal(bool)
    saveFailed = Signal(str)
    KEY = 'ui/explanationBubblesEnabled'

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings('Gapseam', 'GFE')
        self.enabled = self.settings.value(self.KEY, True, type=bool)

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if self.enabled == enabled:
            return
        self.enabled = enabled
        self.settings.setValue(self.KEY, enabled)
        self.settings.sync()
        self.enabledChanged.emit(enabled)
        if self.settings.status() != QSettings.Status.NoError:
            self.saveFailed.emit('말풍선 설정을 저장하지 못했습니다. 이번 실행에만 적용됩니다.')


def help_preferences():
    app = QApplication.instance()
    if not hasattr(app, '_gfe_help_preferences'):
        app._gfe_help_preferences = HelpPreferences(parent=app)
    return app._gfe_help_preferences


def install_help_settings(owner, toolbar):
    preferences = help_preferences()
    owner.help_settings_menu = QMenu(owner)
    owner.action_help_bubbles = QAction('설명 말풍선 표시', owner)
    owner.action_help_bubbles.setCheckable(True)
    owner.action_help_bubbles.setChecked(preferences.enabled)
    owner.action_help_bubbles.setStatusTip('움직이는 설명 말풍선을 켜거나 끕니다. 다음 실행에도 유지됩니다.')
    owner.action_help_bubbles.toggled.connect(preferences.set_enabled)
    preferences.enabledChanged.connect(owner.action_help_bubbles.setChecked)
    preferences.saveFailed.connect(owner.statusBar().showMessage)
    owner.help_settings_menu.addAction(owner.action_help_bubbles)
    owner.settings_button = QToolButton(owner)
    owner.settings_button.setText('설정')
    owner.settings_button.setAccessibleName('설정')
    owner.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    owner.settings_button.setMenu(owner.help_settings_menu)
    toolbar.addWidget(owner.settings_button)

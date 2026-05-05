"""Top-level QMainWindow with a tab-style stacked navigation."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

from gui import APP_NAME, __version__
from gui.pages.config_page import ConfigPage
from gui.pages.generate_page import GeneratePage
from gui.pages.settings_page import SettingsPage
from gui.pages.sprint_select_page import SprintSelectPage
from gui.settings import load_settings, save_settings


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1100, 800)

        # Pages
        self.settings_page = SettingsPage(self.settings)
        self.sprint_page = SprintSelectPage(self.settings)
        self.config_page = ConfigPage(self.settings)
        self.generate_page = GeneratePage(self.settings)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.settings_page)   # 0
        self.stack.addWidget(self.sprint_page)     # 1
        self.stack.addWidget(self.config_page)     # 2
        self.stack.addWidget(self.generate_page)   # 3

        # Sidebar nav buttons
        self.nav_buttons: list[QPushButton] = []
        nav = QVBoxLayout()
        nav.setSpacing(4)
        for i, label in enumerate([
            "1. Settings",
            "2. Sprint",
            "3. Configure",
            "4. Generate",
        ]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(38)
            btn.clicked.connect(lambda _checked, idx=i: self._goto(idx))
            self.nav_buttons.append(btn)
            nav.addWidget(btn)
        nav.addStretch(1)
        version_label = QLabel(f"v{__version__}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet("color: #888; font-size: 10px;")
        nav.addWidget(version_label)

        sidebar = QWidget()
        sidebar.setLayout(nav)
        sidebar.setFixedWidth(160)
        sidebar.setStyleSheet(
            "QPushButton { text-align: left; padding: 6px 12px; }"
            "QPushButton:checked { background: #2176FF; color: white; font-weight: bold; }"
        )

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(sidebar)
        root.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        # Wiring between pages
        self.settings_page.settings_saved.connect(self._on_settings_saved)
        self.sprint_page.sprint_loaded.connect(self._on_sprint_loaded)
        self.config_page.config_ready.connect(self._on_config_ready)

        # Default page: Settings if no creds, otherwise Sprint
        creds = self.settings.effective_credentials()
        if creds.get("JIRA_BASE_URL") and (creds.get("JIRA_TOKEN") or creds.get("JIRA_USER")):
            self._goto(1)
        else:
            self._goto(0)

    # ── nav ─────────────────────────────────────────────────────────────

    def _goto(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    # ── handlers ────────────────────────────────────────────────────────

    def _on_settings_saved(self) -> None:
        self.statusBar().showMessage("Settings saved.", 3000)
        self._goto(1)

    def _on_sprint_loaded(self, payload: dict, sprint: dict) -> None:
        log.info("MainWindow._on_sprint_loaded entered: sprint=%s, issues=%d",
                 sprint.get("name", ""), len(payload.get("issues", [])))
        try:
            self.config_page.populate_from_payload(payload, sprint)
            log.info("config_page.populate_from_payload returned OK")
        except Exception as exc:
            log.exception("populate_from_payload raised")
            QMessageBox.critical(
                self, "Error populating config",
                f"Failed to populate the configuration page:\n\n{exc}",
            )
            return
        try:
            self.statusBar().showMessage(
                f"Loaded {sprint.get('name', '')} — {len(payload.get('issues', []))} issues.", 5000,
            )
            self._goto(2)
            log.info("Navigated to Configure page")
        except Exception:
            log.exception("Failed after populate (navigation step)")
            raise

    def _on_config_ready(self, cfg) -> None:
        self.generate_page.set_inputs(cfg, self.config_page.payload)
        self._goto(3)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        save_settings(self.settings)
        super().closeEvent(event)

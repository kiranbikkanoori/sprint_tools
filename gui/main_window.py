"""Top-level QMainWindow with capsule navigation and presenter pack."""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from gui import APP_NAME, __version__
from gui.pack_model import PackSlot, ReportPack
from gui.pages.config_page import ConfigPage
from gui.pages.generate_page import GeneratePage
from gui.pages.help_page import HelpPage
from gui.pages.settings_page import SettingsPage
from gui.pages.sprint_select_page import SprintSelectPage
from gui.settings import load_settings, save_settings
from gui.theme import theme_colors
from gui.widgets.capsule_bar import CapsuleBar

log = logging.getLogger(__name__)

IDX_HELP = 0
IDX_SETTINGS = 1
IDX_SPRINT = 2
IDX_CONFIG = 3
IDX_GENERATE = 4

_NAV_LABELS = ["Help", "Settings", "Sprint", "Configure", "Generate"]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.pack = ReportPack()
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1200, 820)

        self.help_page = HelpPage()
        self.settings_page = SettingsPage(self.settings)
        self.sprint_page = SprintSelectPage(self.settings)
        self.config_page = ConfigPage(self.settings)
        self.generate_page = GeneratePage(self.settings)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.help_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.sprint_page)
        self.stack.addWidget(self.config_page)
        self.stack.addWidget(self.generate_page)

        self.nav = CapsuleBar(_NAV_LABELS)
        self.nav.currentChanged.connect(self._goto)

        self.brand = QLabel(APP_NAME)
        self.version_label = QLabel(f"v{__version__}")

        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 0)
        header.setSpacing(12)
        header.addWidget(self.brand)
        header.addWidget(self.nav, stretch=1)
        header.addWidget(self.version_label)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(10)
        root.addLayout(header)
        root.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.settings_page.settings_saved.connect(self._on_settings_saved)
        self.sprint_page.sprint_added.connect(self._on_sprint_added)
        self.sprint_page.configure_requested.connect(self._open_configure)
        self.config_page.config_ready.connect(self._on_config_ready)
        self.config_page.back_to_sprint.connect(lambda: self._goto(IDX_SPRINT))

        self.sprint_page.set_pack(self.pack)
        self._apply_chrome_theme()

        creds = self.settings.effective_credentials()
        if creds.get("JIRA_BASE_URL") and (creds.get("JIRA_TOKEN") or creds.get("JIRA_USER")):
            self._goto(IDX_SPRINT)
        else:
            self._goto(IDX_SETTINGS)

    def _apply_chrome_theme(self) -> None:
        c = theme_colors()
        self.brand.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {c['text']};"
        )
        self.version_label.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        self.nav.apply_theme()
        self.generate_page.apply_theme()

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.PaletteChange:
            self._apply_chrome_theme()
        super().changeEvent(event)

    def _goto(self, index: int) -> None:
        if index < 0 or index >= self.stack.count():
            return
        if index == IDX_CONFIG and len(self.pack) == 0:
            QMessageBox.information(
                self,
                "Empty pack",
                "Add at least one sprint on the Sprint tab before Configure.",
            )
            self.stack.setCurrentIndex(IDX_SPRINT)
            self.nav.set_current(IDX_SPRINT)
            return
        if index == IDX_GENERATE and len(self.pack) == 0:
            QMessageBox.information(
                self,
                "Empty pack",
                "Add and configure at least one sprint before Generate.",
            )
            self.stack.setCurrentIndex(IDX_SPRINT)
            self.nav.set_current(IDX_SPRINT)
            return
        if index == IDX_CONFIG and len(self.pack) > 0:
            # Refresh config binding when navigating via capsule.
            if self.stack.currentIndex() != IDX_CONFIG:
                self.config_page.bind_pack(self.pack, active_index=max(0, len(self.pack) - 1))
        self.stack.setCurrentIndex(index)
        self.nav.set_current(index)

    def _on_settings_saved(self) -> None:
        self.statusBar().showMessage("Settings saved.", 3000)
        self._goto(IDX_SPRINT)

    def _on_sprint_added(self, payload: dict, sprint: dict, board_meta: dict) -> None:
        board_id = int(board_meta.get("id") or 0)
        board_name = str(board_meta.get("name") or "")
        log.info(
            "MainWindow._on_sprint_added: board=%s sprint=%s issues=%d",
            board_name,
            sprint.get("name", ""),
            len(payload.get("issues", [])),
        )
        slot = PackSlot(
            board_id=board_id,
            board_name=board_name,
            sprint=sprint,
            payload=payload,
            config=None,
        )
        # Seed default config so Configure / Generate have something ready.
        try:
            slot.config = self.config_page.build_config_from_payload(
                payload, sprint, board_id
            )
        except Exception as exc:
            log.exception("Failed to seed pack slot config")
            QMessageBox.critical(
                self,
                "Error preparing config",
                f"Failed to prepare configuration for {slot.label}:\n\n{exc}",
            )
            return

        action = self.pack.add_or_replace(slot)
        self.sprint_page.set_pack(self.pack)
        verb = "Updated" if action == "replaced" else "Added"
        self.statusBar().showMessage(
            f"{verb} {slot.label} — pack has {len(self.pack)} sprint(s). "
            f"{len(payload.get('issues', []))} issues.",
            6000,
        )
        # Stay on Sprint so the next Add sprint is obvious.

    def _open_configure(self) -> None:
        if len(self.pack) == 0:
            QMessageBox.information(
                self,
                "Empty pack",
                "Add at least one sprint before Configure.",
            )
            return
        self.config_page.bind_pack(self.pack, active_index=len(self.pack) - 1)
        self._goto(IDX_CONFIG)

    def _on_config_ready(self) -> None:
        if len(self.pack) == 0:
            return
        self.generate_page.set_pack(self.pack)
        self._goto(IDX_GENERATE)

    def closeEvent(self, event) -> None:  # noqa: N802
        save_settings(self.settings)
        try:
            self.help_page.cleanup()
        except Exception:
            log.debug("help_page.cleanup failed", exc_info=True)
        super().closeEvent(event)

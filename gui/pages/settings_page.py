"""Jira credentials & general settings."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui import jira_service
from gui.settings import AppSettings, output_dir_default, save_settings


class SettingsPage(QWidget):
    settings_saved = Signal()

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings

        title = QLabel("<h2>Jira connection &amp; preferences</h2>")
        subtitle = QLabel(
            "Credentials are stored encrypted in your user app-data folder. "
            "If left blank, the app falls back to a <code>.env</code> file next to the executable."
        )
        subtitle.setWordWrap(True)

        # ── Jira group ──
        creds = QGroupBox("Jira")
        creds_form = QFormLayout(creds)

        self.url_edit = QLineEdit(settings.jira_base_url)
        self.url_edit.setPlaceholderText("https://jira.silabs.com")

        self.token_edit = QLineEdit(settings.jira_token)
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("Personal Access Token (recommended)")

        self.user_edit = QLineEdit(settings.jira_user)
        self.user_edit.setPlaceholderText("Username (only if not using a token)")

        self.pwd_edit = QLineEdit(settings.jira_password)
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.pwd_edit.setPlaceholderText("Password (only if not using a token)")

        creds_form.addRow("Base URL", self.url_edit)
        creds_form.addRow("Token", self.token_edit)
        creds_form.addRow("Username", self.user_edit)
        creds_form.addRow("Password", self.pwd_edit)

        # ── Output group ──
        out_group = QGroupBox("Output")
        out_form = QFormLayout(out_group)

        out_row = QHBoxLayout()
        self.out_edit = QLineEdit(settings.output_dir or str(output_dir_default()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        out_row.addWidget(self.out_edit)
        out_row.addWidget(browse)
        wrapper = QWidget()
        wrapper.setLayout(out_row)
        out_form.addRow("Default output folder", wrapper)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        self.test_btn = QPushButton("Test connection")
        self.save_btn = QPushButton("Save")
        self.save_btn.setDefault(True)
        btn_row.addStretch(1)
        btn_row.addWidget(self.test_btn)
        btn_row.addWidget(self.save_btn)

        self.test_btn.clicked.connect(self._test_connection)
        self.save_btn.clicked.connect(self._save)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(creds)
        layout.addWidget(out_group)
        layout.addStretch(1)
        layout.addLayout(btn_row)

    # ── handlers ──────────────────────────────────────────────────────────

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose output folder", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def _gather(self) -> AppSettings:
        s = self.settings
        s.jira_base_url = self.url_edit.text().strip()
        s.jira_token = self.token_edit.text().strip()
        s.jira_user = self.user_edit.text().strip()
        s.jira_password = self.pwd_edit.text().strip()
        s.output_dir = self.out_edit.text().strip() or str(output_dir_default())
        return s

    def _save(self) -> None:
        s = self._gather()
        save_settings(s)
        self.settings_saved.emit()
        QMessageBox.information(self, "Settings saved", "Settings saved.")

    def _test_connection(self) -> None:
        s = self._gather()
        creds = s.effective_credentials()
        try:
            client = jira_service.make_client(creds)
            boards = client.find_boards("", board_type="scrum")
        except jira_service.JiraConfigError as e:
            QMessageBox.warning(self, "Connection error", str(e))
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Connection failed", f"Could not reach Jira:\n\n{e}")
            return
        QMessageBox.information(
            self, "Connection OK",
            f"Connected to {creds.get('JIRA_BASE_URL')}.\nFound {len(boards)} boards in initial query.",
        )

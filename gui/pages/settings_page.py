"""Jira credentials & general settings."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
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
from jira_auth import (
    BACKEND_CLOUD,
    BACKEND_LABELS,
    BACKEND_SERVER,
    DEFAULT_URLS,
    normalize_backend,
)


class SettingsPage(QWidget):
    settings_saved = Signal()

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        # Prefill from saved settings, falling back to .env via effective_credentials.
        effective = settings.effective_credentials()

        title = QLabel("<h2>Jira connection &amp; preferences</h2>")
        subtitle = QLabel(
            "Choose the Jira backend, then enter credentials for that system. "
            "Credentials are stored encrypted in your user app-data folder. "
            "If left blank, the app falls back to a <code>.env</code> file next to the executable."
        )
        subtitle.setWordWrap(True)

        # ── Jira group ──
        creds = QGroupBox("Jira")
        self.creds_form = QFormLayout(creds)

        self.backend_combo = QComboBox()
        for key in (BACKEND_SERVER, BACKEND_CLOUD):
            self.backend_combo.addItem(BACKEND_LABELS[key], key)
        try:
            initial_backend = normalize_backend(effective.get("JIRA_BACKEND"))
        except ValueError:
            initial_backend = BACKEND_SERVER
        idx = self.backend_combo.findData(initial_backend)
        if idx >= 0:
            self.backend_combo.setCurrentIndex(idx)

        self.url_edit = QLineEdit(effective.get("JIRA_BASE_URL", ""))
        self.token_edit = QLineEdit(effective.get("JIRA_TOKEN", ""))
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.user_edit = QLineEdit(effective.get("JIRA_USER", ""))
        self.pwd_edit = QLineEdit(effective.get("JIRA_PASSWORD", ""))
        self.pwd_edit.setEchoMode(QLineEdit.Password)

        self.help_label = QLabel()
        self.help_label.setWordWrap(True)
        self.help_label.setStyleSheet("color: #555; margin-top: 4px;")

        self.creds_form.addRow("Backend", self.backend_combo)
        self.creds_form.addRow("Base URL", self.url_edit)
        self._user_label = QLabel("Email / Username")
        self._token_label = QLabel("Token")
        self._pwd_label = QLabel("Password")
        self.creds_form.addRow(self._user_label, self.user_edit)
        self.creds_form.addRow(self._token_label, self.token_edit)
        self.creds_form.addRow(self._pwd_label, self.pwd_edit)
        self.creds_form.addRow(self.help_label)

        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self._on_backend_changed()

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

    # ── backend-dependent field chrome ──────────────────────────────────

    def _selected_backend(self) -> str:
        data = self.backend_combo.currentData()
        return data if isinstance(data, str) else BACKEND_SERVER

    def _on_backend_changed(self) -> None:
        backend = self._selected_backend()
        default_url = DEFAULT_URLS[backend]
        self.url_edit.setPlaceholderText(default_url)
        # Only auto-swap URL when empty or still the other backend's stock default.
        # Do not clobber a real user/Cloud URL during first paint.
        current_url = self.url_edit.text().strip()
        other_defaults = {u for b, u in DEFAULT_URLS.items() if b != backend}
        if current_url in other_defaults:
            self.url_edit.setText(default_url)
        elif not current_url:
            self.url_edit.setPlaceholderText(default_url)

        if backend == BACKEND_CLOUD:
            self._user_label.setText("Email")
            self._token_label.setText("API token")
            self.user_edit.setPlaceholderText("you@silabs.com")
            self.user_edit.setVisible(True)
            self._user_label.setVisible(True)
            self.token_edit.setPlaceholderText("Atlassian API token")
            self.pwd_edit.clear()
            self.pwd_edit.setVisible(False)
            self._pwd_label.setVisible(False)
            self.help_label.setText(
                "Cloud: use your Atlassian account email and an API token from "
                "id.atlassian.com → Security → API tokens. "
                "Typical URL: https://siliconlabs.atlassian.net"
            )
        else:
            self._user_label.setText("Username")
            self._token_label.setText("Personal access token")
            self.user_edit.setPlaceholderText("Optional if using a PAT")
            self.user_edit.setVisible(True)
            self._user_label.setVisible(True)
            self.token_edit.setPlaceholderText("Jira Server / DC personal access token")
            self.pwd_edit.setVisible(True)
            self._pwd_label.setVisible(True)
            self.pwd_edit.setPlaceholderText("Only if not using a PAT")
            self.help_label.setText(
                "Server/DC: prefer a personal access token (Bearer). "
                "Username + password is legacy fallback. "
                "Typical URL: https://jira.silabs.com"
            )

    # ── handlers ──────────────────────────────────────────────────────────

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose output folder", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def _gather(self) -> AppSettings:
        s = self.settings
        s.jira_backend = self._selected_backend()
        s.jira_base_url = self.url_edit.text().strip()
        s.jira_token = self.token_edit.text().strip()
        s.jira_user = self.user_edit.text().strip()
        if s.jira_backend == BACKEND_CLOUD:
            s.jira_password = ""
        else:
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
            base_url, board_count, auth_desc = jira_service.test_connection(creds)
        except jira_service.JiraConfigError as e:
            QMessageBox.warning(self, "Connection error", str(e))
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Connection failed", f"Could not reach Jira:\n\n{e}")
            return
        QMessageBox.information(
            self, "Connection OK",
            f"Connected to {base_url}\n"
            f"Auth: {auth_desc}\n"
            f"Found {board_count} boards in initial query.",
        )

"""Run report + chart generation and preview the output."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from config_parser import SprintConfig
from gui.settings import AppSettings, output_dir_default
from gui.theme import app_theme
from gui.workers.jira_workers import GenerateReportWorker, run_worker

log = logging.getLogger(__name__)


def _preview_html_from_export(html_path: Path, theme: str) -> str:
    """
    Load exported HTML and re-theme it for QTextBrowser.

    The on-disk file keeps dual-theme CSS for browsers; the preview injects a
    resolved single-theme stylesheet so Qt's limited CSS engine looks correct.
    """
    from report_style import report_css_for_theme

    raw = html_path.read_text(encoding="utf-8")
    body_m = re.search(r"<body[^>]*>(.*)</body>", raw, flags=re.IGNORECASE | re.DOTALL)
    body = body_m.group(1) if body_m else raw
    # Remove theme toggle UI (buttons don't work inside QTextBrowser).
    body = re.sub(
        r'<div class="theme-toggle">.*?</div>',
        "",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    body = re.sub(r"<script\b[^>]*>.*?</script>", "", body, flags=re.IGNORECASE | re.DOTALL)
    css = report_css_for_theme(theme)
    return (
        f'<!DOCTYPE html><html lang="en" data-theme="{theme}">'
        f"<head><meta charset='utf-8'/>{css}</head>"
        f"<body>{body}</body></html>"
    )


class GeneratePage(QWidget):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.config: SprintConfig | None = None
        self.payload: dict = {}
        self.last_outputs: dict[str, Path] = {}

        title = QLabel("<h2>Generate report &amp; chart</h2>")

        # ── Options ──
        opts = QGroupBox("Output")
        o_lay = QHBoxLayout(opts)
        self.cb_report = QCheckBox("Report (Markdown + HTML)")
        self.cb_chart = QCheckBox("Burndown PNG")
        self.cb_report.setChecked(True)
        self.cb_chart.setChecked(True)
        o_lay.addWidget(self.cb_report)
        o_lay.addWidget(self.cb_chart)
        o_lay.addStretch(1)

        self.output_label = QLabel(f"Output folder: {settings.output_dir or output_dir_default()}")
        self.choose_dir_btn = QPushButton("Change…")
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_label, stretch=1)
        out_row.addWidget(self.choose_dir_btn)
        self.choose_dir_btn.clicked.connect(self._choose_output_dir)

        # ── Actions ──
        actions = QHBoxLayout()
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setDefault(True)
        self.open_html_btn = QPushButton("Open HTML report")
        self.open_html_btn.setEnabled(False)
        self.open_folder_btn = QPushButton("Open output folder")
        self.open_folder_btn.setEnabled(False)
        actions.addWidget(self.generate_btn)
        actions.addStretch(1)
        actions.addWidget(self.open_html_btn)
        actions.addWidget(self.open_folder_btn)

        self.generate_btn.clicked.connect(self._generate)
        self.open_html_btn.clicked.connect(self._open_html_report)
        self.open_folder_btn.clicked.connect(self._open_output_folder)

        # ── Progress + preview (chart is embedded at the end of the HTML report) ──
        self.progress_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)

        self.report_view = QTextBrowser()
        self.report_view.setOpenExternalLinks(True)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(opts)
        layout.addLayout(out_row)
        layout.addLayout(actions)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.report_view, stretch=1)

    # ── public ──────────────────────────────────────────────────────────

    def set_inputs(self, config: SprintConfig, payload: dict) -> None:
        self.config = config
        self.payload = payload

    # ── handlers ────────────────────────────────────────────────────────

    def _choose_output_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Output folder",
                                             self.settings.output_dir or str(output_dir_default()))
        if d:
            self.settings.output_dir = d
            self.output_label.setText(f"Output folder: {d}")

    def _busy(self, msg: str, busy: bool) -> None:
        self.progress_label.setText(msg if busy else "")
        self.progress_bar.setVisible(busy)
        self.generate_btn.setEnabled(not busy)

    def _generate(self) -> None:
        if not self.config or not self.payload:
            QMessageBox.warning(self, "Nothing to generate",
                                "Load a sprint and configure it first.")
            return
        out_dir = Path(self.settings.output_dir or output_dir_default())
        self._busy("Generating…", True)
        worker = GenerateReportWorker(
            self.config, self.payload, out_dir,
            make_report=self.cb_report.isChecked(),
            make_chart=self.cb_chart.isChecked(),
        )

        def _progress(msg, cur, total):
            self.progress_label.setText(msg)
            if total > 0:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(cur)
            else:
                self.progress_bar.setRange(0, 0)

        worker.progress.connect(_progress)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        run_worker(worker, self)

    def _on_failed(self, msg: str) -> None:
        self._busy("", False)
        QMessageBox.critical(self, "Generation failed", msg)

    def _on_finished(self, written: dict) -> None:
        self._busy("", False)
        self.last_outputs = {k: Path(v) for k, v in (written or {}).items()}
        self.open_folder_btn.setEnabled(bool(self.last_outputs))
        self.open_html_btn.setEnabled("report_html" in self.last_outputs)

        if "report_html" in self.last_outputs:
            try:
                html_path = self.last_outputs["report_html"]
                theme = app_theme()
                html = _preview_html_from_export(html_path, theme)
                # Resolve relative chart images against the output directory.
                self.report_view.document().setBaseUrl(
                    QUrl.fromLocalFile(str(html_path.parent.resolve()) + "/")
                )
                self.report_view.setHtml(html)
            except Exception as e:  # noqa: BLE001
                log.exception("Failed to preview HTML report")
                self.report_view.setPlainText(f"(Could not preview HTML report: {e})")
        elif "report" in self.last_outputs:
            try:
                self.report_view.setPlainText(
                    self.last_outputs["report"].read_text(encoding="utf-8")
                )
            except Exception as e:  # noqa: BLE001
                self.report_view.setPlainText(f"(Could not read report: {e})")

        msg = "Done."
        if "report_html" in self.last_outputs:
            msg += f"\n\nHTML report: {self.last_outputs['report_html']}"
        if "report" in self.last_outputs:
            msg += f"\nMarkdown : {self.last_outputs['report']}"
        if "chart" in self.last_outputs:
            msg += f"\nChart    : {self.last_outputs['chart']}"
        QMessageBox.information(self, "Generated", msg)

    def _open_html_report(self) -> None:
        path = self.last_outputs.get("report_html")
        if not path or not path.is_file():
            QMessageBox.information(self, "No HTML report", "Generate a report first.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _open_output_folder(self) -> None:
        out = self.settings.output_dir or str(output_dir_default())
        if sys.platform.startswith("win"):
            os.startfile(out)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", out])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))

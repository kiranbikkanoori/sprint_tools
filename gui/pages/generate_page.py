"""Run report + chart generation and preview the output."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    import markdown as _markdown
    _HAS_MD = True
    _MD_IMPORT_ERR = ""
except Exception as _e:  # pragma: no cover
    _HAS_MD = False
    _MD_IMPORT_ERR = repr(_e)

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


_REPORT_CSS = """
<style>
  body { font-family: 'Segoe UI', sans-serif; font-size: 13px; color: #222; }
  h1 { font-size: 20px; border-bottom: 2px solid #2176FF; padding-bottom: 6px; }
  h2 { font-size: 16px; color: #2176FF; margin-top: 24px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
  table { border-collapse: collapse; margin: 8px 0 16px 0; }
  th, td { border: 1px solid #c0c0c0; padding: 4px 8px; vertical-align: top; }
  th { background: #f0f4ff; text-align: left; font-weight: 600; }
  td code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; font-size: 12px; }
  tr:nth-child(even) td { background: #fafbfc; }
  blockquote { border-left: 3px solid #2176FF; margin: 8px 0; padding: 4px 12px; background: #f7faff; color: #444; }
  hr { border: 0; border-top: 1px solid #ddd; margin: 16px 0; }
  em { color: #888; }
</style>
"""


def _render_markdown(text: str) -> str:
    """Render markdown to HTML, preserving inline <br> tags inside table cells."""
    import logging
    log = logging.getLogger(__name__)
    if _HAS_MD:
        try:
            body = _markdown.markdown(
                text,
                extensions=["tables", "fenced_code", "md_in_html"],
            )
            log.info("Rendered report via markdown package (%d bytes)", len(body))
        except Exception as e:
            log.exception("markdown rendering failed; falling back to <pre>")
            from html import escape
            body = (
                f"<p style='color:#a00;'>Markdown rendering failed: {escape(str(e))}</p>"
                f"<pre>{escape(text)}</pre>"
            )
    else:
        from html import escape
        log.warning("markdown package not available (%s) — using <pre> fallback",
                    _MD_IMPORT_ERR)
        body = (
            "<p style='color:#a00;'>Note: <code>markdown</code> Python package is not "
            f"bundled in this build ({escape(_MD_IMPORT_ERR)}). Showing raw text.</p>"
            f"<pre>{escape(text)}</pre>"
        )
    return f"<html><head>{_REPORT_CSS}</head><body>{body}</body></html>"

from config_parser import SprintConfig
from gui.settings import AppSettings, output_dir_default
from gui.workers.jira_workers import GenerateReportWorker, run_worker


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
        self.cb_report = QCheckBox("Markdown report")
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
        self.open_folder_btn = QPushButton("Open output folder")
        self.open_folder_btn.setEnabled(False)
        actions.addWidget(self.generate_btn)
        actions.addStretch(1)
        actions.addWidget(self.open_folder_btn)

        self.generate_btn.clicked.connect(self._generate)
        self.open_folder_btn.clicked.connect(self._open_output_folder)

        # ── Progress + preview ──
        self.progress_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)

        self.preview_tabs = QTabWidget()
        self.report_view = QTextBrowser()
        self.report_view.setOpenExternalLinks(True)
        self.preview_tabs.addTab(self.report_view, "Report")

        self.chart_label = QLabel("Chart will appear here once generated.")
        self.chart_label.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.chart_label)
        self.preview_tabs.addTab(scroll, "Burndown chart")

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(opts)
        layout.addLayout(out_row)
        layout.addLayout(actions)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.preview_tabs, stretch=1)

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
        self.last_outputs = written or {}
        self.open_folder_btn.setEnabled(bool(self.last_outputs))

        if "report" in written:
            try:
                text = Path(written["report"]).read_text(encoding="utf-8")
                self.report_view.setHtml(_render_markdown(text))
            except Exception as e:  # noqa: BLE001
                self.report_view.setPlainText(f"(Could not read report: {e})")

        if "chart" in written:
            pix = QPixmap(str(written["chart"]))
            if not pix.isNull():
                self.chart_label.setPixmap(pix)
                self.chart_label.setText("")
            else:
                self.chart_label.setText("(Chart could not be loaded)")

        msg = "Done."
        if "report" in written:
            msg += f"\n\nReport: {written['report']}"
        if "chart" in written:
            msg += f"\nChart : {written['chart']}"
        QMessageBox.information(self, "Generated", msg)

    def _open_output_folder(self) -> None:
        out = self.settings.output_dir or str(output_dir_default())
        if sys.platform.startswith("win"):
            os.startfile(out)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", out])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))

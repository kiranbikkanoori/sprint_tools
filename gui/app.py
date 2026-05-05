"""Main entry point for the Sprint Report desktop app."""

from __future__ import annotations

import io
import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

# When running as a frozen exe or as ``python -m gui.app``, make sure the
# parent directory is importable so we can use the existing CLI modules.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))


class _NullWriter(io.IOBase):
    """Drop-in replacement for sys.stdout/stderr when they're None.

    PyInstaller ``--noconsole`` builds set both to None on Windows, so any
    ``print()`` in worker threads would crash with AttributeError.
    """

    def writable(self):
        return True

    def write(self, s):
        return len(s) if isinstance(s, str) else 0

    def flush(self):
        pass


# This MUST happen before any threads start or any logging is configured.
if sys.stdout is None:
    sys.stdout = _NullWriter()
if sys.stderr is None:
    sys.stderr = _NullWriter()


from PySide6.QtCore import Qt, qInstallMessageHandler, QtMsgType
from PySide6.QtWidgets import QApplication, QMessageBox

from gui import APP_NAME, APP_ORG
from gui.main_window import MainWindow
from gui.settings import app_data_dir


def _setup_logging() -> Path:
    """Write a session log under %APPDATA%\\SprintReport\\logs\\."""
    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"sprintreport_{datetime.now():%Y%m%d_%H%M%S}.log"

    # Enable faulthandler so native crashes (segfaults, access violations)
    # leave a stack trace in a separate file instead of disappearing silently.
    try:
        import faulthandler
        crash_path = log_dir / f"crash_{datetime.now():%Y%m%d_%H%M%S}.log"
        crash_file = open(crash_path, "w", encoding="utf-8")
        faulthandler.enable(file=crash_file, all_threads=True)
        # Keep the file alive for the whole session.
        globals()["_FAULT_FILE"] = crash_file
    except Exception:
        pass

    handlers: list[logging.Handler] = [logging.FileHandler(log_path, encoding="utf-8")]
    # Only add a stream handler if stderr is a real terminal/file.
    if not isinstance(sys.stderr, _NullWriter):
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.info("Sprint Report starting (log file: %s)", log_path)
    logging.info("Frozen=%s, executable=%s, cwd=%s", getattr(sys, "frozen", False), sys.executable, os.getcwd())
    return log_path


def _qt_message_handler(mode, context, message):
    """Forward Qt's internal warnings/errors to our log so they don't disappear."""
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    logging.getLogger("Qt").log(levels.get(mode, logging.INFO), message)


def _make_exception_hook(log_path: Path):
    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("Unhandled exception:\n%s", text)
        try:
            QMessageBox.critical(
                None, "Unexpected Error",
                f"An unhandled error occurred:\n\n{exc_value}\n\n"
                f"Details have been written to:\n{log_path}\n\n{text}",
            )
        except Exception:
            pass
    return hook


def _thread_exception_hook(args):
    """Catch exceptions in non-main threads (Python 3.8+)."""
    text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    logging.error("Unhandled exception in thread %s:\n%s", args.thread.name, text)


def _warm_up_ssl():
    """Force certifi/SSL initialization on the main thread.

    On Windows, ``requests``/``ssl`` lazy-initialise CA bundles on first use.
    Doing this in a worker thread can race with Python's GIL handling and
    crash silently. Touching it on the main thread avoids the race.
    """
    try:
        import ssl
        ssl.create_default_context()
        import certifi  # noqa: F401  - just ensure import succeeds
        logging.info("SSL/certifi initialised on main thread")
    except Exception:
        logging.exception("SSL/certifi warm-up failed (non-fatal)")


def main() -> int:
    log_path = _setup_logging()
    sys.excepthook = _make_exception_hook(log_path)
    threading.excepthook = _thread_exception_hook
    qInstallMessageHandler(_qt_message_handler)
    _warm_up_ssl()

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setStyle("Fusion")
    logging.info("QApplication created")

    win = MainWindow()
    logging.info("MainWindow created")
    win.show()
    logging.info("MainWindow shown — entering event loop")

    rc = app.exec()
    logging.info("Event loop exited with code %d", rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

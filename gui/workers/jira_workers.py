"""QThread workers that wrap the blocking Jira / report calls."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from gui import jira_service, report_service
from config_parser import SprintConfig

log = logging.getLogger(__name__)


# ── Generic worker ────────────────────────────────────────────────────────


class _BaseWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int)

    def run(self) -> None:  # pragma: no cover - subclassed
        raise NotImplementedError


def run_worker(worker: _BaseWorker, owner) -> QThread:
    """
    Move ``worker`` to a new QThread and start it.

    Stores the thread + worker on ``owner`` (any QObject/widget) so
    they stay alive for the duration of the run.  Cleanup is deferred
    via a deleteLater that fires *after* all queued signals have been
    delivered.
    """
    thread = QThread()
    worker.setParent(None)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)

    # Store references to prevent GC while running.
    bag = getattr(owner, "_active_workers", None)
    if bag is None:
        bag = []
        owner._active_workers = bag
    pair = (worker, thread)
    bag.append(pair)

    def _cleanup():
        worker.deleteLater()
        thread.deleteLater()
        try:
            bag.remove(pair)
        except ValueError:
            pass

    # Use thread.finished -> _cleanup so deleteLater only runs after
    # the thread has stopped and pending signals have been delivered.
    thread.finished.connect(_cleanup)
    thread.start()
    return thread


# ── Concrete workers ──────────────────────────────────────────────────────


class FetchSprintsWorker(_BaseWorker):
    """List boards (matching sprint_name_hint) + sprints on the chosen board."""

    def __init__(self, creds: dict, board_id: int | None, sprint_hint: str) -> None:
        super().__init__()
        self.creds = creds
        self.board_id = board_id
        self.sprint_hint = sprint_hint

    def run(self) -> None:
        try:
            client = jira_service.make_client(self.creds)
            self.progress.emit("Looking for boards…", 0, 0)
            board_id = self.board_id
            board_obj = None
            if not board_id and self.sprint_hint:
                board_obj = jira_service.find_board_for_sprint(client, self.sprint_hint)
                if board_obj:
                    board_id = board_obj["id"]
            boards: list[dict]
            if board_obj:
                boards = [board_obj]
            else:
                boards = jira_service.list_boards(client, self.sprint_hint or "")
            sprints: list[dict] = []
            if board_id:
                self.progress.emit("Loading sprints…", 0, 0)
                sprints = jira_service.list_sprints(client, board_id)
            self.finished.emit({"boards": boards, "sprints": sprints, "board_id": board_id})
        except Exception as exc:  # noqa: BLE001 — surface any error to UI
            self.failed.emit(str(exc))


class FetchBoardsWorker(_BaseWorker):
    def __init__(self, creds: dict, query: str) -> None:
        super().__init__()
        self.creds = creds
        self.query = query

    def run(self) -> None:
        try:
            client = jira_service.make_client(self.creds)
            boards = jira_service.list_boards(client, self.query)
            self.finished.emit(boards)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class FetchSprintListWorker(_BaseWorker):
    def __init__(self, creds: dict, board_id: int) -> None:
        super().__init__()
        self.creds = creds
        self.board_id = board_id

    def run(self) -> None:
        try:
            client = jira_service.make_client(self.creds)
            sprints = jira_service.list_sprints(client, self.board_id)
            self.finished.emit(sprints)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class FetchSprintDataWorker(_BaseWorker):
    """Fetch issues + worklogs for a sprint and return the payload dict."""

    def __init__(self, creds: dict, sprint: dict) -> None:
        super().__init__()
        self.creds = creds
        self.sprint = sprint

    def run(self) -> None:
        try:
            log.info("FetchSprintDataWorker.run starting for sprint=%s",
                     self.sprint.get("name"))
            client = jira_service.make_client(self.creds)

            def cb(msg: str, cur: int, total: int) -> None:
                self.progress.emit(msg, cur, total)

            payload = jira_service.fetch_sprint_payload(client, self.sprint, progress_cb=cb)
            log.info("FetchSprintDataWorker fetched %d issues, %d worklog entries",
                     len(payload.get("issues", [])),
                     sum(len(v) for v in payload.get("worklogs", {}).values()))
            self.finished.emit(payload)
            log.info("FetchSprintDataWorker.finished signal emitted")
        except Exception as exc:
            log.exception("FetchSprintDataWorker failed")
            self.failed.emit(str(exc))


class GenerateReportWorker(_BaseWorker):
    def __init__(
        self,
        config: SprintConfig,
        payload: dict,
        output_dir: Path,
        make_report: bool,
        make_chart: bool,
    ) -> None:
        super().__init__()
        self.config = config
        self.payload = payload
        self.output_dir = output_dir
        self.make_report = make_report
        self.make_chart = make_chart

    def run(self) -> None:
        try:
            self.progress.emit("Building report…", 0, 0)
            written = report_service.generate_outputs(
                self.config,
                self.payload,
                self.output_dir,
                make_report=self.make_report,
                make_chart=self.make_chart,
            )
            self.finished.emit(written)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

"""Multi-sprint presenter pack: ordered slots for director review."""

from __future__ import annotations

from dataclasses import dataclass, field

from config_parser import SprintConfig


@dataclass
class PackSlot:
    """One board+sprint entry in a presenter pack."""

    board_id: int
    board_name: str
    sprint: dict
    payload: dict
    config: SprintConfig | None = None

    @property
    def sprint_id(self) -> int:
        try:
            return int(self.sprint.get("id") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def sprint_name(self) -> str:
        return str(self.sprint.get("name") or "")

    @property
    def label(self) -> str:
        board = (self.board_name or "").strip() or f"Board {self.board_id}"
        sprint = self.sprint_name or "Sprint"
        return f"{board} · {sprint}"

    @property
    def identity(self) -> tuple[int, int | str]:
        sid = self.sprint_id
        if sid:
            return (self.board_id, sid)
        return (self.board_id, self.sprint_name)


@dataclass
class ReportPack:
    """Ordered list of pack slots (add order = present order)."""

    slots: list[PackSlot] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.slots)

    def clear(self) -> None:
        self.slots.clear()

    def add_or_replace(self, slot: PackSlot) -> str:
        """Append slot, or replace an existing same board+sprint. Returns 'added' | 'replaced'."""
        key = slot.identity
        for i, existing in enumerate(self.slots):
            if existing.identity == key:
                # Keep prior config if the new fetch didn't bring one.
                if slot.config is None and existing.config is not None:
                    slot.config = existing.config
                self.slots[i] = slot
                return "replaced"
        self.slots.append(slot)
        return "added"

    def remove_at(self, index: int) -> None:
        if 0 <= index < len(self.slots):
            del self.slots[index]

    def labels(self) -> list[str]:
        return [s.label for s in self.slots]

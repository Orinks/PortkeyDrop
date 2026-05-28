"""Shared sound event metadata for Portkey Drop."""

from __future__ import annotations

from collections.abc import Collection
from itertools import chain

DEFAULT_MUTED_SOUND_EVENTS: tuple[str, ...] = ()

SOUND_EVENT_SECTIONS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Transfers",
        "File transfer queue and result sounds.",
        (
            ("transfer_queued", "Transfer queued"),
            ("transfer_started", "Transfer started"),
            ("transfer_complete", "Transfer complete"),
            ("transfer_failed", "Transfer failed"),
            ("transfer_cancelled", "Transfer cancelled"),
        ),
    ),
    (
        "Connections",
        "Server connection lifecycle sounds.",
        (
            ("connect_success", "Connected"),
            ("connect_failed", "Connection failed"),
            ("disconnect", "Disconnected"),
        ),
    ),
    (
        "File operations",
        "Remote and local file operation result sounds.",
        (
            ("delete_complete", "Delete complete"),
            ("delete_failed", "Delete failed"),
            ("rename_complete", "Rename complete"),
            ("rename_failed", "Rename failed"),
            ("folder_created", "Folder created"),
            ("folder_create_failed", "Folder creation failed"),
        ),
    ),
    (
        "General",
        "General application feedback sounds.",
        (
            ("success", "General success"),
            ("error", "General error"),
            ("notify", "General notification"),
            ("startup", "App startup"),
            ("exit", "App exit"),
        ),
    ),
)

USER_MUTABLE_SOUND_EVENTS: tuple[tuple[str, str], ...] = tuple(
    chain.from_iterable(events for _title, _description, events in SOUND_EVENT_SECTIONS)
)

USER_MUTABLE_SOUND_EVENT_KEYS: frozenset[str] = frozenset(
    event_key for event_key, _label in USER_MUTABLE_SOUND_EVENTS
)

FRIENDLY_SOUND_EVENT_CHOICES: tuple[tuple[str, str], ...] = tuple(
    (label, event_key) for event_key, label in USER_MUTABLE_SOUND_EVENTS
)


def normalize_muted_sound_events(events: Collection[str] | None) -> list[str]:
    """Normalize muted event names while preserving order."""
    if not events:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in events:
        event = str(item).strip()
        if not event or event in seen:
            continue
        seen.add(event)
        normalized.append(event)
    return normalized


def normalize_known_muted_sound_events(events: Collection[str] | None) -> list[str]:
    """Normalize muted events and drop unknown keys from the shared catalog."""
    return [
        event
        for event in normalize_muted_sound_events(events)
        if event in USER_MUTABLE_SOUND_EVENT_KEYS
    ]

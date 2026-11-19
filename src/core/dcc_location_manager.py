"""Combine discovered DCC paths and user-registered locations.

This service contains no Qt code. The UI asks it for a snapshot, then asks it
explicitly to register or remove a location. Discovery never writes settings by
itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.dcc_discovery import DccLocationDiscovery, DiscoveryCandidate
from core.settings_store import (
    CustomLocation,
    DuplicateLocationError,
    SettingsStore,
    normalize_path_for_comparison,
)


@dataclass(frozen=True, slots=True)
class ManagedCandidate:
    """One discovery result decorated with its current registration state."""

    candidate: DiscoveryCandidate
    registration_status: str
    existing_location: CustomLocation | None = None

    @property
    def can_register(self) -> bool:
        return (
            self.candidate.registerable
            and bool(self.candidate.path)
            and self.candidate.category in {"cache", "backup"}
            and self.registration_status == "登録可能"
        )


@dataclass(frozen=True, slots=True)
class LocationManagerSnapshot:
    """A consistent view of discovery results and persisted user rules."""

    candidates: tuple[ManagedCandidate, ...]
    registered_locations: tuple[CustomLocation, ...]


class DccLocationManager:
    """Coordinate discovery and persistent registration without doing cleanup."""

    def __init__(
        self,
        store: SettingsStore | None = None,
        discovery: DccLocationDiscovery | None = None,
    ) -> None:
        self._store = store or SettingsStore()
        self._discovery = discovery or DccLocationDiscovery()

    @property
    def store(self) -> SettingsStore:
        return self._store

    def get_snapshot(self) -> LocationManagerSnapshot:
        """Read settings and discovery results, then mark duplicate/conflicting paths."""
        settings = self._store.load()
        registered = settings.custom_locations
        registered_by_path = {
            normalize_path_for_comparison(location.path): location
            for location in registered
        }

        managed: list[ManagedCandidate] = []
        for candidate in self._discovery.discover():
            if (
                not candidate.registerable
                or not candidate.path
                or candidate.category not in {"cache", "backup"}
            ):
                managed.append(ManagedCandidate(candidate, "登録不可"))
                continue

            try:
                path_key = normalize_path_for_comparison(candidate.path)
            except ValueError:
                managed.append(ManagedCandidate(candidate, "登録不可"))
                continue

            existing = registered_by_path.get(path_key)
            if existing is None:
                status = "登録可能"
            elif (
                existing.application == candidate.application
                and existing.category == candidate.category
            ):
                status = "登録済み"
            else:
                status = "別の分類で登録済み"
            managed.append(ManagedCandidate(candidate, status, existing))

        return LocationManagerSnapshot(
            candidates=tuple(managed),
            registered_locations=registered,
        )

    def register_discovered(self, managed_candidate: ManagedCandidate) -> CustomLocation:
        """Persist one explicitly selected discovery candidate with provenance."""
        if not managed_candidate.can_register:
            raise ValueError("この検出結果は登録できないか、すでに登録されています。")

        candidate = managed_candidate.candidate
        # The UI must not convert a hint (for example an AE preferences folder)
        # into a cleanup path. Only candidates with a confirmed category qualify.
        if not candidate.path or candidate.category not in {"cache", "backup"}:
            raise ValueError("保存先の種類またはパスが確定していません。")

        return self._store.add_custom_location(
            application=candidate.application,
            category=candidate.category,
            path=candidate.path,
            origin="discovered",
            source=candidate.source,
        )

    def register_manual(
        self, *, application: str, category: str, path: str
    ) -> CustomLocation:
        """Persist a user-entered path, recording it as a manual registration."""
        return self._store.add_custom_location(
            application=application,
            category=category,
            path=path,
            origin="manual",
            source="手動登録",
        )

    def remove_registered(self, location_id: str) -> bool:
        """Remove only the rule from settings; never touches the actual folder."""
        return self._store.remove_custom_location(location_id)

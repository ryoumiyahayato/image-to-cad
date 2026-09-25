"""Reusable, model-independent human review session persistence.

The review session deliberately knows only about review items, their paired
images, the allowed human vocabulary, and mutable review state.  It does not
contain candidate-mining, model, or production-Draftsman logic so that the
same state contract can later be used by another UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4


ALLOWED_HUMAN_LABELS: tuple[str, ...] = (
    "STRUCTURAL_CONTINUATION",
    "ANNOTATION_OR_GLYPH",
    "AMBIGUOUS",
    "INVALID_FOR_TASK",
)
REVIEW_STATUSES: tuple[str, ...] = ("PENDING", "REVIEWED")
SESSION_SCHEMA_VERSION = 1


class ReviewSessionError(ValueError):
    """Raised when review-session input or persisted state is invalid."""


class ReviewStateMismatchError(ReviewSessionError):
    """Raised when saved state belongs to a different frozen item set."""


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewSessionError(f"could not read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReviewSessionError(f"JSON root must be an object: {path}")
    return value


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    """Write JSON without exposing a partially written mutable session."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def _normalise_relative_asset_path(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewSessionError(f"{field_name} must be a non-empty path")
    normalised = value.replace("\\", "/")
    if normalised.startswith("/") or ":" in normalised.split("/", 1)[0]:
        raise ReviewSessionError(f"{field_name} must be relative: {value!r}")
    parts = [part for part in normalised.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ReviewSessionError(f"{field_name} escapes the asset root: {value!r}")
    return "/".join(parts)


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


@dataclass(frozen=True)
class ReviewItem:
    """A single review item in deterministic presentation order."""

    item_id: str
    review_index: int
    local_image_path: str
    context_image_path: str
    optional_neutral_overlay_path: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id.strip():
            raise ReviewSessionError("review item ID must be a non-empty string")
        if not isinstance(self.review_index, int) or self.review_index < 1:
            raise ReviewSessionError("review index must be a positive integer")
        object.__setattr__(
            self,
            "local_image_path",
            _normalise_relative_asset_path(
                self.local_image_path, field_name="local_image_path"
            ),
        )
        object.__setattr__(
            self,
            "context_image_path",
            _normalise_relative_asset_path(
                self.context_image_path, field_name="context_image_path"
            ),
        )
        if self.optional_neutral_overlay_path is not None:
            object.__setattr__(
                self,
                "optional_neutral_overlay_path",
                _normalise_relative_asset_path(
                    self.optional_neutral_overlay_path,
                    field_name="optional_neutral_overlay_path",
                ),
            )

    def asset_paths(self) -> tuple[str, ...]:
        paths = [self.local_image_path, self.context_image_path]
        if self.optional_neutral_overlay_path:
            paths.append(self.optional_neutral_overlay_path)
        return tuple(paths)


@dataclass(frozen=True)
class ReviewManifest:
    """Validated manifest/order pair used to construct a session."""

    items: tuple[ReviewItem, ...]
    manifest_sha256: str
    ordering_method: str
    manifest_name: str
    order_name: str


def _validate_allowed_labels(value: Any) -> None:
    if tuple(value or ()) != ALLOWED_HUMAN_LABELS:
        raise ReviewSessionError(
            "manifest allowed labels do not match the frozen review vocabulary"
        )


def load_review_manifest(manifest_path: Path, order_path: Path) -> ReviewManifest:
    """Load and validate an ordered review manifest without mutating it."""

    manifest_path = Path(manifest_path)
    order_path = Path(order_path)
    manifest = _read_json(manifest_path)
    order = _read_json(order_path)
    _validate_allowed_labels(manifest.get("allowed_future_human_labels"))

    raw_entries = manifest.get("entries")
    raw_order = order.get("order")
    if not isinstance(raw_entries, list) or not isinstance(raw_order, list):
        raise ReviewSessionError("manifest entries and order must be arrays")

    entries: dict[str, Mapping[str, Any]] = {}
    for entry in raw_entries:
        if not isinstance(entry, Mapping):
            raise ReviewSessionError("manifest entries must be objects")
        item_id = entry.get("candidate_id")
        if not isinstance(item_id, str) or not item_id:
            raise ReviewSessionError("manifest entry is missing candidate_id")
        if item_id in entries:
            raise ReviewSessionError(f"duplicate candidate_id: {item_id}")
        entries[item_id] = entry

    items: list[ReviewItem] = []
    seen_order_ids: set[str] = set()
    for position, order_entry in enumerate(raw_order, start=1):
        if not isinstance(order_entry, Mapping):
            raise ReviewSessionError("review order entries must be objects")
        item_id = order_entry.get("candidate_id")
        if not isinstance(item_id, str) or not item_id:
            raise ReviewSessionError("review order entry is missing candidate_id")
        if item_id in seen_order_ids:
            raise ReviewSessionError(f"duplicate review order candidate_id: {item_id}")
        seen_order_ids.add(item_id)
        entry = entries.get(item_id)
        if entry is None:
            raise ReviewSessionError(f"review order references unknown item: {item_id}")

        review_index = order_entry.get("review_index", entry.get("review_index"))
        if review_index != entry.get("review_index"):
            raise ReviewSessionError(f"review index mismatch for {item_id}")
        if review_index != position:
            raise ReviewSessionError(
                f"review order is not contiguous at {item_id}: {review_index}"
            )
        items.append(
            ReviewItem(
                item_id=item_id,
                review_index=review_index,
                local_image_path=entry.get("local_crop_path"),
                context_image_path=entry.get("context_crop_path"),
                optional_neutral_overlay_path=entry.get(
                    "optional_neutral_overlay_path"
                ),
            )
        )

    if len(items) != len(entries):
        missing = sorted(set(entries) - seen_order_ids)
        raise ReviewSessionError(f"manifest items missing from review order: {missing}")
    if not items:
        raise ReviewSessionError("review manifest must contain at least one item")

    ordering_method = order.get("ordering_method")
    if not isinstance(ordering_method, str) or not ordering_method:
        raise ReviewSessionError("review order is missing ordering_method")

    return ReviewManifest(
        items=tuple(items),
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        ordering_method=ordering_method,
        manifest_name=manifest_path.name,
        order_name=order_path.name,
    )


def verify_review_assets(items: Iterable[ReviewItem], repo_root: Path) -> tuple[Path, ...]:
    """Verify all declared assets exist under the local repository root."""

    root = Path(repo_root).resolve()
    resolved: list[Path] = []
    for item in items:
        for relative_path in item.asset_paths():
            asset_path = (root / Path(*relative_path.split("/"))).resolve()
            try:
                asset_path.relative_to(root)
            except ValueError as exc:
                raise ReviewSessionError(
                    f"review asset escapes repository root: {relative_path}"
                ) from exc
            if not asset_path.is_file():
                raise FileNotFoundError(asset_path)
            resolved.append(asset_path)
    return tuple(resolved)


def _new_item_state() -> dict[str, Any]:
    return {
        "human_label": None,
        "reviewer_note": None,
        "review_status": "PENDING",
        "updated_at": None,
        "label_history": [],
    }


class ReviewSession:
    """Mutable local review state with strict vocabulary and identity checks."""

    def __init__(
        self,
        *,
        items: Sequence[ReviewItem],
        state_path: Path,
        manifest_sha256: str,
        ordering_method: str,
        manifest_name: str = "",
        order_name: str = "",
        export_path: Path | None = None,
    ) -> None:
        self.items = tuple(items)
        if not self.items:
            raise ReviewSessionError("review session requires at least one item")
        ids = [item.item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ReviewSessionError("review item IDs must be unique")
        indexes = [item.review_index for item in self.items]
        if indexes != list(range(1, len(self.items) + 1)):
            raise ReviewSessionError("review indexes must be contiguous and ordered")
        self._items_by_id = {item.item_id: item for item in self.items}
        self.state_path = Path(state_path)
        self.export_path = Path(export_path) if export_path is not None else None
        self.manifest_sha256 = manifest_sha256
        self.ordering_method = ordering_method
        self.manifest_name = manifest_name
        self.order_name = order_name
        self._state = self._new_session_state()
        if self.state_path.exists():
            self._load_state()
        else:
            self._persist()

    def _new_session_state(self) -> dict[str, Any]:
        now = _utc_now()
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": str(uuid4()),
            "manifest_sha256": self.manifest_sha256,
            "manifest_name": self.manifest_name,
            "order_name": self.order_name,
            "ordering_method": self.ordering_method,
            "review_order": [item.item_id for item in self.items],
            "created_at": now,
            "updated_at": now,
            "items": {item.item_id: _new_item_state() for item in self.items},
        }

    def _load_state(self) -> None:
        saved = _read_json(self.state_path)
        expected_order = [item.item_id for item in self.items]
        if saved.get("schema_version") != SESSION_SCHEMA_VERSION:
            raise ReviewStateMismatchError("saved review state schema is unsupported")
        if saved.get("manifest_sha256") != self.manifest_sha256:
            raise ReviewStateMismatchError("saved state belongs to another manifest")
        if saved.get("review_order") != expected_order:
            raise ReviewStateMismatchError("saved state review order does not match")
        saved_items = saved.get("items")
        if not isinstance(saved_items, Mapping) or set(saved_items) != set(expected_order):
            raise ReviewStateMismatchError("saved state item identity does not match")
        session_id = saved.get("session_id")
        created_at = saved.get("created_at")
        updated_at = saved.get("updated_at")
        if not all(isinstance(value, str) and value for value in (session_id, created_at, updated_at)):
            raise ReviewStateMismatchError("saved state is missing session timestamps")

        validated_items: dict[str, dict[str, Any]] = {}
        for item_id in expected_order:
            raw_item = saved_items[item_id]
            if not isinstance(raw_item, Mapping):
                raise ReviewStateMismatchError(f"saved state item is invalid: {item_id}")
            label = raw_item.get("human_label")
            if label is not None and label not in ALLOWED_HUMAN_LABELS:
                raise ReviewStateMismatchError(f"saved state label is invalid: {item_id}")
            status = raw_item.get("review_status")
            if status not in REVIEW_STATUSES:
                raise ReviewStateMismatchError(f"saved state status is invalid: {item_id}")
            if (label is None) != (status == "PENDING"):
                raise ReviewStateMismatchError(
                    f"saved state label/status disagree: {item_id}"
                )
            note = raw_item.get("reviewer_note")
            if note is not None and not isinstance(note, str):
                raise ReviewStateMismatchError(f"saved state note is invalid: {item_id}")
            history = raw_item.get("label_history", [])
            if not isinstance(history, list):
                raise ReviewStateMismatchError(f"saved state history is invalid: {item_id}")
            validated_items[item_id] = {
                "human_label": label,
                "reviewer_note": note,
                "review_status": status,
                "updated_at": raw_item.get("updated_at"),
                "label_history": _copy_json(history),
            }

        self._state = {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": session_id,
            "manifest_sha256": self.manifest_sha256,
            "manifest_name": saved.get("manifest_name", self.manifest_name),
            "order_name": saved.get("order_name", self.order_name),
            "ordering_method": self.ordering_method,
            "review_order": expected_order,
            "created_at": created_at,
            "updated_at": updated_at,
            "items": validated_items,
        }

    def _persist(self) -> None:
        _atomic_write_json(self.state_path, self._state)

    def _require_item(self, item_id: str) -> ReviewItem:
        try:
            return self._items_by_id[item_id]
        except KeyError as exc:
            raise ReviewSessionError(f"unknown review item: {item_id}") from exc

    def item_state(self, item_id: str) -> dict[str, Any]:
        self._require_item(item_id)
        return _copy_json(self._state["items"][item_id])

    def set_label(self, item_id: str, label: str) -> dict[str, Any]:
        """Persist one human-selected label and its small change history."""

        self._require_item(item_id)
        if label not in ALLOWED_HUMAN_LABELS:
            raise ReviewSessionError(f"label is not allowed: {label!r}")
        item_state = self._state["items"][item_id]
        old_label = item_state["human_label"]
        now = _utc_now()
        if old_label != label:
            item_state["label_history"].append(
                {"timestamp": now, "old_label": old_label, "new_label": label}
            )
        item_state["human_label"] = label
        item_state["review_status"] = "REVIEWED"
        item_state["updated_at"] = now
        self._state["updated_at"] = now
        self._persist()
        return self.item_state(item_id)

    def set_note(self, item_id: str, note: str | None) -> dict[str, Any]:
        """Persist a reviewer note without changing the semantic label."""

        self._require_item(item_id)
        if note is not None and not isinstance(note, str):
            raise ReviewSessionError("reviewer note must be a string or null")
        item_state = self._state["items"][item_id]
        now = _utc_now()
        item_state["reviewer_note"] = note if note else None
        item_state["updated_at"] = now
        self._state["updated_at"] = now
        self._persist()
        return self.item_state(item_id)

    def counts(self) -> dict[str, Any]:
        by_label = {
            label: sum(
                state["human_label"] == label
                for state in self._state["items"].values()
            )
            for label in ALLOWED_HUMAN_LABELS
        }
        completed = sum(
            state["review_status"] == "REVIEWED"
            for state in self._state["items"].values()
        )
        return {
            "total": len(self.items),
            "completed": completed,
            "pending": len(self.items) - completed,
            "by_label": by_label,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a UI-neutral snapshot with no model-derived fields."""

        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": self._state["session_id"],
            "ordering_method": self.ordering_method,
            "review_order": [item.item_id for item in self.items],
            "manifest_sha256": self.manifest_sha256,
            "created_at": self._state["created_at"],
            "updated_at": self._state["updated_at"],
            "items": [
                {
                    "review_index": item.review_index,
                    "item_id": item.item_id,
                    "local_image_path": item.local_image_path,
                    "context_image_path": item.context_image_path,
                    "optional_neutral_overlay_path": item.optional_neutral_overlay_path,
                    **self.item_state(item.item_id),
                }
                for item in self.items
            ],
            "counts": self.counts(),
        }

    def export_payload(self) -> dict[str, Any]:
        """Build a label-only export suitable for a later freeze/import task."""

        exported_at = _utc_now()
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": self._state["session_id"],
            "review_order": [item.item_id for item in self.items],
            "ordering_method": self.ordering_method,
            "manifest_identity": {
                "manifest_name": self.manifest_name,
                "order_name": self.order_name,
                "manifest_sha256": self.manifest_sha256,
            },
            "session_created_at": self._state["created_at"],
            "session_updated_at": self._state["updated_at"],
            "exported_at": exported_at,
            "counts": self.counts(),
            "items": [
                {
                    "review_index": item.review_index,
                    "candidate_id": item.item_id,
                    "human_label": self._state["items"][item.item_id]["human_label"],
                    "reviewer_note": self._state["items"][item.item_id]["reviewer_note"],
                    "review_status": self._state["items"][item.item_id]["review_status"],
                    "updated_at": self._state["items"][item.item_id]["updated_at"],
                    "label_history": _copy_json(
                        self._state["items"][item.item_id]["label_history"]
                    ),
                }
                for item in self.items
            ],
        }

    def export(self, path: Path | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self.export_path
        if target is None:
            raise ReviewSessionError("no export path was configured")
        payload = self.export_payload()
        _atomic_write_json(target, payload)
        return payload


def create_session_from_manifest(
    *,
    manifest_path: Path,
    order_path: Path,
    state_path: Path,
    repo_root: Path,
    export_path: Path | None = None,
) -> tuple[ReviewSession, ReviewManifest]:
    """Validate a manifest/order pair, its assets, then resume or create state."""

    manifest = load_review_manifest(manifest_path, order_path)
    verify_review_assets(manifest.items, repo_root)
    session = ReviewSession(
        items=manifest.items,
        state_path=state_path,
        manifest_sha256=manifest.manifest_sha256,
        ordering_method=manifest.ordering_method,
        manifest_name=manifest.manifest_name,
        order_name=manifest.order_name,
        export_path=export_path,
    )
    return session, manifest


__all__ = [
    "ALLOWED_HUMAN_LABELS",
    "REVIEW_STATUSES",
    "ReviewItem",
    "ReviewManifest",
    "ReviewSession",
    "ReviewSessionError",
    "ReviewStateMismatchError",
    "SESSION_SCHEMA_VERSION",
    "create_session_from_manifest",
    "load_review_manifest",
    "verify_review_assets",
]

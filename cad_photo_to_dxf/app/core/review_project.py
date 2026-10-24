"""Persistent review of ONE saved conversion. Not a cross-conversion matcher.

The ZIP contains the existing cache11 baseline, one aligned review frame, a
versioned manifest and an append-only journal. Source PDFs are external. Cache
integrity and source-version checking reuse the production cache mechanisms.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from uuid import UUID, uuid4
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

import cv2
import numpy as np

from app.core.cache import TRACE_CACHE_VERSION, load_trace_cache, save_trace_cache
from app.core.processing import ProcessingCacheKey, file_content_sha256
from app.core.scale_calibrator import ScaleCalibration
from app.core.structure import FINAL_STRUCTURE_SCHEMA_VERSION, metadata_to_jsonable
from app.geometry.raster_trace import RasterTraceResult
from app.export.review_text import (
    REVIEW_EXPORT_VERSION,
    ReviewLayoutGuard,
    fixed_text_placement,
    source_anchored_text_placement,
)

PROJECT_FORMAT = "review-project-format-v1"
SOURCE_LAYOUT_PROJECT_FORMAT = "review-project-format-v2"
_SNAPSHOT_KEY = "review_snapshot_v1"
_ENTRIES = {"project.json", "snapshot.npz", "corrections.json", "review-frame.png"}


class ReviewProjectError(ValueError):
    pass


def _json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )


def _uuid(value):
    try:
        if str(UUID(str(value))) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ReviewProjectError("REJECTED_IDENTITY_MISMATCH: invalid UUID") from None


def _candidate_fact(candidate):
    fact = asdict(candidate)
    if fact.get("display_quad") is None:
        fact.pop("display_quad", None)
    return json.loads(_json(fact))


def _native_fact(candidate, height):
    from app.export.ocr_outline_export import native_text_placement

    try:
        placement = native_text_placement(
            candidate, transform=lambda x, y: (float(x), height - float(y))
        )
    except RuntimeError as exc:
        raise ReviewProjectError(
            "NEEDS_LAYOUT_REVIEW: original packaged font metrics unavailable"
        ) from exc
    return json.loads(_json(asdict(placement))) if placement else None


def _trace_result(structure):
    return RasterTraceResult(
        binary=structure.contour_binary,
        stages={},
        paths=structure.contours,
        threshold=structure.threshold,
        foreground_pixels=int(np.count_nonzero(structure.contour_binary == 0)),
        vertex_count=sum(len(p.points) for p in structure.contours),
        warnings=structure.warnings,
        texts=structure.texts,
        signatures=structure.signatures,
        logos=structure.logos,
        straight_lines=structure.straight_lines,
        arcs=structure.arcs,
        preview_binary=structure.preview_binary,
        final_structure=structure,
    )


@dataclass(frozen=True)
class ConfirmationEvent:
    """GUI creates this only on an explicit confirm/withdraw button action.

    Tests must pass TEST_ONLY; there is no inferred human/source verification.
    """

    kind: str
    event_uuid: str
    at: str

    @classmethod
    def create(cls, *, test_only: bool):
        return cls(
            "TEST_ONLY" if test_only else "GUI_EXPLICIT_CONFIRM",
            str(uuid4()),
            datetime.now(timezone.utc).isoformat(),
        )


class ValidatedTextReview:
    """Ephemeral consumer bound to the exact immutable baseline instance."""

    def __init__(self, project, active):
        self._project = project
        self._structure = project.baseline
        self._active = active
        self._records = project.records
        self._by_candidate = {
            id(project.baseline.texts[b["index"]]): (
                b,
                active.get(b["text_source_uuid"]),
            )
            for b in project._manifest["text_bindings"]
        }

    def validate_structure(self, structure):
        if structure is not self._structure:
            raise ReviewProjectError(
                "NEEDS_RECONFIRM: corrections belong to another conversion snapshot"
            )
        self._project.validate_source()
        self._project._validate_baseline()
        self.validate_current()

    def validate_current(self):
        if (
            self._project.baseline is not self._structure
            or self._project.records != self._records
        ):
            raise ReviewProjectError("NEEDS_RECONFIRM: review changed during export")

    def export_expectation(self, candidate, *, transform):
        """Read expected content from the journal and immutable source binding."""
        self.validate_current()
        binding, record = self._by_candidate[id(candidate)]
        if binding["original_candidate"] != _candidate_fact(candidate):
            raise ReviewProjectError(
                "REJECTED_IDENTITY_MISMATCH: export candidate changed"
            )
        applied = bool(record and record["consumption"] == "APPLIED")
        values = [
            1,
            REVIEW_EXPORT_VERSION,
            self._project.snapshot_uuid,
            binding["text_source_uuid"],
            record["status"] if applied else "OCR_UNVERIFIED",
            record["correction_uuid"] if record else "",
            record["revision"] if record else 0,
            record["confirmation"]["kind"] if record else "NONE",
            record["consumption"] if record else "ORIGINAL",
            "original_ocr_text",
        ]
        original = binding["original_candidate"]["text"]
        values.extend(
            original[start : start + 50] for start in range(0, len(original), 50)
        )
        # This consumer already owns the replayed effective record. Replaying
        # the complete journal twice per candidate repeats source evidence work.
        # validate_current above still rejects any journal change during export.
        from app.export.ocr_outline_export import _normalised_content

        return dict(
            text=record["new_text"] if applied else _normalised_content(original),
            review_values=values,
            placement=self.placement(candidate, transform=transform, doc=None),
            reviewed=1
            if applied and record["confirmation"]["kind"] != "TEST_ONLY"
            else int(candidate.reviewed),
        )

    def validate_output(self, path):
        target = Path(path).resolve()
        if (
            target.suffix.lower() != ".dxf"
            or target == self._project.path
            or target == Path(self._project._manifest["source"]["path"]).resolve()
            or target == self._project._cache_path
        ):
            raise ReviewProjectError(
                "DXF output must not overwrite the project or its source"
            )

    def placement(self, candidate, *, transform, doc):
        from app.export.ocr_outline_export import native_text_placement

        binding, record = self._by_candidate[id(candidate)]
        if record and record["consumption"] == "APPLIED":
            if record.get("action") == "CONFIRM_SOURCE_LAYOUT":
                return source_anchored_text_placement(
                    candidate,
                    record["new_text"],
                    record["layout_check"]["source_quad"],
                    transform=transform,
                    doc=doc,
                )
            return fixed_text_placement(
                candidate, record["new_text"], transform=transform, doc=doc
            )
        return native_text_placement(candidate, transform=transform, doc=doc)

    def annotate(self, entity, candidate):
        binding, record = self._by_candidate[id(candidate)]
        if "TEXT_REVIEW" not in entity.doc.appids:
            entity.doc.appids.add("TEXT_REVIEW")
        applied = bool(record and record["consumption"] == "APPLIED")
        values = [
            (1070, 1),
            (1000, REVIEW_EXPORT_VERSION),
            (1000, self._project.snapshot_uuid),
            (1000, binding["text_source_uuid"]),
            (1000, record["status"] if applied else "OCR_UNVERIFIED"),
            (1000, record["correction_uuid"] if record else ""),
            (1071, record["revision"] if record else 0),
            (1000, record["confirmation"]["kind"] if record else "NONE"),
            (1000, record["consumption"] if record else "ORIGINAL"),
            (1000, "original_ocr_text"),
        ]
        # XDATA strings are limited by bytes, not Python character count.
        for start in range(0, len(candidate.text), 50):
            values.append((1000, candidate.text[start : start + 50]))
        entity.set_xdata("TEXT_REVIEW", values)
        suggestion = self._project.suggestion(binding["text_source_uuid"])
        if suggestion:
            if "PDF_TEXT_SUGGESTION" not in entity.doc.appids:
                entity.doc.appids.add("PDF_TEXT_SUGGESTION")
            entity.set_xdata(
                "PDF_TEXT_SUGGESTION",
                [
                    (1070, 1),
                    (1000, suggestion["suggestion_uuid"]),
                    (1000, self._project.snapshot_uuid),
                    (1000, binding["text_source_uuid"]),
                    (1000, "UNVERIFIED_PDF_MAPPING"),
                    (1000, "suggested_text"),
                    *[
                        (1000, suggestion["evidence"]["text"][i : i + 50])
                        for i in range(0, len(suggestion["evidence"]["text"]), 50)
                    ],
                ],
            )
        if applied and record.get("action") == "CONFIRM_SOURCE_LAYOUT":
            if "TEXT_SOURCE_LAYOUT" not in entity.doc.appids:
                entity.doc.appids.add("TEXT_SOURCE_LAYOUT")
            entity.set_xdata(
                "TEXT_SOURCE_LAYOUT",
                [
                    (1070, 1),
                    (1000, record["layout_check"]["layout_version"]),
                    (1000, record["suggestion_uuid"]),
                    (1000, record["correction_uuid"]),
                    (1071, record["revision"]),
                    (1000, "EXPLICIT_CONTENT_AND_LAYOUT"),
                    (1000, record["confirmation"]["kind"]),
                    *[
                        (1040, float(v))
                        for point in record["layout_check"]["source_quad"]
                        for v in point
                    ],
                ],
            )
        if applied and record["confirmation"]["kind"] != "TEST_ONLY":
            tags = list(entity.get_xdata("OCR_TEXT_LINE"))
            tags[3] = (1070, 1)
            entity.set_xdata("OCR_TEXT_LINE", tags)


class ReviewProject:
    def __init__(self, baseline, manifest, frame, *, tempdir, cache_path, records=()):
        self.baseline = baseline
        self._manifest = deepcopy(manifest)
        self.frame = np.ascontiguousarray(frame).copy()
        self.frame.setflags(write=False)
        self._tempdir = tempdir
        self._cache_path = Path(cache_path)
        self._records = list(deepcopy(records))
        self._bindings = {
            b["text_source_uuid"]: b for b in self._manifest["text_bindings"]
        }
        self._suggestions = {
            s["text_source_uuid"]: s
            for s in self._manifest.get("native_suggestions", ())
        }
        self._guard = None
        self.path = None
        self.dirty = False
        self._validate_baseline()
        self._replay()

    @property
    def snapshot_uuid(self):
        return self._manifest["snapshot_uuid"]

    @property
    def manifest(self):
        return deepcopy(self._manifest)

    @property
    def records(self):
        return deepcopy(self._records)

    @property
    def bindings(self):
        return deepcopy(self._manifest["text_bindings"])

    @property
    def calibration(self):
        value = self._manifest["export_settings"]["calibration"]
        return ScaleCalibration(**value) if value else None

    @classmethod
    def create(
        cls,
        structure,
        *,
        source_path,
        cache_key,
        frame=None,
        calibration=None,
        drawing_multiplier=1.0,
        origin="completed-conversion",
    ):
        if structure.provenance.get("gui_text_reviewed"):
            raise ReviewProjectError(
                "NEEDS_RECONFIRM: legacy edited cache does not preserve original OCR"
            )
        if _SNAPSHOT_KEY in structure.provenance:
            raise ReviewProjectError(
                "Open the saved review project instead of assigning another identity"
            )
        if len({id(c) for c in structure.texts}) != len(structure.texts):
            raise ReviewProjectError(
                "Aliased candidate instances cannot receive independent snapshot identities"
            )
        key = ProcessingCacheKey.from_payload(cache_key)
        source_path = Path(source_path).resolve()
        if not source_path.is_file():
            raise ReviewProjectError("Source document is missing")
        if file_content_sha256(source_path) != key.input_content_sha256:
            raise ReviewProjectError(
                "REJECTED_IDENTITY_MISMATCH: source document version"
            )
        if key.final_structure_schema_version != FINAL_STRUCTURE_SCHEMA_VERSION:
            raise ReviewProjectError("Incompatible source cache schema")
        if not np.isfinite(drawing_multiplier) or drawing_multiplier <= 0:
            raise ReviewProjectError("Invalid export scale")
        if calibration:
            _ = calibration.mm_per_pixel
        manifest = {
            "format": PROJECT_FORMAT,
            "snapshot_uuid": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "origin": origin,
            "source": {
                "document_uuid": str(uuid4()),
                "path": str(source_path),
                "physical_page": key.page_number,
                "cache_identity": key.payload(),
            },
            "structure_id": structure.structure_id,
            "final_structure_schema": FINAL_STRUCTURE_SCHEMA_VERSION,
            "trace_cache": TRACE_CACHE_VERSION,
            "export_version": REVIEW_EXPORT_VERSION,
            "export_settings": {
                "calibration": asdict(calibration) if calibration else None,
                "drawing_multiplier": float(drawing_multiplier),
            },
            "text_bindings": [
                {
                    "text_source_uuid": str(uuid4()),
                    "index": index,
                    "physical_page": key.page_number,
                    "original_candidate": _candidate_fact(candidate),
                    "original_native_placement": _native_fact(
                        candidate, structure.source_size_px[1]
                    ),
                }
                for index, candidate in enumerate(structure.texts)
            ],
        }
        manifest = json.loads(_json(manifest))
        from app.core.native_text_review import bind_native_suggestions

        suggestions = bind_native_suggestions(structure, manifest)
        if suggestions:
            manifest["format"] = SOURCE_LAYOUT_PROJECT_FORMAT
            manifest["native_suggestions"] = suggestions
        # Duplicate the immutable manifest inside the baseline cache so changing
        # a locator/page/config in the JSON alone cannot rebind a saved project.
        baseline = replace(
            structure, provenance={**structure.provenance, _SNAPSHOT_KEY: manifest}
        )
        if frame is None:
            frame = (
                structure.preview_binary
                if structure.preview_binary is not None
                else structure.contour_binary
            )
        if (frame.shape[1], frame.shape[0]) != structure.source_size_px:
            raise ReviewProjectError("Review frame does not match source coordinates")
        temporary = TemporaryDirectory(prefix="image-to-cad-review-")
        try:
            cache_path = Path(temporary.name) / "snapshot.npz"
            save_trace_cache(
                cache_path, _trace_result(baseline), cache_key=key.payload()
            )
            return cls(
                baseline, manifest, frame, tempdir=temporary, cache_path=cache_path
            )
        except BaseException:
            temporary.cleanup()
            raise

    def _validate_baseline(self):
        m = self._manifest
        if (
            m.get("format") not in {PROJECT_FORMAT, SOURCE_LAYOUT_PROJECT_FORMAT}
            or m.get("final_structure_schema") != 4
            or m.get("trace_cache") != 11
            or m.get("export_version") != REVIEW_EXPORT_VERSION
        ):
            raise ReviewProjectError(
                "Incompatible review project format/export version"
            )
        _uuid(m["snapshot_uuid"])
        _uuid(m["source"]["document_uuid"])
        if metadata_to_jsonable(self.baseline.provenance.get(_SNAPSHOT_KEY)) != m:
            raise ReviewProjectError(
                "REJECTED_IDENTITY_MISMATCH: immutable snapshot manifest"
            )
        if self.baseline.structure_id != m["structure_id"]:
            raise ReviewProjectError("REJECTED_IDENTITY_MISMATCH: snapshot payload")
        key = ProcessingCacheKey.from_payload(m["source"]["cache_identity"])
        if key.page_number != m["source"]["physical_page"]:
            raise ReviewProjectError("REJECTED_IDENTITY_MISMATCH: physical page")
        bindings = m["text_bindings"]
        if (
            len(bindings) != len(self.baseline.texts)
            or len(self._bindings) != len(bindings)
            or sorted(b["index"] for b in bindings) != list(range(len(bindings)))
        ):
            raise ReviewProjectError("REJECTED_IDENTITY_MISMATCH: TEXT identity map")
        for binding in bindings:
            _uuid(binding["text_source_uuid"])
            if binding["physical_page"] != key.page_number or binding[
                "original_candidate"
            ] != _candidate_fact(self.baseline.texts[binding["index"]]):
                raise ReviewProjectError(
                    "REJECTED_IDENTITY_MISMATCH: original OCR/geometry/source ownership"
                )
            if binding.get("original_native_placement") != _native_fact(
                self.baseline.texts[binding["index"]], self.baseline.source_size_px[1]
            ):
                raise ReviewProjectError(
                    "NEEDS_LAYOUT_REVIEW: original native placement/font metrics changed or missing"
                )
        if (self.frame.shape[1], self.frame.shape[0]) != self.baseline.source_size_px:
            raise ReviewProjectError("Review frame dimensions are invalid")
        if self.frame.dtype != np.uint8 or self.frame.ndim not in (2, 3):
            raise ReviewProjectError("Review frame must be a lossless uint8 image")
        multiplier = self._manifest["export_settings"]["drawing_multiplier"]
        if (
            isinstance(multiplier, bool)
            or not np.isfinite(multiplier)
            or multiplier <= 0
        ):
            raise ReviewProjectError("Invalid snapshot export scale")
        if self.calibration is not None:
            _ = self.calibration.mm_per_pixel
        if m.get("format") == SOURCE_LAYOUT_PROJECT_FORMAT:
            from app.core.native_text_review import bind_native_suggestions

            expected = bind_native_suggestions(self.baseline, m)
            saved = m.get("native_suggestions", [])
            if (
                len(saved) != len(expected)
                or not saved
                or len({s.get("suggestion_uuid") for s in saved}) != len(saved)
            ):
                raise ReviewProjectError(
                    "REJECTED_IDENTITY_MISMATCH: native suggestion map"
                )
            for actual, proposed in zip(saved, expected):
                _uuid(actual.get("suggestion_uuid"))
                if {k: v for k, v in actual.items() if k != "suggestion_uuid"} != {
                    k: v for k, v in proposed.items() if k != "suggestion_uuid"
                }:
                    raise ReviewProjectError(
                        "REJECTED_IDENTITY_MISMATCH: native suggestion source/region"
                    )
        elif m.get("native_suggestions"):
            raise ReviewProjectError(
                "Source layout requires a versioned review project"
            )

    def validate_source(self):
        source = self._manifest["source"]
        path = Path(source["path"])
        if not path.is_file():
            raise ReviewProjectError(
                "Source document is missing; review and export are blocked"
            )
        if (
            file_content_sha256(path)
            != source["cache_identity"]["input_content_sha256"]
        ):
            raise ReviewProjectError(
                "REJECTED_IDENTITY_MISMATCH: source document version"
            )

    def _replay(self, *, with_effective=False):
        from app.core.manual_text_recovery import KIND, replay as replay_manual

        replay_manual(self)
        active, effective, seen, events = {}, {}, {}, set()
        for record in self._records:
            if not isinstance(record, dict):
                raise ReviewProjectError("Invalid correction record")
            if record.get("event_type") == KIND:
                continue
            _uuid(record.get("correction_uuid"))
            if type(record.get("revision")) is not int or record["revision"] < 1:
                raise ReviewProjectError("Invalid correction revision")
            pair = (record["correction_uuid"], record.get("revision"))
            if pair in seen:
                if seen[pair] != record:
                    raise ReviewProjectError(
                        "Conflicting correction UUID/revision payload"
                    )
                continue
            seen[pair] = record
            text_uuid = record.get("text_source_uuid")
            binding = self._bindings.get(text_uuid)
            if record.get("snapshot_uuid") != self.snapshot_uuid:
                raise ReviewProjectError(
                    "NEEDS_RECONFIRM: REJECTED_IDENTITY_MISMATCH: another conversion snapshot"
                )
            if (
                record.get("format_version") not in {1, 2}
                or record.get("snapshot_uuid") != self.snapshot_uuid
                or binding is None
                or record.get("binding") != binding
                or record.get("snapshot_source") != self._manifest["source"]
            ):
                raise ReviewProjectError(
                    "REJECTED_IDENTITY_MISMATCH: correction snapshot/source/TEXT binding"
                )
            event = record.get("confirmation", {})
            _uuid(event.get("event_uuid"))
            try:
                datetime.fromisoformat(event["at"])
            except (ValueError, KeyError, TypeError):
                raise ReviewProjectError("Missing confirmation time") from None
            if (
                event.get("kind") not in {"GUI_EXPLICIT_CONFIRM", "TEST_ONLY"}
                or event.get("explicit") is not True
                or event["event_uuid"] in events
            ):
                raise ReviewProjectError(
                    "Missing or repeated explicit confirmation event"
                )
            events.add(event["event_uuid"])
            previous = active.get(text_uuid)
            from app.export.ocr_outline_export import _normalised_content

            before = (
                effective[text_uuid]["new_text"]
                if text_uuid in effective
                else _normalised_content(binding["original_candidate"]["text"])
            )
            expected_revision = previous["revision"] + 1 if previous else 1
            previous_ref = (
                {
                    "correction_uuid": previous["correction_uuid"],
                    "revision": previous["revision"],
                }
                if previous
                else None
            )
            if (
                record.get("revision") != expected_revision
                or record.get("previous") != previous_ref
                or (
                    previous
                    and previous["correction_uuid"] != record["correction_uuid"]
                )
                or record.get("expected_before") != before
                or record.get("original_ocr_text")
                != binding["original_candidate"]["text"]
            ):
                raise ReviewProjectError("Correction revision/precondition conflict")
            original = binding["original_candidate"]["text"]
            action, consumption = record.get("action"), record.get("consumption")
            layout = record.get("layout_check", {})
            state = "TEST_ONLY" if event["kind"] == "TEST_ONLY" else "USER_CORRECTED"
            if record.get("source_confirmation_status") != state:
                raise ReviewProjectError("Unsubstantiated confirmation status")
            if action == "WITHDRAW":
                valid = (
                    record.get("new_text") == original
                    and consumption == "WITHDRAWN"
                    and record.get("status") == "OCR_UNVERIFIED"
                    and previous is not None
                    and record.get("format_version") == 1
                )
            elif action == "CONFIRM_SOURCE_LAYOUT":
                suggestion = self.suggestion(text_uuid)
                valid = self._manifest.get("format") == SOURCE_LAYOUT_PROJECT_FORMAT
                valid = bool(
                    valid
                    and record.get("format_version") == 2
                    and suggestion
                    and record.get("suggestion_uuid") == suggestion["suggestion_uuid"]
                    and previous
                    and previous["action"] == "CONFIRM_STRING"
                    and previous["confirmation"]["kind"] == event["kind"]
                    and record.get("content_confirmation") == previous_ref
                    and record.get("new_text") == previous["new_text"]
                    and record.get("request_layout_adjustment") is True
                    and (
                        (
                            consumption == "APPLIED"
                            and layout.get("state") == "PASS"
                            and record.get("status") == state
                        )
                        or (
                            consumption == "HELD"
                            and layout.get("state") == "NEEDS_LAYOUT_REVIEW"
                            and record.get("status") == "NEEDS_LAYOUT_REVIEW"
                        )
                    )
                )
            else:
                valid = (
                    record.get("format_version") == 1
                    and action == "CONFIRM_STRING"
                    and isinstance(record.get("new_text"), str)
                    and record["new_text"] != before
                    and record.get("request_layout_adjustment") is False
                    and (
                        (
                            consumption == "APPLIED"
                            and layout.get("state") == "PASS"
                            and record.get("status") == state
                        )
                        or (
                            consumption == "HELD"
                            and layout.get("state") == "NEEDS_LAYOUT_REVIEW"
                            and record.get("status") == "NEEDS_LAYOUT_REVIEW"
                        )
                    )
                )
            if not valid:
                raise ReviewProjectError(
                    "Invalid correction action/status/layout contract"
                )
            active[text_uuid] = record
            if consumption == "APPLIED":
                effective[text_uuid] = record
            elif consumption == "WITHDRAWN":
                effective.pop(text_uuid, None)
        return (active, effective) if with_effective else active

    @property
    def guard(self):
        if self._guard is None:
            self._guard = ReviewLayoutGuard(self.baseline)
        return self._guard

    def current_text(self, text_uuid):
        from app.export.ocr_outline_export import _normalised_content

        binding = self._bindings[text_uuid]
        record = self._replay(with_effective=True)[1].get(text_uuid)
        return (
            record["new_text"]
            if record and record["consumption"] == "APPLIED"
            else _normalised_content(binding["original_candidate"]["text"])
        )

    def latest(self, text_uuid):
        return deepcopy(self._replay().get(text_uuid))

    def suggestion(self, text_uuid):
        return deepcopy(self._suggestions.get(text_uuid))

    def _active_layout(self, exclude=None):
        active = self._replay(with_effective=True)[1]
        strings = {
            self._bindings[k]["index"]: r["new_text"]
            for k, r in active.items()
            if k != exclude
        }
        quads = {
            self._bindings[k]["index"]: r["layout_check"]["source_quad"]
            for k, r in active.items()
            if k != exclude and r.get("action") == "CONFIRM_SOURCE_LAYOUT"
        }
        return strings, quads

    def current_placement(self, text_uuid, *, transform):
        from app.export.ocr_outline_export import native_text_placement

        candidate = self.baseline.texts[self._bindings[text_uuid]["index"]]
        record = self._replay(with_effective=True)[1].get(text_uuid)
        if not record:
            return native_text_placement(candidate, transform=transform)
        if record.get("action") == "CONFIRM_SOURCE_LAYOUT":
            return source_anchored_text_placement(
                candidate,
                record["new_text"],
                record["layout_check"]["source_quad"],
                transform=transform,
            )
        return fixed_text_placement(candidate, record["new_text"], transform=transform)

    def current_source_layout(self, text_uuid):
        record = self._replay(with_effective=True)[1].get(text_uuid)
        return (
            deepcopy(record["layout_check"])
            if record and record.get("action") == "CONFIRM_SOURCE_LAYOUT"
            else None
        )

    def preview_source_layout(self, text_uuid):
        self.validate_source()
        if text_uuid not in self._bindings:
            raise ReviewProjectError("REJECTED_IDENTITY_MISMATCH: unknown TEXT UUID")
        previous = self.latest(text_uuid)
        suggestion = self.suggestion(text_uuid)
        if (
            not suggestion
            or not previous
            or previous["action"] not in {"CONFIRM_STRING", "CONFIRM_SOURCE_LAYOUT"}
        ):
            return dict(
                state="NEEDS_LAYOUT_REVIEW",
                reason="Confirm text content before requesting a source layout",
            )
        strings, quads = self._active_layout(exclude=text_uuid)
        return self.guard.check_source(
            self._bindings[text_uuid]["index"],
            previous["new_text"],
            suggestion,
            strings,
            quads,
        )

    def confirm_source_layout(self, text_uuid, *, event: ConfirmationEvent):
        """A SECOND explicit event; content confirmation alone cannot call this."""
        layout = self.preview_source_layout(text_uuid)
        previous = self.latest(text_uuid)
        if not previous or previous["action"] not in {
            "CONFIRM_STRING",
            "CONFIRM_SOURCE_LAYOUT",
        }:
            raise ReviewProjectError("Confirm text content first")
        if previous["action"] == "CONFIRM_SOURCE_LAYOUT":
            return None
        if previous["confirmation"]["kind"] != event.kind:
            raise ReviewProjectError(
                "Content and layout confirmation must use the same QA/user domain"
            )
        suggestion = self.suggestion(text_uuid)
        if not suggestion:
            raise ReviewProjectError("No unique native suggestion for this TEXT UUID")
        record = deepcopy(previous)
        record.update(
            format_version=2,
            revision=previous["revision"] + 1,
            expected_before=self.current_text(text_uuid),
            action="CONFIRM_SOURCE_LAYOUT",
            suggestion_uuid=suggestion["suggestion_uuid"],
            content_confirmation={
                "correction_uuid": previous["correction_uuid"],
                "revision": previous["revision"],
            },
            previous={
                "correction_uuid": previous["correction_uuid"],
                "revision": previous["revision"],
            },
            confirmation={**asdict(event), "explicit": True},
            request_layout_adjustment=True,
            source_confirmation_status="TEST_ONLY"
            if event.kind == "TEST_ONLY"
            else "USER_CORRECTED",
            layout_check=layout,
            consumption="APPLIED" if layout["state"] == "PASS" else "HELD",
            status=("TEST_ONLY" if event.kind == "TEST_ONLY" else "USER_CORRECTED")
            if layout["state"] == "PASS"
            else "NEEDS_LAYOUT_REVIEW",
        )
        self.add_records([record])
        return deepcopy(record)

    def confirm(self, text_uuid, new_text, *, event: ConfirmationEvent, withdraw=False):
        self.validate_source()
        if not isinstance(new_text, str):
            raise ReviewProjectError("TEXT correction must be a string")
        if text_uuid not in self._bindings:
            raise ReviewProjectError("REJECTED_IDENTITY_MISMATCH: unknown TEXT UUID")
        binding = self._bindings[text_uuid]
        previous = self._replay().get(text_uuid)
        current = self.current_text(text_uuid)
        original = binding["original_candidate"]["text"]
        if withdraw:
            if not previous or previous["consumption"] == "WITHDRAWN":
                return None
            new_text = original
        elif new_text == current:
            return None
        elif (
            previous
            and previous["action"] == "CONFIRM_STRING"
            and new_text == previous["new_text"]
        ):
            return None
        if not withdraw:
            effective = self._replay(with_effective=True)[1].get(text_uuid)
            if effective and effective.get("action") == "CONFIRM_SOURCE_LAYOUT":
                # Format-1 string edits preserve the ORIGINAL placement. Do
                # not silently restore it after a separately approved layout.
                raise ReviewProjectError(
                    "请先撤回已批准的源区域修订，再确认新的文字和显示区域。"
                )
        from app.ocr.text_output_contract import accepted_ocr_texts

        if not accepted_ocr_texts((self.baseline.texts[binding["index"]],)):
            raise ReviewProjectError(
                "Only an existing native editable TEXT may be corrected"
            )
        active_strings, active_quads = self._active_layout(exclude=text_uuid)
        layout = (
            {"state": "NOT_REQUIRED", "reason": "Restore immutable baseline"}
            if withdraw
            else self.guard.check(
                binding["index"], new_text, active_strings, active_quads
            )
        )
        applied = layout["state"] == "PASS"
        record = {
            "format_version": 1,
            "correction_uuid": previous["correction_uuid"]
            if previous
            else str(uuid4()),
            "revision": previous["revision"] + 1 if previous else 1,
            "snapshot_uuid": self.snapshot_uuid,
            "text_source_uuid": text_uuid,
            "binding": deepcopy(binding),
            "snapshot_source": deepcopy(self._manifest["source"]),
            "original_ocr_text": original,
            "expected_before": current,
            "new_text": new_text,
            "source_confirmation_status": "TEST_ONLY"
            if event.kind == "TEST_ONLY"
            else "USER_CORRECTED",
            "confirmation": {**asdict(event), "explicit": True},
            "action": "WITHDRAW" if withdraw else "CONFIRM_STRING",
            "request_layout_adjustment": False,
            "layout_check": layout,
            "consumption": "WITHDRAWN"
            if withdraw
            else ("APPLIED" if applied else "HELD"),
            "status": "OCR_UNVERIFIED"
            if withdraw
            else (
                ("TEST_ONLY" if event.kind == "TEST_ONLY" else "USER_CORRECTED")
                if applied
                else "NEEDS_LAYOUT_REVIEW"
            ),
            "previous": (
                {
                    "correction_uuid": previous["correction_uuid"],
                    "revision": previous["revision"],
                }
                if previous
                else None
            ),
        }
        self.add_records([record])
        return deepcopy(record)

    def add_records(self, records):
        """Import only exact same-snapshot records; identical repeats are no-ops."""
        proposed = deepcopy(self._records)
        for record in records:
            if record not in proposed:
                proposed.append(deepcopy(record))
        old = self._records
        self._records = proposed
        try:
            self._replay()
        except BaseException:
            self._records = old
            raise
        if proposed != old:
            self.dirty = True

    def validated_review(self):
        self.validate_source()
        latest, active = self._replay(with_effective=True)
        strings, quads = self._active_layout()
        for text_uuid, record in active.items():
            if record["consumption"] == "APPLIED":
                if record.get("action") == "CONFIRM_SOURCE_LAYOUT":
                    result = self.guard.check_source(
                        self._bindings[text_uuid]["index"],
                        record["new_text"],
                        self.suggestion(text_uuid),
                        strings,
                        quads,
                    )
                    if result != record["layout_check"]:
                        raise ReviewProjectError(
                            "NEEDS_LAYOUT_REVIEW: source layout payload or environment changed"
                        )
                else:
                    result = self.guard.check(
                        self._bindings[text_uuid]["index"],
                        record["new_text"],
                        strings,
                        quads,
                    )
                if result["state"] != "PASS":
                    raise ReviewProjectError("NEEDS_LAYOUT_REVIEW: " + result["reason"])
        return ValidatedTextReview(self, deepcopy({**latest, **active}))

    def draft(self):
        # Shared read-only baseline/cache/guard; independent journal for Cancel.
        draft = object.__new__(ReviewProject)
        draft.__dict__ = {
            **self.__dict__,
            "_records": deepcopy(self._records),
            "_tempdir": None,
        }
        return draft

    def save(self, path):
        self._validate_baseline()
        self.validated_review()
        target = Path(path).resolve()
        if (
            target.suffix.lower() != ".icreview"
            or target == Path(self._manifest["source"]["path"]).resolve()
            or target.is_relative_to(self._cache_path.parent)
        ):
            raise ReviewProjectError(
                "Choose a persistent .icreview path outside the application temporary directory"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        success, png = cv2.imencode(".png", self.frame)
        if not success:
            raise ReviewProjectError("Cannot serialize review frame")
        temporary = None
        try:
            with NamedTemporaryFile(
                dir=target.parent,
                prefix="." + target.name + ".",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            with ZipFile(
                temporary, "w", compression=ZIP_DEFLATED, compresslevel=1
            ) as archive:
                archive.writestr("project.json", _json(self._manifest))
                archive.writestr(
                    "corrections.json",
                    _json(
                        {
                            "format_version": 2
                            if any(
                                r.get("event_type") == "MANUAL_TEXT_INSERTION"
                                for r in self._records
                            )
                            else 1,
                            "snapshot_uuid": self.snapshot_uuid,
                            "records": self._records,
                        }
                    ),
                )
                archive.write(self._cache_path, "snapshot.npz")
                archive.writestr("review-frame.png", png.tobytes())
            # Read through the real parser before atomically replacing a good save.
            checked = type(self).open(temporary)
            try:
                if checked.records != self.records or checked.manifest != self.manifest:
                    raise ReviewProjectError("Saved project readback mismatch")
            finally:
                checked.close()
            with temporary.open("r+b") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            self.path, self.dirty = target, False
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @classmethod
    def open(cls, path):
        temporary = TemporaryDirectory(prefix="image-to-cad-review-open-")
        try:
            with ZipFile(path) as archive:
                if set(archive.namelist()) != _ENTRIES or len(
                    archive.namelist()
                ) != len(_ENTRIES):
                    raise ReviewProjectError("Incomplete review project")
                if archive.testzip() is not None:
                    raise ReviewProjectError("Review project ZIP integrity error")
                manifest = json.loads(archive.read("project.json"))
                journal = json.loads(archive.read("corrections.json"))
                if (
                    not isinstance(journal, dict)
                    or not isinstance(journal.get("records"), list)
                    or any(
                        not isinstance(record, dict) for record in journal["records"]
                    )
                ):
                    raise ReviewProjectError("Invalid correction record")
                cache_path = Path(temporary.name) / "snapshot.npz"
                with (
                    archive.open("snapshot.npz") as source,
                    cache_path.open("wb") as output,
                ):
                    import shutil

                    shutil.copyfileobj(source, output)
                frame = cv2.imdecode(
                    np.frombuffer(archive.read("review-frame.png"), np.uint8),
                    cv2.IMREAD_UNCHANGED,
                )
            if journal.get("format_version") not in {1, 2} or journal.get(
                "snapshot_uuid"
            ) != manifest.get("snapshot_uuid"):
                raise ReviewProjectError("REJECTED_IDENTITY_MISMATCH: journal snapshot")
            if journal.get("format_version") == 1 and any(
                r.get("event_type") == "MANUAL_TEXT_INSERTION"
                for r in journal["records"]
            ):
                raise ReviewProjectError(
                    "Manual insertion requires journal format version 2"
                )
            stored = load_trace_cache(cache_path)
            if (
                stored.final_structure is None
                or stored.cache_key != manifest["source"]["cache_identity"]
                or frame is None
            ):
                raise ReviewProjectError(
                    "REJECTED_IDENTITY_MISMATCH: saved cache context"
                )
            project = cls(
                stored.final_structure,
                manifest,
                frame,
                tempdir=temporary,
                cache_path=cache_path,
                records=journal["records"],
            )
            project.validate_source()
            project.path = Path(path).resolve()
            return project
        except (
            KeyError,
            TypeError,
            OSError,
            ValueError,
            BadZipFile,
            AssertionError,
            AttributeError,
            IndexError,
            EOFError,
        ) as exc:
            temporary.cleanup()
            raise ReviewProjectError(str(exc)) from exc

    def export_dxf(self, path, **kwargs):
        from app.export.trace_single_export import export_final_structure_dxf

        return export_final_structure_dxf(
            self.baseline,
            path,
            self.calibration,
            drawing_multiplier=self._manifest["export_settings"]["drawing_multiplier"],
            text_review=self.validated_review(),
            **kwargs,
        )

    def close(self):
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None

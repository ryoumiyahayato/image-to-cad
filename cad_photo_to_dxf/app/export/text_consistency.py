"""Compare emitted native TEXT with the input snapshot before atomic publish."""

from math import isclose

from app.export.ocr_outline_export import (
    _normalised_content,
    native_text_placement,
    native_text_file_content,
)
from app.ocr.text_output_contract import accepted_ocr_texts


TEXT_CONSISTENCY_VERSION = "snapshot-text-consistency-v2-literal-caret"


class TextConsistencyError(ValueError):
    pass


class TextConsistencyGuard:
    def __init__(self):
        self._pages = []
        self._manual_pages = []

    def expect_manual(self, layer, expected, review):
        self._manual_pages.append((layer, expected, review))

    def expect_page(self, texts, layer, *, transform, doc, review=None):
        expected = []
        for candidate in accepted_ocr_texts(texts):
            authority = (
                review.export_expectation(candidate, transform=transform)
                if review is not None
                else None
            )
            placement = (
                authority["placement"]
                if authority
                else native_text_placement(candidate, transform=transform, doc=doc)
            )
            if placement is None:
                raise TextConsistencyError(
                    f"TEXT_CONSISTENCY: layer={layer} source has no placement"
                )
            expected.append(
                (
                    authority["text"]
                    if authority
                    else _normalised_content(candidate.text),
                    str(candidate.source)[:250],
                    int(candidate.reviewed) if not authority else authority["reviewed"],
                    authority,
                    (*placement.geometry.insert, placement.geometry.rotation),
                )
            )
        self._pages.append((layer, tuple(expected), review))

    def validate(self, doc):
        manual_ids = {
            wanted["values"][3]
            for _, expected, _ in self._manual_pages
            for wanted in expected
        }
        for entity in doc.modelspace():
            if not entity.has_xdata("MANUAL_TEXT_INSERTION"):
                continue
            values = [tag.value for tag in entity.get_xdata("MANUAL_TEXT_INSERTION")]
            slot = 3 if entity.dxftype() == "TEXT" else 1
            if (
                entity.dxftype() not in {"TEXT", "LWPOLYLINE"}
                or len(values) <= slot
                or values[slot] not in manual_ids
            ):
                raise TextConsistencyError(
                    "TEXT_CONSISTENCY: unexpected manual source identity"
                )
        for layer, expected, review in self._manual_pages:
            review.validate_current()
            entities = [
                e for e in doc.modelspace().query("TEXT") if e.dxf.layer == layer
            ]
            if len(entities) != len(expected):
                raise TextConsistencyError(
                    "TEXT_CONSISTENCY: manual TEXT count differs"
                )
            expected_backups = [
                wanted["backup"] for wanted in expected if wanted["backup"]
            ]
            actual_backups = [
                e
                for e in doc.modelspace().query("LWPOLYLINE")
                if e.has_xdata("MANUAL_TEXT_INSERTION")
                and len(e.get_xdata("MANUAL_TEXT_INSERTION")) > 1
                and e.get_xdata("MANUAL_TEXT_INSERTION")[1].value
                in {w["values"][3] for w in expected}
            ]
            if len(actual_backups) != len(expected_backups):
                raise TextConsistencyError(
                    "TEXT_CONSISTENCY: manual source backup count differs"
                )
            for wanted in expected_backups:
                matches = [
                    e
                    for e in actual_backups
                    if [t.value for t in e.get_xdata("MANUAL_TEXT_INSERTION")]
                    == wanted["values"]
                ]
                if len(matches) != 1:
                    raise TextConsistencyError(
                        "TEXT_CONSISTENCY: manual source backup identity differs"
                    )
                backup = matches[0]
                points = list(backup.get_points("xy"))
                if len(points) != len(wanted["points"]) or any(
                    not isclose(a, b, rel_tol=0, abs_tol=1e-7)
                    for actual, target in zip(points, wanted["points"])
                    for a, b in zip(actual, target)
                ):
                    raise TextConsistencyError(
                        "TEXT_CONSISTENCY: manual source backup boundary differs"
                    )
                layer_state = doc.layers.get(wanted["layer"])
                if (
                    backup.dxf.layer != wanted["layer"]
                    or not backup.closed
                    or not layer_state.is_off()
                    or not layer_state.is_frozen()
                ):
                    raise TextConsistencyError(
                        "TEXT_CONSISTENCY: manual source backup must be hidden and frozen"
                    )
            for entity, wanted in zip(entities, expected):
                try:
                    if (
                        entity.dxf.text != wanted["content"]
                        or entity.dxf.style != wanted["style"]
                        or entity.dxf.halign != 0
                        or entity.dxf.valign != 0
                        or [t.value for t in entity.get_xdata("MANUAL_TEXT_INSERTION")]
                        != wanted["values"]
                    ):
                        raise ValueError(
                            "manual identity/content/source/style mismatch"
                        )
                    actual = [
                        entity.dxf.insert.x,
                        entity.dxf.insert.y,
                        entity.dxf.height,
                        entity.dxf.width,
                        entity.dxf.rotation,
                    ]
                    target = [
                        *wanted["insert"],
                        wanted["height"],
                        wanted["width"],
                        wanted["rotation"],
                    ]
                    if any(
                        not isclose(a, b, rel_tol=0, abs_tol=1e-7)
                        for a, b in zip(actual, target)
                    ):
                        raise ValueError("manual TEXT placement mismatch")
                    layer_state = doc.layers.get(layer)
                    if (
                        layer_state.is_off() != wanted["layer_off"]
                        or layer_state.is_frozen()
                        or entity.dxf.get("invisible", 0)
                    ):
                        raise ValueError("manual TEXT is hidden")
                except (ValueError, IndexError, AttributeError) as exc:
                    raise TextConsistencyError("TEXT_CONSISTENCY: " + str(exc)) from exc
        for layer, expected, review in self._pages:
            if review is not None:
                review.validate_current()
            entities = [
                entity
                for entity in doc.modelspace().query("TEXT")
                if entity.dxf.layer == layer
            ]
            if len(entities) != len(expected):
                raise TextConsistencyError(
                    f"TEXT_CONSISTENCY: layer={layer} native TEXT count differs from snapshot"
                )
            seen = set()
            for entity in entities:
                index, source_uuid = "missing", "unknown"
                try:
                    tags = entity.get_xdata("OCR_TEXT_LINE")
                    index = tags[0].value
                    if (
                        type(index) is not int
                        or not 1 <= index <= len(expected)
                        or index in seen
                    ):
                        raise ValueError("invalid source line identity")
                    seen.add(index)
                    content, source, reviewed, authority, position = expected[index - 1]
                    source_uuid = (
                        authority["review_values"][3] if authority else "unreviewed"
                    )
                    contract = entity.get_xdata("TEXT_OUTPUT_CONTRACT")
                    if (
                        entity.dxf.text != native_text_file_content(content)
                        or tags[1].value != content
                        or tags[3].value != reviewed
                        or contract[1].value != source
                    ):
                        raise ValueError("effective text/source record mismatch")
                    actual_position = (
                        entity.dxf.insert.x,
                        entity.dxf.insert.y,
                        entity.dxf.rotation,
                    )
                    recorded_position = tuple(tag.value for tag in contract[5:8])
                    if len(recorded_position) != 3 or any(
                        not isclose(
                            float(actual), float(wanted), rel_tol=0.0, abs_tol=1e-7
                        )
                        for actuals in (actual_position, recorded_position)
                        for actual, wanted in zip(actuals, position)
                    ):
                        raise ValueError("source placement/target identity mismatch")
                    if authority is not None:
                        actual = [tag.value for tag in entity.get_xdata("TEXT_REVIEW")]
                        if actual != authority["review_values"]:
                            raise ValueError("snapshot/revision/history mismatch")
                except (ValueError, IndexError, AttributeError) as exc:
                    raise TextConsistencyError(
                        f"TEXT_CONSISTENCY: layer={layer} handle={entity.dxf.handle} "
                        f"line_index={index} source_uuid={source_uuid}: {exc}"
                    ) from exc

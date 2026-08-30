from __future__ import annotations

import json
from pathlib import Path
import sys

import ezdxf
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.draftsman_adapter import (
    RC3_CREATION_METHOD,
    adapt_legacy_final_structure,
    load_v2_restoration_records,
    shadow_manifest_sha256,
)
from app.draftsman_contract import EvidenceState, TransformRef
from app.final_structure import FinalStructure, build_final_structure
from app.line_detect import LineSegment
from app.raster_trace import TracePath
from app.text_protection import TEXT_MASK_RESTORATION
from app.trace_single_export import export_final_structure_dxf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from v2_canonical_structure import canonical_json_bytes, canonical_payload  # noqa: E402


SOURCE_SHA256 = "1" * 64


def _transform(height: int = 100) -> TransformRef:
    return TransformRef.create(
        source_space="source-pixel",
        target_space="cad-page",
        transform_payload={
            "origin": [0.0, float(height)],
            "scale": [1.0, -1.0],
            "rotation_degrees": 0.0,
        },
    )


def _structure(
    *,
    lines: tuple[LineSegment, ...],
    texts: tuple[TextCandidate, ...] = (),
    contours: tuple[TracePath, ...] = (),
    size: tuple[int, int] = (200, 100),
    observations: tuple[dict[str, object], ...] = (),
) -> FinalStructure:
    width, height = size
    binary = np.full((height, width), 255, dtype=np.uint8)
    return build_final_structure(
        source_size_px=size,
        contour_binary=binary,
        contours=contours,
        straight_lines=lines,
        texts=texts,
        preview_binary=binary,
        provenance={"pipeline": "unit-test-current-production"},
        observations=observations,
    )


def _adapt(
    structure: FinalStructure,
    *,
    records: tuple[dict[str, object], ...] = (),
    source_sha256: str = SOURCE_SHA256,
) -> object:
    return adapt_legacy_final_structure(
        structure,
        document_id="document-A",
        page_number=1,
        source_sha256=source_sha256,
        transform=_transform(structure.source_size_px[1]),
        v2_restoration_records=records,
    )


def _v2_record(line: LineSegment, ordinal: int = 1) -> dict[str, object]:
    evidence_hash = f"{ordinal:064x}"
    return {
        "contract_version": "non-destructive-editable-text-v2",
        "restoration_id": f"restoration-{ordinal:04d}",
        "canonical_entity_id": f"candidate:line:{ordinal:04d}",
        "evidence_hash": evidence_hash,
        "source_geometry": {
            "coordinate_space": "source-pixel",
            "coords": [line.x1, line.y1, line.x2, line.y2],
            "width": line.width,
        },
        "r2_restoration_provenance": {
            "acceptance_stage": "late_restoration_output",
            "r2_history": list(line.history),
        },
        "transform_provenance": {
            "origin": [0.0, 100.0],
            "scale": [1.0, -1.0],
        },
    }


def test_rc3_history_maps_to_reconstructed_and_preserves_v2_provenance() -> None:
    line = LineSegment(
        10.0,
        20.0,
        80.0,
        20.0,
        width=1.5,
        confidence=0.94,
        source_ids=("lsd-17",),
        history=("detected:lsd", TEXT_MASK_RESTORATION),
    )
    record = _v2_record(line)
    snapshot = _adapt(_structure(lines=(line,)), records=(record,))
    entity = snapshot.entities[0]  # type: ignore[attr-defined]
    assert entity.state is EvidenceState.RECONSTRUCTED
    assert entity.provenance.creation_method == RC3_CREATION_METHOD
    assert entity.provenance.reconstruction_rule == TEXT_MASK_RESTORATION
    assert entity.provenance.history == line.history
    assert set(entity.source_candidate_ids) == {
        "candidate:line:0001",
        "lsd-17",
        "restoration-0001",
    }
    external = entity.provenance.external_evidence[0]
    assert json.loads(external.evidence_json) == record


def test_normal_structure_maps_to_observed_with_explicit_missing_evidence() -> None:
    line = LineSegment(2.0, 3.0, 40.0, 3.0, history=("detected:hough",))
    snapshot = _adapt(_structure(lines=(line,)))
    entity = snapshot.entities[0]  # type: ignore[attr-defined]
    assert entity.state is EvidenceState.OBSERVED
    assert entity.provenance.reconstruction_method is None
    assert "legacy_source_candidate_ids" in (
        entity.provenance.legacy_evidence_unavailable
    )


def test_adapter_is_deterministic_and_independent_of_collection_order() -> None:
    first = LineSegment(1.0, 2.0, 30.0, 2.0, source_ids=("line-a",))
    second = LineSegment(5.0, 8.0, 5.0, 40.0, source_ids=("line-b",))
    forward = _adapt(_structure(lines=(first, second)))
    reverse = _adapt(_structure(lines=(second, first)))
    replay = _adapt(_structure(lines=(first, second)))
    assert forward.canonical_bytes() == reverse.canonical_bytes()  # type: ignore[attr-defined]
    assert forward.canonical_bytes() == replay.canonical_bytes()  # type: ignore[attr-defined]
    assert shadow_manifest_sha256(forward) == shadow_manifest_sha256(replay)  # type: ignore[arg-type]
    assert {
        entity.stable_entity_id for entity in forward.entities  # type: ignore[attr-defined]
    } == {
        entity.stable_entity_id for entity in reverse.entities  # type: ignore[attr-defined]
    }


def test_duplicate_semantics_receive_deterministic_counted_ids() -> None:
    line = LineSegment(1.0, 2.0, 30.0, 2.0)
    snapshot = _adapt(_structure(lines=(line, line)))
    ids = [entity.stable_entity_id for entity in snapshot.entities]  # type: ignore[attr-defined]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert sorted(entity.occurrence for entity in snapshot.entities) == [1, 2]  # type: ignore[attr-defined]


def test_adapter_does_not_mutate_final_structure() -> None:
    line = LineSegment(4.0, 5.0, 60.0, 5.0, source_ids=("line-1",))
    structure = _structure(lines=(line,))
    structure_id = structure.structure_id
    contour_bytes = structure.contour_binary.tobytes()
    preview_bytes = structure.preview_binary.tobytes()  # type: ignore[union-attr]
    lines = structure.straight_lines
    provenance = dict(structure.provenance)
    _adapt(structure)
    assert structure.structure_id == structure_id
    assert structure.contour_binary.tobytes() == contour_bytes
    assert structure.preview_binary.tobytes() == preview_bytes  # type: ignore[union-attr]
    assert structure.straight_lines == lines
    assert dict(structure.provenance) == provenance
    assert not structure.contour_binary.flags.writeable
    assert not structure.preview_binary.flags.writeable  # type: ignore[union-attr]


def test_existing_page_ownership_uncertainty_gets_stable_review_item() -> None:
    structure = _structure(
        lines=(LineSegment(1.0, 2.0, 20.0, 2.0),),
        observations=(
            {
                "event": "ownership_partitioned",
                "conflict_objects": 2,
                "downgrades": 1,
            },
        ),
    )
    first = _adapt(structure)
    replay = _adapt(structure)
    assert len(first.review_items) == 2  # type: ignore[attr-defined]
    assert [item.review_item_id for item in first.review_items] == [  # type: ignore[attr-defined]
        item.review_item_id for item in replay.review_items  # type: ignore[attr-defined]
    ]


def _dxf_semantics(path: Path) -> list[dict[str, object]]:
    document = ezdxf.readfile(path)
    payloads = [canonical_payload(entity) for entity in document.modelspace()]
    return sorted(payloads, key=canonical_json_bytes)


def test_adapter_has_zero_production_dxf_semantic_delta(tmp_path: Path) -> None:
    structure = _structure(
        lines=(
            LineSegment(
                5.0,
                6.0,
                80.0,
                6.0,
                width=1.25,
                source_ids=("line-1",),
            ),
        ),
        texts=(
            TextCandidate(
                "A-101",
                (20, 20, 40, 12),
                0.99,
                "text",
                source="unit-test",
                approved=True,
                replacement_safe=True,
            ),
        ),
    )
    before = tmp_path / "before.dxf"
    after = tmp_path / "after.dxf"
    before_result = export_final_structure_dxf(structure, before)
    snapshot = _adapt(structure)
    after_result = export_final_structure_dxf(structure, after)
    assert before_result.structure_id == after_result.structure_id
    assert snapshot.final_structure_id == structure.structure_id  # type: ignore[attr-defined]
    assert _dxf_semantics(before) == _dxf_semantics(after)


def _current_v2_page() -> Path | None:
    candidates = (
        WORKSPACE_ROOT
        / "local-artifacts/review/p1-v2-implementation/v2-pages"
        / "environment-plan-page-003-150dpi.json",
        PROJECT_ROOT
        / "validation/baselines/non-destructive-editable-text-v2/pages"
        / "environment-plan-page-003-150dpi.json",
    )
    return next((path for path in candidates if path.is_file()), None)


def test_current_v2_91_restorations_map_reconstructed() -> None:
    page_path = _current_v2_page()
    if page_path is None:
        return
    page = json.loads(page_path.read_text(encoding="utf-8"))
    records = load_v2_restoration_records(page_path)
    assert len(records) == 91
    lines = []
    for record in records:
        source_geometry = record["source_geometry"]
        assert isinstance(source_geometry, dict)
        coords = source_geometry["coords"]
        assert isinstance(coords, list)
        history_payload = record["r2_restoration_provenance"]
        assert isinstance(history_payload, dict)
        history = history_payload["r2_history"]
        assert isinstance(history, list)
        lines.append(
            LineSegment(
                *[float(value) for value in coords],
                width=float(source_geometry["width"]),
                history=tuple(str(item) for item in history),
            )
        )
    source = page["source"]
    transform_payload = page["transform"]
    assert isinstance(source, dict)
    assert isinstance(transform_payload, dict)
    size_payload = source["dimensions"]
    assert isinstance(size_payload, list)
    size = (int(size_payload[0]), int(size_payload[1]))
    structure = _structure(lines=tuple(lines), size=size)
    transform = TransformRef.create(
        source_space="source-pixel",
        target_space="cad-page",
        transform_payload=transform_payload,
    )
    first = adapt_legacy_final_structure(
        structure,
        document_id=str(page["page_id"]),
        page_number=int(source["page_number"]),
        source_sha256=str(source["sha256"]),
        transform=transform,
        v2_restoration_records=records,
    )
    replay = adapt_legacy_final_structure(
        structure,
        document_id=str(page["page_id"]),
        page_number=int(source["page_number"]),
        source_sha256=str(source["sha256"]),
        transform=transform,
        v2_restoration_records=tuple(reversed(records)),
    )
    reconstructed = [
        entity
        for entity in first.entities
        if entity.state is EvidenceState.RECONSTRUCTED
    ]
    assert len(reconstructed) == 91
    assert all(entity.provenance.external_evidence for entity in reconstructed)
    assert first.canonical_bytes() == replay.canonical_bytes()


def test_production_modules_do_not_import_shadow_contracts() -> None:
    excluded = {"draftsman_contract.py", "draftsman_adapter.py"}
    consumers = []
    for path in (PROJECT_ROOT / "app").glob("*.py"):
        if path.name in excluded:
            continue
        source = path.read_text(encoding="utf-8")
        if "draftsman_contract" in source or "draftsman_adapter" in source:
            consumers.append(path.name)
    assert consumers == []

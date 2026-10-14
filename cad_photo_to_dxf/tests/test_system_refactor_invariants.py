from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
import re

import cv2
import ezdxf
import numpy as np
import pytest

from app.ocr.auxiliary_recognition import TextCandidate
from app.geometry.content_ownership import partition_content
from app.core.structure import metadata_to_jsonable
from app.core.structure_build import build_final_structure
from app.geometry.line_detect import LineSegment
from app.core.preview import render_final_structure_preview
from app.geometry.raster_trace import trace_binary
from app.ocr.signature_overlay import SignatureRegion
from app.export.trace_single_export import export_final_structure_dxf


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def test_application_has_no_morphological_closing() -> None:
    occurrences = {
        path.name
        for path in APP_ROOT.rglob("*.py")
        if "MORPH_CLOSE" in path.read_text(encoding="utf-8")
    }
    assert occurrences == set()


def test_classifiers_have_no_position_or_fixed_field_rules() -> None:
    sources = "\n".join(
        (APP_ROOT / name).read_text(encoding="utf-8")
        for name in (
            "ocr/ocr_pipeline.py",
            "ocr/ocr_layout.py",
            "ocr/logo_detection.py",
            "ocr/signature_overlay.py",
            "geometry/content_ownership.py",
        )
    )
    assert not re.search(r"(page|image)_(width|height)\s*\*\s*0\.", sources)
    for forbidden in (
        "_signature_header",
        "_right_title_block_region",
        "_infer_ruled_title_block_labels",
        "DESIGNGROUP",
        "建设单位",
        "项目负责",
        "会签",
    ):
        assert forbidden not in sources


def test_connectivity_safety_has_no_object_classification_dependency() -> None:
    source = (APP_ROOT / "geometry/connectivity_safety.py").read_text(encoding="utf-8")
    assert "TextCandidate" not in source
    assert "LogoRegion" not in source
    assert "SignatureRegion" not in source
    assert ".kind" not in source


def test_ambiguous_pixels_are_residual_not_resolved_by_type_priority() -> None:
    binary = np.full((60, 100), 255, dtype=np.uint8)
    cv2.line(binary, (10, 30), (90, 30), 0, 3)
    line = LineSegment(10.0, 30.0, 90.0, 30.0, width=3.0)
    signature_mask = np.full((5, 30), 255, dtype=np.uint8)
    signature = SignatureRegion((35, 28, 30, 5), signature_mask)

    ownership = partition_content(
        binary,
        lines=(line,),
        texts=(),
        signatures=(signature,),
    )

    assert ownership.ambiguous[30, 50] == 255
    assert ownership.residual[30, 50] == 255
    assert ownership.line[30, 50] == 0
    assert ownership.signature[30, 50] == 0
    ownership.assert_valid()


def test_preview_and_dxf_export_share_one_structure_id(tmp_path: Path) -> None:
    binary = np.full((80, 120), 255, dtype=np.uint8)
    cv2.rectangle(binary, (10, 10), (110, 70), 0, 3)
    paths = trace_binary(binary)
    structure = build_final_structure(
        source_size_px=(120, 80),
        contour_binary=binary,
        contours=paths,
        preview_binary=binary,
        provenance={"test": "single-source"},
    )

    preview = render_final_structure_preview(structure)
    result = export_final_structure_dxf(
        structure,
        tmp_path / "single-source.dxf",
    )

    assert np.any(preview < 128)
    assert not np.array_equal(preview, binary)  # emitted contours, not source ink
    assert result.structure_id == structure.structure_id
    assert result.path.exists()


def test_preview_is_part_of_the_final_structure_fingerprint() -> None:
    contour_binary = np.full((40, 60), 255, dtype=np.uint8)
    preview_a = contour_binary.copy()
    preview_b = contour_binary.copy()
    preview_b[10, 10] = 0
    first = build_final_structure(
        source_size_px=(60, 40),
        contour_binary=contour_binary,
        contours=(),
        preview_binary=preview_a,
    )
    second = build_final_structure(
        source_size_px=(60, 40),
        contour_binary=contour_binary,
        contours=(),
        preview_binary=preview_b,
    )

    assert first.structure_id != second.structure_id
    assert not first.contour_binary.flags.writeable
    assert first.preview_binary is not None
    assert not first.preview_binary.flags.writeable


def test_native_text_quad_changes_output_identity_and_export_geometry(
    tmp_path: Path,
) -> None:
    binary = np.full((100, 160), 255, dtype=np.uint8)
    first_text = TextCandidate(
        "ABC 123",
        (10, 20, 100, 20),
        0.99,
        "text_candidate",
        quad=((10.0, 20.0), (110.0, 20.0), (110.0, 40.0), (10.0, 40.0)),
        reviewed=True,
    )
    second_text = replace(
        first_text,
        quad=((10.0, 20.0), (110.0, 30.0), (110.0, 40.0), (10.0, 30.0)),
    )

    def structure(text: TextCandidate):
        return build_final_structure(
            source_size_px=(160, 100),
            contour_binary=binary,
            contours=(),
            texts=(text,),
            preview_binary=binary,
        )

    first = structure(first_text)
    equivalent = structure(replace(first_text))
    diagnostic_only = structure(
        replace(
            first_text,
            rotation_deg=37.0,
            character_boxes=((11, 21, 10, 18),),
            review_note="review-only note",
        )
    )
    second = structure(second_text)
    first_export = export_final_structure_dxf(first, tmp_path / "first.dxf")
    second_export = export_final_structure_dxf(second, tmp_path / "second.dxf")
    first_entity = list(ezdxf.readfile(first_export.path).modelspace().query("TEXT"))[0]
    second_entity = list(ezdxf.readfile(second_export.path).modelspace().query("TEXT"))[0]

    assert first.structure_id == equivalent.structure_id
    assert first.structure_id == diagnostic_only.structure_id
    assert first.structure_id != second.structure_id
    assert (
        tuple(first_entity.dxf.insert),
        first_entity.dxf.height,
        first_entity.dxf.rotation,
    ) != (
        tuple(second_entity.dxf.insert),
        second_entity.dxf.height,
        second_entity.dxf.rotation,
    )


def test_nested_metadata_is_a_detached_immutable_json_snapshot() -> None:
    binary = np.full((20, 30), 255, dtype=np.uint8)
    provenance = {"nested": {"source_ids": ["one"]}}
    observation = {"event": "contract", "details": {"count": 1}}
    structure = build_final_structure(
        source_size_px=(30, 20),
        contour_binary=binary,
        contours=(),
        provenance=provenance,
        observations=(observation,),
    )

    provenance["nested"]["source_ids"].append("caller-mutation")
    observation["details"]["count"] = 9
    assert metadata_to_jsonable(structure.provenance) == {
        "nested": {"source_ids": ["one"]}
    }
    assert metadata_to_jsonable(structure.observations) == [
        {"event": "contract", "details": {"count": 1}}
    ]

    nested = structure.provenance["nested"]
    assert isinstance(nested, Mapping)
    with pytest.raises(TypeError):
        nested["new"] = True  # type: ignore[index]
    details = structure.observations[0]["details"]
    assert isinstance(details, Mapping)
    with pytest.raises(TypeError):
        details["count"] = 2  # type: ignore[index]

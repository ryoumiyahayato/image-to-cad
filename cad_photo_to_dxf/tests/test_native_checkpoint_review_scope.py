"""Local omission accounting never exempts saved entities from source review."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import ezdxf
import numpy as np
from PIL import Image
import pytest

from app.native_objects import cad_io
from app.native_objects.quality_review import (
    _connection_checkpoint_scope,
    run_quality_review,
)
from app.native_objects.review_binding import (
    canonical_sha256,
    file_sha256,
    source_identity,
    verify_saved_review,
)


ROI = (0, 0, 160, 120)
DPI = 200


@pytest.fixture
def source_case(tmp_path):
    gray = np.full((120, 160), 255, np.uint8)
    gray[25, 15:101] = 0  # Complete retained neighbor crosses the context edge.
    gray[45, 20] = 0  # An actual missing one-pixel source component in context.
    gray[90, 120] = 0  # Another missing component outside this local task.
    source = tmp_path / "synthetic-source.png"
    Image.fromarray(gray).save(source)
    source_hash = hashlib.sha256(gray.tobytes()).hexdigest()
    objects = [
        {
            "id": "retained-neighbor",
            "kind": "LINE",
            "layer": "LINES",
            "geometry": {"start": [15, 25], "end": [100, 25]},
        }
    ]
    dxf = tmp_path / "candidate.dxf"
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.header["$MEASUREMENT"] = 1
    doc.appids.new(cad_io.APPID)
    doc.layers.new("LINES", dxfattribs={"plot": 1})
    review = doc.layers.new("REVIEW", dxfattribs={"plot": 0})
    review.off()
    review.lock()
    mm = 25.4 / DPI
    entity = doc.modelspace().add_line(
        (15 * mm, (ROI[3] - 25) * mm),
        (100 * mm, (ROI[3] - 25) * mm),
        dxfattribs={"layer": "LINES"},
    )
    cad_io.mark(entity, objects[0])
    cad_io.save_native_dxf(doc, dxf)
    manifest = {
        "source_path": str(source),
        "source_sha256": file_sha256(source),
        "working_array_sha256": source_hash,
        "selection": {"format": "PNG", "source_size_px": [160, 120]},
        "coordinates": {"working_ROI_xyxy_px": list(ROI)},
        "job": {
            "recognition_dpi": DPI,
            "roi_source_xyxy_px": list(ROI),
            "orientation_clockwise_degrees": 0,
            "mode": "native-objects",
            "unit": "paper_mm",
        },
    }
    texts = {
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [160, 120],
        "source_array_sha256": source_hash,
        "roi_xyxy_px": list(ROI),
        "regions": [],
        "groups": [
            {"id": "local-unresolved-text", "bbox_xyxy_px": [18, 42, 24, 48]},
            {"id": "outside-unresolved-text", "bbox_xyxy_px": [115, 85, 125, 95]},
        ],
    }
    checkpoint = {
        "manifest_sha256": "a" * 64,
        "baseline_dxf_sha256": file_sha256(dxf),
        # Deliberate overlap: union pixels must not be counted twice.
        "context_rois": [[10, 10, 70, 60], [30, 20, 80, 65]],
    }
    return gray, dxf, objects, texts, manifest, checkpoint


def _review(source_case, out, *, scoped):
    gray, dxf, objects, texts, manifest, checkpoint = source_case
    current = deepcopy(manifest)
    if scoped:
        current["connection_checkpoint"] = deepcopy(checkpoint)
    untouched = gray.copy()
    report = run_quality_review(
        dxf, gray, ROI, DPI, objects, texts, [], current, out
    )
    assert np.array_equal(gray, untouched)
    assert report["actual_saved_DXF_unchanged"]
    return report, current


def test_default_review_still_accounts_for_the_whole_roi_and_old_identity_shape(
    source_case, tmp_path
):
    report, manifest = _review(source_case, tmp_path / "full", scoped=False)
    assert set(source_identity(manifest)) == {
        "source_file_sha256", "working_array_sha256", "selection_sha256",
        "coordinates_sha256", "job_input_interpretation",
    }
    assert "review_scope" not in report
    counts = report["source_to_output"]["counts"]
    assert counts["source_ink_pixels"] == 88
    assert counts["source_group_count"] == 3
    assert counts["source_neither_rendered_nor_near_verified_geometry_pixels"] == 2
    assert report["summary"]["all_original_source_pixels_in_group_ledger"]
    pending = [i for i in report["issues"] if i["status"] == "PENDING_TEXT_GROUP"]
    assert {i["source_support"]["text_group_id"] for i in pending} == {
        "local-unresolved-text", "outside-unresolved-text"
    }


def test_scoped_review_preserves_missing_pixels_boundary_limits_and_original_source(
    source_case, tmp_path
):
    report, _ = _review(source_case, tmp_path / "local", scoped=True)
    scope = report["review_scope"]
    assert scope["context_union_pixel_count"] == 3650
    assert not scope["full_parent_region_review_performed"]
    assert "does not establish completeness or acceptance" in scope["limitation"]
    counts = report["source_to_output"]["counts"]
    assert counts["source_ink_pixels"] == 66
    assert counts["source_group_count"] == 2
    assert counts["source_neither_rendered_nor_near_verified_geometry_pixels"] == 1
    assert counts["one_pixel_groups_preserved"] == 1
    assert report["summary"]["not_all_ink_explained"]
    assert report["summary"]["source_geometry_gate_pass"]
    assert report["summary"]["requires_manual_review"]
    assert report["summary"]["formal_object_count"] == 1
    assert not report["summary"]["full_source_reconstruction_proven"]
    assert "all_original_source_pixels_in_group_ledger" not in report["summary"]
    assert report["summary"]["all_in_scope_original_source_pixels_in_group_ledger"]
    pending = [i for i in report["issues"] if i["status"] == "PENDING_TEXT_GROUP"]
    assert [i["source_support"]["text_group_id"] for i in pending] == [
        "local-unresolved-text"
    ]
    ledger = json.loads((tmp_path / "local/quality_source_groups.json").read_text())
    assert ledger["review_scope"] == scope
    clipped = next(g for g in ledger["groups"] if g["support"]["source_pixel_count"] > 1)
    assert clipped["support"]["touches_context_union_frame"]
    assert not clipped["support"]["complete_source_component_extent_in_scope"]
    assert any(
        issue["reason"] == "SOURCE_GROUP_EXTENT_UNVERIFIED_AT_CONTEXT_SCOPE_BOUNDARY"
        and clipped["id"] in issue["source_group_ids"]
        for issue in report["issues"]
    )
    with Image.open(tmp_path / "local/quality_source_roi.png") as saved:
        assert np.array_equal(np.asarray(saved), source_case[0])


def test_invalid_contexts_are_rejected_before_saved_file_review(source_case, tmp_path):
    gray, dxf, objects, texts, manifest, checkpoint = source_case
    invalid = [[], [[0, 0, 161, 120]], [[0, 0, 20, 20]] * 9, [[True, 0, 20, 20]]]
    for contexts in invalid:
        changed = {**manifest, "connection_checkpoint": {**checkpoint, "context_rois": contexts}}
        with pytest.raises(ValueError, match="REVIEW_CONNECTION"):
            _connection_checkpoint_scope(changed, ROI)
    manifest["connection_checkpoint"] = {
        **checkpoint, "context_rois": [[0, 0, 161, 120]]
    }
    with pytest.raises(ValueError, match="OUTSIDE_PARENT_ROI"):
        run_quality_review(
            dxf, gray, ROI, DPI, objects, texts, [], manifest, tmp_path / "invalid"
        )
    assert not (tmp_path / "invalid/quality_review.json").exists()


def test_changed_scope_or_preserved_baseline_cannot_inherit_a_review(source_case, tmp_path):
    report, manifest = _review(source_case, tmp_path / "bound", scoped=True)
    _, dxf, objects, _, _, checkpoint = source_case
    assert source_identity(manifest)["connection_checkpoint_sha256"] == canonical_sha256(checkpoint)
    review_path = tmp_path / "bound/quality_review.json"
    assert verify_saved_review(review_path, dxf, objects, manifest)["valid"]
    for key, value in (
        ("context_rois", [[10, 10, 70, 60]]),
        ("baseline_dxf_sha256", "b" * 64),
        ("manifest_sha256", "c" * 64),
    ):
        changed = deepcopy(manifest)
        changed["connection_checkpoint"][key] = value
        result = verify_saved_review(review_path, dxf, objects, changed)
        assert not result["valid"]
        assert result["status"] == "STALE_REVIEW_PENDING"
        assert any(row["field"] == "source_identity" for row in result["mismatches"])
        assert result["current_binding"]["binding_sha256"] != report["binding"]["binding_sha256"]


def test_outside_context_geometry_still_gets_source_and_structure_checks(source_case, tmp_path):
    _, dxf, objects, _, _, _ = source_case
    bad = {
        "id": "outside-unsupported-and-mismatched",
        "kind": "LINE",
        "layer": "LINES",
        "geometry": {"start": [100, 100], "end": [129, 100]},
    }
    objects.append(bad)
    doc = ezdxf.readfile(dxf)
    mm = 25.4 / DPI
    entity = doc.modelspace().add_line(
        (100 * mm, 20 * mm), (130 * mm, 20 * mm), dxfattribs={"layer": "LINES"}
    )
    cad_io.mark(entity, bad)
    cad_io.save_native_dxf(doc, dxf)
    report, _ = _review(source_case, tmp_path / "bad-neighbor", scoped=True)
    assert report["summary"]["formal_object_count"] == 2
    assert not report["summary"]["safe_artifact_structure"]
    assert not report["summary"]["source_geometry_gate_pass"]
    assert report["summary"]["review_status"] == "REJECT_SAVED_ARTIFACT"
    rows = [i for i in report["issues"] if bad["id"] in i["object_ids"]]
    assert {i["status"] for i in rows} >= {"REJECT_STRUCTURE", "REJECT_SOURCE"}

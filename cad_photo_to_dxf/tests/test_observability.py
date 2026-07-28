from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import cv2
import ezdxf
import numpy as np

from app.debug_bundle import capture_debug_bundle
from app.image_loader import save_image
from app.observability import STAGE_SPECS
from app.optimized_trace import trace_image_optimized


class _MemorySink:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, Mapping[str, Any]]] = []

    def record(
        self,
        stage_key: str,
        *,
        image: np.ndarray | None = None,
        payload: Mapping[str, Any] | None = None,
        status: str = "captured",
    ) -> None:
        metadata = dict(payload or {})
        if image is not None:
            metadata["image_sha256"] = __import__("hashlib").sha256(
                np.ascontiguousarray(image).tobytes()
            ).hexdigest()
        self.records.append((stage_key, status, metadata))


def _synthetic_page() -> np.ndarray:
    image = np.full((240, 320, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (20, 20), (300, 220), (0, 0, 0), 3)
    cv2.line(image, (20, 120), (300, 120), (0, 0, 0), 3)
    cv2.line(image, (160, 20), (160, 220), (0, 0, 0), 3)
    cv2.putText(
        image,
        "A1",
        (50, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    return image


def test_observation_sink_does_not_change_final_structure() -> None:
    image = _synthetic_page()
    baseline = trace_image_optimized(image, enable_ocr=False)
    sink = _MemorySink()
    observed = trace_image_optimized(
        image,
        enable_ocr=False,
        observation_sink=sink,
    )

    assert baseline.final_structure is not None
    assert observed.final_structure is not None
    assert (
        baseline.final_structure.structure_id
        == observed.final_structure.structure_id
    )
    assert baseline.foreground_pixels == observed.foreground_pixels
    assert baseline.vertex_count == observed.vertex_count
    assert baseline.paths == observed.paths
    assert baseline.straight_lines == observed.straight_lines
    assert {record[0] for record in sink.records} == {
        spec.key for spec in STAGE_SPECS if spec.index < 26
    }


def test_debug_bundle_has_all_stages_metadata_and_pixel_lineage(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "page.png"
    save_image(input_path, _synthetic_page())
    bundle = tmp_path / "bundle"
    manifest_path = capture_debug_bundle(
        input_path,
        bundle,
        enable_ocr=False,
        dpi=300,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["passed"] is True
    assert manifest["stage_count"] == 26
    assert [stage["stage_id"] for stage in manifest["stages"]] == [
        spec.stage_id for spec in STAGE_SPECS
    ]
    assert manifest["data_source_contract"] == {
        "gui_preview": "FinalStructure",
        "dxf_export": "FinalStructure",
        "same_structure_id_required": True,
    }
    required_metadata = {
        "input_file_sha256",
        "page_index",
        "dpi",
        "algorithm_version",
        "application_source_digest",
        "git_worktree_dirty",
        "configuration_summary",
        "configuration_digest",
        "structure_id",
        "stage_id",
        "stage_name",
        "generated_at",
        "upstream_stage_ids",
    }
    for stage in manifest["stages"]:
        metadata = json.loads(
            (bundle / stage["metadata_path"]).read_text(encoding="utf-8")
        )
        assert required_metadata <= set(metadata)
        assert metadata["structure_id"] == manifest["structure_id"]
        assert (bundle / stage["data_path"]).is_file()
        for artifact in stage["artifacts"]:
            assert (bundle / artifact["path"]).is_file()
            file_metadata = json.loads(
                (bundle / artifact["metadata_path"]).read_text(encoding="utf-8")
            )
            assert required_metadata <= set(file_metadata)

    lineage = cv2.imread(
        str(bundle / manifest["pixel_lineage"]["path"]),
        cv2.IMREAD_GRAYSCALE,
    )
    assert lineage is not None
    assert lineage.shape == _synthetic_page().shape[:2]
    assert set(np.unique(lineage)).issubset({0, 1, 2, 3, 4, 5})
    dxf = ezdxf.readfile(bundle / manifest["dxf"]["path"])
    assert not dxf.audit().errors
    assert manifest["dxf"]["structure_id"] == manifest["structure_id"]


def test_ocr_overview_records_raw_and_rule_removed_views(
    monkeypatch,
) -> None:
    from app import ocr_pipeline

    monkeypatch.setattr(ocr_pipeline, "_recognize_overview", lambda _image: [])
    sink = _MemorySink()
    texts, _warnings = ocr_pipeline.recognize_text_candidates_optimized(
        _synthetic_page(),
        observation_sink=sink,
    )

    assert texts == ()
    keys = [record[0] for record in sink.records]
    assert keys == ["ocr_raw_tiles", "ocr_rule_removed_tiles"]
    assert sink.records[0][2]["used_by_ocr"] is True
    assert sink.records[1][2]["diagnostic_only"] is True

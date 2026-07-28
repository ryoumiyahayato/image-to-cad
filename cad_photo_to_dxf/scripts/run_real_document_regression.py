from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

import cv2
import ezdxf
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.optimized_trace import trace_image_optimized  # noqa: E402
from app.final_structure import FINAL_STRUCTURE_SCHEMA_VERSION  # noqa: E402
from app.preview_renderer import render_final_structure_preview  # noqa: E402
from app.trace_single_export import export_final_structure_dxf  # noqa: E402


EXPECTED_METRICS = {
    "structure_id",
    "source_size_px",
    "contour_count",
    "straight_line_count",
    "text_count",
    "logo_count",
    "signature_count",
    "foreground_pixels",
    "contour_vertex_count",
    "preview_sha256",
    "dxf_entity_count",
    "dxf_line_count",
    "dxf_text_count",
    "dxf_trace_path_count",
    "dxf_trace_vertex_count",
}
REQUIRED_PROVENANCE = {
    "source",
    "usage",
    "rights_basis",
    "review_status",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the complete trace, preview and DXF-export pipeline against "
            "the mandatory full-page real-document regression set."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/real_regression/manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/real-document-regression.json"),
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("output/real-document-regression"),
    )
    return parser


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Regression manifest must contain a JSON object")
    return value


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _array_sha256(value: np.ndarray) -> str:
    return sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def _validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    baseline_schema = int(manifest.get("final_structure_schema_version", 0))
    if baseline_schema != FINAL_STRUCTURE_SCHEMA_VERSION:
        raise ValueError(
            "Regression baseline schema does not match FinalStructure: "
            f"{baseline_schema} != {FINAL_STRUCTURE_SCHEMA_VERSION}"
        )
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("Real-document regression set must not be empty")
    minimum_documents = int(manifest.get("minimum_documents", 3))
    if len(documents) < minimum_documents:
        raise ValueError(
            f"Expected at least {minimum_documents} real documents, "
            f"found {len(documents)}"
        )

    ids: set[str] = set()
    source_documents: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, raw_document in enumerate(documents):
        if not isinstance(raw_document, dict):
            raise ValueError(f"Document {index + 1} must be a JSON object")
        document_id = str(raw_document.get("id", "")).strip()
        source_document = str(raw_document.get("source_document", "")).strip()
        source_path = str(raw_document.get("source_path", "")).strip()
        expected_hash = str(raw_document.get("sha256", "")).strip().lower()
        provenance = raw_document.get("provenance")
        expected = raw_document.get("expected")
        if not document_id or document_id in ids:
            raise ValueError(f"Document {index + 1} has a missing or duplicate id")
        if not source_document:
            raise ValueError(f"{document_id}: source_document is required")
        if not source_path:
            raise ValueError(f"{document_id}: source_path is required")
        if len(expected_hash) != 64:
            raise ValueError(f"{document_id}: sha256 must be a full digest")
        if raw_document.get("full_page") is not True:
            raise ValueError(f"{document_id}: only complete pages are allowed")
        if raw_document.get("cropped") is not False:
            raise ValueError(f"{document_id}: cropped fixtures are forbidden")
        if (
            not isinstance(provenance, dict)
            or not REQUIRED_PROVENANCE.issubset(provenance)
            or any(not str(provenance[key]).strip() for key in REQUIRED_PROVENANCE)
        ):
            raise ValueError(f"{document_id}: provenance metadata is incomplete")
        if not isinstance(expected, dict):
            raise ValueError(f"{document_id}: expected metrics are required")
        missing_metrics = EXPECTED_METRICS - set(expected)
        if missing_metrics:
            raise ValueError(
                f"{document_id}: expected metrics missing "
                f"{', '.join(sorted(missing_metrics))}"
            )
        ids.add(document_id)
        source_documents.add(source_document)
        validated.append(raw_document)

    minimum_sources = int(manifest.get("minimum_source_documents", 2))
    if len(source_documents) < minimum_sources:
        raise ValueError(
            f"Expected at least {minimum_sources} independent source documents, "
            f"found {len(source_documents)}"
        )
    return validated


def _resolve_source(source_path: str) -> Path:
    resolved = (PROJECT_ROOT / source_path).resolve()
    if not resolved.is_relative_to(PROJECT_ROOT):
        raise ValueError("Regression source must remain inside the project")
    return resolved


def _measure_document(
    document: dict[str, Any],
    *,
    artifacts: Path,
) -> tuple[dict[str, Any], list[str]]:
    document_id = str(document["id"])
    source_path = _resolve_source(str(document["source_path"]))
    errors: list[str] = []
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing regression page: {source_path}")
    observed_hash = _file_sha256(source_path)
    if observed_hash != str(document["sha256"]).lower():
        errors.append(
            f"source sha256 mismatch: expected {document['sha256']}, "
            f"observed {observed_hash}"
        )

    image = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"OpenCV could not load {source_path}")
    started = perf_counter()
    trace_result = trace_image_optimized(
        image,
        enable_ocr=bool(document.get("enable_ocr", True)),
    )
    structure = trace_result.final_structure
    if structure is None:
        raise AssertionError("Trace pipeline did not produce FinalStructure")
    structure.assert_valid()

    preview = render_final_structure_preview(structure)
    if preview.shape != structure.contour_binary.shape:
        errors.append("preview shape differs from FinalStructure coordinates")

    artifacts.mkdir(parents=True, exist_ok=True)
    dxf_path = artifacts / f"{document_id}.dxf"
    export_result = export_final_structure_dxf(structure, dxf_path)
    if export_result.structure_id != structure.structure_id:
        errors.append("preview and DXF export did not consume the same structure")

    dxf_document = ezdxf.readfile(dxf_path)
    audit = dxf_document.audit()
    if audit.errors:
        errors.append(f"DXF audit reported {len(audit.errors)} errors")
    modelspace = dxf_document.modelspace()
    metrics: dict[str, Any] = {
        "structure_id": structure.structure_id,
        "source_size_px": list(structure.source_size_px),
        "contour_count": len(structure.contours),
        "straight_line_count": len(structure.straight_lines),
        "text_count": len(structure.texts),
        "logo_count": len(structure.logos),
        "signature_count": len(structure.signatures),
        "foreground_pixels": int(
            np.count_nonzero(structure.contour_binary == 0)
        ),
        "contour_vertex_count": sum(
            len(path.points) for path in structure.contours
        ),
        "preview_sha256": _array_sha256(preview),
        "dxf_entity_count": len(modelspace),
        "dxf_line_count": int(export_result.line_count),
        "dxf_text_count": int(export_result.text_count),
        "dxf_trace_path_count": int(export_result.trace_path_count),
        "dxf_trace_vertex_count": int(export_result.trace_vertex_count),
    }
    expected = document["expected"]
    for key in sorted(EXPECTED_METRICS):
        if metrics[key] != expected[key]:
            errors.append(
                f"{key} mismatch: expected {expected[key]!r}, "
                f"observed {metrics[key]!r}"
            )
    result = {
        "id": document_id,
        "source_path": str(source_path.relative_to(PROJECT_ROOT).as_posix()),
        "source_sha256": observed_hash,
        "elapsed_seconds": round(perf_counter() - started, 3),
        "metrics": metrics,
        "dxf_path": str(dxf_path.resolve()),
        "errors": errors,
        "passed": not errors,
    }
    return result, errors


def main() -> int:
    args = _parser().parse_args()
    manifest_path = args.manifest.resolve()
    output_path = args.output.resolve()
    artifacts = args.artifacts.resolve()
    report: dict[str, Any] = {
        "manifest": str(manifest_path),
        "passed": False,
        "documents": [],
        "errors": [],
    }
    try:
        manifest = _load_manifest(manifest_path)
        documents = _validate_manifest(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report["errors"].append(str(exc))
        documents = []

    for document in documents:
        try:
            result, errors = _measure_document(
                document,
                artifacts=artifacts,
            )
            report["documents"].append(result)
            report["errors"].extend(
                f"{document['id']}: {message}" for message in errors
            )
        except Exception as exc:  # keep the full set observable after one failure
            message = f"{document['id']}: {type(exc).__name__}: {exc}"
            report["documents"].append(
                {
                    "id": document["id"],
                    "passed": False,
                    "errors": [message],
                }
            )
            report["errors"].append(message)

    report["document_count"] = len(report["documents"])
    report["passed"] = bool(documents) and not report["errors"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

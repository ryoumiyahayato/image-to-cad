from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Mapping

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.processing_contract import (  # noqa: E402
    LayoutProfileSelection,
    ProductionProcessingConfig,
    ProductionProcessingService,
    build_processing_cache_key,
    cache_key_matches,
    file_content_sha256,
)
from app.trace_storage import load_trace_cache, save_trace_cache  # noqa: E402


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    return file_content_sha256(path)


def _content_summary(structure: Any) -> dict[str, object]:
    payload = {
        "structure_id": structure.structure_id,
        "source_size_px": list(structure.source_size_px),
        "contour_count": len(structure.contours),
        "straight_line_count": len(structure.straight_lines),
        "text_count": len(structure.texts),
        "logo_count": len(structure.logos),
        "signature_count": len(structure.signatures),
    }
    payload["sha256"] = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return payload


def _architecture_checks() -> dict[str, bool]:
    app_root = PROJECT_ROOT / "app"
    active_gui = (app_root / "gui_librecad_release.py").read_text(
        encoding="utf-8"
    )
    exact_gui = (app_root / "gui_exact_release.py").read_text(
        encoding="utf-8"
    )
    generic_sources = "\n".join(
        (app_root / name).read_text(encoding="utf-8")
        for name in (
            "ocr_pipeline.py",
            "ocr_layout.py",
            "logo_detection.py",
            "signature_overlay.py",
            "content_ownership.py",
        )
    )
    forbidden = (
        "_right_title_block_region",
        "_infer_ruled_title_block_labels",
        "DESIGNGROUP",
        "建设单位",
        "项目负责",
        "会签",
    )
    return {
        "no_fixed_template_or_field_dictionary_in_generic_flow": (
            all(token not in generic_sources for token in forbidden)
        ),
        "single_and_batch_use_one_processing_service": (
            active_gui.count(
                "ProductionProcessingService.process_page("
            )
            == 2
            and "trace_image_optimized(" not in active_gui
        ),
        "active_cache_restore_sets_final_structure": (
            "self._final_structure = structure" in active_gui
            and "self._preview_structure_id = structure.structure_id"
            in active_gui
        ),
        "text_review_rebuilds_final_structure": (
            "_replace_final_structure_texts" in exact_gui
            and "build_final_structure(" in exact_gui
        ),
        "preview_and_export_guard_share_structure_id": (
            "_preview_structure_id" in exact_gui
            and "structure.structure_id" in exact_gui
        ),
    }


def _document_record(
    document: Mapping[str, Any],
    *,
    expected_structure_id: str,
    artifacts: Path,
    repeat: bool,
) -> dict[str, object]:
    raster_path = Path(str(document["raster_path"]))
    image = cv2.imread(str(raster_path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"Could not load validation page: {raster_path}")
    config = ProductionProcessingConfig(
        source_dpi=float(document["page"]["dpi"]),
        enable_ocr=True,
    )
    content_hash = _file_sha256(raster_path)
    key = build_processing_cache_key(
        input_content_sha256=content_hash,
        page_index=int(document["page"]["number"]) - 1,
        config=config,
    )
    started = perf_counter()
    result = ProductionProcessingService.process_page(image, config)
    structure = result.final_structure
    if structure is None:
        raise AssertionError("Production service returned no FinalStructure")
    summary = _content_summary(structure)

    repeated_summary = summary
    if repeat:
        repeated = ProductionProcessingService.process_page(image, config)
        if repeated.final_structure is None:
            raise AssertionError("Repeated processing returned no FinalStructure")
        repeated_summary = _content_summary(repeated.final_structure)

    artifacts.mkdir(parents=True, exist_ok=True)
    cache_path = artifacts / f"{document['id']}.npz"
    save_trace_cache(
        cache_path,
        result,
        cache_key=key.payload(),
    )
    stored = load_trace_cache(cache_path)
    if stored.final_structure is None:
        raise AssertionError("Cache roundtrip returned no FinalStructure")

    key_variants = {
        "content": build_processing_cache_key(
            input_content_sha256=(
                ("0" if content_hash[0] != "0" else "1")
                + content_hash[1:]
            ),
            page_index=int(document["page"]["number"]) - 1,
            config=config,
        ),
        "ocr": build_processing_cache_key(
            input_content_sha256=content_hash,
            page_index=int(document["page"]["number"]) - 1,
            config=replace(config, enable_ocr=False),
        ),
        "dpi": build_processing_cache_key(
            input_content_sha256=content_hash,
            page_index=int(document["page"]["number"]) - 1,
            config=replace(config, source_dpi=config.source_dpi + 1.0),
        ),
        "algorithm": build_processing_cache_key(
            input_content_sha256=content_hash,
            page_index=int(document["page"]["number"]) - 1,
            config=replace(
                config,
                algorithm_version=f"{config.algorithm_version}-changed",
            ),
        ),
        "model": build_processing_cache_key(
            input_content_sha256=content_hash,
            page_index=int(document["page"]["number"]) - 1,
            config=replace(
                config,
                model_version=f"{config.model_version}-changed",
            ),
        ),
        "configuration": build_processing_cache_key(
            input_content_sha256=content_hash,
            page_index=int(document["page"]["number"]) - 1,
            config=replace(config, foreground_threshold=128),
        ),
        "profile": build_processing_cache_key(
            input_content_sha256=content_hash,
            page_index=int(document["page"]["number"]) - 1,
            config=replace(
                config,
                layout_profile=LayoutProfileSelection(
                    enabled=True,
                    name="validation-profile",
                ),
            ),
        ),
    }
    checks = {
        "structure_matches_phase10_baseline": (
            structure.structure_id == expected_structure_id
        ),
        "same_input_same_structure_id": (
            summary["structure_id"]
            == repeated_summary["structure_id"]
        ),
        "same_input_same_content_summary": (
            summary["sha256"] == repeated_summary["sha256"]
        ),
        "cache_key_roundtrip_matches": cache_key_matches(
            stored.cache_key,
            key,
        ),
        "cache_roundtrip_structure_matches": (
            stored.final_structure.structure_id
            == structure.structure_id
        ),
        "all_required_key_changes_miss": all(
            variant.digest != key.digest
            and not cache_key_matches(stored.cache_key, variant)
            for variant in key_variants.values()
        ),
        "profile_default_disabled": (
            not config.layout_profile.enabled
            and config.layout_profile.name == "disabled"
        ),
        "final_structure_masks_immutable": (
            not structure.contour_binary.flags.writeable
            and (
                structure.preview_binary is None
                or not structure.preview_binary.flags.writeable
            )
        ),
    }
    return {
        "id": str(document["id"]),
        "raster_path": str(raster_path.resolve()),
        "raster_sha256": content_hash,
        "page": dict(document["page"]),
        "processing_config": config.payload(),
        "cache_key": key.payload(),
        "cache_key_digest": key.digest,
        "cache_path": str(cache_path.resolve()),
        "content_summary": summary,
        "elapsed_seconds": round(perf_counter() - started, 3),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _run(args: argparse.Namespace) -> int:
    manifest_path = args.input_manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_path = args.expected.resolve()
    expected_payload = json.loads(expected_path.read_text(encoding="utf-8"))
    expected = {
        str(document["id"]): str(document["structure_id"])
        for document in expected_payload["documents"]
    }
    documents = [
        _document_record(
            document,
            expected_structure_id=expected[str(document["id"])],
            artifacts=args.artifacts.resolve(),
            repeat=index == 0,
        )
        for index, document in enumerate(manifest["documents"])
    ]
    architecture = _architecture_checks()
    acceptance = {
        "minimum_ten_pages": len(documents) >= 10,
        "all_documents_passed": all(
            bool(document["passed"]) for document in documents
        ),
        "all_architecture_checks_passed": all(architecture.values()),
        "same_evidence_is_deterministic": all(
            document["checks"]["same_input_same_structure_id"]
            and document["checks"]["same_input_same_content_summary"]
            for document in documents
        ),
        "all_cache_key_mutations_miss": all(
            document["checks"]["all_required_key_changes_miss"]
            for document in documents
        ),
    }
    payload = {
        "schema_version": 1,
        "input_manifest": str(manifest_path),
        "input_manifest_sha256": _file_sha256(manifest_path),
        "expected_phase10": str(expected_path),
        "expected_phase10_sha256": _file_sha256(expected_path),
        "document_count": len(documents),
        "architecture_checks": architecture,
        "acceptance": acceptance,
        "documents": documents,
    }
    _write_json(args.output.resolve(), payload)
    print(args.output.resolve())
    return 0 if not args.enforce or all(acceptance.values()) else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the production processing service, complete cache key, "
            "disabled layout profile and FinalStructure GUI contract."
        )
    )
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--enforce", action="store_true")
    return parser


def main() -> int:
    return _run(_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable

import ezdxf


PAGE_LAYER_PREFIX = re.compile(r"^PAGE_\d{3}_(.+)$")


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _base_layer(layer_name: str) -> str:
    match = PAGE_LAYER_PREFIX.fullmatch(str(layer_name))
    return match.group(1) if match is not None else str(layer_name)


def _layer_visibility(document: ezdxf.document.Drawing) -> dict[str, bool]:
    visibility: dict[str, bool] = {}
    for layer in document.layers:
        visibility[_base_layer(str(layer.dxf.name))] = not layer.is_off()
    return visibility


def _audit_one(
    path: Path,
    candidate_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    document = ezdxf.readfile(path)
    audit = document.audit()
    layer_types: dict[str, Counter[str]] = defaultdict(Counter)
    for entity in document.modelspace():
        layer_types[_base_layer(str(entity.dxf.layer))][
            entity.dxftype()
        ] += 1

    def layer_total(name: str) -> int:
        return sum(layer_types[name].values())

    native_text_entities = list(document.modelspace().query("TEXT"))
    native_ocr_text_entities = [
        entity
        for entity in native_text_entities
        if _base_layer(str(entity.dxf.layer)) == "OCR_TEXT"
    ]
    metrics = dict(candidate_metrics or {})
    metrics.update(
        {
            "path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "modelspace_entity_count": len(document.modelspace()),
            "native_TEXT_count": len(native_ocr_text_entities),
            "all_TEXT_entity_count": len(native_text_entities),
            "fallback_outline_entity_count": layer_total(
                "TEXT_FALLBACK_OUTLINE"
            ),
            "source_text_outline_entity_count": layer_total(
                "SOURCE_TEXT_OUTLINE"
            ),
            "uncertain_text_outline_entity_count": layer_total(
                "UNCERTAIN_TEXT_OUTLINE"
            ),
            "text_symbol_entity_count": layer_total("TRACE_TEXT_SYMBOL"),
            "residual_entity_count": layer_total("RESIDUAL_GRAPHIC"),
            "dxf_audit_error_count": len(audit.errors),
            "layer_visible": _layer_visibility(document),
            "layer_entity_types": {
                layer_name: dict(sorted(counts.items()))
                for layer_name, counts in sorted(layer_types.items())
            },
            "native_text_entity_type_check": (
                len(native_text_entities) == len(native_ocr_text_entities)
                and all(
                    entity.dxftype() == "TEXT"
                    for entity in native_ocr_text_entities
                )
            ),
        }
    )
    return metrics


def _contract_inputs(
    report_path: Path,
) -> Iterable[tuple[Path, dict[str, Any]]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for document in report["documents"]:
        yield Path(str(document["dxf_path"])), {
            "id": str(document["id"]),
            "page": dict(document["page"]),
            "ocr_candidate_count": int(document["ocr_candidate_count"]),
            "native_text_candidate_count": int(document["text_count"]),
            "fallback_candidate_count": int(document["fallback_count"]),
            "residual_candidate_count": int(document["residual_count"]),
            "downgrade_reasons": dict(document["downgrade_reasons"]),
        }


def _user_report_inputs(
    report_path: Path,
) -> Iterable[tuple[Path, dict[str, Any]]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for page in report["pages"]:
        yield Path(str(page["dxf"])), {
            "id": f"user-pdf-page-{int(page['page']):03d}",
            "page": int(page["page"]),
            "ocr_candidate_count": int(page["ocr_candidate_count"]),
            "native_text_candidate_count": int(page["ocr_text_line_count"]),
            "fallback_candidate_count": int(
                page["text_fallback_outline_count"]
            ),
            "residual_candidate_count": int(
                page["residual_graphic_count"]
            ),
            "downgrade_reasons": dict(page["text_downgrade_reasons"]),
            "structure_id": str(page["structure_id"]),
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report-kind",
        choices=("text-contract", "user-export"),
        required=True,
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report_path = args.report.resolve()
    inputs = (
        _contract_inputs(report_path)
        if args.report_kind == "text-contract"
        else _user_report_inputs(report_path)
    )
    records = [
        _audit_one(path.resolve(), candidate_metrics)
        for path, candidate_metrics in inputs
    ]
    payload = {
        "schema_version": 1,
        "report_kind": args.report_kind,
        "source_report": str(report_path),
        "dxf_count": len(records),
        "all_dxf_audits_passed": all(
            int(record["dxf_audit_error_count"]) == 0
            for record in records
        ),
        "documents": records,
    }
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(output_path)
    return 0 if payload["all_dxf_audits_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, cast

import numpy as np


REPORT_SCHEMA_VERSION = "1.3"


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        dataclass_value = cast(Any, value)
        return {
            key: _json_value(item)
            for key, item in asdict(dataclass_value).items()
        }
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_json_report(path: str | Path, report: dict[str, Any]) -> Path:
    """Write a UTF-8 JSON report atomically without shared temp-name races."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(
                _json_value(report),
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return output_path


def build_lineage(
    raw_lines: Iterable[Any],
    final_lines: Iterable[Any],
) -> dict[str, Any]:
    """Build bidirectional raw-source to final-entity lineage."""
    raw_source_ids: list[str] = []
    for line in raw_lines:
        raw_source_ids.extend(str(item) for item in getattr(line, "source_ids", ()))
    raw_source_ids = sorted(set(raw_source_ids))

    final_entities: list[dict[str, Any]] = []
    source_to_final: dict[str, list[str]] = {source_id: [] for source_id in raw_source_ids}
    for index, line in enumerate(final_lines, start=1):
        entity_id = f"LINE-{index:06d}"
        source_ids = sorted(set(str(item) for item in getattr(line, "source_ids", ())))
        operations = list(dict.fromkeys(str(item) for item in getattr(line, "history", ())))
        final_entities.append(
            {
                "entity_id": entity_id,
                "layer": getattr(line, "layer", "DETAIL"),
                "source_ids": source_ids,
                "operations": operations,
                "classification_confidence": float(
                    getattr(line, "classification_confidence", 1.0)
                ),
                "classification_reasons": list(
                    getattr(line, "classification_reasons", ())
                ),
                "geometry": {
                    "start": [float(line.x1), float(line.y1)],
                    "end": [float(line.x2), float(line.y2)],
                    "width_px": float(line.width),
                },
            }
        )
        for source_id in source_ids:
            source_to_final.setdefault(source_id, []).append(entity_id)

    dropped = sorted(
        source_id for source_id, entity_ids in source_to_final.items() if not entity_ids
    )
    return {
        "raw_source_count": len(raw_source_ids),
        "final_entity_count": len(final_entities),
        "source_to_final": source_to_final,
        "dropped_source_ids": dropped,
        "final_entities": final_entities,
    }

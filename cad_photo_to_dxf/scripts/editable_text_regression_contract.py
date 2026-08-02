from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from collections.abc import Iterable, Mapping
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from typing import Any

import ezdxf


PHASE12_CONTRACT = "phase12-architecture-safety-v1"
ARCHITECTURE_CONTRACT = PHASE12_CONTRACT
EDITABLE_TEXT_CONTRACT = "non-destructive-editable-text-v1"
BASELINE_SOURCE_COMMIT = "5f7846e00b41913c003f178558a110e6475c0ee0"
CANDIDATE_COMMIT = "80be85aba985e457bc7bff1e9ece49f50e7a46d2"
CONTRACT_SCHEMA_VERSION = 2
PHASE12_COMMIT = "6f5f69329aabf0bd3a7eda84baf66eb1959bdcba"
PHASE12_MANIFEST_PATH = "cad_photo_to_dxf/tests/real_regression/manifest.json"
PHASE12_MANIFEST_BLOB = "533ae15afcef24dd4444f9acc3d504bbd94d9c87"
PHASE12_EXPECTED_TITLE = "perf: complete final acceptance baseline (phase 12)"
PHASE12_RECORDED_TAG = "baseline/phase12-final-acceptance-2026-07-30"
PHASE12_TAG_REF_STATUS = "absent"
SUCCESS_STATUS = (
    "Editable-text regression contract reconciled using immutable "
    "commit/blob anchors; P1B-3 rerun required."
)

TEXT_LAYER = "OCR_TEXT"
SOURCE_OUTLINE_LAYER = "SOURCE_TEXT_OUTLINE"
TEXT_SYMBOL_LAYER = "TRACE_TEXT_SYMBOL"
UNCERTAIN_TEXT_LAYER = "TEXT_FALLBACK_OUTLINE"
PROTECTED_LAYER_TOKENS = ("LOGO", "SIGNATURE", "RESIDUAL", "UNCERTAIN")
TEXT_XDATA_APP = "OCR_TEXT_LINE"
TEXT_CONTRACT_XDATA_APP = "TEXT_OUTPUT_CONTRACT"
TEXT_GEOMETRY_XDATA_APP = "OCR_TEXT_GEOMETRY"

SUPERSEDED_CONTRACT_ERROR = (
    "Phase-12 routing expectations are historical and cannot validate "
    "current non-destructive editable TEXT counts."
)


@dataclass(frozen=True)
class Phase12ImmutableAnchor:
    commit_sha: str = PHASE12_COMMIT
    manifest_path: str = PHASE12_MANIFEST_PATH
    manifest_blob_sha: str = PHASE12_MANIFEST_BLOB
    expected_commit_title: str = PHASE12_EXPECTED_TITLE
    contract_identifier: str = PHASE12_CONTRACT
    recorded_tag_name: str = PHASE12_RECORDED_TAG
    tag_ref_status: str = PHASE12_TAG_REF_STATUS
    verification_timestamp: str = ""
    verification_method: str = (
        "git cat-file/rev-parse/show against immutable commit and blob"
    )


def _git(repository: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ValueError(
            f"Git verification failed for {' '.join(args)}: {detail}"
        ) from exc
    return result.stdout.strip()


def verify_phase12_anchor(
    repository: Path,
    anchor: Phase12ImmutableAnchor = Phase12ImmutableAnchor(),
) -> dict[str, Any]:
    object_type = _git(repository, "cat-file", "-t", anchor.commit_sha)
    if object_type != "commit":
        raise ValueError(
            f"Phase-12 anchor object is {object_type!r}, expected 'commit'"
        )
    resolved_commit = _git(repository, "rev-parse", f"{anchor.commit_sha}^{{commit}}")
    if resolved_commit != anchor.commit_sha:
        raise ValueError(
            f"Phase-12 commit mismatch: {resolved_commit} != {anchor.commit_sha}"
        )
    title = _git(repository, "show", "-s", "--format=%s", anchor.commit_sha)
    if title != anchor.expected_commit_title:
        raise ValueError(
            "Phase-12 commit title mismatch: "
            f"{title!r} != {anchor.expected_commit_title!r}"
        )
    blob = _git(
        repository,
        "rev-parse",
        f"{anchor.commit_sha}:{anchor.manifest_path}",
    )
    if blob != anchor.manifest_blob_sha:
        raise ValueError(
            f"Phase-12 manifest blob mismatch: {blob} != "
            f"{anchor.manifest_blob_sha}"
        )
    remote_tag_status = _remote_tag_status(
        repository,
        anchor.recorded_tag_name,
    )
    return {
        **asdict(anchor),
        "object_type": object_type,
        "resolved_commit_sha": resolved_commit,
        "observed_commit_title": title,
        "observed_manifest_blob_sha": blob,
        "tag_ref_observed": remote_tag_status,
        "local_tag_ref_observed": _local_tag_status(
            repository,
            anchor.recorded_tag_name,
        ),
        "verified": True,
    }


def _local_tag_status(repository: Path, tag_name: str) -> str:
    return (
        "present"
        if subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/tags/{tag_name}",
            ],
            check=False,
        ).returncode
        == 0
        else "absent"
    )


def _remote_tag_status(repository: Path, tag_name: str) -> str:
    remotes = _git(repository, "remote").splitlines()
    if "origin" not in remotes:
        return "absent"
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "ls-remote",
            "--tags",
            "origin",
            f"refs/tags/{tag_name}",
            f"refs/tags/{tag_name}^{{}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "absent"
    return "present" if result.stdout.strip() else "absent"


def verify_current_manifest_blob(
    repository: Path,
    *,
    ref: str,
    manifest_path: str = PHASE12_MANIFEST_PATH,
    expected_blob_sha: str = PHASE12_MANIFEST_BLOB,
) -> str:
    observed = _git(repository, "rev-parse", f"{ref}:{manifest_path}")
    if observed != expected_blob_sha:
        raise ValueError(
            f"Current manifest blob mismatch at {ref}: "
            f"{observed} != {expected_blob_sha}"
        )
    return observed


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return sha256(_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_json_from_commit(
    repository: Path,
    *,
    commit_sha: str,
    manifest_path: str,
) -> dict[str, Any]:
    value = json.loads(
        _git(repository, "show", f"{commit_sha}:{manifest_path}")
    )
    if not isinstance(value, dict):
        raise ValueError(
            f"Historical manifest {commit_sha}:{manifest_path} must be an object"
        )
    return value


def _materialize_commit(
    repository: Path,
    *,
    commit_sha: str,
    destination: Path,
) -> None:
    """Extract an immutable commit tree without mutating the Git directory."""
    archive_path = destination.parent / "historical-commit.tar"
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "archive",
            "--format=tar",
            "--output",
            str(archive_path),
            commit_sha,
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                raise ValueError(
                    f"Historical archive member escapes destination: {member.name}"
                )
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(
                    f"Unsupported historical archive member: {member.name}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(
                    f"Unable to read historical archive member: {member.name}"
                )
            target.write_bytes(source.read())
    archive_path.unlink()


def require_explicit_contract(contract: str | None) -> str:
    value = (contract or "").strip()
    if not value:
        raise ValueError(
            "A contract version is required; pass "
            f"--contract {EDITABLE_TEXT_CONTRACT!s}."
        )
    if value not in {ARCHITECTURE_CONTRACT, EDITABLE_TEXT_CONTRACT}:
        raise ValueError(f"Unknown regression contract: {value}")
    return value


def select_baseline_manifest(
    *,
    contract: str | None,
    architecture_manifest: Path,
    editable_text_manifest: Path,
    validation_scope: str,
) -> Path:
    selected = require_explicit_contract(contract)
    if (
        selected == ARCHITECTURE_CONTRACT
        and validation_scope == "editable-text-geometry"
    ):
        raise ValueError(SUPERSEDED_CONTRACT_ERROR)
    path = (
        architecture_manifest
        if selected == ARCHITECTURE_CONTRACT
        else editable_text_manifest
    )
    if not path.is_file():
        raise FileNotFoundError(f"Baseline manifest does not exist: {path}")
    manifest = load_json(path)
    manifest_contract = str(manifest.get("contract_version", "")).strip()
    if selected == EDITABLE_TEXT_CONTRACT:
        if manifest_contract != EDITABLE_TEXT_CONTRACT:
            raise ValueError(
                "Editable-text baseline manifest contract_version does not match "
                f"{EDITABLE_TEXT_CONTRACT}."
            )
        source = str(manifest.get("baseline_source_commit", "")).strip()
        if source != BASELINE_SOURCE_COMMIT:
            raise ValueError(
                "Editable-text baseline source commit mismatch: "
                f"{source!r} != {BASELINE_SOURCE_COMMIT!r}"
            )
    return path



def validate_fixture_hashes(
    manifest: Mapping[str, Any],
    source_root: Path,
) -> list[dict[str, str]]:
    verified: list[dict[str, str]] = []
    for document in manifest.get("documents", []):
        if not isinstance(document, Mapping):
            raise ValueError("Regression documents must be objects")
        page_id = str(document.get("id", "")).strip()
        for path_key, hash_key in (
            ("source_path", "sha256"),
            ("original_path", "original_sha256"),
        ):
            relative = Path(str(document.get(path_key, "")))
            path = (source_root / relative).resolve()
            if not path.is_relative_to(source_root.resolve()) or not path.is_file():
                raise ValueError(f"{page_id}: fixture missing: {relative}")
            observed = file_sha256(path)
            expected = str(document.get(hash_key, "")).lower()
            if observed != expected:
                raise ValueError(
                    f"{page_id}: input fixture hash changed for {relative}: "
                    f"{observed} != {expected}"
                )
            verified.append(
                {
                    "page_id": page_id,
                    "path": relative.as_posix(),
                    "sha256": observed,
                }
            )
    return verified


def _normalise(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value == 0:
            return 0.0
        return round(value, 9)
    if isinstance(value, Mapping):
        return {
            str(key): _normalise(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if hasattr(value, "x") and hasattr(value, "y"):
        result = [float(value.x), float(value.y)]
        if hasattr(value, "z"):
            result.append(float(value.z))
        return _normalise(result)
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _xdata_values(entity: Any, appid: str) -> list[tuple[int, Any]]:
    try:
        return [
            (int(tag.code), _normalise(tag.value))
            for tag in entity.get_xdata(appid)
        ]
    except Exception:
        return []


def _entity_payload(entity: Any) -> dict[str, Any]:
    entity_type = entity.dxftype()
    layer = str(entity.dxf.get("layer", "0"))
    payload: dict[str, Any] = {"type": entity_type, "layer": layer}
    if entity_type == "LINE":
        payload.update(
            start=_normalise(entity.dxf.start),
            end=_normalise(entity.dxf.end),
        )
    elif entity_type == "LWPOLYLINE":
        payload.update(
            closed=bool(entity.closed),
            points=_normalise(list(entity.get_points("xyseb"))),
        )
    elif entity_type == "POLYLINE":
        payload.update(
            closed=bool(entity.is_closed),
            points=_normalise(
                [vertex.dxf.location for vertex in entity.vertices]
            ),
        )
    elif entity_type in {"CIRCLE", "ARC"}:
        payload.update(
            center=_normalise(entity.dxf.center),
            radius=_normalise(float(entity.dxf.radius)),
        )
        if entity_type == "ARC":
            payload.update(
                start_angle=_normalise(float(entity.dxf.start_angle)),
                end_angle=_normalise(float(entity.dxf.end_angle)),
            )
    elif entity_type == "SPLINE":
        payload.update(
            degree=int(entity.dxf.degree),
            flags=int(entity.dxf.flags),
            control_points=_normalise(list(entity.control_points)),
            fit_points=_normalise(list(entity.fit_points)),
            knots=_normalise(list(entity.knots())),
        )
    elif entity_type == "INSERT":
        payload.update(
            name=str(entity.dxf.name),
            insert=_normalise(entity.dxf.insert),
            rotation=_normalise(float(entity.dxf.get("rotation", 0.0))),
            xscale=_normalise(float(entity.dxf.get("xscale", 1.0))),
            yscale=_normalise(float(entity.dxf.get("yscale", 1.0))),
            zscale=_normalise(float(entity.dxf.get("zscale", 1.0))),
        )
    elif entity_type == "TEXT":
        payload.update(
            text=str(entity.dxf.text),
            insert=_normalise(entity.dxf.insert),
            align_point=_normalise(entity.dxf.get("align_point")),
            height=_normalise(float(entity.dxf.height)),
            width=_normalise(float(entity.dxf.get("width", 1.0))),
            rotation=_normalise(float(entity.dxf.get("rotation", 0.0))),
            style=str(entity.dxf.get("style", "Standard")),
            halign=int(entity.dxf.get("halign", 0)),
            valign=int(entity.dxf.get("valign", 0)),
        )
    else:
        attributes = {
            key: value
            for key, value in entity.dxfattribs().items()
            if key not in {"handle", "owner", "paperspace"}
        }
        payload["attributes"] = _normalise(attributes)
    return payload


def _sorted_entities(entities: Iterable[Any]) -> list[dict[str, Any]]:
    payloads = [_entity_payload(entity) for entity in entities]
    return sorted(payloads, key=lambda value: _json_bytes(value))


def _line_semantics(entity: Any, page_id: str) -> dict[str, Any]:
    line_xdata = _xdata_values(entity, TEXT_XDATA_APP)
    contract_xdata = _xdata_values(entity, TEXT_CONTRACT_XDATA_APP)
    integers = [value for code, value in line_xdata if code == 1070]
    floats = [value for code, value in line_xdata if code == 1040]
    line_index = int(integers[0]) if integers else -1
    confidence = float(floats[0]) if floats else None
    contract_strings = [value for code, value in contract_xdata if code == 1000]
    candidate_id = f"{page_id}:{line_index:06d}"
    return {
        "page_id": page_id,
        "candidate_id": candidate_id,
        "line_index": line_index,
        "ocr_text": str(entity.dxf.text),
        "confidence": _normalise(confidence),
        "text_emit_eligible": True,
        "primary_semantic_layer": str(entity.dxf.layer),
        "entity_type": entity.dxftype(),
        "output_state": contract_strings[0] if contract_strings else "editable_text",
    }


def _predicted_visible_bounds(
    *,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    rotation: float,
) -> list[list[float]]:
    from math import cos, radians, sin

    angle = radians(rotation)
    ux = (cos(angle), sin(angle))
    uy = (-sin(angle), cos(angle))
    half_width = width * 0.5
    half_height = height * 0.5
    points = []
    for x_sign, y_sign in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        points.append(
            [
                center_x + ux[0] * half_width * x_sign + uy[0] * half_height * y_sign,
                center_y + ux[1] * half_width * x_sign + uy[1] * half_height * y_sign,
            ]
        )
    return _normalise(points)


def _line_geometry(entity: Any, page_id: str) -> dict[str, Any]:
    semantics = _line_semantics(entity, page_id)
    geometry_xdata = _xdata_values(entity, TEXT_GEOMETRY_XDATA_APP)
    floats = [float(value) for code, value in geometry_xdata if code == 1040]
    target_center_x = floats[0] if len(floats) > 0 else float(entity.dxf.insert.x)
    target_center_y = floats[1] if len(floats) > 1 else float(entity.dxf.insert.y)
    target_width = floats[2] if len(floats) > 2 else 0.0
    target_height = floats[3] if len(floats) > 3 else float(entity.dxf.height)
    rendered_width = floats[4] if len(floats) > 4 else 0.0
    rendered_height = floats[5] if len(floats) > 5 else float(entity.dxf.height)
    center_error = floats[6] if len(floats) > 6 else None
    raw_width_factor = floats[7] if len(floats) > 7 else None
    final_width_factor = floats[8] if len(floats) > 8 else float(entity.dxf.width)
    xdata_rotation = floats[9] if len(floats) > 9 else float(entity.dxf.rotation)
    return {
        "candidate_id": semantics["candidate_id"],
        "height": _normalise(float(entity.dxf.height)),
        "width_factor": _normalise(float(entity.dxf.width)),
        "rotation": _normalise(float(entity.dxf.rotation)),
        "insertion_point": _normalise(entity.dxf.insert),
        "alignment_point": _normalise(entity.dxf.get("align_point")),
        "halign": int(entity.dxf.get("halign", 0)),
        "valign": int(entity.dxf.get("valign", 0)),
        "style": str(entity.dxf.get("style", "Standard")),
        "target_center": _normalise([target_center_x, target_center_y]),
        "target_width": _normalise(target_width),
        "target_height": _normalise(target_height),
        "rendered_width": _normalise(rendered_width),
        "rendered_height": _normalise(rendered_height),
        "center_error": _normalise(center_error),
        "raw_width_factor": _normalise(raw_width_factor),
        "final_width_factor": _normalise(final_width_factor),
        "xdata_rotation": _normalise(xdata_rotation),
        "predicted_visible_bounds": _predicted_visible_bounds(
            center_x=target_center_x,
            center_y=target_center_y,
            width=rendered_width,
            height=rendered_height,
            rotation=xdata_rotation,
        ),
    }


def _protected_category(layer: str) -> str | None:
    upper = layer.upper()
    if "LOGO" in upper:
        return "logo"
    if "SIGNATURE" in upper:
        return "signature"
    if layer == UNCERTAIN_TEXT_LAYER or "UNCERTAIN" in upper:
        return "uncertain"
    if "RESIDUAL" in upper:
        return "residual"
    return None


def _protected_layer(layer: str) -> bool:
    return _protected_category(layer) is not None


def _layer_state(document: Any, layer_name: str) -> dict[str, Any]:
    try:
        layer = document.layers.get(layer_name)
    except Exception:
        return {"exists": False, "off": False, "frozen": False}
    return {
        "exists": True,
        "off": bool(layer.is_off()),
        "frozen": bool(layer.is_frozen()),
    }


def _roundtrip(document: Any, source: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / source.name
        document.saveas(target)
        reopened = ezdxf.readfile(target)
        original_text = [
            _line_geometry(entity, source.stem)
            for entity in document.modelspace().query(f'TEXT[layer=="{TEXT_LAYER}"]')
        ]
        reopened_text = [
            _line_geometry(entity, source.stem)
            for entity in reopened.modelspace().query(f'TEXT[layer=="{TEXT_LAYER}"]')
        ]
        return {
            "passed": original_text == reopened_text,
            "audit_errors_after": len(reopened.audit().errors),
            "source_outline_state_after": _layer_state(
                reopened, SOURCE_OUTLINE_LAYER
            ),
        }


def audit_dxf(
    *,
    page_id: str,
    dxf_path: Path,
    page_metadata: Mapping[str, Any],
    report_metrics: Mapping[str, Any],
    content_audit: Mapping[str, Any],
) -> dict[str, Any]:
    document = ezdxf.readfile(dxf_path)
    audit_errors = len(document.audit().errors)
    modelspace = document.modelspace()
    entities = list(modelspace)
    text_entities = [
        entity
        for entity in entities
        if entity.dxftype() == "TEXT" and str(entity.dxf.layer) == TEXT_LAYER
    ]
    semantics = sorted(
        (_line_semantics(entity, page_id) for entity in text_entities),
        key=lambda item: str(item["candidate_id"]),
    )
    geometries = sorted(
        (_line_geometry(entity, page_id) for entity in text_entities),
        key=lambda item: str(item["candidate_id"]),
    )
    candidate_ids = [str(item["candidate_id"]) for item in semantics]
    contents = [str(item["ocr_text"]) for item in semantics]

    source_outline_entities = [
        entity for entity in entities if str(entity.dxf.layer) == SOURCE_OUTLINE_LAYER
    ]
    text_symbol_entities = [
        entity for entity in entities if str(entity.dxf.layer) == TEXT_SYMBOL_LAYER
    ]
    protected_partitions: dict[str, list[Any]] = {
        "logo": [],
        "signature": [],
        "residual": [],
        "uncertain": [],
    }
    for entity in entities:
        category = _protected_category(str(entity.dxf.layer))
        if category is not None:
            protected_partitions[category].append(entity)
    protected_entities = [
        entity
        for category in ("logo", "signature", "residual", "uncertain")
        for entity in protected_partitions[category]
    ]
    excluded_layers = {
        TEXT_LAYER,
        SOURCE_OUTLINE_LAYER,
        TEXT_SYMBOL_LAYER,
    }
    non_text_entities = [
        entity
        for entity in entities
        if str(entity.dxf.layer) not in excluded_layers
        and not _protected_layer(str(entity.dxf.layer))
        and entity.dxftype() != "TEXT"
    ]

    source_size = report_metrics.get("source_size_px", [0, 0])
    width = int(source_size[0]) if len(source_size) > 0 else 0
    height = int(source_size[1]) if len(source_size) > 1 else 0
    page_transform = {
        "page_id": page_id,
        "source_size_px": [width, height],
        "dpi": page_metadata.get("dpi"),
        "source_to_cad_transform": {
            "origin": [0.0, float(height)],
            "scale": [1.0, -1.0],
            "rotation_degrees": 0.0,
        },
        "insunits": int(document.header.get("$INSUNITS", 0)),
    }
    summary = content_audit.get("text_output_contract", {})
    source_outline_state = _layer_state(document, SOURCE_OUTLINE_LAYER)
    roundtrip = _roundtrip(document, dxf_path)
    partition_payloads = {
        "text_semantic": semantics,
        "text_geometry": geometries,
        "non_text_structure": _sorted_entities(non_text_entities),
        "text_symbol": _sorted_entities(text_symbol_entities),
        "source_outline": {
            "state": source_outline_state,
            "entities": _sorted_entities(source_outline_entities),
        },
        "protected_content": {
            category: _sorted_entities(values)
            for category, values in protected_partitions.items()
        },
        "page_transform": page_transform,
    }
    hashes = {
        f"{name}_hash": content_hash(payload)
        for name, payload in partition_payloads.items()
    }
    return {
        "page_id": page_id,
        "dxf_path": str(dxf_path),
        "input_source": page_metadata.get("source_path"),
        "page": dict(page_metadata),
        "full_structure_id": report_metrics.get("structure_id"),
        "eligible_count": int(summary.get("text_emit_eligible_count", 0)),
        "native_text_count": len(text_entities),
        "candidate_ids": candidate_ids,
        "candidate_id_hash": content_hash(candidate_ids),
        "ocr_contents": contents,
        "ocr_content_hash": content_hash(contents),
        "source_outline_entity_count": len(source_outline_entities),
        "source_outline_state": source_outline_state,
        "text_symbol_entity_count": len(text_symbol_entities),
        "protected_entity_count": len(protected_entities),
        "protected_content_part_hashes": {
            category: content_hash(_sorted_entities(values))
            for category, values in protected_partitions.items()
        },
        "non_text_structure_entity_count": len(non_text_entities),
        "fallback_count": int(summary.get("fallback_count", 0)),
        "residual_count": int(summary.get("residual_count", 0)),
        "logo_count": int(report_metrics.get("logo_count", 0)),
        "signature_count": int(report_metrics.get("signature_count", 0)),
        "replacement_unsafe_downgrade_count": int(
            summary.get("downgrade_reasons", {}).get("replacement_unsafe", 0)
        ),
        "dxf_audit_errors": audit_errors,
        "read_save_read": roundtrip,
        "partition_hashes": hashes,
        "partition_payloads": partition_payloads,
    }


def _report_documents(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["id"]): item
        for item in report.get("documents", [])
        if isinstance(item, Mapping) and item.get("id")
    }


def _manifest_documents(
    manifest: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["id"]): item
        for item in manifest.get("documents", [])
        if isinstance(item, Mapping) and item.get("id")
    }


def _audit_run(
    *,
    report: Mapping[str, Any],
    dxf_directory: Path,
) -> dict[str, dict[str, Any]]:
    pages: dict[str, dict[str, Any]] = {}
    for page_id, item in _report_documents(report).items():
        metrics = item.get("metrics")
        content_audit = item.get("content_audit")
        page = item.get("page")
        if not isinstance(metrics, Mapping):
            raise ValueError(f"{page_id}: missing observed metrics")
        if not isinstance(content_audit, Mapping):
            raise ValueError(f"{page_id}: missing content audit")
        if not isinstance(page, Mapping):
            raise ValueError(f"{page_id}: missing page metadata")
        page_metadata = dict(page)
        page_metadata["source_path"] = item.get("source_path")
        dxf_path = dxf_directory / f"{page_id}.dxf"
        if not dxf_path.is_file():
            raise FileNotFoundError(f"{page_id}: DXF not generated at {dxf_path}")
        pages[page_id] = audit_dxf(
            page_id=page_id,
            dxf_path=dxf_path,
            page_metadata=page_metadata,
            report_metrics=metrics,
            content_audit=content_audit,
        )
    return pages


def validate_before_contract(page: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if int(page["native_text_count"]) != int(page["eligible_count"]):
        errors.append(
            "eligible/native mismatch: "
            f"{page['eligible_count']} != {page['native_text_count']}"
        )
    if int(page["replacement_unsafe_downgrade_count"]) != 0:
        errors.append("replacement_safe still gates native TEXT")
    state = page["source_outline_state"]
    if not state.get("exists") or not state.get("off") or not state.get("frozen"):
        errors.append("SOURCE_TEXT_OUTLINE is not present, off and frozen")
    if int(page["dxf_audit_errors"]) != 0:
        errors.append(f"DXF audit errors: {page['dxf_audit_errors']}")
    roundtrip = page["read_save_read"]
    if not roundtrip.get("passed") or int(roundtrip.get("audit_errors_after", 0)):
        errors.append("DXF read-save-read did not preserve native TEXT geometry")
    candidate_ids = page["candidate_ids"]
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("candidate IDs are not unique")
    return errors


REQUIRED_EQUAL_PARTITIONS = (
    "text_semantic_hash",
    "non_text_structure_hash",
    "text_symbol_hash",
    "source_outline_hash",
    "protected_content_hash",
    "page_transform_hash",
)


def compare_before_after(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    before_hashes = before["partition_hashes"]
    after_hashes = after["partition_hashes"]
    equal = {
        key: before_hashes.get(key) == after_hashes.get(key)
        for key in REQUIRED_EQUAL_PARTITIONS
    }
    protected_parts_equal = {
        key: before.get("protected_content_part_hashes", {}).get(key)
        == after.get("protected_content_part_hashes", {}).get(key)
        for key in ("logo", "signature", "residual", "uncertain")
    }
    geometry_changed = (
        before_hashes.get("text_geometry_hash")
        != after_hashes.get("text_geometry_hash")
    )
    errors = [
        f"{key} changed"
        for key, unchanged in equal.items()
        if not unchanged
    ]
    errors.extend(
        f"protected_content.{key} changed"
        for key, unchanged in protected_parts_equal.items()
        if not unchanged
    )
    if before["candidate_id_hash"] != after["candidate_id_hash"]:
        errors.append("candidate ID hash changed")
    if before["ocr_content_hash"] != after["ocr_content_hash"]:
        errors.append("OCR content hash changed")
    for count_key in ("eligible_count", "native_text_count"):
        if int(before.get(count_key, 0)) != int(after.get(count_key, 0)):
            errors.append(f"{count_key} changed")
    return {
        "page_id": before["page_id"],
        "required_partition_equality": equal,
        "protected_content_part_equality": protected_parts_equal,
        "eligible_count_before": before.get("eligible_count"),
        "eligible_count_after": after.get("eligible_count"),
        "native_text_count_before": before.get("native_text_count"),
        "native_text_count_after": after.get("native_text_count"),
        "candidate_id_hash_before": before.get("candidate_id_hash"),
        "candidate_id_hash_after": after.get("candidate_id_hash"),
        "ocr_content_hash_before": before.get("ocr_content_hash"),
        "ocr_content_hash_after": after.get("ocr_content_hash"),
        "text_geometry_hash_before": before_hashes.get("text_geometry_hash"),
        "text_geometry_hash_after": after_hashes.get("text_geometry_hash"),
        "text_geometry_changed": geometry_changed,
        "text_geometry_before": before.get("partition_payloads", {}).get(
            "text_geometry", []
        ),
        "text_geometry_after": after.get("partition_payloads", {}).get(
            "text_geometry", []
        ),
        "full_structure_id_before": before.get("full_structure_id"),
        "full_structure_id_after": after.get("full_structure_id"),
        "full_structure_id_changed": (
            before.get("full_structure_id") != after.get("full_structure_id")
        ),
        "errors": errors,
        "passed": not errors,
    }


A_TO_B_STABLE_METRICS = (
    "straight_line_count",
    "dxf_line_count",
    "logo_count",
    "signature_count",
    "source_size_px",
)


def classify_architecture_to_editable(
    architecture_pages: Mapping[str, Mapping[str, Any]],
    editable_pages: Mapping[str, Mapping[str, Any]],
    architecture_report: Mapping[str, Any],
    editable_report: Mapping[str, Any],
) -> dict[str, Any]:
    architecture_documents = _report_documents(architecture_report)
    editable_documents = _report_documents(editable_report)
    page_results: list[dict[str, Any]] = []
    unexplained: list[str] = []
    for page_id in sorted(architecture_pages):
        architecture = architecture_pages[page_id]
        editable = editable_pages[page_id]
        architecture_metrics = architecture_documents[page_id].get("metrics", {})
        editable_metrics = editable_documents[page_id].get("metrics", {})
        stable_metrics = {
            key: {
                "architecture": architecture_metrics.get(key),
                "editable": editable_metrics.get(key),
                "equal": architecture_metrics.get(key)
                == editable_metrics.get(key),
            }
            for key in A_TO_B_STABLE_METRICS
        }
        for key, value in stable_metrics.items():
            if not value["equal"]:
                unexplained.append(f"{page_id}:metric:{key}")

        transition_checks = {
            "native_text_not_reduced": (
                int(editable.get("native_text_count", 0))
                >= int(architecture.get("native_text_count", 0))
            ),
            "fallback_outline_not_increased": (
                int(editable.get("fallback_count", 0))
                <= int(architecture.get("fallback_count", 0))
            ),
            "source_outline_not_reduced": (
                int(editable.get("source_outline_entity_count", 0))
                >= int(architecture.get("source_outline_entity_count", 0))
            ),
            "replacement_unsafe_downgrades_not_increased": (
                int(editable.get("replacement_unsafe_downgrade_count", 0))
                <= int(architecture.get("replacement_unsafe_downgrade_count", 0))
            ),
        }
        for check, passed in transition_checks.items():
            if not passed:
                unexplained.append(f"{page_id}:transition:{check}")

        architecture_hashes = architecture["partition_hashes"]
        editable_hashes = editable["partition_hashes"]
        partition_changes: dict[str, dict[str, Any]] = {}
        for key in sorted(set(architecture_hashes) | set(editable_hashes)):
            equal = architecture_hashes.get(key) == editable_hashes.get(key)
            if key == "page_transform_hash":
                classification = "stable-page-transform" if equal else "unexplained"
                if not equal:
                    unexplained.append(f"{page_id}:{key}")
            elif key in {"text_semantic_hash", "text_geometry_hash"}:
                classification = "approved-editable-text-contract"
            elif key in {"text_symbol_hash", "source_outline_hash"}:
                classification = "approved-editable-text-routing"
            elif key in {"non_text_structure_hash", "protected_content_hash"}:
                stable = all(item["equal"] for item in stable_metrics.values())
                classification = (
                    "derived-from-approved-text-routing"
                    if stable
                    else "unexplained"
                )
                if not equal and not stable:
                    unexplained.append(f"{page_id}:{key}")
            else:
                classification = "recorded"
            partition_changes[key] = {
                "architecture": architecture_hashes.get(key),
                "editable": editable_hashes.get(key),
                "equal": equal,
                "classification": classification,
            }

        protected_parts = {}
        for key in ("logo", "signature", "residual", "uncertain"):
            architecture_value = architecture.get(
                "protected_content_part_hashes", {}
            ).get(key)
            editable_value = editable.get(
                "protected_content_part_hashes", {}
            ).get(key)
            equal = architecture_value == editable_value
            classification = (
                "must-remain-stable"
                if key in {"logo", "signature"}
                else "derived-from-approved-text-routing"
            )
            if key in {"logo", "signature"} and not equal:
                unexplained.append(f"{page_id}:protected:{key}")
            protected_parts[key] = {
                "architecture": architecture_value,
                "editable": editable_value,
                "equal": equal,
                "classification": classification,
            }

        page_results.append(
            {
                "page_id": page_id,
                "native_text_count": {
                    "architecture": architecture.get("native_text_count"),
                    "editable": editable.get("native_text_count"),
                },
                "fallback_count": {
                    "architecture": architecture.get("fallback_count"),
                    "editable": editable.get("fallback_count"),
                },
                "source_outline": {
                    "architecture_count": architecture.get(
                        "source_outline_entity_count"
                    ),
                    "editable_count": editable.get(
                        "source_outline_entity_count"
                    ),
                    "architecture_state": architecture.get(
                        "source_outline_state"
                    ),
                    "editable_state": editable.get("source_outline_state"),
                },
                "trace_text_symbol_count": {
                    "architecture": architecture.get("text_symbol_entity_count"),
                    "editable": editable.get("text_symbol_entity_count"),
                },
                "stable_non_text_metrics": stable_metrics,
                "approved_text_contract_transitions": transition_checks,
                "protected_content_parts": protected_parts,
                "partition_changes": partition_changes,
                "full_structure_id": {
                    "architecture": architecture.get("full_structure_id"),
                    "editable": editable.get("full_structure_id"),
                    "equal": architecture.get("full_structure_id")
                    == editable.get("full_structure_id"),
                    "classification": "recorded-derived-identifier",
                },
            }
        )
    return {
        "from_contract": PHASE12_CONTRACT,
        "from_commit": PHASE12_COMMIT,
        "to_contract": EDITABLE_TEXT_CONTRACT,
        "to_commit": BASELINE_SOURCE_COMMIT,
        "pages": page_results,
        "unexplained_non_text_changes": unexplained,
        "passed": not unexplained,
    }


def _font_hashes(source_tree: Path) -> list[dict[str, str]]:
    extensions = {".lff", ".ttf", ".otf", ".ttc"}
    values: list[dict[str, str]] = []
    for path in sorted(source_tree.rglob("*")):
        if path.is_file() and path.suffix.lower() in extensions:
            values.append(
                {
                    "path": path.relative_to(source_tree).as_posix(),
                    "sha256": file_sha256(path),
                }
            )
    return values


def build_baseline(
    *,
    repository_root: Path,
    phase12_manifest_path: Path,
    architecture_report_path: Path,
    architecture_dxf_directory: Path,
    before_report_path: Path,
    before_dxf_directory: Path,
    after_report_path: Path,
    after_dxf_directory: Path,
    output_directory: Path,
    environment_path: Path,
    authorization_path: Path,
    before_source_tree: Path,
) -> dict[str, Any]:
    if not authorization_path.is_file():
        raise ValueError("Human authorization record is required")
    try:
        manifest_relative_path = phase12_manifest_path.resolve().relative_to(
            repository_root.resolve()
        ).as_posix()
    except ValueError as exc:
        raise ValueError(
            "Phase-12 manifest must be inside the repository root"
        ) from exc
    if manifest_relative_path != PHASE12_MANIFEST_PATH:
        raise ValueError(
            "Phase-12 manifest path must use the immutable configured path: "
            f"{PHASE12_MANIFEST_PATH}"
        )
    authorization = authorization_path.read_text(encoding="utf-8").strip()
    for required in (
        BASELINE_SOURCE_COMMIT,
        CANDIDATE_COMMIT,
        PHASE12_COMMIT,
        PHASE12_MANIFEST_BLOB,
        EDITABLE_TEXT_CONTRACT,
    ):
        if required not in authorization:
            raise ValueError(
                f"Authorization record does not name required anchor {required}"
            )

    verified_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    anchor = Phase12ImmutableAnchor(verification_timestamp=verified_at)
    anchor_verification = verify_phase12_anchor(repository_root, anchor)
    current_manifest_blob = verify_current_manifest_blob(
        repository_root,
        ref=CANDIDATE_COMMIT,
    )
    phase12_manifest = load_json_from_commit(
        repository_root,
        commit_sha=PHASE12_COMMIT,
        manifest_path=PHASE12_MANIFEST_PATH,
    )
    verified_fixtures = validate_fixture_hashes(
        phase12_manifest,
        before_source_tree,
    )
    architecture_report = load_json(architecture_report_path)
    before_report = load_json(before_report_path)
    after_report = load_json(after_report_path)
    environment = load_json(environment_path)
    phase12_documents = _manifest_documents(phase12_manifest)

    architecture_pages = _audit_run(
        report=architecture_report,
        dxf_directory=architecture_dxf_directory,
    )
    before_pages = _audit_run(
        report=before_report,
        dxf_directory=before_dxf_directory,
    )
    after_pages = _audit_run(
        report=after_report,
        dxf_directory=after_dxf_directory,
    )
    expected_ids = set(phase12_documents)
    observed_sets = {
        "phase12": set(architecture_pages),
        "editable_before": set(before_pages),
        "p1b_candidate": set(after_pages),
    }
    for name, observed_ids in observed_sets.items():
        if observed_ids != expected_ids:
            raise ValueError(
                f"{name}: the 12 configured observations are incomplete or "
                "use different IDs"
            )
    if len(expected_ids) != 12:
        raise ValueError(
            f"Expected 12 document/DPI configurations, found {len(expected_ids)}"
        )

    unique_pages = {
        (
            str(item.get("source_document")),
            int(item.get("page", {}).get("number", 0)),
        )
        for item in phase12_manifest.get("documents", [])
    }
    if len(unique_pages) != 10:
        raise ValueError(f"Expected 10 unique pages, found {len(unique_pages)}")

    before_contract_errors: dict[str, list[str]] = {}
    comparisons: list[dict[str, Any]] = []
    baseline_pages: list[dict[str, Any]] = []
    output_directory.mkdir(parents=True, exist_ok=True)
    page_directory = output_directory / "pages"
    page_directory.mkdir(parents=True, exist_ok=True)

    for page_id in sorted(expected_ids):
        architecture = architecture_pages[page_id]
        before = before_pages[page_id]
        after = after_pages[page_id]
        errors = validate_before_contract(before)
        if errors:
            before_contract_errors[page_id] = errors
        comparison = compare_before_after(before, after)
        comparisons.append(comparison)
        phase12_document = phase12_documents[page_id]
        page_entry = {
            "page_id": page_id,
            "source_path": phase12_document.get("source_path"),
            "source_sha256": phase12_document.get("sha256"),
            "original_path": phase12_document.get("original_path"),
            "original_sha256": phase12_document.get("original_sha256"),
            "page": phase12_document.get("page"),
            "eligible_count": before["eligible_count"],
            "native_text_count": before["native_text_count"],
            "fallback_count": before["fallback_count"],
            "candidate_id_hash": before["candidate_id_hash"],
            "ocr_content_hash": before["ocr_content_hash"],
            "source_outline_entity_count": before[
                "source_outline_entity_count"
            ],
            "source_outline_state": before["source_outline_state"],
            "text_symbol_entity_count": before["text_symbol_entity_count"],
            "residual_count": before["residual_count"],
            "logo_count": before["logo_count"],
            "signature_count": before["signature_count"],
            "protected_content_part_hashes": before[
                "protected_content_part_hashes"
            ],
            "non_text_structure_entity_count": before[
                "non_text_structure_entity_count"
            ],
            "partition_hashes": before["partition_hashes"],
            "full_structure_id": before["full_structure_id"],
            "dxf_entity_audit": {
                "errors": before["dxf_audit_errors"],
                "native_text_count": before["native_text_count"],
                "source_outline_entity_count": before[
                    "source_outline_entity_count"
                ],
                "text_symbol_entity_count": before[
                    "text_symbol_entity_count"
                ],
                "protected_entity_count": before["protected_entity_count"],
                "non_text_structure_entity_count": before[
                    "non_text_structure_entity_count"
                ],
            },
            "read_save_read": before["read_save_read"],
            "candidate_ids": before["candidate_ids"],
            "ocr_contents": before["ocr_contents"],
        }
        baseline_pages.append(page_entry)
        (page_directory / f"{page_id}.json").write_text(
            json.dumps(
                {
                    "phase12_architecture": architecture,
                    "editable_text_baseline": before,
                    "p1b_candidate": after,
                    "before_to_candidate_comparison": comparison,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    architecture_to_editable = classify_architecture_to_editable(
        architecture_pages,
        before_pages,
        architecture_report,
        before_report,
    )
    comparison_errors = {
        item["page_id"]: item["errors"]
        for item in comparisons
        if item["errors"]
    }
    if before_contract_errors:
        raise ValueError(
            "The 5f7846e baseline does not satisfy the editable-text contract: "
            + json.dumps(before_contract_errors, ensure_ascii=False)
        )
    if not architecture_to_editable["passed"]:
        raise ValueError(
            "A -> B contains unexplained non-text changes: "
            + ", ".join(
                architecture_to_editable["unexplained_non_text_changes"]
            )
        )
    if comparison_errors:
        raise ValueError(
            "B -> C changed prohibited partitions: "
            + json.dumps(comparison_errors, ensure_ascii=False)
        )

    manifest = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract_version": EDITABLE_TEXT_CONTRACT,
        "baseline_source_commit": BASELINE_SOURCE_COMMIT,
        "candidate_commit": CANDIDATE_COMMIT,
        "created_at": verified_at,
        "created_by_command": (
            "python scripts/editable_text_regression_contract.py build "
            f"--contract {EDITABLE_TEXT_CONTRACT}"
        ),
        "document_configuration_count": len(baseline_pages),
        "unique_page_count": len(unique_pages),
        "phase12_immutable_anchor": {
            **anchor_verification,
            "current_target_manifest_blob_sha": current_manifest_blob,
            "legacy_tag_history_note": (
                "Project history documents recorded the tag name, but the "
                "remote tag ref was absent and must not be claimed as "
                "historically present. Commit/blob SHAs are authoritative."
            ),
            "cloud_tag_write_channel": "unavailable",
            "tag_required_for_validation": False,
        },
        "environment": environment,
        "fixture_hashes": verified_fixtures,
        "font_hashes": _font_hashes(before_source_tree),
        "partition_contract": {
            "must_equal_before_to_candidate": list(REQUIRED_EQUAL_PARTITIONS),
            "protected_subpart_must_equal": [
                "logo",
                "signature",
                "residual",
                "uncertain",
            ],
            "may_change_before_to_candidate": ["text_geometry_hash"],
            "record_only": ["full_structure_id"],
            "full_structure_id_gate": False,
        },
        "documents": baseline_pages,
    }
    comparison_report = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract_version": EDITABLE_TEXT_CONTRACT,
        "phase12_architecture_to_editable_before": architecture_to_editable,
        "editable_before_to_p1b_candidate": {
            "from_commit": BASELINE_SOURCE_COMMIT,
            "to_commit": CANDIDATE_COMMIT,
            "comparisons": comparisons,
            "passed": not comparison_errors,
        },
        "full_structure_id_rule": (
            "Record full_structure_id for traceability. A difference does not "
            "fail validation when every prohibited semantic, non-text, symbol, "
            "source-outline, protected-content and page-transform partition "
            "remains unchanged; the changed partition is text_geometry_hash."
        ),
        "passed": True,
    }
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_directory / "comparison-report.json").write_text(
        json.dumps(
            comparison_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_directory / "README.md").write_text(
        "# Non-destructive editable text regression baseline v1\n\n"
        f"- Contract: `{EDITABLE_TEXT_CONTRACT}`\n"
        f"- Baseline source: `{BASELINE_SOURCE_COMMIT}`\n"
        f"- Candidate audited: `{CANDIDATE_COMMIT}`\n"
        f"- Phase-12 commit anchor: `{PHASE12_COMMIT}`\n"
        f"- Phase-12 manifest blob anchor: `{PHASE12_MANIFEST_BLOB}`\n"
        f"- Recorded legacy tag: `{PHASE12_RECORDED_TAG}` (absent)\n"
        f"- Configurations: {len(baseline_pages)}\n"
        f"- Unique pages: {len(unique_pages)}\n\n"
        "The historical tag name is retained only as an identifier. Validation "
        "uses the immutable phase-12 commit and manifest blob. This baseline "
        "validates editable-text semantics and protected/non-text partitions. "
        "`text_geometry_hash` may change for P1B geometry; "
        "`full_structure_id` is recorded but is not an independent gate.\n",
        encoding="utf-8",
    )
    return {
        "status": SUCCESS_STATUS,
        "manifest": str(output_directory / "manifest.json"),
        "comparison_report": str(output_directory / "comparison-report.json"),
        "document_configuration_count": len(baseline_pages),
        "unique_page_count": len(unique_pages),
        "phase12_anchor_verified": True,
        "passed": True,
    }



def validate_observation_against_baseline(
    *,
    baseline_manifest_path: Path,
    observed_report_path: Path,
    observed_dxf_directory: Path,
) -> dict[str, Any]:
    baseline = load_json(baseline_manifest_path)
    if baseline.get("contract_version") != EDITABLE_TEXT_CONTRACT:
        raise ValueError("Observed editable text must use editable-text-v1 baseline")
    expected_pages = {
        str(item["page_id"]): item
        for item in baseline.get("documents", [])
        if isinstance(item, Mapping) and item.get("page_id")
    }
    report = load_json(observed_report_path)
    observed_pages = _audit_run(
        report=report,
        dxf_directory=observed_dxf_directory,
    )
    if set(expected_pages) != set(observed_pages):
        raise ValueError("Observed page set does not match editable-text-v1")
    results: list[dict[str, Any]] = []
    for page_id in sorted(expected_pages):
        expected = expected_pages[page_id]
        observed = observed_pages[page_id]
        errors: list[str] = []
        if expected.get("source_sha256") != _report_documents(report)[page_id].get(
            "source_sha256"
        ):
            errors.append("input source hash changed")
        if expected.get("candidate_id_hash") != observed.get("candidate_id_hash"):
            errors.append("text_semantic candidate IDs changed")
        if expected.get("ocr_content_hash") != observed.get("ocr_content_hash"):
            errors.append("text_semantic OCR content changed")
        expected_hashes = expected.get("partition_hashes", {})
        observed_hashes = observed.get("partition_hashes", {})
        for key in REQUIRED_EQUAL_PARTITIONS:
            if expected_hashes.get(key) != observed_hashes.get(key):
                errors.append(f"{key} changed")
        expected_parts = expected.get("protected_content_part_hashes", {})
        observed_parts = observed.get("protected_content_part_hashes", {})
        for key in ("logo", "signature", "residual", "uncertain"):
            if expected_parts.get(key) != observed_parts.get(key):
                errors.append(f"protected_content.{key} changed")
        for count_key in ("eligible_count", "native_text_count"):
            if int(expected.get(count_key, 0)) != int(observed.get(count_key, 0)):
                errors.append(f"{count_key} changed")
        results.append(
            {
                "page_id": page_id,
                "text_geometry_changed": (
                    expected_hashes.get("text_geometry_hash")
                    != observed_hashes.get("text_geometry_hash")
                ),
                "full_structure_id_expected": expected.get("full_structure_id"),
                "full_structure_id_observed": observed.get("full_structure_id"),
                "errors": errors,
                "passed": not errors,
            }
        )
    return {
        "contract_version": EDITABLE_TEXT_CONTRACT,
        "baseline_source_commit": baseline.get("baseline_source_commit"),
        "results": results,
        "passed": all(item["passed"] for item in results),
    }


def replay_commit(
    *,
    repository_root: Path,
    contract: str | None,
    commit_sha: str,
    output_path: Path,
    artifacts_directory: Path,
    manifest_relative_path: str = "tests/real_regression/manifest.json",
) -> dict[str, Any]:
    selected_contract = require_explicit_contract(contract)
    if commit_sha not in {PHASE12_COMMIT, BASELINE_SOURCE_COMMIT, CANDIDATE_COMMIT}:
        raise ValueError(f"Replay commit is not an authorized anchor: {commit_sha}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="editable-text-replay-") as directory:
        worktree = Path(directory) / "tree"
        _materialize_commit(
            repository_root,
            commit_sha=commit_sha,
            destination=worktree,
        )
        project_root = worktree / "cad_photo_to_dxf"
        manifest_path = project_root / manifest_relative_path
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"Replay manifest is missing from historical tree: {manifest_path}"
            )
        command = [
            sys.executable,
            "scripts/run_real_document_regression.py",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_path),
            "--artifacts",
            str(artifacts_directory),
        ]
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        (output_path.parent / "run.log").write_text(
            completed.stdout + completed.stderr,
            encoding="utf-8",
        )
        if not output_path.is_file():
            raise RuntimeError(
                "Historical replay did not produce a report: "
                f"return code {completed.returncode}"
            )
        report = load_json(output_path)
        documents = report.get("documents", [])
        unique_pages = {
            (
                str(item.get("original_path")),
                int(item.get("page", {}).get("number", 0)),
            )
            for item in documents
            if isinstance(item, Mapping)
        }
        if len(documents) != 12 or len(unique_pages) != 10:
            raise ValueError(
                "Historical replay must cover 12 configurations and 10 pages: "
                f"{len(documents)} configurations / {len(unique_pages)} pages"
            )
        report["regression_contract"] = selected_contract
        report["replayed_commit"] = commit_sha
        report["runner_return_code"] = completed.returncode
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return {
            "contract": selected_contract,
            "commit": commit_sha,
            "report": str(output_path),
            "artifacts": str(artifacts_directory),
            "runner_return_code": completed.returncode,
            "configuration_count": len(documents),
            "unique_page_count": len(unique_pages),
            "passed": True,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Select, audit and build versioned real-document contracts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    select = subparsers.add_parser("select")
    select.add_argument("--contract", required=True)
    select.add_argument(
        "--scope",
        choices=("architecture-safety", "editable-text-geometry"),
        required=True,
    )
    select.add_argument("--architecture-manifest", type=Path, required=True)
    select.add_argument("--editable-text-manifest", type=Path, required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--contract", required=True)
    build.add_argument("--repository-root", type=Path, required=True)
    build.add_argument("--phase12-manifest", type=Path, required=True)
    build.add_argument("--architecture-report", type=Path, required=True)
    build.add_argument("--architecture-dxf-directory", type=Path, required=True)
    build.add_argument("--before-report", type=Path, required=True)
    build.add_argument("--before-dxf-directory", type=Path, required=True)
    build.add_argument("--after-report", type=Path, required=True)
    build.add_argument("--after-dxf-directory", type=Path, required=True)
    build.add_argument("--output-directory", type=Path, required=True)
    build.add_argument("--environment", type=Path, required=True)
    build.add_argument("--authorization", type=Path, required=True)
    build.add_argument("--before-source-tree", type=Path, required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--contract", required=True)
    validate.add_argument(
        "--scope",
        choices=("architecture-safety", "editable-text-geometry"),
        required=True,
    )
    validate.add_argument("--architecture-manifest", type=Path, required=True)
    validate.add_argument("--editable-text-manifest", type=Path, required=True)
    validate.add_argument("--observed-report", type=Path, required=True)
    validate.add_argument("--observed-dxf-directory", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)

    replay = subparsers.add_parser("replay")
    replay.add_argument("--contract", required=True)
    replay.add_argument("--repository-root", type=Path, required=True)
    replay.add_argument("--commit", required=True)
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--artifacts", type=Path, required=True)
    replay.add_argument(
        "--manifest",
        default="tests/real_regression/manifest.json",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "select":
        path = select_baseline_manifest(
            contract=args.contract,
            architecture_manifest=args.architecture_manifest,
            editable_text_manifest=args.editable_text_manifest,
            validation_scope=args.scope,
        )
        print(path)
        return 0

    if args.command == "validate":
        selected = select_baseline_manifest(
            contract=args.contract,
            architecture_manifest=args.architecture_manifest,
            editable_text_manifest=args.editable_text_manifest,
            validation_scope=args.scope,
        )
        if require_explicit_contract(args.contract) != EDITABLE_TEXT_CONTRACT:
            raise ValueError(SUPERSEDED_CONTRACT_ERROR)
        result = validate_observation_against_baseline(
            baseline_manifest_path=selected,
            observed_report_path=args.observed_report.resolve(),
            observed_dxf_directory=args.observed_dxf_directory.resolve(),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1

    if args.command == "replay":
        result = replay_commit(
            repository_root=args.repository_root.resolve(),
            contract=args.contract,
            commit_sha=args.commit,
            output_path=args.output.resolve(),
            artifacts_directory=args.artifacts.resolve(),
            manifest_relative_path=args.manifest,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    contract = require_explicit_contract(args.contract)
    if contract != EDITABLE_TEXT_CONTRACT:
        raise ValueError(SUPERSEDED_CONTRACT_ERROR)
    result = build_baseline(
        repository_root=args.repository_root.resolve(),
        phase12_manifest_path=args.phase12_manifest.resolve(),
        architecture_report_path=args.architecture_report.resolve(),
        architecture_dxf_directory=args.architecture_dxf_directory.resolve(),
        before_report_path=args.before_report.resolve(),
        before_dxf_directory=args.before_dxf_directory.resolve(),
        after_report_path=args.after_report.resolve(),
        after_dxf_directory=args.after_dxf_directory.resolve(),
        output_directory=args.output_directory.resolve(),
        environment_path=args.environment.resolve(),
        authorization_path=args.authorization.resolve(),
        before_source_tree=args.before_source_tree.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

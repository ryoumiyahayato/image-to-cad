from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg
import numpy as np

from . import __version__
from .final_structure import FINAL_STRUCTURE_SCHEMA_VERSION, FinalStructure
from .image_loader import load_image, save_image
from .observability import STAGE_BY_KEY, STAGE_SPECS
from .optimized_trace import trace_image_optimized
from .trace_single_export import export_final_structure_dxf


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        contiguous = np.ascontiguousarray(value)
        return {
            "shape": [int(item) for item in contiguous.shape],
            "dtype": str(contiguous.dtype),
            "sha256": sha256(contiguous.tobytes()).hexdigest(),
        }
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            _json_safe(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _git_state(project_root: Path) -> tuple[str, bool]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    commit = completed.stdout.strip() or "unknown"
    status = subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--",
            "app",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return commit, bool(status.stdout.strip()) or status.returncode != 0


def _application_source_digest(project_root: Path) -> str:
    digest = sha256()
    for path in sorted((project_root / "app").glob("*.py")):
        digest.update(path.relative_to(project_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass
class _ArtifactFile:
    path: Path
    generated_at: str
    payload_index: int
    role: str


@dataclass
class _StageRecord:
    status: str
    generated_at: str
    payloads: list[dict[str, Any]]
    artifacts: list[_ArtifactFile]


class DebugBundleCollector:
    """Write observation images immediately and finalize metadata after structure ID."""

    def __init__(
        self,
        output_dir: Path,
        *,
        input_path: Path,
        input_sha256: str,
        page_index: int,
        dpi: int,
        algorithm_version: str,
        git_commit: str,
        git_worktree_dirty: bool,
        application_source_digest: str,
        configuration: Mapping[str, Any],
    ) -> None:
        self.output_dir = output_dir.resolve()
        if self.output_dir.exists() and any(self.output_dir.iterdir()):
            raise ValueError(
                f"Debug bundle output directory is not empty: {self.output_dir}"
            )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir = self.output_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.input_path = input_path.resolve()
        self.input_sha256 = input_sha256
        self.page_index = int(page_index)
        self.dpi = int(dpi)
        self.algorithm_version = algorithm_version
        self.git_commit = git_commit
        self.git_worktree_dirty = bool(git_worktree_dirty)
        self.application_source_digest = application_source_digest
        self.configuration = dict(configuration)
        serialized_config = json.dumps(
            _json_safe(self.configuration),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.config_digest = sha256(serialized_config).hexdigest()
        self._records: dict[str, _StageRecord] = {}

    def _record_for(self, stage_key: str, status: str) -> _StageRecord:
        if stage_key not in STAGE_BY_KEY:
            raise KeyError(f"Unknown observability stage: {stage_key}")
        record = self._records.get(stage_key)
        now = _utc_now()
        if record is None:
            record = _StageRecord(status, now, [], [])
            self._records[stage_key] = record
        elif status == "captured":
            record.status = "captured"
        elif record.status == "not_observed":
            record.status = status
        record.generated_at = now
        return record

    def _stage_dir(self, stage_key: str) -> Path:
        spec = STAGE_BY_KEY[stage_key]
        path = self.artifacts_dir / f"{spec.index:02d}-{spec.slug}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def record(
        self,
        stage_key: str,
        *,
        image: np.ndarray | None = None,
        payload: Mapping[str, Any] | None = None,
        status: str = "captured",
    ) -> None:
        record = self._record_for(stage_key, status)
        normalized_payload = dict(_json_safe(dict(payload or {})))
        payload_index = len(record.payloads)
        record.payloads.append(normalized_payload)
        if image is None:
            return
        if image.size == 0 or image.ndim not in (2, 3):
            raise ValueError(f"{stage_key}: observation image is empty or invalid")
        normalized_image = np.ascontiguousarray(image)
        artifact_path = (
            self._stage_dir(stage_key)
            / f"artifact-{len(record.artifacts) + 1:03d}.png"
        )
        save_image(artifact_path, normalized_image)
        record.artifacts.append(
            _ArtifactFile(
                path=artifact_path,
                generated_at=_utc_now(),
                payload_index=payload_index,
                role=str(normalized_payload.get("role", "")),
            )
        )

    def register_existing_file(
        self,
        stage_key: str,
        path: Path,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        if not resolved.is_relative_to(self.output_dir):
            raise ValueError("Observed files must remain inside the debug bundle")
        record = self._record_for(stage_key, "captured")
        normalized_payload = dict(_json_safe(dict(payload or {})))
        payload_index = len(record.payloads)
        record.payloads.append(normalized_payload)
        record.artifacts.append(
            _ArtifactFile(
                path=resolved,
                generated_at=_utc_now(),
                payload_index=payload_index,
                role=str(normalized_payload.get("role", "")),
            )
        )

    def stage_artifact_path(
        self,
        stage_key: str,
        *,
        suffix: str,
    ) -> Path:
        record = self._record_for(stage_key, "captured")
        return (
            self._stage_dir(stage_key)
            / f"artifact-{len(record.artifacts) + 1:03d}{suffix}"
        )

    def finalize(
        self,
        *,
        structure: FinalStructure,
        dxf_path: Path,
        dxf_audit_errors: int,
        dxf_entity_count: int,
    ) -> Path:
        structure.assert_valid()
        missing = [
            spec.key for spec in STAGE_SPECS if spec.key not in self._records
        ]
        if missing:
            raise AssertionError(
                "Debug bundle did not observe required stages: "
                + ", ".join(missing)
            )

        structure_id = structure.structure_id
        stage_entries: list[dict[str, Any]] = []
        pixel_lineage_path = None
        pixel_lineage_codebook = None
        for spec in STAGE_SPECS:
            record = self._records[spec.key]
            stage_dir = self._stage_dir(spec.key)
            data_path = stage_dir / "data.json"
            _write_json(
                data_path,
                {
                    "stage_id": spec.stage_id,
                    "stage_key": spec.key,
                    "stage_name": spec.name,
                    "observations": record.payloads,
                },
            )
            artifact_entries = []
            for artifact in record.artifacts:
                relative_artifact = artifact.path.relative_to(self.output_dir)
                payload = record.payloads[artifact.payload_index]
                metadata = {
                    "input_file_sha256": self.input_sha256,
                    "input_path": str(self.input_path),
                    "page_index": self.page_index,
                    "dpi": self.dpi,
                    "algorithm_version": self.algorithm_version,
                    "git_commit": self.git_commit,
                    "git_worktree_dirty": self.git_worktree_dirty,
                    "application_source_digest": self.application_source_digest,
                    "configuration_summary": self.configuration,
                    "configuration_digest": self.config_digest,
                    "structure_id": structure_id,
                    "stage_id": spec.stage_id,
                    "stage_key": spec.key,
                    "stage_name": spec.name,
                    "generated_at": artifact.generated_at,
                    "upstream_stage_ids": [
                        STAGE_BY_KEY[key].stage_id
                        for key in spec.upstream_keys
                    ],
                    "artifact_path": relative_artifact.as_posix(),
                    "artifact_sha256": _file_sha256(artifact.path),
                    "artifact_role": artifact.role,
                    "observation": payload,
                }
                metadata_path = artifact.path.with_suffix(
                    artifact.path.suffix + ".metadata.json"
                )
                _write_json(metadata_path, metadata)
                artifact_entries.append(
                    {
                        "path": relative_artifact.as_posix(),
                        "metadata_path": metadata_path.relative_to(
                            self.output_dir
                        ).as_posix(),
                        "sha256": metadata["artifact_sha256"],
                        "role": artifact.role,
                    }
                )
                if spec.key == "residual_mask" and artifact.role == "pixel-lineage":
                    pixel_lineage_path = relative_artifact.as_posix()
                    pixel_lineage_codebook = payload.get("codebook")

            stage_metadata = {
                "input_file_sha256": self.input_sha256,
                "page_index": self.page_index,
                "dpi": self.dpi,
                "algorithm_version": self.algorithm_version,
                "git_commit": self.git_commit,
                "git_worktree_dirty": self.git_worktree_dirty,
                "application_source_digest": self.application_source_digest,
                "configuration_summary": self.configuration,
                "configuration_digest": self.config_digest,
                "structure_id": structure_id,
                "stage_id": spec.stage_id,
                "stage_key": spec.key,
                "stage_name": spec.name,
                "status": record.status,
                "generated_at": record.generated_at,
                "upstream_stage_ids": [
                    STAGE_BY_KEY[key].stage_id for key in spec.upstream_keys
                ],
                "data_path": data_path.relative_to(self.output_dir).as_posix(),
                "artifacts": artifact_entries,
            }
            stage_metadata_path = stage_dir / "metadata.json"
            _write_json(stage_metadata_path, stage_metadata)
            stage_entries.append(
                {
                    **stage_metadata,
                    "metadata_path": stage_metadata_path.relative_to(
                        self.output_dir
                    ).as_posix(),
                }
            )

        if pixel_lineage_path is None or pixel_lineage_codebook is None:
            raise AssertionError("Debug bundle has no pixel-lineage ownership map")
        dxf_path = dxf_path.resolve()
        manifest = {
            "schema_version": 1,
            "passed": dxf_audit_errors == 0,
            "generated_at": _utc_now(),
            "input": {
                "path": str(self.input_path),
                "sha256": self.input_sha256,
                "page_index": self.page_index,
                "dpi": self.dpi,
                "source_size_px": list(structure.source_size_px),
            },
            "algorithm_version": self.algorithm_version,
            "git_commit": self.git_commit,
            "git_worktree_dirty": self.git_worktree_dirty,
            "application_source_digest": self.application_source_digest,
            "configuration_summary": self.configuration,
            "configuration_digest": self.config_digest,
            "structure_id": structure_id,
            "final_structure_schema_version": FINAL_STRUCTURE_SCHEMA_VERSION,
            "stage_count": len(stage_entries),
            "stages": stage_entries,
            "pixel_lineage": {
                "path": pixel_lineage_path,
                "codebook": pixel_lineage_codebook,
            },
            "dxf": {
                "path": dxf_path.relative_to(self.output_dir).as_posix(),
                "sha256": _file_sha256(dxf_path),
                "entity_count": int(dxf_entity_count),
                "audit_error_count": int(dxf_audit_errors),
                "structure_id": structure_id,
            },
            "data_source_contract": {
                "gui_preview": "FinalStructure",
                "dxf_export": "FinalStructure",
                "same_structure_id_required": True,
            },
        }
        manifest_path = self.output_dir / "manifest.json"
        _write_json(manifest_path, manifest)
        return manifest_path


def _render_dxf_svg(
    dxf_path: Path,
    output_path: Path,
    *,
    source_size_px: tuple[int, int],
) -> dict[str, Any]:
    document = ezdxf.readfile(dxf_path)
    backend = svg.SVGBackend()
    Frontend(RenderContext(document), backend).draw_layout(document.modelspace())
    source_width, source_height = source_size_px
    render_width = 1600
    render_height = max(
        400,
        min(2200, int(round(render_width * source_height / source_width))),
    )
    page = layout.Page(render_width, render_height, units=layout.Units.px)
    settings = layout.Settings(
        fit_page=True,
        crop_at_margins=True,
        min_stroke_width=0.35,
        fixed_stroke_width=0.0,
        output_layers=True,
    )
    rendered = backend.get_string(page, settings=settings)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return {
        "role": "actual-dxf-render",
        "render_format": "svg",
        "render_size_px": [render_width, render_height],
        "source_dxf": dxf_path.name,
    }


def capture_debug_bundle(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    page_index: int = 0,
    dpi: int = 300,
    enable_ocr: bool = True,
    foreground_threshold: int | None = None,
) -> Path:
    source_path = Path(input_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    target = Path(output_dir).resolve()
    project_root = Path(__file__).resolve().parents[1]
    git_commit, git_worktree_dirty = _git_state(project_root)
    application_source_digest = _application_source_digest(project_root)
    algorithm_version = (
        f"{__version__}/optimized-trace/"
        f"final-structure-schema-{FINAL_STRUCTURE_SCHEMA_VERSION}/"
        f"source-{application_source_digest[:12]}"
    )
    configuration = {
        "page_index": int(page_index),
        "dpi": int(dpi),
        "enable_ocr": bool(enable_ocr),
        "foreground_threshold": foreground_threshold,
        "final_structure_schema_version": FINAL_STRUCTURE_SCHEMA_VERSION,
        "legacy_whole_page_closing": False,
    }
    collector = DebugBundleCollector(
        target,
        input_path=source_path,
        input_sha256=_file_sha256(source_path),
        page_index=page_index,
        dpi=dpi,
        algorithm_version=algorithm_version,
        git_commit=git_commit,
        git_worktree_dirty=git_worktree_dirty,
        application_source_digest=application_source_digest,
        configuration=configuration,
    )
    image = load_image(
        source_path,
        page_index=page_index,
        pdf_dpi=dpi,
    )
    result = trace_image_optimized(
        image,
        foreground_threshold=foreground_threshold,
        enable_ocr=enable_ocr,
        source_dpi=float(dpi),
        observation_sink=collector,
    )
    structure = result.final_structure
    if structure is None:
        raise AssertionError("Observable trace produced no FinalStructure")
    final_dir = target / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    dxf_path = final_dir / "final-structure.dxf"
    export_result = export_final_structure_dxf(structure, dxf_path)
    if export_result.structure_id != structure.structure_id:
        raise AssertionError("DXF export consumed a different FinalStructure")
    dxf_document = ezdxf.readfile(dxf_path)
    audit = dxf_document.audit()

    render_path = collector.stage_artifact_path(
        "actual_dxf_render",
        suffix=".svg",
    )
    render_payload = _render_dxf_svg(
        dxf_path,
        render_path,
        source_size_px=structure.source_size_px,
    )
    collector.register_existing_file(
        "actual_dxf_render",
        render_path,
        payload={
            **render_payload,
            "dxf_sha256": _file_sha256(dxf_path),
            "dxf_entity_count": len(dxf_document.modelspace()),
            "dxf_audit_error_count": len(audit.errors),
        },
    )
    return collector.finalize(
        structure=structure,
        dxf_path=dxf_path,
        dxf_audit_errors=len(audit.errors),
        dxf_entity_count=len(dxf_document.modelspace()),
    )


def copy_debug_bundle(source: Path, destination: Path) -> None:
    """Copy one completed bundle without silently merging stale artifacts."""

    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(source, destination)

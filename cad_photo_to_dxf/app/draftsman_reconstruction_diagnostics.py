"""Diagnostic-only DXF writer for Draftsman M3 reconstruction UAT."""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import units

from .draftsman_candidate import (
    CandidateKind,
    DraftsmanCandidateManifest,
    LineCandidatePayload,
)
from .draftsman_geometry_reconstruction import (
    DraftsmanGeometryReconstructionManifest,
    LineGeometry,
    ReconstructionState,
)


DIAGNOSTIC_LAYERS: tuple[str, ...] = (
    "EXISTING_STRUCTURE",
    "RC3_ACCEPTED_RECONSTRUCTION",
    "M3_RECONSTRUCTION_PROPOSAL",
    "M3_PROVISIONAL",
    "SOURCE_REFERENCE",
)


def _dxf_point(
    point: tuple[float, float],
    *,
    page_height: float,
) -> tuple[float, float]:
    return (float(point[0]), page_height - float(point[1]))


def _add_line(
    modelspace: object,
    geometry: LineGeometry,
    *,
    page_height: float,
    layer: str,
    record_id: str,
) -> None:
    entity = modelspace.add_line(  # type: ignore[attr-defined]
        _dxf_point(geometry.start, page_height=page_height),
        _dxf_point(geometry.end, page_height=page_height),
        dxfattribs={"layer": layer, "lineweight": max(0, min(211, int(round(geometry.width * 13))))},
    )
    entity.set_xdata("DRAFTSMAN_M3", [(1000, record_id)])


def write_reconstruction_review_dxf(
    path: str | Path,
    *,
    candidate_manifest: DraftsmanCandidateManifest,
    reconstruction_manifest: DraftsmanGeometryReconstructionManifest,
    source_image_path: str | Path | None = None,
) -> Path:
    """Write isolated UAT geometry; this function never touches production DXF."""

    if reconstruction_manifest.candidate_manifest_id != candidate_manifest.manifest_id:
        raise ValueError("reconstruction and candidate manifests do not match")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = ezdxf.new("R2010", setup=True)
    document.units = units.MM
    document.appids.add("DRAFTSMAN_M3")
    colors = {
        "EXISTING_STRUCTURE": 8,
        "RC3_ACCEPTED_RECONSTRUCTION": 3,
        "M3_RECONSTRUCTION_PROPOSAL": 1,
        "M3_PROVISIONAL": 2,
        "SOURCE_REFERENCE": 9,
    }
    for name in DIAGNOSTIC_LAYERS:
        document.layers.add(name, color=colors[name])
    modelspace = document.modelspace()
    page_height = float(candidate_manifest.source_page.source_size_px[1])

    for candidate in candidate_manifest.candidates:
        if candidate.candidate_kind is not CandidateKind.LINE_SEGMENT:
            continue
        payload = candidate.payload
        if not isinstance(payload, LineCandidatePayload):
            continue
        _add_line(
            modelspace,
            LineGeometry.create(payload.start, payload.end, payload.width),
            page_height=page_height,
            layer="EXISTING_STRUCTURE",
            record_id=candidate.stable_candidate_id,
        )
    for accepted in reconstruction_manifest.accepted_reconstructions:
        _add_line(
            modelspace,
            accepted.geometry,
            page_height=page_height,
            layer="RC3_ACCEPTED_RECONSTRUCTION",
            record_id=accepted.stable_entity_id,
        )
    for proposal in reconstruction_manifest.proposals:
        layer = (
            "M3_RECONSTRUCTION_PROPOSAL"
            if proposal.state is ReconstructionState.RECONSTRUCTED
            else "M3_PROVISIONAL"
        )
        _add_line(
            modelspace,
            proposal.proposed_geometry,
            page_height=page_height,
            layer=layer,
            record_id=proposal.stable_proposal_id,
        )

    if source_image_path is not None:
        source = Path(source_image_path).resolve()
        if source.is_file():
            image_definition = document.add_image_def(
                filename=str(source),
                size_in_pixel=candidate_manifest.source_page.source_size_px,
            )
            modelspace.add_image(
                image_definition,
                insert=(0.0, 0.0),
                size_in_units=(
                    float(candidate_manifest.source_page.source_size_px[0]),
                    page_height,
                ),
                dxfattribs={"layer": "SOURCE_REFERENCE"},
            )
    document.header["$EXTMIN"] = (0.0, 0.0, 0.0)
    document.header["$EXTMAX"] = (
        float(candidate_manifest.source_page.source_size_px[0]),
        page_height,
        0.0,
    )
    document.saveas(target)
    return target

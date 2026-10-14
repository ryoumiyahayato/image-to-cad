"""Artificial ARC contract tests. These are not real drawing repair evidence."""

from dataclasses import replace

import ezdxf
import numpy as np
import pytest

from app.core.arc_types import ArcSegment, PdfPathReference, transformed_arc
from app.core.cache import load_trace_cache, save_trace_cache
from app.core.preview import render_final_structure_preview
from app.core.processing import ProductionProcessingConfig, build_processing_cache_key
from app.core.structure import FinalStructure
from app.export.document_export import DocumentPage
from app.export.trace_document_export import export_trace_document_streaming
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.raster_trace import RasterTraceResult


def _structure(arcs=()):
    return FinalStructure((160, 160), np.full((160, 160), 255, np.uint8), (), arcs=arcs)


def _arc(**kw):
    values = dict(
        object_id="contract:arc",
        center=(80, 80),
        radius=35,
        start_angle_deg=300,
        sweep_angle_deg=120,
        source=PdfPathReference("contract.pdf", 1, 0),
        replaced_members=("contract:contour:0",),
        acceptance_reason="artificial contract fixture",
    )
    values.update(kw)
    return ArcSegment(**values)


def _result(s):
    return RasterTraceResult(
        s.contour_binary,
        {},
        s.contours,
        s.threshold,
        int((s.contour_binary == 0).sum()),
        0,
        arcs=s.arcs,
        final_structure=s,
    )


@pytest.mark.parametrize(
    "changes",
    [
        dict(radius=0),
        dict(radius=-1),
        dict(radius=float("nan")),
        dict(center=(float("inf"), 2)),
        dict(start_angle_deg=float("nan")),
        dict(sweep_angle_deg=0),
        dict(sweep_angle_deg=360),
        dict(sweep_angle_deg=-360),
        dict(stroke_width_px=0),
        dict(source_dpi=0),
        dict(lineweight=14),
        dict(object_id=""),
        dict(radius=True),
    ],
)
def test_invalid_arc_is_rejected_before_structure(changes):
    with pytest.raises((ValueError, TypeError)):
        _arc(**changes)


@pytest.mark.parametrize("start,sweep", [(0, 90), (300, 120), (30, -90), (45, 270)])
def test_saved_arc_locus_and_preview(tmp_path, start, sweep):
    a = _arc(start_angle_deg=start, sweep_angle_deg=sweep)
    s = _structure((a,))
    output = export_final_structure_dxf(s, tmp_path / "contract.dxf")
    assert output.arc_count == 1
    doc = ezdxf.readfile(output.path)
    (e,) = doc.modelspace().query("ARC")
    assert tuple(e.dxf.center) == pytest.approx((80, 80, 0))
    assert e.dxf.radius == pytest.approx(35)
    assert e.dxf.layer == "TRACE_CURVE"
    expected_start = start if sweep > 0 else start + sweep
    expected_end = start + sweep if sweep > 0 else start
    assert e.dxf.start_angle == pytest.approx(expected_start % 360)
    assert e.dxf.end_angle == pytest.approx(expected_end % 360)
    image = render_final_structure_preview(s)
    for t in (0.05, 0.5, 0.95):
        x, y = a.point_at(t)
        assert (
            image[round(y) - 2 : round(y) + 3, round(x) - 2 : round(x) + 3].min() < 128
        )
    e.dxf.radius = 36.25
    e.dxf.start_angle = 297
    doc.saveas(tmp_path / "contract-edited.dxf")
    (reread,) = (
        ezdxf.readfile(tmp_path / "contract-edited.dxf").modelspace().query("ARC")
    )
    assert reread.dxf.radius == 36.25
    assert reread.dxf.start_angle == 297


def test_arc_extrema_include_interior_cardinal_and_output_extents(tmp_path):
    a = _arc(start_angle_deg=45, sweep_angle_deg=270)
    assert a.bounds == pytest.approx((45, 45, 80 + 35 / 2**0.5, 115))
    output = export_final_structure_dxf(_structure((a,)), tmp_path / "bounds.dxf")
    doc = ezdxf.readfile(output.path)
    assert tuple(doc.header["$EXTMIN"])[:2] == pytest.approx((45, 45))
    assert tuple(doc.header["$EXTMAX"])[:2] == pytest.approx((80 + 35 / 2**0.5, 115))


def test_mirror_rotation_and_anisotropic_rejection(tmp_path):
    a = _arc(start_angle_deg=0, sweep_angle_deg=90)
    c, r, start, end, extrema = transformed_arc(a, lambda x, y: (-2 * x, 2 * (160 - y)))
    assert c == (-160, 160)
    assert r == 70
    assert start == pytest.approx(90)
    assert end == pytest.approx(180)
    c, r, start, end, _ = transformed_arc(a, lambda x, y: (y, x))
    assert start == pytest.approx(90)
    assert end == pytest.approx(180)
    with pytest.raises(ValueError, match="uniform"):
        transformed_arc(a, lambda x, y: (2 * x, 160 - y))
    with pytest.raises(ValueError, match="uniform"):
        transformed_arc(a, lambda x, y: (x + 0.2 * y, 160 - y))
    with pytest.raises(ValueError):
        transformed_arc(a, lambda x, y: (x * 1e308, y * 1e308))


def test_cache_roundtrip_and_output_identity(tmp_path):
    a = _arc()
    s = _structure((a,))
    stored = load_trace_cache(save_trace_cache(tmp_path / "arc.npz", _result(s)))
    assert stored.arcs == (a,)
    assert stored.final_structure.arcs == (a,)
    assert stored.final_structure.structure_id == s.structure_id
    assert replace(s, arcs=(replace(a, radius=36),)).structure_id != s.structure_id
    assert (
        replace(
            s, arcs=(replace(a, source=PdfPathReference("different.pdf", 1, 0)),)
        ).structure_id
        != s.structure_id
    )


def test_legacy_no_arc_cache_migrates_without_losing_members(tmp_path):
    s = _structure()
    path = save_trace_cache(tmp_path / "legacy.npz", _result(s))
    with np.load(path, allow_pickle=False) as z:
        fields = {key: z[key] for key in z.files if key != "arcs_json"}
    fields.update(
        cache_version=np.array([10]),
        final_structure_schema_version=np.array([3]),
        structure_id=np.array([s.identity_for_schema(3)]),
    )
    np.savez(path, **fields)
    restored = load_trace_cache(path)
    assert restored.arcs == ()
    assert restored.paths == s.contours
    assert np.array_equal(restored.binary, s.contour_binary)


@pytest.mark.parametrize("damage", ["missing", "invalid", "legacy_label"])
def test_arc_cache_cannot_silently_drop_new_contents(tmp_path, damage):
    path = save_trace_cache(tmp_path / "bad.npz", _result(_structure((_arc(),))))
    with np.load(path, allow_pickle=False) as z:
        fields = {key: z[key] for key in z.files}
    if damage == "missing":
        fields.pop("arcs_json")
    elif damage == "invalid":
        import json

        payload = json.loads(str(fields["arcs_json"][0]))
        payload[0]["radius"] = 0
        fields["arcs_json"] = np.array([json.dumps(payload)])
    else:
        fields["cache_version"], fields["final_structure_schema_version"] = (
            np.array([10]),
            np.array([3]),
        )
    np.savez(path, **fields)
    with pytest.raises(ValueError):
        load_trace_cache(path)


def test_pdf_evidence_presence_changes_cache_identity():
    args = dict(
        input_content_sha256="a" * 64, page_index=0, config=ProductionProcessingConfig()
    )
    plain = build_processing_cache_key(**args)
    native = build_processing_cache_key(
        **args,
        pdf_geometry_binding=dict(
            policy="pdf-simple-arc-evidence-v1",
            document="contract.pdf",
            page_number=1,
            requested_dpi=240,
        ),
    )
    assert plain != native


def test_document_export_consumes_arc_and_refuses_ellipse_transform(tmp_path):
    s = _structure((_arc(),))
    page = DocumentPage(1, None, (160, 160), final_structure=s)
    output = export_trace_document_streaming(
        (page,), tmp_path / "document.dxf", total_pages=1
    )
    assert output.arc_count == 1
    doc = ezdxf.readfile(output.path)
    assert len(doc.modelspace().query("ARC")) == 1
    assert tuple(doc.header["$EXTMIN"])[:2] == pytest.approx(
        (80 + 35 * 0.5, 80 - 35 * 3**0.5 / 2)
    )
    assert tuple(doc.header["$EXTMAX"])[:2] == pytest.approx(
        (115, 80 + 35 * 3**0.5 / 2)
    )
    with pytest.raises(ValueError, match="uniform"):
        export_trace_document_streaming(
            (replace(page, page_size_mm=(320, 160)),),
            tmp_path / "anisotropic.dxf",
            total_pages=1,
        )
    assert not (tmp_path / "anisotropic.dxf").exists()


def test_duplicate_final_member_and_frozen_composite_are_explicit_errors():
    with pytest.raises(ValueError, match="Duplicate"):
        _structure((_arc(), _arc()))
    with pytest.raises(ValueError, match="frozen"):
        replace(_structure((_arc(),)), provenance={"draftsman_output_v1": {}})

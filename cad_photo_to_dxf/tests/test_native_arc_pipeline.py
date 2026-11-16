"""Artificial ARC contract tests. These are not real drawing repair evidence."""

from dataclasses import replace

import ezdxf
import numpy as np
import pytest

from app.core.arc_types import ArcSegment, PdfPathReference, transformed_arc
from app.core.cache import load_trace_cache, save_trace_cache
from app.core.preview import render_emitted_dxf_preview, render_final_structure_preview
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


@pytest.mark.parametrize("kind", ["ARC", "CIRCLE"])
def test_curve_preview_uses_same_pixel_width_at_both_dxf_scales(tmp_path, kind):
    views = []
    for unit in (1.0, 25.4 / 240):
        doc = ezdxf.new()
        space = doc.modelspace()
        center = (72.13 * unit, 76.59 * unit)
        attrs = {"lineweight": 25}
        if kind == "ARC":
            curve = space.add_arc(center, 14.2 * unit, 90, 270, dxfattribs=attrs)
        else:
            curve = space.add_circle(center, 7 * unit, dxfattribs=attrs)
        curve.set_xdata("P3A_STROKE", [
            (1000, "NATIVE_PDF_SOURCE_WIDTH"), (1040, 2.4), (1040, 240.0),
        ])
        views.append(render_emitted_dxf_preview(
            doc, tmp_path, (160, 160), roi=(35, 48, 90, 84), output_scale=2,
            units_per_source_pixel=unit,
        ))
    assert views[0].min() < 128
    np.testing.assert_array_equal(views[0], views[1])


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


def test_document_export_consumes_arc(tmp_path):
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


@pytest.mark.parametrize("page_size_mm", [(320, 160), (160, 320)])
@pytest.mark.parametrize("start,sweep", [(300, 120), (30, -90), (45, 270)])
def test_document_unequal_paper_pitches_preserve_arc_locus_as_ellipse(
    tmp_path, page_size_mm, start, sweep
):
    """Paper mapping changes the entity type without changing the source locus.

    The circular-only transformed_arc API still rejects non-similarities in
    test_mirror_rotation_and_anisotropic_rejection. Formal paper export has an
    explicit ELLIPSE branch for unequal raster pitches.
    """
    arc = _arc(start_angle_deg=start, sweep_angle_deg=sweep)
    page = DocumentPage(1, None, page_size_mm, final_structure=_structure((arc,)))
    output = export_trace_document_streaming(
        (page,), tmp_path / "anisotropic.dxf", total_pages=1
    )
    assert output.arc_count == 1

    # Independently map the analytic source circle into paper coordinates.
    # Native PDF curves use edge coordinates, without the raster LINE offset.
    sx, sy = page_size_mm[0] / 160, page_size_mm[1] / 160
    fractions = np.linspace(0.0, 1.0, 17)
    if sweep < 0:
        fractions = 1.0 - fractions  # DXF stores the same locus CCW.
    angles = np.deg2rad(start + sweep * fractions)
    expected = np.column_stack((
        sx * (80 + 35 * np.cos(angles)),
        sy * (80 + 35 * np.sin(angles)),
    ))
    cardinal = [angle for angle in (0, 90, 180, 270)
                if ((angle - start) * (1 if sweep > 0 else -1)) % 360 <= abs(sweep)]
    extent_angles = np.deg2rad([start, start + sweep, *cardinal])
    extrema = np.column_stack((
        sx * (80 + 35 * np.cos(extent_angles)),
        sy * (80 + 35 * np.sin(extent_angles)),
    ))

    reread_path = tmp_path / "anisotropic-reread.dxf"
    ezdxf.readfile(output.path).saveas(reread_path)
    for path in (output.path, reread_path):
        doc = ezdxf.readfile(path)
        assert len(doc.modelspace()) == 1
        (entity,) = doc.modelspace().query("ELLIPSE")
        assert entity.dxf.layer == "PAGE_001_TRACE_CURVE"
        assert entity.dxf.lineweight == arc.lineweight
        assert list(entity.get_xdata("P9_ARC")) == [
            (1000, arc.object_id), (1040, arc.stroke_width_px),
            (1040, arc.source_dpi),
        ]
        ellipse = entity.construction_tool()
        actual = np.array([tuple(point)[:2] for point in
                           ellipse.vertices(ellipse.params(len(fractions)))])
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-9)
        np.testing.assert_allclose(tuple(doc.header["$EXTMIN"])[:2],
                                   extrema.min(axis=0), rtol=0, atol=1e-9)
        np.testing.assert_allclose(tuple(doc.header["$EXTMAX"])[:2],
                                   extrema.max(axis=0), rtol=0, atol=1e-9)


def test_duplicate_final_member_and_frozen_composite_are_explicit_errors():
    with pytest.raises(ValueError, match="Duplicate"):
        _structure((_arc(), _arc()))
    with pytest.raises(ValueError, match="frozen"):
        replace(_structure((_arc(),)), provenance={"draftsman_output_v1": {}})

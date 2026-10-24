"""Snapshot-bound manual TEXT. No OCR candidate or inferred OCR identity."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from math import cos, isfinite, radians, sin
from uuid import UUID, uuid4

import cv2
import numpy as np

from app.export.ocr_outline_export import (
    NativeTextPlacement,
    _librecad_text_extent,
    _line_placement_from_quad,
    _normalised_content,
)
from app.ocr.librecad_lff import LIBRECAD_STYLE_NAME, ensure_librecad_dxf_style

KIND = "MANUAL_TEXT_INSERTION"
APPID = "MANUAL_TEXT_INSERTION"
EVENT_VERSION = 3


def _fail(message):
    from app.core.review_project import ReviewProjectError

    raise ReviewProjectError(message)


def _uuid(value):
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        _fail("REJECTED_IDENTITY_MISMATCH: manual UUID")


def content_metrics(content):
    if (
        not isinstance(content, str)
        or not content
        or content != _normalised_content(content)
        or any(ord(c) < 32 for c in content)
        or len(content.encode("utf-8")) > 250
    ):
        _fail("请输入非空单行文字（UTF-8最多250字节）")
    metrics = _librecad_text_extent(content, style_name=LIBRECAD_STYLE_NAME)
    if metrics.fallback_reason or metrics.width <= 0 or metrics.height <= 0:
        _fail("正式LFF缺少该字符；不能把替代字形当作正确预览")
    return metrics


def source_evidence(project, selection):
    """Keep exact leaf contour points; mixed/partial selections stay visible."""
    if (
        not isinstance(selection, (list, tuple))
        or len(selection) != 4
        or any(type(v) is not int for v in selection)
    ):
        _fail("Invalid manual source selection")
    width, height = project.baseline.source_size_px
    x, y, w, h = [int(v) for v in selection]
    if not (0 <= x < x + w <= width and 0 <= y < y + h <= height):
        _fail("选区必须位于源图内")
    frame = project.frame[y : y + h, x : x + w]
    if frame.ndim == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    ys, xs = np.where(frame < 180)
    if not len(xs):
        _fail("选区没有源墨迹")
    ink = [
        int(x + xs.min()),
        int(y + ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    ]
    s = project.baseline
    records = []
    crossing = False
    for index, p in enumerate(s.contours):
        a = np.asarray(p.points, dtype=float)
        if not len(a):
            continue
        if (
            a[:, 0].max() < x
            or a[:, 0].min() >= x + w
            or a[:, 1].max() < y
            or a[:, 1].min() >= y + h
        ):
            continue
        inside = (a[:, 0] >= x) & (a[:, 0] < x + w) & (a[:, 1] >= y) & (a[:, 1] < y + h)
        intersects = any(
            cv2.clipLine(
                (x, y, w, h),
                tuple(np.rint(start).astype(int)),
                tuple(np.rint(end).astype(int)),
            )[0]
            for start, end in zip(a, np.roll(a, -1, axis=0))
        )
        if intersects and not inside.all():
            crossing = True
        if inside.any():
            if not inside.all():
                crossing = True
            else:
                records.append(
                    dict(
                        index=index,
                        points=[[float(a), float(b)] for a, b in p.points],
                        parent=p.parent,
                        depth=p.depth,
                        root=p.root,
                    )
                )
    reason = "来源不全或混合；保留原轮廓，人工TEXT可能重叠"
    complete = False
    if len(records) == 1 and not crossing:
        r = records[0]
        p = s.contours[r["index"]]
        local = (s.contour_binary[y : y + h, x : x + w] < 128).astype(np.uint8)
        n, labels = cv2.connectedComponents(local, 8)
        a = np.asarray(p.points)
        component = labels[int(a[0, 1]) - y, int(a[0, 0]) - x]
        mask = labels == component
        # A single complete connected leaf, strictly inside the selection.
        source_ink = (frame < 180).astype(np.uint8)
        source_components, _ = cv2.connectedComponents(source_ink, 8)
        complete = bool(
            n == 2
            and source_components == 2
            and component
            and p.parent is None
            and p.depth == 0
            and not any(q.parent == r["index"] for q in s.contours)
            and 4 <= len(p.points) <= 64
            and not (
                mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any()
            )
            and all(mask[int(b) - y, int(a) - x] for a, b in p.points)
        )
        if complete:
            from app.export.trace_dxf_entities import _classify_region

            complete = (
                _classify_region(p, source_size=s.source_size_px, hole_count=0)
                == "TRACE_TEXT_SYMBOL"
            )
            # Existing P16 bound contours retain their original layer contract.
            bindings = s.provenance.get("contour_source_bindings_v1", {})
            if any(
                item.get("member_index") == r["index"]
                for item in bindings.get("records", ())
            ):
                complete = False
        # Any independent native structure in the selection prevents transfer.
        if complete:
            for line in s.straight_lines:
                if cv2.clipLine(
                    (x, y, w, h),
                    (round(line.x1), round(line.y1)),
                    (round(line.x2), round(line.y2)),
                )[0]:
                    complete = False

            def overlaps(left, top, right, bottom):
                return min(x + w, right) > max(x, left) and min(y + h, bottom) > max(
                    y, top
                )

            for arc in s.arcs:
                cx, cy = arc.center
                radius = arc.radius + arc.stroke_width_px
                if overlaps(cx - radius, cy - radius, cx + radius, cy + radius):
                    complete = False
            for fill in s.native_fills:
                pts = np.asarray(fill.points)
                if overlaps(*pts.min(axis=0), *pts.max(axis=0)):
                    complete = False
            for text in s.texts:
                tx, ty, tw, th = text.bbox
                if overlaps(tx, ty, tx + tw, ty + th):
                    complete = False
            for obj in (*s.signatures, *s.logos):
                tx, ty, tw, th = obj.bbox
                if overlaps(tx, ty, tx + tw, ty + th):
                    complete = False
    return dict(
        selection=[x, y, w, h],
        ink_bounds=ink,
        contours=records,
        state="COMPLETE_INDEPENDENT_CONTOUR" if complete else "SAFE_OVERLAY_ONLY",
        reason="完整独立源轮廓；最终布局确认后转入隐藏备份" if complete else reason,
    )


def suggest(project, selection, content):
    metrics = content_metrics(content)
    evidence = source_evidence(project, selection)
    x, y, w, h = evidence["ink_bounds"]
    quad = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    geometry = _line_placement_from_quad(
        quad,
        transform=lambda a, b: (a, project.baseline.source_size_px[1] - b),
        metrics=metrics,
    )
    params = dict(
        x=geometry.insert[0],
        y=project.baseline.source_size_px[1] - geometry.insert[1],
        height=geometry.character_height,
        width=geometry.width_factor,
        rotation=geometry.rotation,
    )
    return dict(evidence=evidence, parameters=params)


def placement(project, content, parameters, transform):
    metrics = content_metrics(content)
    if set(parameters) != {"x", "y", "height", "width", "rotation"} or any(
        type(v) not in (int, float) or not isfinite(v) for v in parameters.values()
    ):
        _fail("Invalid manual TEXT parameters")
    p = parameters
    if not (
        0 < p["height"] <= max(project.baseline.source_size_px)
        and 0.01 <= p["width"] <= 100
        and -360 <= p["rotation"] <= 360
    ):
        _fail("人工TEXT字高、宽度或角度超出范围")
    a = radians(p["rotation"])
    c, s = cos(a), sin(a)
    sx = p["height"] / metrics.em_height * p["width"]
    sy = p["height"] / metrics.em_height

    def source(u, v):
        return p["x"] + c * u * sx - s * v * sy, p["y"] - s * u * sx - c * v * sy

    source_quad = tuple(
        source(u, v)
        for u, v in (
            (metrics.min_x, metrics.max_y),
            (metrics.max_x, metrics.max_y),
            (metrics.max_x, metrics.min_y),
            (metrics.min_x, metrics.min_y),
        )
    )
    if any(
        not (
            0 <= x <= project.baseline.source_size_px[0]
            and 0 <= y <= project.baseline.source_size_px[1]
        )
        for x, y in source_quad
    ):
        _fail("人工TEXT可见字形超出源页面")
    geometry = _line_placement_from_quad(
        source_quad, transform=transform, metrics=metrics
    )
    return NativeTextPlacement(content, metrics, geometry)


def replay(project):
    active = {}
    seen = {}
    events = set()
    for r in project._records:
        if not isinstance(r, dict):
            _fail("Invalid review journal record")
        if r.get("event_type") != KIND:
            continue
        if set(r) != {
            "format_version",
            "event_type",
            "project_uuid",
            "snapshot_uuid",
            "snapshot_source",
            "manual_uuid",
            "event_uuid",
            "revision",
            "previous_event_uuid",
            "action",
            "selection",
            "evidence",
            "content",
            "parameters",
            "confirmation",
            "content_confirmation",
            "layout_confirmation",
            "source_transfer",
            "source_hide_authorized",
            "content_transaction",
            "layout_transaction",
            "source_transaction",
        }:
            _fail(
                "Invalid manual event fields; OCR identity is not manual source evidence"
            )
        _uuid(r.get("manual_uuid"))
        _uuid(r.get("event_uuid"))
        if r["event_uuid"] in seen:
            if seen[r["event_uuid"]] != r:
                _fail("Conflicting manual event UUID")
            continue
        seen[r["event_uuid"]] = r
        if (
            r.get("format_version") != EVENT_VERSION
            or r.get("snapshot_uuid") != project.snapshot_uuid
            or r.get("snapshot_source") != project._manifest["source"]
            or r.get("project_uuid") != project.snapshot_uuid
        ):
            _fail("NEEDS_RECONFIRM: manual source/document/snapshot identity")
        previous = active.get(r["manual_uuid"])
        if type(r.get("revision")) is not int or r.get("revision") != (
            previous["revision"] + 1 if previous else 1
        ):
            _fail("Manual event revision conflict")
        if r.get("previous_event_uuid") != (
            previous["event_uuid"] if previous else None
        ):
            _fail("Manual event precondition conflict")
        action = r.get("action")
        if action not in {"CONFIRM_CONTENT", "CONFIRM_LAYOUT", "WITHDRAW"}:
            _fail("Unknown manual event action")
        confirmation = r.get("confirmation", {})
        _uuid(confirmation.get("event_uuid"))
        try:
            datetime.fromisoformat(confirmation["at"])
        except (KeyError, ValueError, TypeError):
            _fail("Manual confirmation time is missing")
        if (
            confirmation.get("kind") not in {"GUI_EXPLICIT_CONFIRM", "QA_TEST_ONLY"}
            or confirmation.get("explicit") is not True
            or confirmation["event_uuid"] in events
        ):
            _fail("Missing or repeated manual confirmation")
        events.add(confirmation["event_uuid"])
        if (
            "TEST_ONLY" in project._manifest.get("origin", "").upper()
            and confirmation["kind"] != "QA_TEST_ONLY"
        ):
            _fail("QA project cannot record a human confirmation")
        if r.get("evidence") != source_evidence(project, r.get("selection")):
            _fail("NEEDS_RECONFIRM: manual source contour/ink evidence changed")
        placement(
            project,
            r.get("content"),
            r.get("parameters"),
            lambda x, y: (x, project.baseline.source_size_px[1] - y),
        )
        if type(r.get("source_hide_authorized")) is not bool:
            _fail("Explicit source transfer authorization is missing")
        if action == "CONFIRM_CONTENT":
            if (
                r.get("content_confirmation") != r["event_uuid"]
                or r.get("layout_confirmation") is not None
                or r.get("source_transfer") != "VISIBLE_PENDING"
            ):
                _fail("Content confirmation cannot hide source geometry")
        else:
            if not previous or previous["action"] == "WITHDRAW":
                _fail("Confirm manual content first")
            for key in (
                "content",
                "selection",
                "evidence",
                "parameters",
                "content_confirmation",
                "source_hide_authorized",
            ):
                if r.get(key) != previous.get(key):
                    _fail("Manual content/layout precondition changed")
            if confirmation["kind"] != previous["confirmation"]["kind"]:
                _fail("Manual QA and human confirmation domains differ")
            expected = (
                (
                    "HIDDEN_FROZEN_BACKUP"
                    if r["evidence"]["state"] == "COMPLETE_INDEPENDENT_CONTOUR"
                    and len(r["content"]) == 1
                    and r["source_hide_authorized"]
                    else "COEXISTING_OVERLAY"
                )
                if action == "CONFIRM_LAYOUT"
                else "RESTORED_VISIBLE"
            )
            if r.get("source_transfer") != expected or r.get("layout_confirmation") != (
                r["event_uuid"]
                if action == "CONFIRM_LAYOUT"
                else previous["layout_confirmation"]
            ):
                _fail("Invalid manual source transfer/layout confirmation")
        if any(r[key] != value for key, value in transactions(r).items()):
            _fail("Manual content/layout/source transactions differ from their events")
        active[r["manual_uuid"]] = r
    # Prevent duplicate selected source ink, including separate UUIDs.
    records = [r for r in active.values() if r["action"] != "WITHDRAW"]
    for i, a in enumerate(records):
        x, y, w, h = a["selection"]
        for b in records[i + 1 :]:
            u, v, sw, sh = b["selection"]
            if min(x + w, u + sw) > max(x, u) and min(y + h, v + sh) > max(y, v):
                _fail("同一源区域已有人工补录；请编辑或撤回现有记录")
    return deepcopy(active)


def transactions(record):
    action = record["action"]
    withdrawn = action == "WITHDRAW"
    layout = record["layout_confirmation"]
    state = record["source_transfer"]
    reason = (
        record["evidence"]["reason"]
        if record["evidence"]["state"] != "COMPLETE_INDEPENDENT_CONTOUR"
        else "多字符保留原轮廓；不声称逐字符完整来源"
        if len(record["content"]) != 1
        else "未授权源轮廓转交"
        if not record["source_hide_authorized"]
        else ""
    )
    return dict(
        content_transaction=dict(
            state="WITHDRAWN" if withdrawn else "CONFIRMED",
            confirmation_event=record["content_confirmation"],
            withdrawal_event=record["event_uuid"] if withdrawn else None,
        ),
        layout_transaction=dict(
            state="WITHDRAWN" if withdrawn else "CONFIRMED" if layout else "PENDING",
            confirmation_event=layout,
            withdrawal_event=record["event_uuid"] if withdrawn else None,
        ),
        source_transaction=dict(
            state=state,
            qualification=record["evidence"]["state"],
            failure_reason=reason
            if state in {"VISIBLE_PENDING", "COEXISTING_OVERLAY"}
            else "",
            authorization=record["source_hide_authorized"],
            confirmation_event=layout,
            withdrawal_event=record["event_uuid"] if withdrawn else None,
            withdrawal_behavior="REMOVE_MANUAL_TEXT_AND_RESTORE_IMMUTABLE_SOURCE",
            contour_references=record["evidence"]["contours"]
            if state == "HIDDEN_FROZEN_BACKUP"
            else [],
        ),
    )


def confirm(
    project,
    *,
    selection=None,
    content=None,
    parameters=None,
    manual_uuid=None,
    action="CONFIRM_CONTENT",
    event,
    source_hide_authorized=False,
):
    project.validate_source()
    current = replay(project)
    previous = current.get(manual_uuid)
    if action == "WITHDRAW" and (not previous or previous["action"] == "WITHDRAW"):
        return None
    if (
        action == "CONFIRM_LAYOUT"
        and previous
        and previous["action"] == "CONFIRM_LAYOUT"
    ):
        return None
    if action != "CONFIRM_CONTENT":
        if not previous:
            _fail("请先确认内容")
        selection, content, parameters = (
            previous["selection"],
            previous["content"],
            previous["parameters"],
        )
        source_hide_authorized = previous["source_hide_authorized"]
    proposal = suggest(project, selection, content)
    parameters = parameters or proposal["parameters"]
    if (
        previous
        and previous["action"] == "CONFIRM_CONTENT"
        and action == "CONFIRM_CONTENT"
        and all(
            previous[k] == v
            for k, v in [
                ("selection", list(selection)),
                ("content", content),
                ("parameters", parameters),
                ("source_hide_authorized", source_hide_authorized),
            ]
        )
    ):
        return None
    identity = manual_uuid or str(uuid4())
    eid = str(uuid4())
    confirmation = {**asdict(event), "explicit": True}
    if confirmation["kind"] == "TEST_ONLY":
        confirmation["kind"] = "QA_TEST_ONLY"
    r = dict(
        format_version=EVENT_VERSION,
        event_type=KIND,
        project_uuid=project.snapshot_uuid,
        snapshot_uuid=project.snapshot_uuid,
        snapshot_source=deepcopy(project._manifest["source"]),
        manual_uuid=identity,
        event_uuid=eid,
        revision=previous["revision"] + 1 if previous else 1,
        previous_event_uuid=previous["event_uuid"] if previous else None,
        action=action,
        selection=list(selection),
        evidence=proposal["evidence"],
        content=content,
        parameters=parameters,
        source_hide_authorized=source_hide_authorized,
        confirmation=confirmation,
        content_confirmation=eid
        if action == "CONFIRM_CONTENT"
        else previous["content_confirmation"],
        layout_confirmation=eid
        if action == "CONFIRM_LAYOUT"
        else (previous["layout_confirmation"] if action == "WITHDRAW" else None),
        source_transfer=(
            "VISIBLE_PENDING"
            if action == "CONFIRM_CONTENT"
            else "RESTORED_VISIBLE"
            if action == "WITHDRAW"
            else "HIDDEN_FROZEN_BACKUP"
            if proposal["evidence"]["state"] == "COMPLETE_INDEPENDENT_CONTOUR"
            and len(content) == 1
            and source_hide_authorized
            else "COEXISTING_OVERLAY"
        ),
    )
    r.update(transactions(r))
    project.add_records([r])
    return deepcopy(r)


def xdata_values(project, record):
    return [
        EVENT_VERSION,
        KIND,
        project.snapshot_uuid,
        record["manual_uuid"],
        record["event_uuid"],
        record["confirmation"]["kind"],
        record["source_transfer"],
        project._manifest["source"]["document_uuid"],
        project._manifest["source"]["physical_page"],
        "USER_SUPPLIED_NO_OCR",
        record["content_confirmation"],
        record["layout_confirmation"],
    ]


def emit(review, doc, modelspace, transform, names, guard):
    project = review._project
    layer = names["OCR_TEXT"] + "_MANUAL"
    if layer not in doc.layers:
        doc.layers.add(layer, color=6, lineweight=0)
        if doc.layers.get(names["OCR_TEXT"]).is_off():
            doc.layers.get(layer).off()
    expected = []
    entities = []
    coordinates = []
    records = [r for r in replay(project).values() if r["action"] == "CONFIRM_LAYOUT"]
    for r in records:
        p = placement(project, r["content"], r["parameters"], transform)
        g = p.geometry
        e = modelspace.add_text(
            r["content"],
            dxfattribs=dict(
                layer=layer,
                style=ensure_librecad_dxf_style(doc),
                insert=g.insert,
                height=g.character_height,
                width=g.width_factor,
                rotation=g.rotation,
            ),
        )
        if APPID not in doc.appids:
            doc.appids.add(APPID)
        values = xdata_values(project, r)
        e.set_xdata(
            APPID,
            [
                (
                    1070
                    if type(v) is int and i == 0
                    else 1071
                    if type(v) is int
                    else 1000,
                    v,
                )
                for i, v in enumerate(values)
            ],
        )
        backup = None
        if r["source_transfer"] == "HIDDEN_FROZEN_BACKUP":
            # Match the COMPLETE ordered boundary. Never select by bounding box.
            source = r["evidence"]["contours"][0]
            target = [transform(x, y) for x, y in source["points"]]
            matches = []
            for other in modelspace.query("LWPOLYLINE"):
                if other.dxf.layer != names["TRACE_TEXT_SYMBOL"]:
                    continue
                pts = list(other.get_points("xy"))
                if len(pts) == len(target) and np.allclose(
                    pts, target, rtol=0, atol=1e-7
                ):
                    matches.append(other)
            if len(matches) != 1:
                _fail(
                    "NEEDS_RECONFIRM: complete manual source boundary is not uniquely emitted"
                )
            matches[0].dxf.layer = names["SOURCE_TEXT_OUTLINE"]
            matches[0].set_xdata(
                APPID,
                [
                    (1070, EVENT_VERSION),
                    (1000, r["manual_uuid"]),
                    (1000, "COMPLETE_SOURCE_BACKUP"),
                ],
            )
            backup = dict(
                points=[list(pt) for pt in target],
                layer=names["SOURCE_TEXT_OUTLINE"],
                values=[EVENT_VERSION, r["manual_uuid"], "COMPLETE_SOURCE_BACKUP"],
            )
        expected.append(
            dict(
                content=r["content"],
                values=values,
                insert=list(g.insert),
                height=g.character_height,
                width=g.width_factor,
                rotation=g.rotation,
                style=p.metrics.style_name,
                backup=backup,
                layer_off=doc.layers.get(layer).is_off(),
            )
        )
        entities.append(e)
        from app.export.review_text import visible_corners

        coordinates.extend(visible_corners(p))
    guard.expect_manual(layer, expected, review)
    return entities, coordinates

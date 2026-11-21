"""GUI-independent native-task display and coordinate contracts.

No OCR, candidate selection, source reassignment, or CAD rendering lives here.
"""

from __future__ import annotations

from pathlib import Path
import json
import math
import os


ACTIVE_STATUSES = frozenset({"STARTING", "RUNNING", "CANCEL_REQUESTED"})
RECOVERABLE_STATUSES = frozenset({"QUEUED", "CANCELLED", "FAILED", "INTERRUPTED"})
PUBLISHED_STATUSES = frozenset({"COMPLETED_WITH_ISSUES", "COMPLETED"})
STATUS_LABELS = {
    "QUEUED": "待开始",
    "STARTING": "正在启动",
    "RUNNING": "处理中",
    "CANCEL_REQUESTED": "正在取消",
    "CANCELLED": "已取消，可恢复",
    "FAILED": "失败，证据已保留",
    "INTERRUPTED": "中断，可恢复",
    "RESOURCE_STOP": "资源预算已停止，检查点保留；不能自动扩大预算恢复",
    "COMPLETED_WITH_ISSUES": "已生成，含待修项",
    "COMPLETED": "已生成",
}


def default_jobs_root() -> Path:
    configured = os.environ.get("I2CAD_JOBS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return base / "ImageToCAD" / "jobs"


def _edge_transform(x: float, y: float, width: float, height: float, orientation: int):
    """Half-open pixel-cell edges; intentionally not pixel-centre W-1/H-1."""
    if orientation == 0:
        return x, y
    if orientation == 90:
        return height - y, x
    if orientation == 180:
        return width - x, height - y
    if orientation == 270:
        return y, width - x
    raise ValueError("Orientation must be 0, 90, 180 or 270 degrees")


def source_roi_to_preview(roi, source_size, preview_size, orientation):
    width, height = map(float, source_size)
    work_width, work_height = (
        (height, width) if orientation in (90, 270) else (width, height)
    )
    sx, sy = preview_size[0] / work_width, preview_size[1] / work_height
    x0, y0, x1, y1 = roi
    points = [
        _edge_transform(x, y, width, height, orientation)
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
    return [
        min(p[0] for p in points) * sx,
        min(p[1] for p in points) * sy,
        max(p[0] for p in points) * sx,
        max(p[1] for p in points) * sy,
    ]


def preview_rect_to_source(rect, source_size, preview_size, orientation):
    width, height = map(int, source_size)
    work_width, work_height = (
        (height, width) if orientation in (90, 270) else (width, height)
    )
    sx, sy = work_width / preview_size[0], work_height / preview_size[1]
    x0, y0, x1, y1 = rect
    points = []
    for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        x, y = px * sx, py * sy
        if orientation == 0:
            p = x, y
        elif orientation == 90:
            p = y, height - x
        elif orientation == 180:
            p = width - x, height - y
        elif orientation == 270:
            p = width - y, x
        else:
            raise ValueError("Invalid orientation")
        points.append(p)

    # Undo only binary round-off from displaying an exact integer pixel-cell
    # edge at thumbnail scale. This does not snap fitted geometry, alter a
    # source mask, or expand any CAD acceptance tolerance. A genuinely
    # fractional drag still encloses whole source cells with floor/ceil.
    def pixel_edge(value):
        integer = round(value)
        return (
            float(integer)
            if abs(value - integer) <= 8 * math.ulp(max(1.0, abs(value)))
            else value
        )

    return [
        max(0, min(width, math.floor(pixel_edge(min(p[0] for p in points))))),
        max(0, min(height, math.floor(pixel_edge(min(p[1] for p in points))))),
        max(0, min(width, math.ceil(pixel_edge(max(p[0] for p in points))))),
        max(0, min(height, math.ceil(pixel_edge(max(p[1] for p in points))))),
    ]


def issue_local_box(issue, working_roi):
    box = issue.get("bbox_xyxy_px")
    if box is None:
        return None
    if len(box) != 4 or not all(math.isfinite(float(v)) for v in box):
        raise ValueError("Malformed issue location; do not silently drop it")
    x0, y0, _, _ = working_roi
    return [
        float(box[0]) - x0,
        float(box[1]) - y0,
        float(box[2]) - x0,
        float(box[3]) - y0,
    ]


def load_quality(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("coordinate_system") != "job_working_pixels_top_left":
        raise ValueError(
            "Quality issues are not in the current job working coordinate system"
        )
    if len(data.get("roi_xyxy_px", [])) != 4 or not isinstance(
        data.get("issues"), list
    ):
        raise ValueError("Incomplete quality issue document")
    ids = [row.get("id") for row in data["issues"]]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(
        set(ids)
    ):
        raise ValueError("Quality issue IDs must be present and unique")
    for row in data["issues"]:
        issue_local_box(row, data["roi_xyxy_px"])
    return data


ISSUE_STATUS_LABELS = {
    "PENDING_SOURCE_REPAIR": "待补全",
    "PENDING_TEXT_GROUP": "注释待补全",
    "REVIEW_TEXT_OR_SHARED_SOURCE": "文字 / 共享来源待核对",
    "REVIEW_TEXT_CONTENT_AND_LAYOUT": "文字内容与排版待核对",
    "REVIEW_OBJECT_EXTENT": "完整范围待核对",
    "REVIEW_SOURCE_SHAPE": "来源形状待核对",
    "REVIEW_OBJECT_CLASS_AND_EDIT_SCOPE": "类别与编辑范围待核对",
    "REJECT_STRUCTURE": "文件结构不合格",
    "REJECT_SOURCE": "来源检查不合格",
    "SOURCE_PIXELS_REPRESENTED_NOT_SEMANTIC_PROOF": "来源像素已对应，类别未确认",
}

ISSUE_REASON_LABELS = {
    "UNEXPLAINED_OR_PARTLY_RECONSTRUCTED_SOURCE_GROUP": "这组原图墨迹尚未完整重建",
    "TEXT_OR_SHARED_INK_GROUP_REQUIRES_CONTENT_AND_OWNERSHIP_REVIEW": "文字或共享墨迹的内容与归属尚未确认",
    "SOURCE_GROUP_CLIPPED_BY_SELECTED_REGION": "来源组触及选区边缘，需要核对完整范围",
    "TOLERANCE_SUPPORT_WITHOUT_FULL_RASTER_SOURCE_REPLACEMENT": "图元接近来源，但原扫形状仍有差异",
    "LOCAL_OCR_AND_LITERAL_DXF_AGREE_BUT_CONTENT_AND_LAYOUT_REQUIRE_REVIEW": "已保存可编辑文字，内容与排版仍需对照原图",
    "OBSERVED_OBJECT_EXTENT_CLIPPED_BY_SELECTION": "选区截断了候选对象的范围",
    "COMPOSITE_GEOMETRY_CHECKED_ENGINEERING_CLASS_OR_EDIT_SCOPE_NOT_HUMAN_VERIFIED": "组合几何已有检查，工程类别和整体编辑范围尚未确认",
    "CURRENT_TEXT_GROUP_NOT_EXPORTED_COMPLETE": "这组注释尚未完整输出",
    "CURRENT_CANDIDATE_MISSING_FROM_SAVED_DXF": "本次候选未出现在实际保存的 DXF 中",
    "EXACT_DUPLICATE_SAVED_NATIVE_GEOMETRY": "保存的原生几何存在精确重复",
    "DXF_UNITS_DO_NOT_MATCH_EXPLICIT_PAPER_MM": "DXF 单位与纸面毫米约定不一致",
    "NAVIGATION_REVIEW_LAYER_MUST_BE_OFF_LOCKED_NONPLOTTING": "导航图层的关闭、锁定或打印设置不正确",
    "TEXT_STYLE_OR_PORTABLE_FONT_DEPENDENCY_MISSING": "文字样式或配套字体缺失",
    "SAVED_FORMAL_ENTITY_WITHOUT_CANDIDATE_IDENTITY": "保存实体缺少本次候选的身份记录",
    "SAVED_ENTITY_DUPLICATE_OR_UNKNOWN_CANDIDATE_ID": "保存实体的候选身份重复或无法对应",
    "SAVED_NATIVE_ENTITY_DIFFERS_FROM_CURRENT_CANDIDATE_OR_STRUCTURE": "保存图元与本次候选或约定结构不一致",
    "SAVED_OBJECT_FAILS_OR_LACKS_SOURCE_GEOMETRY_CHECK": "保存对象未通过来源几何检查，或缺少该检查",
    "DXF_AUDITOR_ERRORS": "实际 DXF 存在审计错误",
    "DXF_AUDITOR_IN_MEMORY_FIXES_ARE_NOT_ORIGINAL_VALIDITY": "DXF 需要读取器修复，不能视为原文件合格",
    "CURVED_OR_BRANCH_CONTINUATION_NOT_A_WHOLE_LINE": "曲线或分支仍有延续，不能当作完整独立直线",
    "CONNECTION_EDIT_RESPONSIBILITY_PENDING": "连接线与邻近来源的编辑责任尚未确认",
    "DOOR_EDIT_RESPONSIBILITY_PENDING": "门及邻近来源的编辑责任尚未确认",
    "DENSE_SOURCE_GATE_REJECT": "密集位置的候选未通过来源检查",
    "WALL_EDIT_PARTITION_REJECTED_SOURCE_GATE": "墙段的编辑范围分解未通过来源检查",
    "RESUMED_LINE_NEW_TEXT_RESPONSIBILITY": "恢复后的直线与文字区域关系需要重新核对",
    "INCOMPLETE_OR_AMBIGUOUS_COMPOSITE_ANNOTATION": "组合标注不完整或存在多种解释",
    "TEXT_UNRESOLVED_WHOLE_FRAME_PENDING": "文字未确认，完整边框保留为待修",
    "ANNOTATION_GROUP_INCOMPLETE": "注释组不完整",
    "BOUNDED_EXPERIMENT_CANDIDATE_CAP_NOT_A_GEOMETRY_FAILURE": "候选数量达到本轮限制，未继续研究的部分保留待修",
}


def issue_reason_text(issue):
    reason = str(issue.get("reason") or "")
    code = reason.removeprefix("CANDIDATE_UNCERTAINTY:")
    return ISSUE_REASON_LABELS.get(
        code, "此处仍有未确定的来源或候选关系，需要对照原图核对"
    )


def issue_position_text(issue):
    box = issue.get("bbox_xyxy_px")
    if box is None:
        return "尚无可靠位置"

    def number(value):
        return f"{float(value):.3f}".rstrip("0").rstrip(".")

    return f"({number(box[0])}, {number(box[1])})—({number(box[2])}, {number(box[3])}) 像素"


def issue_label(issue):
    status = ISSUE_STATUS_LABELS.get(issue.get("status"), "待核对")
    return f"{status} · {issue_reason_text(issue)}\n位置：{issue_position_text(issue)}"


def issue_user_details(issue):
    lines = [
        f"状态：{ISSUE_STATUS_LABELS.get(issue.get('status'), '待核对')}",
        f"原因：{issue_reason_text(issue)}",
        f"位置：{issue_position_text(issue)}（当前工作图像坐标）",
    ]
    support = issue.get("source_support") or {}
    if "source_pixel_count" in support:
        lines.append(f"该组来源墨迹：{support['source_pixel_count']} 个像素")
    if "neither_rendered_nor_near_verified_geometry" in support:
        lines.append(
            f"尚未由输出或已验证邻近几何解释：{support['neither_rendered_nor_near_verified_geometry']} 个像素"
        )
    if issue.get("source_group_ids"):
        lines.append("这是原图中的相接墨迹组，尚不能据此认定为一个工程对象。")
    if issue.get("object_ids"):
        label = (
            "附近候选" if support.get("bbox_contact_is_not_ownership") else "相关候选"
        )
        lines.append(
            f"{label}：{len(issue['object_ids'])} 个；相邻或相交本身不能证明共同归属。"
        )
    lines.append("完整来源记录、编号及审核字段保留在下方“技术记录”。")
    return "\n".join(lines)


def saved_review_notice(verification):
    if verification and verification.get("valid") is True:
        return "审核绑定与当前输入及版本匹配；待修项仍需核对。"
    fields = {row.get("field") for row in (verification or {}).get("mismatches", [])}
    if fields & {"review_code_sha256", "runtime_sha256"}:
        return "旧版本结果，待按当前版本重新审核。可查看来源和历史，暂不可导出。"
    return "审核绑定已失效或证据不完整，待重新审核。可查看来源和历史，暂不可导出。"


def request_from_controls(
    input_path, roi, dpi, page, frame, orientation, language="eng"
):
    if not input_path:
        raise ValueError("请先选择原始文件")
    if language != "eng":
        raise ValueError("当前部署的原生文字流程仅支持英语；未部署语言不可冒充可用")
    values = [int(value) for value in roi]
    if not (0 <= values[0] < values[2] and 0 <= values[1] < values[3]):
        raise ValueError("请选择有效的原始像素区域")
    return {
        "input_path": str(Path(input_path).expanduser().resolve()),
        "roi": values,
        "dpi": int(dpi),
        "page_number": int(page) if page else None,
        "frame_number": int(frame) if frame else None,
        "orientation": int(orientation),
        "language": language,
    }

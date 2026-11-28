"""Fit editable text to the clear area of confirmed scan table cells."""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from math import cos, radians, sin
from pathlib import Path

import cv2
import numpy as np
from ezdxf.enums import TextEntityAlignment
from ezdxf.fonts import fonts
from ezdxf.lldxf.encoding import decode_dxf_unicode

from app.core.cancellation import checkpoint


def _printed_cells(binary, span):
    """Find rectangular holes bounded by observed horizontal and vertical ink."""
    ink = cv2.bitwise_not(binary)
    opening = dict(borderType=cv2.BORDER_CONSTANT, borderValue=0)
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, span), np.uint8), **opening)
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((span, 1), np.uint8), **opening)
    contours, hierarchy = cv2.findContours(
        horizontal | vertical, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE,
    )
    if hierarchy is None:
        return

    groups = defaultdict(list)
    for contour, parent in zip(contours, hierarchy[0, :, 3]):
        if parent < 0:
            continue
        _, _, width, height = cv2.boundingRect(contour)
        if min(width, height) < 6 or cv2.contourArea(contour) < 0.92 * (width - 1) * (height - 1):
            continue
        corners = cv2.approxPolyDP(contour, max(1.0, 0.025 * min(width, height)), True)
        if len(corners) != 4 or not cv2.isContourConvex(corners):
            continue
        # Use the inner edge at each end of a slightly skewed ruling.
        low, high = np.sort(corners[:, 0, :], axis=0)[1:3].astype(float)
        if np.all(high - low >= 4):
            groups[parent].append(np.concatenate((low, high)))

    for cells in groups.values():
        if len(cells) < 2:
            continue
        others = np.asarray(cells)
        for cell in cells:
            low, high = cell[:2], cell[2:]
            pen_limit = np.clip(0.2 * min(high - low), 3, 12)
            gap = np.maximum(others[:, :2] - high, low - others[:, 2:])
            length = np.minimum(others[:, 2:] - others[:, :2], high - low)
            # Adjacent holes must share enough of one divider. A common
            # perpendicular edge distinguishes rows/columns from nearby boxes.
            aligned = np.minimum(abs(others[:, :2] - low), abs(others[:, 2:] - high))
            for axis in (0, 1):
                across = 1 - axis
                if np.any((gap[:, axis] >= 0) & (gap[:, axis] <= pen_limit)
                          & (gap[:, across] <= -0.5 * length[:, across])
                          & (aligned[:, across] <= pen_limit)):
                    yield cell
                    break


def _cad_rules(geometry, dpi):
    rules = [[], []]
    for shape in geometry:
        if shape["type"] not in {"LINE", "LWPOLYLINE"}:
            continue
        points = np.asarray(shape["points"], dtype=float)
        if shape.get("closed"):
            points = np.vstack((points, points[0]))
        pen = shape.get("const_width_px", shape["lineweight"] * dpi / 2540)
        for start, end in zip(points[:-1], points[1:]):
            delta = abs(end - start)
            axis = int(np.argmax(delta))
            across = 1 - axis
            if delta[axis] >= 6 and delta[across] <= 1.5:
                low, high = sorted((start[axis], end[axis]))
                middle = (start[across] + end[across]) / 2
                radius = max(0.5, pen / 2) + delta[across] / 2
                rules[axis].append((low, high, middle, radius))
    return [np.asarray(axis_rules, dtype=float).reshape(-1, 4) for axis_rules in rules]


def _clearance(cell, rules):
    """Include the pen of any exported CAD ruling matching the printed edge."""
    interior = cell.copy()
    for axis, strokes in enumerate(rules):
        low, high, center, radius = strokes.T
        across = 1 - axis
        overlap = np.minimum(high, cell[axis + 2]) - np.maximum(low, cell[axis])
        spans_edge = overlap >= 0.25 * (cell[axis + 2] - cell[axis])
        for edge, inward in ((across, 1), (across + 2, -1)):
            near_edge = abs(center - cell[edge]) <= radius + 2
            setback = inward * (center[spans_edge & near_edge] - cell[edge]) + radius[spans_edge & near_edge]
            interior[edge] += inward * (0.75 + max(0, setback.max(initial=0)))
    return interior


def _cell_slots(binary, geometry, lines, symbols, dpi, cancellation_token=None):
    if not lines:
        return
    heights = [np.linalg.norm(np.subtract(line.quad[3], line.quad[0])) for line in lines]
    span = int(np.clip(np.median(heights) / 2, 9, 31)) | 1
    bounds = np.asarray(list(_printed_cells(binary, span)), dtype=float).reshape(-1, 4)
    if not len(bounds):
        return
    rules = _cad_rules(geometry, dpi)
    symbol_texts = {index for symbol in symbols for index in symbol["text_indices"]}
    cells = defaultdict(list)
    for index, line in enumerate(lines):
        checkpoint(cancellation_token)
        if index in symbol_texts:
            continue
        quad = np.asarray(line.quad, dtype=float)
        baseline = abs(quad[1] - quad[0])
        if max(baseline) <= 0 or min(baseline) > 0.12 * max(baseline):
            continue
        low, high = quad.min(axis=0), quad.max(axis=0)
        center = quad.mean(axis=0)
        nearby = bounds[np.all((center > bounds[:, :2]) & (center < bounds[:, 2:]), axis=1)]
        if len(nearby) != 1:
            continue
        cell = nearby[0]
        # A small OCR overshoot is common. A box spanning several cells is
        # ambiguous and must not be squeezed into the cell of its midpoint.
        slack = max(1.0, heights[index] * 0.15)
        if np.any(low < cell[:2] - slack) or np.any(high > cell[2:] + slack):
            continue
        cells[tuple(cell)].append((index, low, high))

    for cell, members in cells.items():
        checkpoint(cancellation_token)
        clearance = _clearance(np.asarray(cell), rules)
        slots = {index: clearance.copy() for index, _, _ in members}
        ambiguous = set()
        for first, second in combinations(members, 2):
            first_index, first_low, first_high = first
            second_index, second_low, second_high = second
            gaps = np.maximum(second_low - first_high, first_low - second_high)
            if max(gaps) < 0:
                ambiguous.update((first_index, second_index))
                continue
            # Leave a gap between rows or between distinct runs on the same row.
            axis = int(np.argmax(gaps))
            a, b = first_index, second_index
            if first_low[axis] > second_low[axis]:
                a, b = b, a
            split = (min(first_high[axis], second_high[axis]) + max(first_low[axis], second_low[axis])) / 2
            slots[a][axis + 2] = min(slots[a][axis + 2], split - 0.25)
            slots[b][axis] = max(slots[b][axis], split + 0.25)
        for index, slot in slots.items():
            if index not in ambiguous:
                yield index, slot


def _fit_text(entity, box, font_name):
    content = decode_dxf_unicode(entity.plain_text())
    font = fonts.make_font(font_name, entity.dxf.height, entity.dxf.width)
    path = font.text_path(content)
    if not len(path):
        return
    text_advance = font.text_width(content)
    if text_advance <= 0:
        return
    glyphs = path.bbox()
    low, high = np.array(glyphs.extmin), np.array(glyphs.extmax)
    low[0], high[0] = min(0, low[0]), max(text_advance, high[0])
    corners = np.array([(low[0], low[1]), (low[0], high[1]), (high[0], low[1]), (high[0], high[1])])
    angle = radians(entity.dxf.rotation)
    rotation = np.array([(cos(angle), sin(angle)), (-sin(angle), cos(angle))])
    main = int(np.argmax(abs(rotation[0])))
    cross = 1 - main
    available = box[2:] - box[:2]
    size = np.ptp(corners @ rotation, axis=0)
    if np.any(available <= 0) or np.any(size <= 0):
        return

    height = min(1.0, available[cross] / size[cross])
    # Reduce the width factor independently so a narrow cell can retain the
    # original cap height. Account for the rotated height's share of its span.
    advance, vertical = np.ptp(corners, axis=0) * abs(rotation[:, main])
    if advance <= 0:
        return
    width = min(1.0, (available[main] / height - vertical) / advance)
    if width < 0.8:
        # Share larger reductions between height and width so letters do not
        # become excessively narrow.
        width = 0.8
        height = available[main] / (width * advance + vertical)
    if height < 0.65:
        return

    footprint = (corners * (width, 1) * height) @ rotation
    insert = np.array(entity.dxf.insert)[:2]
    start = box[:2] - footprint.min(axis=0)
    end = np.maximum(start, box[2:] - footprint.max(axis=0))
    placed = np.clip(insert, start, end)
    entity.dxf.height *= height
    entity.dxf.width *= width
    # CAD programs may substitute a different font. Keep the same baseline
    # length in either renderer and when a user edits the native string.
    end_point = placed + rotation[0] * (text_advance * height * width)
    entity.set_placement(tuple(placed), tuple(end_point), TextEntityAlignment.FIT)


def place_cell_text(binary, geometry, lines, symbols, entities, font_path, *, dpi,
                    scale, cancellation_token=None):
    """Apply the second-layer layout rule to whole native TEXT entities."""
    slots = list(_cell_slots(binary, geometry, lines, symbols, dpi, cancellation_token))
    if not slots:
        return
    font_name = "txt"
    if font_path:
        font = Path(font_path)
        fonts.font_manager.scan_folder(font.parent)
        font_name = font.name
    origin_y = binary.shape[0]
    for index, (left, top, right, bottom) in slots:
        checkpoint(cancellation_token)
        box = np.array((left, origin_y - bottom, right, origin_y - top)) * scale
        _fit_text(entities[index], box, font_name)

"""Copy-ready tests; unchanged product fails the nested-member assertions."""

import cv2
import numpy as np
import pytest

from app.geometry.raster_trace import trace_binary
from app.geometry import scan_artifact_filter as artifact


def _sparse_flight_with_independent_inner_dot(dot_tone):
    gray = np.full((600, 900), 220, dtype=np.uint8)
    binary = np.full_like(gray, 255)
    for image, tone in ((gray, 70), (binary, 0)):
        cv2.polylines(
            image,
            [np.array(((230, 260), (350, 180), (690, 170)), np.int32)],
            False,
            tone,
            1,
        )
        cv2.circle(image, (700, 170), 10, tone, 1)
    cv2.circle(gray, (700, 170), 2, dot_tone, -1)
    cv2.circle(binary, (700, 170), 2, 0, -1)
    _, labels = cv2.connectedComponents((binary == 0).astype(np.uint8), connectivity=8)
    return gray, binary, labels == labels[170, 700], labels == labels[170, 690]


@pytest.mark.parametrize("dot_tone", [70, 170])
def test_sparse_flight_rejection_keeps_disconnected_nested_member(dot_tone):
    gray, binary, dot, flight = _sparse_flight_with_independent_inner_dot(dot_tone)
    result = artifact.suppress_scan_artifact_traces(gray, binary, trace_binary(binary))
    assert result.removed_root_count == 1
    assert not np.any(result.binary[flight] == 0)
    assert np.count_nonzero(dot) == 13
    assert np.all(result.binary[dot] == 0), (
        "independent nested member was erased by another root"
    )


def test_root_removal_keeps_geometric_damage_corridor_on_white_input():
    _, binary, dot, _ = _sparse_flight_with_independent_inner_dot(70)
    paths = trace_binary(binary)
    root = max(
        (i for i, p in enumerate(paths) if p.depth == 0),
        key=lambda i: len(paths[i].points),
    )
    white = np.full_like(binary, 255)
    cleaned, corridor = artifact._remove_roots_from_binary(white, paths, {root})
    assert np.array_equal(cleaned, white)
    assert np.all(corridor[dot] == 255), "geometric corridor must include inner area"


def test_root_removal_keeps_unselected_disjoint_outer_member():
    _, binary, dot, flight = _sparse_flight_with_independent_inner_dot(70)
    cv2.rectangle(binary, (400, 400), (430, 430), 0, 2)
    paths = trace_binary(binary)
    root = next(
        i
        for i, p in enumerate(paths)
        if p.depth == 0 and min(x for x, y in p.points) == 230
    )
    cleaned, _ = artifact._remove_roots_from_binary(binary, paths, {root})
    assert not np.any(cleaned[flight] == 0)
    assert np.all(cleaned[dot] == 0)
    assert np.array_equal(cleaned[395:435, 395:435], binary[395:435, 395:435])

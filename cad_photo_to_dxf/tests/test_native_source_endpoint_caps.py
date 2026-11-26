"""Source tails are restored only when ink and topology make them unambiguous."""

import json

import cv2
import numpy as np

from app.native_objects.source_endpoint_caps import restore_source_endpoint_caps
from app.native_objects import source_endpoint_caps as caps


def fixture():
    ink = np.zeros((90, 90), np.uint8)
    skel = np.zeros_like(ink)
    cv2.line(ink, (20, 60), (60, 20), 1, 3)
    cv2.line(skel, (21, 59), (53, 27), 1, 1)
    return skel.astype(bool), ink.astype(bool), [[10, 10, 75, 75]]


def restore(skel, ink, boxes):
    old_skel, old_ink = skel.copy(), ink.copy()
    result, proof = restore_source_endpoint_caps(skel, ink, (0, 0), boxes)
    assert np.array_equal(skel, old_skel) and np.array_equal(ink, old_ink)
    assert np.all(result[skel]) and not np.any(result & ~ink)
    return result, proof


def test_unique_original_ink_tail_restores_thinning_recession():
    skel, ink, boxes = fixture()
    result, proof = restore(skel, ink, boxes)
    assert proof['restored'] and int(result.sum()) > int(skel.sum())
    assert any(row['original_endpoint_source_xy_px'] == [53.0, 27.0] for row in proof['restored'])
    assert all(row['extension_length_px'] <= 12 for row in proof['restored'])
    assert all(row['old_skeleton_vertices_and_adjacencies_preserved'] for row in proof['restored'])
    assert json.loads(json.dumps(proof))['refined_skeleton_sha256'] == proof['refined_skeleton_sha256']


def test_no_verified_candidate_scope_leaves_skeleton_exactly_unchanged():
    skel, ink, _ = fixture()
    result, proof = restore(skel, ink, [])
    assert np.array_equal(result, skel) and not proof['restored']


def test_separate_real_dot_is_never_bridged():
    skel, ink, boxes = fixture()
    ink[15:17, 64:66] = True
    result, proof = restore(skel, ink, boxes)
    assert not result[15:17, 64:66].any()
    assert not result[17:19, 62:64].any()
    assert proof['source_pixels_modified'] is False


def test_nearby_separate_character_ink_is_never_connected():
    skel, ink, boxes = fixture()
    ink[11:21, 67] = True
    ink[11, 67:74] = True
    ink[15, 67:72] = True
    result, _ = restore(skel, ink, boxes)
    assert not result[11:21, 67:74].any()


def test_forward_fork_remains_unextended():
    skel, ink, boxes = fixture()
    source = ink.astype(np.uint8)
    cv2.line(source, (53, 27), (65, 27), 1, 3)
    result, proof = restore(skel, source.astype(bool), boxes)
    assert np.array_equal(result, skel)
    assert any('DIVERGES' in row['decision'] or 'BRANCH' in row['decision'] for row in proof['rejected'])


def test_source_hole_and_loop_are_not_filled():
    skel, ink, boxes = fixture()
    source = ink.astype(np.uint8)
    cv2.circle(source, (58, 22), 4, 1, 1)
    result, proof = restore(skel, source.astype(bool), boxes)
    assert np.array_equal(result, skel)
    assert not np.any(result & ~source.astype(bool))
    assert proof['rejected']


def test_candidate_boundary_cannot_be_extended_by_ink_outside_it():
    skel, ink, _ = fixture()
    result, proof = restore(skel, ink, [[10, 24, 75, 75]])
    assert np.array_equal(result, skel)
    assert any(row['decision'] == 'ORIGINAL_CAP_EXTENDS_OUTSIDE_BOUND_CANDIDATE' for row in proof['rejected'])


def test_short_cap_can_be_observed_without_changing_default_graph_restoration():
    ink = np.zeros((90, 90), bool)
    skeleton = np.zeros_like(ink)
    ink[44:47, 20:61] = True
    skeleton[45, 21:59] = True
    before_ink, before_skeleton = ink.copy(), skeleton.copy()
    distance = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    ordinary, reason, _ = caps._extension(skeleton, ink, distance, (45, 58))
    assert ordinary is None and reason == 'ORIGINAL_CAP_ALREADY_WITHIN_UNCHANGED_TOLERANCE'
    observed, _, proof = caps._extension(skeleton, ink, distance, (45, 58), observe_short_cap=True)
    assert observed == [(45, 58), (45, 59), (45, 60)]
    assert proof['complete_short_cap_observation_requested']
    assert proof['no_gap_filled'] and proof['no_branch_pruned']
    restored, receipt = restore(skeleton, ink, [[10, 30, 75, 65]])
    assert np.array_equal(restored, before_skeleton) and not receipt['restored']
    assert np.array_equal(ink, before_ink) and np.array_equal(skeleton, before_skeleton)

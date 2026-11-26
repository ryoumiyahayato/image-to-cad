"""Minimum genuine TEXT members fitted to measured short source components."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from ezdxf.fonts import fonts

from .single_line_neighbor_clearance import native_font_path
from .single_line_text_audit import source_ink_text_layout
from .short_contact_partition import digest


POLICY = {
    "version": "short-components-minimum-native-TEXT-layout-v1",
    "font": "DejaVuSans.ttf",
    "maximum_component_center_error_heights": 0.20,
    "maximum_component_height_edge_error_heights": 0.12,
    "maximum_component_horizontal_edge_error_source_px": 1.0,
    "maximum_inter_character_gap_error_source_px": 1.0,
    "minimum_inter_character_white_gap_px": 0.5,
    "try_one_whole_TEXT_first": True,
    "fallback": "unique_instance_block_of_one_TEXT_per_source_component",
    "font_is_transcription_evidence": False,
}


def _measure(text, boxes, roi, dpi, font_path):
    mm = 25.4 / float(dpi)
    union = [min(b[0] for b in boxes), min(b[1] for b in boxes),
             max(b[2] for b in boxes), max(b[3] for b in boxes)]
    ink_geometry = {"text":text,"x":union[0],"y":union[3],
                    "height_px":union[3]-union[1],"width_px":union[2]-union[0]}
    layout = source_ink_text_layout(ink_geometry, roi, dpi, font_path)
    unit = fonts.sideload_ttf(Path(font_path),1.0)
    glyphs = unit.text_glyph_paths(text,1.0)
    actual = []
    for glyph in glyphs:
        bbox = glyph.bbox()
        lo, hi = bbox.extmin, bbox.extmax
        actual.append([roi[0]+(layout["insert"][0]+lo.x*layout["height"]*layout["width"])/mm,
                       roi[3]-(layout["insert"][1]+hi.y*layout["height"])/mm,
                       roi[0]+(layout["insert"][0]+hi.x*layout["height"]*layout["width"])/mm,
                       roi[3]-(layout["insert"][1]+lo.y*layout["height"])/mm])
    actual, expected = np.asarray(actual,float), np.asarray(boxes,float)
    height = float(np.median(expected[:,3]-expected[:,1]))
    centers = (actual[:,:2]+actual[:,2:]-expected[:,:2]-expected[:,2:])/2
    edges = actual[:,[1,3]]-expected[:,[1,3]]
    horizontal_edges = actual[:,[0,2]]-expected[:,[0,2]]
    checks = {
        "literal_component_count_matches":len(actual)==len(expected),
        "component_positions_match_source":bool(np.max(np.abs(centers))<=0.20*height+1e-9),
        "component_heights_and_baselines_match_source":bool(np.max(np.abs(edges))<=max(2.0,0.12*height)+1e-9),
        "component_left_and_right_edges_match_source":bool(np.max(np.abs(horizontal_edges))<=POLICY["maximum_component_horizontal_edge_error_source_px"]+1e-9),
        "inter_character_spacing_matches_source":all(
            abs((actual[i+1,0]-actual[i,2])-(expected[i+1,0]-expected[i,2]))
            <=POLICY["maximum_inter_character_gap_error_source_px"]+1e-9
            for i in range(len(actual)-1)),
        "original_white_character_gaps_remain_open":all(
            expected[i+1,0] <= expected[i,2] or actual[i+1,0]-actual[i,2]>=0.5
            for i in range(len(actual)-1)),
    }
    # The normal TEXT writer's contract is cap height and advance width. Bind
    # the source-ink fit to that contract explicitly, instead of changing the
    # existing long-row writer or making it borrow a different source schema.
    cap_height = layout["height"]/mm
    geometry = {"text":text,"x":roi[0]+layout["insert"][0]/mm,
                "y":roi[3]-layout["insert"][1]/mm,"height_px":cap_height,
                "width_px":unit.text_width(text)*cap_height*layout["width"],
                "rotation_deg_image":0.0}
    return {"pass":all(checks.values()),"checks":checks,"geometry":geometry,
            "source_component_boxes":boxes,"actual_font_component_boxes":actual.tolist(),
            "source_ink_layout":layout,"component_center_errors_px":centers.tolist(),
            "component_vertical_edge_errors_px":edges.tolist(),
            "component_horizontal_edge_errors_px":horizontal_edges.tolist()}


def plan_short_text_layout(text, partition, roi, dpi, font_path=None):
    path = Path(font_path) if font_path is not None else native_font_path()
    components = partition["components"]
    if len(text)!=len(components) or not text or any(c.isspace() for c in text):
        raise ValueError("SHORT_TEXT_LITERAL_COMPONENT_COUNT_CHANGED")
    boxes = [c["bbox_xyxy_px"] for c in components]
    whole = _measure(text,boxes,roi,dpi,path)
    if whole["pass"]:
        kind, geometry, members = "TEXT",whole["geometry"],[whole]
    else:
        members = [_measure(character,[box],roi,dpi,path) for character,box in zip(text,boxes)]
        if not all(m["pass"] for m in members):
            raise ValueError("SHORT_TEXT_SOURCE_COMPONENT_LAYOUT_NOT_SUPPORTED")
        kind = "TEXT_GROUP"
        geometry = {"text":text,"text_members":[m["geometry"] for m in members],
                    "bbox_xyxy_px":partition["bbox_xyxy_px"]}
    return {"schema":POLICY["version"],"policy":dict(POLICY),"pass":True,
            "font":{"font":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()},
            "source_partition_sha256":digest(partition),"kind":kind,"geometry":geometry,
            "one_TEXT_attempt":whole,"members":members,
            "minimum_native_member_count":len(members),"independent_paths_in_group":False}

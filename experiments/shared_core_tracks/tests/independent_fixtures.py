"""Hand-constructed adversarial sources, independent of the proposal algorithm.

These are synthetic controls, never evidence of a recovered real drawing.
Nothing here imports thinning, graph decomposition, fitting, or source ownership
code.  Every 'must retain' annotation is specified from the construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
from PIL import Image, ImageDraw


SHAPE = (192, 256)


@dataclass(frozen=True)
class Fixture:
    name: str
    family: str
    gray: np.ndarray
    protected: np.ndarray
    must_retain: np.ndarray
    white_fence: np.ndarray
    visible: np.ndarray
    expectation: str
    notes: str
    dpi: float = 100.0

    @property
    def source(self) -> np.ndarray:
        return self.gray < 254


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("L", (SHAPE[1], SHAPE[0]), 255)
    return image, ImageDraw.Draw(image)


def _mask_rect(box: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = box
    mask = np.zeros(SHAPE, bool)
    mask[y0:y1, x0:x1] = True
    return mask


def _fixture(name: str, family: str, image: Image.Image, *, retain=None,
             protected=None, white_fence=None, visible=None,
             expectation="partial_candidate_permitted", notes="") -> Fixture:
    gray = np.asarray(image).copy()
    source = gray < 254
    zero = np.zeros(SHAPE, bool)
    retain = zero.copy() if retain is None else np.asarray(retain, bool) & source
    protected = zero.copy() if protected is None else np.asarray(protected, bool)
    fence = zero.copy() if white_fence is None else np.asarray(white_fence, bool)
    if np.any(fence & source):
        raise ValueError(f"{name}: a declared white fence contains source ink")
    visible = np.where(source, 0, 255).astype(np.uint8) if visible is None else visible
    return Fixture(name, family, gray, protected, retain, fence, visible,
                   expectation, notes)


def fixtures() -> Iterator[Fixture]:
    # Deliberately long control: a candidate can satisfy the existing 10 mm
    # threshold without changing it. This is not a new production positive.
    image, draw = _canvas()
    draw.line([(24, 96), (232, 96)], fill=0, width=3)
    yield _fixture("isolated_long_control", "isolated_control", image,
                   expectation="candidate_expected",
                   notes="Old isolated behavior must remain available; not a new capability.")

    for kind in ("T", "cross"):
        image, draw = _canvas()
        draw.line([(24, 96), (232, 96)], fill=0, width=3)
        draw.line([(128, 96 if kind == "T" else 16), (128, 176)], fill=0, width=3)
        yield _fixture(f"{kind}_long_arms", "junction", image,
                       retain=_mask_rect((124, 92, 133, 101)),
                       notes="Retain shared center. Geometry contact, object identity, and conductivity stay separate.")

    # Three exact, nonzero white gaps. Endpoint-distance merging would fail.
    for gap in (1, 2, 3):
        image, draw = _canvas()
        draw.line([(24, 96), (125, 96)], fill=0, width=3)
        draw.line([(126 + gap, 96), (232, 96)], fill=0, width=3)
        fence = _mask_rect((126, 0, 126 + gap, SHAPE[0]))
        yield _fixture(f"end_gap_{gap}px", "near_without_contact", image,
                       white_fence=fence,
                       notes="Independent collinear strokes; the complete vertical white fence must remain open.")

    image, draw = _canvas()
    draw.line([(24, 94), (232, 94)], fill=0, width=3)
    draw.line([(24, 98), (232, 98)], fill=0, width=3)
    yield _fixture("parallel_1px_gap", "near_without_contact", image,
                   white_fence=_mask_rect((0, 96, SHAPE[1], 97)),
                   notes="Nearby parallel sources have one complete white row; no owner expansion across it.")

    image, draw = _canvas()
    draw.line([(24, 96), (232, 96)], fill=0, width=3)
    teeth = np.zeros(SHAPE, bool)
    for x, endpoint in ((55, 88), (82, 104), (109, 86), (136, 105), (163, 89), (190, 106), (217, 87)):
        draw.line([(x, 96), (x, endpoint)], fill=0, width=1)
        teeth |= _mask_rect((x - 2, min(94, endpoint), x + 3, max(99, endpoint + 1)))
    yield _fixture("comb_short_teeth", "short_attached_strokes", image,
                   retain=teeth,
                   notes="All deliberately 7-10 px short teeth and their contact regions stay; length threshold may reject every segment.")

    # Two true, nearby contacts are explicit in the construction. No expected
    # graph-node count is imposed: the test concerns preserving their evidence.
    for separation in (2, 3, 6):
        image, draw = _canvas()
        draw.line([(24, 96), (232, 96)], fill=0, width=1)
        draw.line([(124, 96), (124, 64)], fill=0, width=1)
        draw.line([(124 + separation, 96), (124 + separation, 128)], fill=0, width=1)
        retain = _mask_rect((122, 62, 127 + separation, 131))
        yield _fixture(f"opposite_contacts_{separation}px", "close_true_junctions", image,
                       retain=retain,
                       notes="Keep both branches and intervening evidence; no fixed-distance real-node assertion.")

    image, draw = _canvas()
    draw.line([(24, 96), (232, 96)], fill=0, width=3)
    # A manually constructed E-shaped glyph touches the engineering stroke.
    draw.line([(128, 52), (128, 96)], fill=0, width=3)
    for y in (52, 74, 94):
        draw.line([(128, y), (151, y)], fill=0, width=3)
    text_region = _mask_rect((125, 49, 154, 97))
    yield _fixture("text_touching_line_protected", "text_engineering_contact", image,
                   protected=text_region, retain=np.asarray(image) < 254,
                   expectation="whole_source_rejection",
                   notes="A small protected text region intersects the full connected source; preserve the complete source.")
    yield _fixture("text_touching_line_unlabelled", "text_engineering_contact", image,
                   retain=text_region,
                   notes="Unknown membership cannot be resolved merely by long straight geometry.")

    image, draw = _canvas()
    draw.rectangle((66, 54, 190, 138), outline=0, width=3)
    yield _fixture("closed_rectangle", "hole_closed_loop", image,
                   white_fence=_mask_rect((71, 59, 186, 134)),
                   notes="Hole must stay paper. A source-supported closed representation is allowed; an invented open shortcut is not.")
    draw.line([(36, 96), (66, 96)], fill=0, width=3)
    yield _fixture("loop_with_short_tail", "hole_closed_loop", image,
                   retain=_mask_rect((34, 92, 70, 101)),
                   white_fence=_mask_rect((71, 59, 186, 134)),
                   notes="The attached short tail and its core stay; the hole remains paper.")

    image, draw = _canvas()
    draw.line([(128, 96), (24, 32)], fill=0, width=3)
    draw.line([(128, 96), (232, 32)], fill=0, width=3)
    draw.line([(128, 96), (128, 176)], fill=0, width=3)
    yield _fixture("true_Y_branch", "real_branch", image,
                   retain=_mask_rect((122, 90, 135, 103)),
                   notes="Branch is deliberate, not skeleton noise; retained center remains undecided semantically.")

    image, draw = _canvas()
    # Two boxes use one entire observed vertical member. Pixel evidence alone
    # cannot give it to both independently editable objects.
    draw.rectangle((36, 46, 128, 146), outline=0, width=3)
    draw.rectangle((126, 46, 220, 146), outline=0, width=3)
    yield _fixture("two_boxes_shared_stroke", "shared_stroke", image,
                   retain=_mask_rect((124, 44, 131, 149)),
                   white_fence=_mask_rect((41, 51, 122, 142)) | _mask_rect((133, 51, 216, 142)),
                   notes="Shared vertical stroke and both holes stay; no invented historical object identity.")

    for protected_kind in ("logo", "signature", "manual_protection"):
        image, draw = _canvas()
        if protected_kind == "logo":
            draw.ellipse((60, 32, 196, 160), outline=0, width=3)
            draw.line([(24, 96), (232, 96)], fill=0, width=3)
        elif protected_kind == "signature":
            draw.line([(24, 140), (64, 44), (83, 134), (120, 76), (142, 142),
                       (180, 50), (195, 126), (232, 106)], fill=0, width=3)
        else:
            draw.line([(24, 96), (232, 96)], fill=0, width=3)
            draw.line([(128, 30), (128, 160)], fill=0, width=3)
        source = np.asarray(image) < 254
        yield _fixture(protected_kind, "protected_sources", image,
                       protected=source, retain=source,
                       expectation="whole_source_rejection",
                       notes="Explicitly protected full source: no candidate retirement, irrespective of geometric fit.")

    image, draw = _canvas()
    draw.line([(24, 96), (232, 96)], fill=0, width=3)
    draw.line([(128, 30), (128, 160)], fill=0, width=3)
    source = np.asarray(image) < 254
    visible = np.where(source, 0, 255).astype(np.uint8)
    visible[95:98, 42:46] = 255
    yield _fixture("already_claimed_fragment", "old_correct_owner", image,
                   retain=source, visible=visible,
                   expectation="whole_source_rejection",
                   notes="Only a small source fragment is already owned; new processing must not claim the larger connected source.")


def rotated(fixture: Fixture, quarter_turns: int) -> Fixture:
    """Rotation provides different array order without changing annotations."""
    rot = lambda a: np.rot90(a, quarter_turns).copy()
    return Fixture(f"{fixture.name}_rot{quarter_turns * 90}", fixture.family,
                   rot(fixture.gray), rot(fixture.protected), rot(fixture.must_retain),
                   rot(fixture.white_fence), rot(fixture.visible), fixture.expectation,
                   fixture.notes, fixture.dpi)


def native_version(fixture: Fixture, scale=2) -> Fixture:
    """A declared synthetic original grid, not evidence added to a real scan.

    Replication is only a deterministic construction of synthetic black cells.
    The caller must continue to identify all of these sources as synthetic.
    """
    expand = lambda a: np.repeat(np.repeat(a, scale, axis=0), scale, axis=1)
    return Fixture(f"{fixture.name}_native{scale}", fixture.family,
                   expand(fixture.gray), expand(fixture.protected),
                   expand(fixture.must_retain), expand(fixture.white_fence),
                   expand(fixture.visible), fixture.expectation, fixture.notes,
                   fixture.dpi * scale)

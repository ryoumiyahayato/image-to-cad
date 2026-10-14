# Real-world LibreCAD UAT

UAT date recorded: 2026-07-31  
Authority: direct user observation in LibreCAD  
Coverage: partial real-DXF inspection, not every page and not every final DXF

Automated tests are supporting evidence only. They do not replace this record.

## Result summary

| Area | Status | Human evidence |
|---|---|---|
| Overall position and scale | Pass | No blank page, obvious global offset, or whole-page clipping; overall scale broadly normal. |
| `OCR_TEXT` quantity | Pass | Real DXFs contain large amounts of editable text rather than isolated items. |
| Entity type | Partial pass | Checked recognized items are DXF `TEXT`; some Chinese, vertical, rotated, and small title-block text remains outline/polyline or symbol output. |
| Text content editing | Pass | Native DXF `TEXT` objects can be edited. |
| Save, close, reopen | Pass | Two real DXFs were edited, saved, fully closed, reopened, and retained modified Chinese text. |
| `SOURCE_TEXT_OUTLINE` default state | Pass | Seven inspected DXFs showed the layer default-off and frozen without large visible duplication. |
| `SOURCE_TEXT_OUTLINE` visual quality | Accepted as evidence layer | The outline is rough and may contain jagged edges, stains, and uneven weight. It is not a final text rendering. |
| Text size, width, placement, rotation | **Fail** | Many texts are too large, overlap, exceed table or border bounds, appear stretched/compressed, or have unreasonable rotated/vertical placement. |
| Ordinary text in `TRACE_TEXT_SYMBOL` | Partial fail | Large-scale misrouting is gone, but typically about five to nine ordinary characters per drawing remain, especially in title blocks and rotated/vertical regions. |
| Automatic line and structure recovery | Partial pass | Safety improved and old page-crossing line failures are much rarer, but damaged frames and structural lines remain incomplete and some lines are inaccurate. |

## Detailed acceptance facts

### 1. Overall drawing geometry

The inspected environmental-office drawing opened at a broadly correct location and scale. The page was not empty, globally displaced, or visibly clipped. Damaged and rough page borders remain an input-quality and structure-recovery concern, not evidence of a page-coordinate order-of-magnitude failure.

### 2. Editable text availability

The non-destructive text-emission route is effective. There are now many native editable text entities. Future work must not regress those entities to `LWPOLYLINE`, glyph outlines, images, `HATCH`, or other non-editable representations.

### 3. Entity classification

Not every black object should become text. True engineering symbols remain graphics. The target is:

- ordinary readable print should become native `TEXT` where confidence permits;
- real engineering symbols should remain graphics;
- uncertain or unreadable content should retain visible evidence;
- text-count improvement must not be obtained by fabricating incorrect text.

### 4. Edit persistence

The user verified edit persistence in two real DXFs:

1. edit one Chinese native `TEXT`;
2. save;
3. close LibreCAD completely;
4. reopen;
5. confirm the modified Chinese content remains.

This gate is confirmed, not unverified.

### 5. Source-outline contract

`SOURCE_TEXT_OUTLINE` is a hidden evidence and recovery layer. It may be visually rough, but it must remain default-off, must not block native `TEXT`, must not become the final visible font, and must not be allowed to inflate text geometry through dirty outer bounds.

### 6. Highest-priority failure: text geometry

Content recognition and geometry correctness are separate contracts. Text emission has improved, but geometry has not passed real use. P1 must address:

- text height;
- width factor;
- insertion and alignment points;
- baseline;
- rotation;
- 90° and 270° text;
- OCR box/quad fitting;
- predicted DXF bounds;
- cell and border overflow;
- abnormal geometry fallback and reporting.

### 7. Symbol routing

`TRACE_TEXT_SYMBOL` is not required to reach zero. The requirement is to reduce ordinary-print misrouting without converting real symbols into OCR text and without lowering the global confidence contract.

### 8. Structure recovery

Current conservative repair is an acceptable safety stage. Structure recall must be addressed only after text geometry and protection masks are stable. Missing lines are preferable to reintroducing long unsafe bridges through text, signatures, logos, or unrelated regions.

## Coverage limitation

The user inspected seven DXFs for several layer/entity behaviors and two DXFs for edit-save-close-reopen persistence. This must not be rewritten as complete human acceptance of all pages or all generated DXFs.

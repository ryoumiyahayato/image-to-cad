# IMAGE TO CAD — PRODUCT FIX P2B REPORT

Date: 2026-10-06, Asia/Taipei. Product: Image to CAD 0.3.0-dev.
Base: `2aa8345` (closed P2A font evidence). P1 remains CLOSED.
Working checkout: `C:/Users/agcrf/Desktop/image-to-cad/instrumented-e03`.

```text
W02_M_SYMBOL: PASS
W02_SL_SYMBOL: PASS
E01_LOGO: PRESERVED
W02_LOGO: PRESERVED
W03_LOGO: PRESERVED
W03_SIGNATURE: PRESERVED
PRINTED_NAME_SEPARATE_FROM_SIGNATURE: YES
GRAPHIC_REPRESENTATION: existing LogoRegion/SignatureRegion masks → DXF IMAGE
GRAPHIC_BACKGROUND: TRANSPARENT
GRAPHIC_PATHS_RELATIVE: YES
GRAPHIC_MOVE_SCALE_SAVE_REOPEN: PASS (ezdxf; delete also verified)
LIBRECAD_IMAGE_RENDER: PASS (valid native PDFs; teardown limitation below)
PREVIEW_FINAL_PARITY: PASS
KNOWN_1_TO_7_PREVIEW: SHOWS_FINAL_7
LOGO_PREVIEW_PARITY: PASS
P1_GRID_REGRESSION: PASS
DXF_AUDIT: PASS
FOCUSED_TESTS: 29 passed
FULL_TESTS: 554 passed
NEW_PRODUCT_REGRESSION: NONE found by current suite and listed real acceptance
ARCHITECTURE_REOPEN_REQUIRED: NO
COMMITS: one combined fix commit containing this report; SHA in chat closeout
WORKTREE: CLEAN after evidence commit
TEXT_FONT_BLOCKER: REMAINS_ISOLATED
NEXT_FAILURE_FAMILY: TEXT_FONT_RESOURCE_CAD_COMPATIBILITY
```

## Representation and source evidence

The existing post-reconciliation production stage now commits source-supported
object representation after structural LINE authority is established. It does
not alter straight-line reconstruction, grid normalization, line tuples, or
their identities. There is one FinalStructure and one shared DXF entity writer.
No symbol dictionary, GraphicManager, facade, or parallel export pipeline was added.

W02 has two source motor boxes. The real failure ROI exports two closed native
LWPOLYLINE enclosures, two native TEXT `M`, one native CIRCLE with TEXT `SL`, and
four independent native TEXT `2`. No `M2` remains in that ROI. Character centers
and source contours establish the relation; production code has no `M`/`SL`
lookup or fixed page coordinates. Dense boundary samples and independent source
components distinguish an enclosure from a closed ordinary glyph. A complex
supported enclosure retains its whole foreground as GRAPHIC; an adjacent known
label stays separate. Unusable OCR cannot leave an empty replacement enclosure.

Whole logo evidence comes from original source ink, before cleanup could erase
it. Expected source bboxes in pixels are E01 `(3651,83,99,98)`, W02
`(4240,1489,254,100)`, and W03 `(4338,1204,206,82)`. Each is an actual final
IMAGE with the source aspect and placement. W02/W03 logo candidates are not
replaced by TEXT `S`. W01's existing wordmark is also retained as a whole IMAGE.

W03 contains seven source signature patches. The adjacent seven printed names
remain independently emitted native TEXT. The signing field is located from
printed headings and verified source rules; OCR names never supply handwriting
shape. Table rules remain native LINE. Only original intersection pixels near
signature ink are restored; ambiguous crossings are not redrawn.

The existing foreground mask also carries ink opacity. Black RGB with
`alpha = 255 - source gray` on claimed foreground preserves gray ink and fine
hatching while unclaimed paper stays transparent. The existing cache preserves
these alpha bytes and object class. Its point codec now retains float64 so native
circle geometry survives a cache round trip without changing the canonical ID.
Legacy binary masks remain readable; deliberately lossy/stale bindings still fail.

## Preview and packaging

FINAL OUTPUT PREVIEW rasterizes the actual emitted DXF and relative PNG assets
through the existing exporter. It honors disabled/frozen layers, including the
hidden source-text backup, and never returns source binary as the result. SOURCE
REFERENCE is explicit; the annotated visual diagnosis panel is labelled separately.
Both actual W01 and W03 revision entities remain `7`, and their final crops show `7`.
Normal native TEXT font resources and ordinary text fitting remain unchanged.

Packages use relative sibling assets, for example `drawing.dxf`,
`drawing.logo-001.png`, and `drawing.signature-001.png`. IMAGE definitions contain
relative filenames; each asset exists. Every real package passed audit and all
IMAGE entities were translated, scaled, saved, reopened, and one deleted. Package
relocation is covered by a focused regression. IMAGE pixels are intentionally
not individually editable.

## Validation and limits

W01/W02/W03 evidence uses full production processing with frozen UAT OCR content.
Final source-opacity assets were refreshed with the same production encoder.
E01 replays the production post-LINE representation stage on the captured real
UAT FinalStructure; it is not claimed as a fresh full reconstruction run. Its
1,394 LINE tuple is frozen. W01's 358 and W03's 842 LINE tuples exactly match
closed P1 verified caches. W02's 183 LINE tuple matches the initial closed-P1
equality assertion snapshot. A first evidence cache exposed float32 rounding;
source-bound recomputation recovered the original canonical fingerprint before
the precision fix and final regeneration. No 901-line census was reopened.

The existing W01 regression proves duplicate reduction, exact shared nodes, and
source support. Focused tests also cover compound symbols, whole real logos,
signature/name separation, source gray detail, preview parity, absent-logo parity,
relative packaging, cache identity, and IMAGE editing. The current full suite
passed after the final product changes.

Installed LibreCAD 2.2.1.5 generated valid native PDFs showing all three logos,
a real W03 signature, and M/SL native geometry/text. Poppler reopened each PDF;
IMAGE-vs-no-IMAGE controls differ by thousands of pixels. A native LINE remains
visible through the transparent E01 patch. The installed CLI then reports an
access violation during QWidget/tool-bar teardown (`0xc0000005`); this is recorded,
not concealed by its valid rendered output. GUI edit/save/reopen is not claimed.
The required IMAGE edit/save/reopen validation uses ezdxf.

The installed ODA converter additionally retained an E01 IMAGE, its relative
filename, and an error-free audit. No ODA renderer or new software was installed.
The installed wqy-unicode resource SHA still matches the closed P2A inventory.
There was no font search, font replacement/conversion, OCR accuracy change,
training, paper-damage work, or performance optimization.

Small measurements, acceptance results, test logs, and reproducible scripts are
in this directory. Large PNG/NPZ/DXF/PDF artifacts remain in ignored
`local-artifacts/product-fix-p2b/`. The outer checkout's pre-existing corrupt Git
index was not repaired or used. This healthy managed checkout contains the fix.

STOP.

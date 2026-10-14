# IMAGE TO CAD — PRODUCT FIX P2 REPORT

**P2_REPRESENTATION_BLOCKER. STOP at A1 under user STOP condition 3.**

The available font resources provide no reasonable native TEXT scheme satisfying
both the requested Chinese coverage and improved hollow appearance in the
installed LibreCAD. This experiment does not justify replacing the current font.
P2 is incomplete and is not closed. P1 remains formally closed.

## Exact gap

The bundled and installed wqy-unicode LFF covers the requested characters but
its closed contours are stroked as hollow outlines by actual native LibreCAD.
Installed stroke LFF alternatives do not cover the required simplified Chinese.
System SimHei and Noto TTF files do contain Chinese, but the native LibreCAD
comparison renders their DXF styles through standard-font fallback. Their actual
body pixels are identical to a deliberately missing-font control, with Chinese
shown as diamonds. Both simhei and simhei.ttf style-name variants were tested.
The project manifest's four licensed Noto OTF files are absent from this checkout.

See [TEXT_STYLE_CANDIDATE_MATRIX](TEXT_STYLE_CANDIDATE_MATRIX.md), with all requested
coverage, appearance, editability, portability, and fallback columns. Ten native
comparison DXFs include every requested string and ®. All 47 installed LFF files
were checked. The experiment changed no product code, input source, or fonts.

The specific missing resource is a legally usable, sufficiently complete
Chinese native font that the required installed CAD renderer can display with
an acceptable filled or stroke appearance. Supplying another outline-derived
LFF would not establish a fix; a new resource would require repeating A1.
No new architecture or glyph reconstruction was attempted.

## Scope and verification

FinalStructure already carries immutable logo/signature masks, and the current
exporter already has relative IMAGE/transparent signature support. STOP conditions
1 and 2 were not established. They are not the reason work stopped.

A2/A3, B, C, and D were not implemented after the A1 STOP condition. No new P2
real regression tests or W01/W02/W03 text-sizing acceptance were claimed. Existing
symbol, logo, signature, sizing, and preview defects remain unresolved. OCR 1→7
was not changed. There was no P1 structural modification or reopened census.

P1 preservation: the existing five real P1 grid/protection regression cases pass.
They include W01 duplicate reduction, exact shared nodes through native DXF
save/reopen, original ink support, independent wordmark enclosure, W03 protected
geometry, and source-gap/protection vetoes. Full-page coverage is the unchanged
closed P1 result, not a new P2 full-page census. Production code is byte-for-byte
unchanged by this task.

The full current suite also passes: **535 passed in 71.38 s**. The first focused
run passed **5 tests in 4.88 s**, with one existing denied pytest-cache-write
warning. Full suite used `-p no:cacheprovider` and produced no warning.

All ten comparison DXFs audit with **0 errors, 0 fixes**. Native TEXT content and
insertion were changed, saved, and reopened through ezdxf for each candidate;
values persisted. This establishes logical editability, not GUI edit acceptance.
LibreCAD's native renderer successfully produced all ten final PDFs. Visual
acceptance of a suitable improved native font failed. GUI activation failed and
was not bypassed. No graphic move/scale/delete/save/reopen package exists for P2.

## Requested result fields

The FAIL fields below mean P2 acceptance is unresolved after STOP, not that a new
product regression was introduced. NOT RUN is used where a result would otherwise
be invented; the requested binary choices cannot honestly encode an unrun check.

```text
TEXT_FONT_ROOT_CAUSE:
  wqy-unicode.lff closed glyph contours are stroked hollow in native LibreCAD.
  Existing stroke alternatives lack required Chinese; system TTF styles fall back.
TEXT_REPRESENTATION:
  Unchanged native TEXT using wqy-unicode.lff; alternative selection BLOCKED.
TEXT_NATIVE_EDITABLE: YES (existing product and comparison; GUI edit not tested)
TEXT_SIZE_FIDELITY: FAIL (unresolved; A2/A3 NOT RUN after STOP)
HOLLOW_GLYPH_IMPROVED: NO
W02_M_SYMBOL: FAIL (existing defect unresolved; B NOT RUN)
W02_SL_SYMBOL: FAIL (existing defect unresolved; B NOT RUN)
E01_LOGO: FAIL (existing omission unresolved; C NOT RUN)
W02_LOGO: FAIL (existing TEXT S defect unresolved; C NOT RUN)
W03_LOGO: FAIL (existing TEXT S defect unresolved; C NOT RUN)
W03_SIGNATURE: FAIL (existing replacement defect unresolved; C NOT RUN)
GRAPHIC_REPRESENTATION: NONE (no P2 output; existing signature IMAGE support exists)
GRAPHIC_BACKGROUND: N/A
GRAPHIC_PATHS_RELATIVE: N/A (no P2 graphic package)
PREVIEW_FINAL_PARITY: FAIL (unresolved; D NOT RUN)
KNOWN_1_TO_7_PREVIEW: NOT RUN (recognition frozen; parity change not implemented)
P1_GRID_REGRESSION: PASS (5 existing real cases; closed coverage preserved unchanged)
LIBRECAD_RENDER: FAIL (native rendering succeeded; font acceptance failed)
DXF_AUDIT: PASS (10 comparison DXFs; not a new complete P2 export)
GRAPHIC_EDIT_SAVE_REOPEN: N/A
FOCUSED_TESTS: 5 passed; existing P1 cases, no new P2 focused tests after STOP
FULL_TESTS: 535 passed
NEW_PRODUCT_REGRESSION: NONE (no product-code changes)
ARCHITECTURE_REOPEN_REQUIRED: NO
COMMITS: one documentation/evidence commit; see Git history and chat closeout
WORKTREE: CLEAN after evidence commit; runtime artifacts ignored
NEXT_FAILURE_FAMILY: TEXT_FONT_RESOURCE_CAD_COMPATIBILITY
STOP
```

Only small evidence and the reproducible A1 script are committed under
`docs/product-fix-p2/`. Heavy DXF/PDF/PNG outputs remain under ignored
`local-artifacts/product-fix-p2/`. No misleading `fix:` commit is used for a
documentation-only blocked run.

Working checkout:
`C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03`

The outer original checkout's Git index was already corrupt, as noted in the
closed P1 report; it was not repaired or used for this task.

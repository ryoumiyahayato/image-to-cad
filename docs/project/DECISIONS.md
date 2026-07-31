# Decision log

## D-001 — Never restore full-page topology modification

Status: accepted

Full-page morphological close, generic gap bridging, endpoint-only connection, unlimited extension, or equivalent topology changes are prohibited. Repair may occur only inside validated structural ROI/corridors with full-path protection checks.

## D-002 — Separate text emission from source-glyph suppression

Status: accepted

`text_emit_eligible` determines whether trusted OCR becomes native DXF `TEXT`. `source_outline_suppressible` determines whether original source glyph pixels can be hidden. `replacement_safe` must not block trusted text emission.

## D-003 — Native text may not regress to outlines or images

Status: accepted

Geometry, font, routing, and display improvements must preserve editable native `TEXT`. Visual similarity is not a valid reason to convert text into `LWPOLYLINE`, images, `HATCH`, or glyph outlines.

## D-004 — Source outlines are hidden evidence, not final typography

Status: accepted

Unsafe original glyphs are retained in default-off, frozen `SOURCE_TEXT_OUTLINE`. The layer may be rough. It must not be the formal visible text and must not inflate native-text geometry through contaminated outer bounds.

## D-005 — Diagnostic color is a display mode

Status: accepted

Diagnostic colors are useful for quality review, but formal output remains the default. Formal and diagnostic modes share one `FinalStructure`; color and visibility may change, but entity types, ownership, OCR routing, counts, and repair decisions may not.

## D-006 — Text geometry precedes text routing and structure repair

Status: accepted

P1 text geometry must be stabilized and accepted before P2 symbol routing and P4 line repair. Text placement and protection masks are prerequisites for safe structure recovery.

## D-007 — Every page and every final DXF is accepted independently

Status: accepted

A global average or a single-page success cannot hide a failed page. Automated page/DXF reports and human sampling must state exact coverage.

## D-008 — Human LibreCAD evidence outranks broad automated PASS labels

Status: accepted

When automated results and user observations conflict, record the conflict, preserve both evidence classes, and investigate. Do not replace human failure with an automated success claim.

## D-009 — One major issue per task

Status: accepted

Each task uses one isolated commit, a 20–45 minute recoverable checkpoint where practical, explicit modification boundaries, acceptance criteria, and a stop condition. Recommendations are not executed automatically.

## D-010 — Phase 12 remains an immutable safety baseline

Status: accepted

`baseline/phase12-final-acceptance-2026-07-30` at `6f5f69329aabf0bd3a7eda84baf66eb1959bdcba` is an architecture/safety baseline, not a final product release. It must not be moved or overwritten to make later results appear better.

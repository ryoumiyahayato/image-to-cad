# Primitive Integrity Review UI V2

Status: `COMPLETE`

This change is a reviewer-facing UI redesign only. It does not change the
selected cases, candidate order, protocol, persisted values, import/export
schema, diagnostics, guards, mining, models, or production behavior.

## Frozen review invariants

- Candidate count: `16`
- Candidate set ID: `FRESH-DEV-CANDIDATE-REMINING-V1-5EA8AAE98504-PRIMITIVE-INTEGRITY-748C5A4B61CD`
- Candidate order: unchanged; package order matches the frozen selection
  manifest and candidate registry.
- Selection digest: `748c5a4b61cde3fb0ce5c754d000498275e06cdb9ae87263d7af0f0d4a47f94a`
- Review protocol: `PRIMITIVE_INTEGRITY_REVIEW_V1`
- Primary and secondary enum values: unchanged internally.
- Existing localStorage key and session fields: unchanged.

## UI-only redesign

- Human-facing page title and labels are concise Chinese.
- Long technical enum names remain internal data values and are not rendered
  as normal reviewer-facing text.
- Four logical images remain present as a compact 2×2 preview grid:
  `局部原图`, `局部红线`, `整体原图`, `整体红线`.
- Preview images use contain sizing, fixed compact heights, and click-to-open
  enlarged paired views.
- Escape and outside-click close the lightbox; enlarged red views retain the
  endpoint marker automatically without a persistent marker toggle.
- Six primary choices are compact, use Chinese titles and muted explanations,
  and have a clear selected state.
- Optional secondary flags are in `补充标记（可选）`, collapsed by default,
  with Chinese labels only.
- Notes use a normal four-line textarea with a short Chinese helper and keep
  entered text verbatim.
- Previous/next navigation is in normal document flow and does not overlay
  images, notes, or controls.
- Import, export, and restart are grouped under the small `数据` menu.
- Persistent clean/overlay/focus/marker display controls were removed.
- The visible shortcut hint remains `1–6` for choice and `←/→` for case
  navigation.

## Compatibility and blindness

- Legacy array imports and object-with-`items` imports remain accepted.
- Export round-trip retains 16 rows and the original keys:
  `protocol`, `candidate_set_id`, `candidate_id`, `review_index`,
  `primary_class`, `secondary_flags`, `optional_note`.
- Notes are preserved verbatim, including surrounding whitespace and newlines.
- No machine verdict, diagnostic score, selection stratum, prior human label,
  or other answer leakage is rendered to the reviewer.

## QA

Static package QA:

- Focused package tests: `7/7 PASS`.
- Runtime package validation: `PASS`.
- Four-view assets: `16` local clean, `16` local red, `16` overall clean,
  `16` overall red.
- `git diff --check`: `PASS`.

Live browser QA:

- Browser plugin was unavailable; Playwright `1.63.0` used with the existing
  local Chrome executable, without installing browser dependencies.
- URL: `http://127.0.0.1:8765/review.html`
- Desktop viewport: `1440×900`.
- Mobile viewport: `390×844`.
- Page identity, image loading, Chinese-only visible labels, compact geometry,
  selected state, collapsed defaults, note persistence, lightbox open/close,
  keyboard navigation, previous/next restoration, and grouped data controls:
  `PASS`.
- Browser console errors, page errors, and failed responses: none.
- Import/export compatibility interaction: `PASS` with 16 rows and unchanged
  schema keys.

Screenshots were rendered and visually inspected for the desktop initial state,
selected state, enlarged lightbox, and mobile state in the temporary QA output
directory under `C:\Users\agcrf\AppData\Local\Temp\primitive-integrity-review-v2-qa`.

## Governance

```text
PRODUCTION_SEMANTIC_DELTA: NONE
NEW CANDIDATE MINING: NO
BATCH03: NO
MODEL RUN: NO
MODEL-ASSISTED LABELING: NO
SPAN GUARD CHANGED: NO
AXIS GUARD CHANGED: NO
ADMISSIBILITY GUARD CHANGED: NO
COHERENCE GUARD IMPLEMENTED: NO
ENDPOINT GUARD IMPLEMENTED: NO
VALIDATION: NO
LOCKED_BLIND: 0 / 8
H1/H2: DO NOT OPEN
HUMAN REVIEW: NOT STARTED
```

The next action remains `HUMAN_PRIMITIVE_INTEGRITY_REVIEW`.

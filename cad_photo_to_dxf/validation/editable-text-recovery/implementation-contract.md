# Implementation contract

## Independent decisions

Each OCR candidate has two independent booleans:

1. `text_emit_eligible`: whether native editable DXF `TEXT` may be emitted.
2. `source_outline_suppressible`: whether the scanned source glyph may be
   omitted from the default-visible output without losing unrelated ink.

`text_emit_eligible` is determined only by non-empty encodable content, the
existing confidence contract, approval/review state, valid bbox or quad,
finite position/size/rotation geometry, and absence of an explicit OCR hard
reject.

Replacement safety, connected-component crossings, multi-character connected
components, nearby uncovered ink, incomplete ownership, straight-line
conflicts, table contact/cropping, nearby noise, or an inability to erase the
whole source glyph affect only `source_outline_suppressible`.

The existing OCR confidence threshold is unchanged.

## Routing

- Eligible and suppressible: one visible `OCR_TEXT` entity; no visible source
  glyph duplicate.
- Eligible and not suppressible: one visible `OCR_TEXT` entity plus source
  glyph pixels on the default-off `SOURCE_TEXT_OUTLINE` backup layer.
- Not eligible: no native `TEXT`; source glyphs remain visible on
  `TEXT_FALLBACK_OUTLINE` or `UNCERTAIN_TEXT_OUTLINE`.

An OCR candidate has exactly one primary semantic:
`editable_text`, `uncertain_text`, or `residual_non_text`.
`SOURCE_TEXT_OUTLINE` is a backup representation and not a second primary
semantic.

## Geometry

The existing page coordinate transform remains:

```text
dxf_x = source_x * scale_x
dxf_y = page_height_mm - source_y * scale_y
```

Native TEXT placement prefers the OCR quad over the axis-aligned bbox and fits
the measured font extent to the target center, width, height, and rotation.
No unconditional `0.78` height shrink or generic `0.60` width compression is
permitted.

## Immutable scope

This change does not alter OCR confidence thresholds, automatic line repair,
colors, Logo/signature classification, page-specific rules, text dictionaries,
or recorded real-regression baselines.


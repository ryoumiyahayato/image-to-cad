# Next task

## P1 — Repair native `TEXT` geometry fitting

Status: authorized by roadmap only; **not started and not automatically authorized for execution**

### Objective

Make native DXF `TEXT` fit the OCR region in real LibreCAD use without reducing editable-text coverage.

### Required initial audit

Before changing code:

1. identify every path that creates or rebuilds a DXF text entity;
2. determine whether geometry is calculated in more than one place;
3. trace OCR bbox/quad, orientation, font metrics, height, width factor, insertion/alignment, baseline, and rotation into final DXF attributes;
4. verify whether rough source-outline bounds affect text dimensions;
5. compare current automated geometry metrics with the user-visible failures.

### Modification boundary

Allowed only:

- text height;
- width factor;
- insertion point;
- alignment point;
- baseline;
- rotation;
- OCR bbox/quad-to-text fitting;
- font metrics and abnormal-box fallback reporting.

Not allowed:

- OCR content or threshold changes;
- text eligibility or source-outline contracts;
- symbol routing;
- structure/repair;
- logo/signature;
- PDF export;
- diagnostic colors.

### Development set

Use exactly three representative real pages first:

1. low-quality environmental-office scan;
2. dense lower-right title-block page;
3. comparatively clean digital-PDF page.

After those pass, rerun every real page and every final DXF independently.

### Acceptance and stop

P1 stops after automated geometry evidence, entity/read-save-read regression, and user LibreCAD review are available. P2 must not begin in the same task.

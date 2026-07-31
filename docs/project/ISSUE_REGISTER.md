# Issue register

Status values: open, deferred, accepted risk, verified.  
Evidence classes: code, automated, user UAT, hypothesis.

| ID | Issue | Evidence | Risk | Priority | Status | Related areas | Release blocker |
|---|---|---|---|---|---|---|---|
| CAD-001 | Native `TEXT` is frequently too large, overlapping, stretched/compressed, misplaced, or outside table bounds. | User UAT: direct LibreCAD failure. Automated reports claim valid geometry and no systematic height shrink. | Drawings remain impractical to edit and visually incorrect. | P0 | Open; next task P1 | `librecad_lff.py`, DXF text-entity creation paths, OCR bbox/quad geometry, geometry validation artifacts | Yes |
| CAD-002 | Ordinary printed text still appears in `TRACE_TEXT_SYMBOL`, especially vertical/rotated/title-block text. | User UAT: typically about 5–9 characters per drawing. Automated candidate-owned conflict count is zero. | Missed editability and ambiguous semantics. | P1 | Deferred until P1 | OCR routing, ownership, rotation handling, title-block/small-text cases | Yes |
| CAD-003 | Damaged frames and structural lines remain incomplete; repair recall is conservative. | User UAT: broken borders and missing lines; old page-crossing errors greatly reduced. | Incomplete CAD structure. | P2 | Deferred until text protection is stable | structural ROI, connectivity safety, `REPAIRED_STRUCTURE` | Yes |
| CAD-004 | Formal output and diagnostic coloring are not fully separated. | User requirement and prior diagnostic-output experience. | Production files may be visually noisy; reviewers lack a controlled inspection mode. | P2 | Deferred until P1/P2 | layer policy, exporter display configuration | Yes |
| CAD-005 | Full per-page human UAT is incomplete. | User inspected seven DXFs for several behaviors and two DXFs for edit persistence, not all pages. | Automated coverage could hide page-specific visual failures. | P0 | Open through P6 | UAT procedure and release gate | Yes |
| CAD-006 | PR #23 has very large review scope and artifact volume. | GitHub inspection: 18 commits, 434 changed files, 12,444,529 additions. Many validation DXF/PNG/log artifacts are included. | Reviewability, repository weight, and release confidence are reduced. | P1 | Open; no cleanup in P0 | PR scope, validation artifact retention policy | Yes |
| CAD-007 | Rough `SOURCE_TEXT_OUTLINE` bounds may contaminate text fitting. | User UAT observes rough outlines; cause of text oversizing is a hypothesis, not confirmed. | Incorrect font height/width if dirty outer bounds are used. | P0 | Open hypothesis for P1 audit | source outline masks and geometry metric inputs | Potentially |
| CAD-008 | Current automated geometry acceptance does not represent real visual fit. | Automated completion says PASS, 33/33, center/rotation error 0; user sees oversize/overlap/overflow. | False release confidence and ineffective acceptance thresholds. | P0 | Open; P1 must redefine geometry gates | geometry XDATA, rendered bounds, OCR target bounds, cell constraints | Yes |
| CAD-009 | Exact live tag-ref verification is limited in this execution environment. | Phase-12 commit exists; repository checkpoint records the tag mapping; the available connector does not expose tag-ref listing. | Low risk of unnoticed tag movement unless separately verified before release. | P2 | Accepted execution limitation; recheck at P6 with a tag-capable client | phase-12 tag | No for P0; yes for release |
| CAD-010 | GitHub combined status returned no status entries for the inspected HEAD. | Remote inspection result. This does not establish pass or fail. | CI state may be misunderstood. | P1 | Open observation | Actions/check suites | Yes until verified |

## Evidence conflict notes

### CAD-001 / CAD-008

Automated evidence states:

- 33/33 final pages and DXFs passed;
- invalid geometry rejects: zero;
- native geometry has no systematic height shrink;
- rendered height ratio and center/rotation error meet the current numeric checks.

Human evidence states:

- many texts are too large;
- strings overlap;
- text exceeds table/border regions;
- width and rotated placement are visibly wrong.

Conclusion: the current automated geometry metrics are insufficient or measure a different contract. Human failure stands.

### CAD-002

Automated evidence states eligible candidate-owned `TRACE_TEXT_SYMBOL` conflicts are zero. Human evidence sees ordinary printed characters on that layer. Possible explanations include OCR-missed candidates, object-boundary adjacency, different ownership definitions, or page categories not represented by the candidate metric. These are hypotheses requiring P2 audit.

### CAD-003

Automated protection checks and human UAT agree that catastrophic unsafe lines are reduced. They do not prove structure restoration is complete. Safety and recall must remain separate measurements.

## P1A evidence update — 2026-07-31

- CAD-001 remains open/release blocker: P1A found 346/436 minimum-width clamps and 94 predicted extra boundary crossings. Root cause identified, not fixed.
- CAD-002 remains deferred: no native 90°/270° TEXT occurs in the selected pages or current 12-DXF evidence.
- CAD-007 hypothesis is rejected for the canonical path: SOURCE_TEXT_OUTLINE does not size formal TEXT.
- CAD-008 remains open/release blocker: the focused test explicitly accepts overflow and the GUI preview omits native TEXT geometry.
- CAD-011 open: exact original OCR bbox/quad is not persisted in final DXF.
- CAD-012 open: three inconsistent native TEXT creators remain in the repository.
- CAD-013 open: live LibreCAD font resolution/substitution is not recorded.

No issue is marked resolved by P1A. Existing routing, structure, color, OCR and full-UAT statuses are unchanged.

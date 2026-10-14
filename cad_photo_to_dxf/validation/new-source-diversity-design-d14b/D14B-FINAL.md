# New source diversity design D14B

## Decision and scope

**NEW SOURCE ACQUISITION JUSTIFIED: YES**, but acquisition is not authorized or performed in D14B.

The minimum P0 design is **three genuinely independent source families, four documents, and 15 qualified independent cases**. Two of the three families are designated `NEW-SOURCE HOLDOUT CANDIDATES`. All future material from this plan is DEV-only; none may enter VALIDATION or LOCKED_BLIND.

This is a design result based on the committed D11–D14A reports. No candidate mining, labeling, model run, web search, file download, PDF inspection, or production change was performed.

## Evidence from the current six source groups

The current 28 qualified cases already contain building/floor-plan, electrical/installation, and civil/profile-like structure, plus hard negatives from aligned glyphs, one dimension chain, drawing-layout rules, legend/table rules, revision-table rules, and title-block rules. That coverage makes another nominally different building PDF insufficient by itself.

The actual gaps are:

1. **Qualified degraded historical raster evidence.** D11 explicitly found no evidence of robust performance on degraded historical drawings. The degraded source produced one ambiguous case and invalid embedded-figure borders, not a usable mixed-class family.
2. **Dense mechanical dimension/leader evidence.** Only one qualified dimension-chain negative exists, and D11 observed no qualified leader/marker negative. There is no demonstrated independent family dominated by mechanical dimensions, witnesses, leaders, and close parallel object lines.
3. **Independent civil/site/profile drafting style.** The current civil/profile-like source `G0R2-C2D095E069663C17` remains the weakest group. Its class centroids are unusually close and its structural styles transfer weakly. A different organization and drafting convention are needed to distinguish a representation limitation from one-source idiosyncrasy.

Electrical conductor-like structure and table/title/revision rules are already represented, so a dense control schematic remains useful as P1 rather than part of the minimum P0 set. Clean architectural/building material is also already represented and is P2 unless a candidate supplies unusually independent typography or drafting conventions.

## What qualifies as a new source family

A family is defined by a materially independent combination of publisher/organization, drafting standard, discipline, document-generation process, and visual style—not by filename, project number, mirror URL, or individual PDF count.

A proposed family must document at least two meaningful differences from the current corpus, with at least one being a strong visual-generation or drafting-convention difference. Relevant axes include vector versus scanned origin, raster degradation, line-weight hierarchy, dimensioning and leader conventions, page density, typography, title/revision layout, structural-line appearance, annotation-line appearance, age, and organizational template.

The following do **not** create separate families:

- two revisions or sheets using the same organization template;
- a scan and a vector export of the same underlying drawing;
- mirrored or republished copies of one file;
- multiple documents by one vendor using the same drafting system;
- different filenames with no evidenced style independence.

Related documents remain in one `SOURCE_FAMILY_ID`. Near-duplicate sheets and repeated details may not count as independent qualified cases.

## Acquisition matrix

| Priority | Proposed source family | Why needed | Missing style axis | Expected structural cases | Expected hard negatives | Target documents | Target qualified cases | Preferred rights status | Holdout candidate |
|---|---|---|---|---|---|---:|---:|---|---|
| **P0** | Degraded scanned historical engineering drawings from one archive/organization | Tests the largest unqualified style gap and scan robustness | archival age, raster degradation, faded/broken strokes, historical typography and dimensioning | 2 long object/boundary/profile continuations | 2 table/frame/dimension or glyph-aligned lines | **2** | **4** | Public domain with documented basis; otherwise `RIGHTS_REVIEW_REQUIRED` | **YES — H1** |
| **P0** | Dense vector mechanical fabrication/assembly drawings from a new vendor | Directly stresses the dimension-chain failure and absent leader/marker coverage | dense dimensioning, witness/extension lines, leaders, close parallel object edges, mechanical line weights | 3 object-edge/centerline or section continuations | 3 dimension/witness/leader chains | **1** | **6** | CC0, public domain, CC BY, or express retention/training permission | **YES — H2** |
| **P0** | Modern civil/site/profile drawings from an organization unrelated to `C2D0` | Tests whether the weak civil/profile behavior transfers across drafting families | independent civil convention, long profiles/boundaries, grids, stationing and panel layout | 2 roadway/profile/site-boundary continuations | 3 grid/dimension/panel-divider/title rules | **1** | **5** | Clear public-domain or explicit reuse/training terms; government availability alone is insufficient | NO — development-transfer family |
| **P1** | Dense electrical/control or instrumentation schematic from a new organization | Extends existing sparse conductor-like evidence with symbol- and table-dense pages | long conductors versus leaders, grid rules, terminal tables, dense symbols | 2–3 conductor/bus continuations | 2–3 table/grid/leader/legend rules | 1–2 | 4–6 | CC0/public domain/CC BY or express permission | NO |
| **P2** | Clean vector architectural/building set with a demonstrably new organizational template | Adds a clean reference only if typography, title layout, and line weights are genuinely independent | vendor typography, revision/title conventions, high-density vector drafting | 2 wall/grid continuations | 1–3 dimension/title/revision/legend rules | 1 | 3–5 | CC0/public domain/CC BY or express permission | NO |

P0 is the complete minimum acquisition. P1 and P2 are not authorized fallback downloads; they should be considered only after the P0 result or if a P0 family fails the usability/rights gate before acquisition.

## P0 stopping rule and case independence

Stop once the three P0 families yield the planned **15 qualified independent cases** from at most **four documents**. Do not continue toward a large corpus merely because more files are available.

Targets are deliberately small and natural rather than forcibly balanced:

- historical scan: aim for 2 structural and 2 annotation/glyph cases across two documents;
- mechanical: aim for 3 structural and 3 hard negatives in one sufficiently rich document;
- independent civil/profile: aim for 2 structural and 3 hard negatives in one document.

Each usable family should contain both classes where naturally available. If a document cannot yield both classes, record the shortfall; do not relabel or select invalid cases to meet a quota. A second document is allowed only within the historical P0 allocation. Any expansion beyond four P0 documents requires a new decision.

Independence must be assessed from drawing identity and repeated-pattern metadata. Repeated details, adjacent segments of one rule, repeated title blocks, and near-identical sheets count once.

## Candidate selection and human-label protocol

1. Resolve family independence and rights before a file enters the usable DEV registry.
2. Select a small set of pages using document structure and discipline coverage, not MobileNet output.
3. Candidate proposal may use the existing geometric gap criteria only. It may not use embedding, class score, margin, uncertainty, or model-error ranking.
4. Freeze candidate IDs, source-family grouping, page identities, and independence clusters before human labeling.
5. Human reviewers label from existing-style local/context evidence while blind to all MobileNet predictions.
6. Record `STRUCTURAL_CONTINUATION`, `ANNOTATION_OR_GLYPH`, `AMBIGUOUS`, and `INVALID_FOR_TASK` without forcing class balance.
7. Freeze the human registry before extracting frozen MobileNet features or revealing predictions.

This prevents active-learning leakage and preserves an unbiased first test of new-source diversity.

## New-source holdout governance

The historical family is reserved as **H1** and the mechanical family as **H2**. Both remain DEV-governed `NEW-SOURCE HOLDOUT CANDIDATES`, never VALIDATION or LOCKED_BLIND.

For the initial new-source experiment, all three P0 families are evaluated only after candidate selection and labels are frozen. The existing six-source dataset supplies any frozen class prototypes. No P0 sample may affect representation, classifier fitting, threshold selection, or preprocessing.

After the initial result:

- H1 and H2 remain permanently excluded from future probe fitting and threshold selection unless governance is explicitly redesigned in a later task;
- the civil/profile P0 family may become a DEV adaptation pool only after its untouched baseline result is durably recorded;
- results must be reported per family, not hidden in a 15-case aggregate;
- no model predictions may be viewed during source/page/candidate selection or human labeling.

## Separate provenance tracks

### A. Source evidence provenance

Each acquired document must have a source-evidence record containing:

- `SOURCE_FAMILY_ID` and the documented style-independence rationale;
- original direct source URL and landing-page URL;
- publisher/organization and, if different, drafting vendor;
- document title, document/revision identifier, publication date, and access timestamp;
- original filename, byte length, MIME type, and SHA-256 after acquisition;
- page number plus printed sheet/page identifier for every retained case;
- mirror/duplicate relationship checks;
- full transformation history: original file → page render parameters/software → crop coordinates → review-pair generation → any later feature extraction;
- stable candidate ID and near-duplicate/independence cluster.

This track establishes what the evidence is and how a case was derived. It does not establish permission to use it.

### B. Data rights provenance

A separate rights record must contain:

- asserted copyright owner and publisher;
- license name/version, license or terms URL, access date, and retained evidence of the applicable terms;
- public-domain basis where claimed, including jurisdiction and rationale;
- redistribution and commercial-use permissions/restrictions;
- whether raw-file retention is allowed;
- whether rendered pages and derived crops may be retained or redistributed;
- whether human labels/metadata may be retained;
- whether model-training and evaluation use is permitted, prohibited, or unclear;
- attribution, notice, share-alike, access-control, or deletion obligations;
- reviewer, review date, and disposition.

Preferred disposition is public domain, CC0, CC BY, or explicit permission covering retention, derived artifacts, and ML evaluation/training. A publicly downloadable file is not presumed reusable. Any missing or ambiguous field yields **`RIGHTS_REVIEW_REQUIRED`**; the source may not enter the usable experiment until resolved. Source evidence and data rights must never be merged into one implied approval.

## Predeclared representation outcomes

The next experiment must use the frozen D12D/D13B representation and report raw, per-family results before any adaptation.

### Outcome A — frozen representation remains useful

This outcome is supported if class-directed separation persists in multiple P0 families, neither H1 nor H2 collapses to trivial behavior, and dangerous false structural errors remain materially below the always-structural baseline. A single aggregate score is insufficient. This outcome justifies a larger labeled DEV collection and later investigation of classifier/calibration strategy; it does not justify production integration.

### Outcome B — frozen representation substantially collapses

This outcome is supported if multiple independent P0 families approach trivial classification, show reversed or absent class separation, or make annotation-derived long lines commonly structural—especially in H1 or H2. This would support treating generic ImageNet MobileNet features as insufficient and investigating a domain-specific perception representation. It would not authorize automatic geometry bridging.

Mixed small-sample evidence should be reported as inconclusive rather than assigned to the more favorable outcome. No classifier or threshold may be tuned to make Outcome A occur.

## General perception versus domain knowledge

**General perception** owns visual continuity, structural-line versus annotation-line appearance, robustness to line weight and degradation, local/context visual encoding, and recognition that dimension/table/layout strokes are visually distinct or overlapping. The new-source experiment primarily tests this capability.

**Domain knowledge** may later contribute discipline-specific symbol meanings, title/revision conventions, dimension semantics, drafting standards, or system-connectivity context. Such evidence must remain explicit and advisory. It may reject or qualify a visual proposal, but it must not manufacture unsupported geometry or turn an uncertain visual gap into `FinalStructure` by convention alone.

No knowledge pack is designed or built in D14B.

## Final design decision

- Minimum P0: **3 new source families, 4 documents, 15 qualified independent cases**.
- New-source holdout candidates: **2 families (H1 historical, H2 mechanical)**.
- Rights provenance: required and independently gated.
- Source evidence provenance: required and independently recorded.
- New source acquisition is justified, but **not authorized in this task**.
- New PDFs acquired: **0**.
- Ready for production integration: **NO**.
- Production semantic delta: **NONE**.
- VALIDATION: **NO**.
- LOCKED_BLIND: **0 / 8**.

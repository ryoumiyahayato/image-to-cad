# Draftsman current state

This is the canonical first entry point for fresh-clone Draftsman development.
It describes the state at base commit
`5f964e5a0ad74f9cea4b1b0d4e2c9b8c8aae16c9`. Use the tracked
[replay matrix](REPLAY_MATRIX.md) to validate it. When code and this document
disagree, stop, inspect the relevant commit and tests, and update the canonical
record explicitly; do not fill the gap from chat history.

## Project goal and scope

Draftsman reconstructs old PDFs, scans, and images into CAD working drawings
that are:

- visually faithful;
- structurally coherent;
- editable;
- auditable.

The current professional domain is **Electrical**. The goal is not to recover
the original CAD file or infer unavailable original design semantics. Source
content, explicit drawing/domain authority, and recorded uncertainty bound every
claim.

The product direction is **batch, editable, auditable, and exception-driven**.
The intended workflow processes large historical drawing sets unattended and
concentrates professional attention on a small exception queue. Best-case
single-page speed is not the primary value.

Candidate product KPIs are zero-touch page rate, active human minutes per 100
pages, review actions per 100 pages, editable CAD coverage, silent-omission
rate, false-review burden, and batch-failure isolation. No current numerical
value is claimed here unless a tracked measurement explicitly supplies it.

## Canonical architecture

```text
INPUT
  -> SOURCE NORMALIZATION
  -> EVIDENCE FRONTEND
  -> UNIFIED EVIDENCE
  -> DOMAIN INTERPRETATION
  -> LOGICAL DRAWING MODEL
  -> FINAL ENTITY ASSEMBLY
  -> EDITABLE CAD IR
  -> QUALITY AUDIT
  -> EXCEPTION REVIEW
  -> DXF/DWG
```

**SOURCE IS TRUTH.** Detection is an observation mechanism, not final drawing
authority:

```text
Detection Fragment != Logical Entity != Final CAD Entity
```

Evidence frontends may differ for vector PDF, raster/scan, and photo inputs,
but their facts enter a unified evidence boundary before domain interpretation.
Domain interpretation applies explicit professional and drawing-specific
authority. Logical entities express drawing structure; final assembly chooses
supported entity boundaries; CAD IR describes editable output independently of
a particular exporter. Quality audit and exception review never silently invent
authority.

## Product priorities and uncertainty

The canonical priority order is:

1. **EDITABILITY**
2. **VISUAL FIDELITY**
3. **ERROR CONTROLLABILITY / EXPLICIT UNCERTAINTY**
4. **AUTOMATION COVERAGE**
5. **SEMANTIC DEPTH**

`SEMANTIC_IDENTITY_UNVERIFIED` geometry may remain editable. Unknown semantics
must not automatically delete source-supported geometry. Conversely, editability
does not permit inventing geometry or promoting an uncertain identity to a
verified engineering fact.

## Hypothesis and authority policy

The pipeline must not collapse observations into premature irreversible
decisions. Evidence, domain, and topology stages may preserve competing
hypotheses in `ACCEPTED`, `PROVISIONAL`, or `UNRESOLVED` states. Rejection or
non-selection must retain an auditable reason where the contract provides one.

Orientation and layout do not establish semantic identity. `LEFT/RIGHT`,
horizontal-only layout, exactly two ports, or a fixed tag side are not universal
semantic gates without source/domain authority. T0 found those to be accidental
assumptions of the original five-instance slice.

ML/CV may produce evidence and semantic/topology hypotheses. A probabilistic
model is not, by itself, an opaque final engineering fact source. Authoritative
acceptance must remain traceable to:

```text
source evidence + domain/drawing authority + constraints + explicit review state
```

This policy does **not** require ML to exist only in the Evidence Layer. It may
propose downstream hypotheses as long as provenance, authority, constraints,
and uncertainty remain inspectable.

## Production boundary

The shipping application under the existing production pipeline and the new
Draftsman architecture are separate paths. VS1/VS2/VS3, E1, T1, U1, QA1, and
QA2 are **shadow architecture**. Focused tests enforce that production entry
points do not import these shadow modules.

The new pipeline has not taken ownership of production DXF generation.
Production semantic delta for the milestones below is currently **NONE**. A
successful shadow replay, clean preview, or audit result must not be described
as a production capability.

## Milestones that still define current state

| Milestone | Purpose | Disposition | Canonical code commit | Key result | Important limitation |
|---|---|---|---|---|---|
| VS1 | Prove vector-PDF Evidence -> Logical -> CAD IR on table rules | Keep; shadow baseline | `a56c3c718a2aa8b018e1687148f60b0945807d9a` | Page 1: 19 source rules -> 19 logical rules -> 19 CAD lines | Narrow annotated table-rule slice; not general table reconstruction |
| VS2 | Prove one electrical symbol and connections from vector PDF | Keep; shadow baseline | `1033b07b6b8651cfea24502cbc5fd39a19181c8f` | One C1 symbol plus four source-backed ports/lines | One source instance and drawing-specific legend authority |
| VS3 | Prove a raster Electrical slice through shared contracts | Keep as historical narrow baseline | `a8df9ba05b7dea43dbf9c0263d019ff14c10b284` | Five repeated smoke instances accepted with editable CAD IR | Original signature/topology did not generalize across the family |
| VS3-E1 | Separate high-recall raster evidence from domain assumptions | Keep; tracked audit baseline | `004f4c42203b4bf4d71d3ff7740d0ffaa8a11fc0` | 154 candidates; matched-glyph coverage 37/38; frozen downstream | `evidence_covered` was only matched glyph evidence; candidate growth/noise remains |
| VS3-T0 | Human root-cause and topology audit | Operative decisions extracted below; full report is non-canonical evidence | N/A (read-only local audit) | Three topology families and two reusable rules; tested-family explosion risk LOW | Per-instance adjudication included one bad reference and must not become runtime truth |
| VS3-T1 | Orientation-neutral topology hypotheses | Keep; shadow baseline | `8c72134c8e6df36a435b0dce48d057bdf0234e22` | 26/38 accepted; degree 1/2/3 and competing hypotheses preserved | Logical/assembly claims cover only the 26 evaluated accepted instances |
| VS3-U1 | Preserve editable geometry with unverified semantics | Keep; shadow baseline | `652357e97b49c316a3c34750d8c13810797336eb` | 36/38 family positions received verified or unverified editable geometry | Unverified relations are not asserted connections; no silent-omission detection |
| QA0 | Define candidate accounting and silent-omission boundary | Operative decisions extracted below | N/A (read-only local audit) | Established need for independent source coverage and a reference-free QA1 boundary | Proposed generic omission alerts were too noisy for user action |
| QA1 | Reference-free candidate disposition and lineage audit | Keep; shadow read-only auditor | `0f60e03bc9eb213cf347906487378b319a39ff0d` | Deterministic disposition for all 154 runtime candidates; lineage checks | Cannot find an object for which the frontend emitted no evidence |
| QA2-S1 | Independent source-coverage measurement | Keep measurement-only | `5215f2da52ae3f795e29310b0634e96781dea116` | Found the known true omission with an independent signal | 220 residual signals and very low precision; not actionable |
| QA2-S2 | Reference-free residual risk triage | Keep frozen and measurement-only | `5f964e5a0ad74f9cea4b1b0d4e2c9b8c8aae16c9` | Golden page Tier A: 104, including 1 known true and 103 false | **STILL_TOO_NOISY**; must not enter the actionable Review Queue |
| B1 | Frozen cross-drawing blind generalization audit | Completed; preserve frozen baseline | N/A (read-only audit at `5f964e5`) | Generic-core reuse 6/12; sampled outcomes 0 correct, 2 partial, 34 missed, 4 wrong | Existing domain knowledge did not transfer; false semantic promotion and QA2-S2 Golden-count guard were exposed |

## Operative T0 decisions

- The tested smoke family has three topology families: **series-through**
  (degree 2), **terminal** (degree 1), and **branch** (degree 3).
- Two reusable topology rules are sufficient at this level: infer incident ports
  from source-backed runs meeting the symbol boundary without compass semantics;
  preserve observed degree 1/2/3 without inventing or deleting a run.
- Rule-explosion risk was **LOW on this tested family** only if crowded cases
  remain reviewable. B1 separately found cross-drawing rule-explosion risk HIGH;
  these denominators must not be conflated.
- Accidental original assumptions were horizontal-only geometry, fixed
  left/right ports, exactly two ports, both-side support as semantics, five
  aligned repetitions as a semantic gate, and one fixture-calibrated template.
- Competing hypotheses must remain reversible through Evidence, Domain, and
  Topology; unverified source-supported geometry remains eligible for editable
  preservation without semantic promotion.

## Operative QA0 and current QA boundaries

QA1 is a reference-free, read-only candidate-disposition and cross-layer
lineage auditor. It can audit evidence, hypotheses, logical entities, CAD IR,
review items, and rejections that runtime actually produced. It cannot discover
an object for which the frontend produced no evidence. A complete candidate
ledger is therefore not proof of complete page/source coverage.

Independent source coverage is required for silent omissions. QA2-S1 and
QA2-S2 provide that measurement path, but remain measurement-only and may not
change QA1 dispositions, production routing, or the actionable Review Queue.
On the current Golden page QA2-S2 Tier A contains **104/page**: **1 known true**
and **103 false**. Status: **STILL_TOO_NOISY**. High-noise signals stay out of
the actionable queue until a separately authorized, cross-drawing validation
establishes acceptable burden.

## Metric interpretation guardrails

1. Historical E1 `evidence_covered` means a reference region had matched glyph
   evidence. It does not mean complete reconstruction evidence, line/endpoint/
   tag association, or reconstructability.
2. Historical family-audit `false positives = 0` counts accepted final
   hypotheses unmatched to the reference family. It does not mean Evidence
   candidate noise is zero.
3. Historical `DOMAIN` and `TOPOLOGY` failure labels are programmatic auditor
   labels. They are not automatically the earliest factual root cause; human T0
   and B1 attribution found frontend, evidence, domain, topology, logical-model,
   and audit causes.
4. `Logical / Assembly = 0 failures` applies only to the subset that entered and
   was evaluated at those layers. It has a survivorship denominator and cannot
   make upstream omissions disappear.

Always report the denominator and distinguish runtime observations, reference
evaluation, and human adjudication.

## Canonical sources and local artifacts

The tracked canonical source registry is
`cad_photo_to_dxf/tests/real_regression/draftsman_golden_manifest.json`.
Generated JSON reports, overlays, crops, previews, DXFs, logs, B1 source/evidence,
and manual UAT packages belong under `local-artifacts/` by default. That tree is
ignored, non-canonical review/UAT evidence and should be reproducible where
possible. It must never be the only home of architecture truth, operative
decisions, required replay configuration, or Golden identities.

## Cloud/local boundary

Cloud-ready after this canonical repair: architecture, Domain Pack development,
topology, CAD IR, QA1/QA2, tests, machine-readable audits, and source/evidence
work that uses tracked or explicitly supplied authorized inputs.

Local-required or recommended: Windows-native final smoke, LibreCAD UAT,
ODA/DWG behavior, final visual Golden acceptance, and final human workflow/time
validation. These are an accepted product/UAT boundary, not a hidden dependency
for ordinary architecture/domain/auditor development.

## Start here in a fresh clone

1. Use Python 3.11 and install `cad_photo_to_dxf/requirements.txt` plus
   `cad_photo_to_dxf/requirements-test.txt`.
2. Read the tracked Golden manifest named above.
3. Run `python -m pytest -q tests/test_draftsman_cloud_readiness.py` from
   `cad_photo_to_dxf/` to validate source hashes and this bootstrap contract.
4. Choose a representative command from [REPLAY_MATRIX.md](REPLAY_MATRIX.md),
   write its outputs to a disposable directory, and inspect its JSON summary.

No chat history or existing `local-artifacts` content is required for these
steps.

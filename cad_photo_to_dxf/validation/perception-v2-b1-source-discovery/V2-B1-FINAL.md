# Perception V2-B1: P0 Wave-1 source discovery and rights gate

## Decision

All three Wave-1 slots are `READY_TO_ACQUIRE` under a controlled, separate
acquisition task. Three preferred source families and two fallbacks were
reviewed—five serious candidates total, below the nine-family ceiling. The
preferred plan contains one document per family (three documents total). A
second or third document is not planned unless post-acquisition source
inventory demonstrates a genuine class or hard-negative coverage gap.

This decision is discovery-only. No PDF, image, TIFF, ZIP, dataset, or source
binary was downloaded; no full document was rendered; and no candidate mining,
crop generation, labeling, model inference, embedding, or classifier scoring
occurred. Screening used official catalog metadata, indexed official-document
content, and official preview descriptions only.

## Acquisition matrix

| Slot | Preferred source family | Preferred document | Organization | Style / generation difference | Expected structural value | Expected hard-negative value | Rights | Planned docs | Role | Result |
|---|---|---|---|---|---|---|---|---:|---|---|
| `SF-V2-01` | `V2-USACE-CIVIL-WORKS-MECHANICAL-CAD-2025` | EM 1110-2-2610, *Mechanical and Electrical Design for Civil Works Structures* (18 Mar 2025) | U.S. Army Corps of Engineers | Current USACE CAD illustrative-plate system; hydraulic machinery, multi-view assembly plates, dense conventional dimensions and leaders; unrelated to NIST PMI | Gate/pintle/drive object edges, sections, close parallel parts, machinery assemblies | witness/extension lines, dimension chains, leaders, datum/annotation structures | `PUBLIC_DOMAIN` | 1 | `TRAIN_POOL` | `READY_TO_ACQUIRE` |
| `SF-V2-03` | `V2-USDA-RUS-UNDERGROUND-DISTRIBUTION-2018` | RUS Bulletin 1728F-806 / RD-GD-2018-93, *Specifications and Drawings for Underground Electric Distribution* | USDA Rural Utilities Service | Federal construction-unit drawing system for real underground power installation; agency page also exposes AutoCAD source files | cable/conductor routes, enclosures, equipment boundaries, installation and grounding geometry | leaders, glyph strokes, layout/table rules, callouts, witness lines | `PUBLIC_DOMAIN` | 1 | `TRAIN_POOL` | `READY_TO_ACQUIRE` |
| `SF-V2-08` | `V2-NASA-GENERAL-DYNAMICS-LEGACY-SCAN-1980` | NASA-CR-161594 / GDC-ASP-80-010, *Low thrust vehicle concept study* | NASA MSFC / NTRS; General Dynamics Convair study contractor | Genuine 1980 report/drawing film-scan lineage with rotation, variable contrast, dense hatch, weakened raster edges, and mixed handwritten/typed marks | structural members, pipe/beam assemblies, tanks, vehicle outlines, sections/details | witness lines, dimension chains, layout rules, leaders, glyph strokes | `PUBLIC_DOMAIN` with actual-byte recheck | 1 | `DEV_COMPARISON` | `READY_TO_ACQUIRE` |

### Bounded fallbacks

| Slot | Fallback | Why not preferred | Rights |
|---|---|---|---|
| `SF-V2-01` | DoD/DLA ASSIST MIL-DTL-83723/88E connector detail-specification family | Excellent dense dimensions and datum/leader content, but B1 did not establish a candidate-specific reusable-rights statement or final binary URL | `RIGHTS_REVIEW_REQUIRED` |
| `SF-V2-03` | None | Preferred USDA family is official, rights-clear, and sufficiently drawing-rich at discovery stage | — |
| `SF-V2-08` | NASA-CR-161557, *Solar heating and hot water system installed at Shoney's Restaurant* | Plausible scanned as-built sections and installation geometry, but preferred report has stronger observed structural/detail and degradation evidence | `PUBLIC_DOMAIN` with actual-byte recheck |

No fallback is part of the planned three-document acquisition. A fallback may
replace its preferred family only if controlled acquisition finds an identity,
rights, independence, or suitability contradiction; it does not add a family
or document automatically.

## SF-V2-01 mechanical qualification

The official USACE publications catalog identifies current EM 1110-2-2610 as
the 18 March 2025 manual for mechanical and electrical design of civil-works
structures. Its Appendix B organizes 95 computer-aided-design illustrative
plates, including mechanical components, hydraulic drives, miter/sector/lift/
tainter gates, and related machinery. The official indexed Plate 20 preview
contains several pintle assembly views, bolt circles, sections, work/thrust
lines, dense dimensions, leaders, notes, and a plate title block. This is
plausibly rich in both genuine mechanical structure and the three priority
negative types. [USACE manual catalog](https://www.publications.usace.army.mil/USACE-Publications/Engineer-Manuals/),
[official EM 1110-2-2610 PDF endpoint](https://www.publications.usace.army.mil/Portals/76/Publications/EngineerManuals/EM%201110-2-2610_FINAL_18Mar2025.pdf).

The proposed family is independent of H2 NIST on at least five meaningful
axes: organization/template, hydraulic-machinery drafting convention,
traditional mechanical dimensioning, line-weight convention, and CAD manual/
plate generation. It is also unlike H1's archival HAER raster and C1's FHWA
civil plan/profile layout. Different subject matter is not the sole basis.

USACE states that its website information is public information and may be
distributed or copied unless otherwise specified. Combined with federal-work
status under 17 U.S.C. 105 and no contrary discovery notice, the preferred
candidate is classified `PUBLIC_DOMAIN`. Controlled acquisition must still
inspect the actual bytes for any incorporated third-party plates or specific
contrary notice. [USACE privacy and reuse statement](https://www.usace.army.mil/Privacy-and-Security/).

The sole fallback is the official DLA ASSIST connector specification family.
Its official preview shows clean multi-view component geometry with unusually
dense limits, diameters, tolerances, datum structures, dimensions, and leaders,
making it technically attractive and independent of NIST. It remains
`RIGHTS_REVIEW_REQUIRED`: government hosting and public availability do not by
themselves prove downstream reuse rights. It may not enter labeling, model
development, or retained derived crops unless that gate is resolved.

## SF-V2-03 electrical-installation qualification

USDA's official catalog and guidance record identify RUS Bulletin 1728F-806 as
a complete specification and drawing set for underground electric distribution,
issued by the Rural Utilities Service on 11 October 2018. The catalog also
offers corresponding AutoCAD files, supporting an authentic engineering-
drawing origin rather than a marketing diagram. The source plausibly provides
cables and conductors, equipment/enclosure boundaries, installation/grounding
geometry, leaders, callouts, standard drawing borders, tables, text strokes,
and dimensions. [USDA guidance record](https://www.usda.gov/guidance-documents/electric/rus/specifications-and-drawings-underground-electric-distribution),
[RUS bulletin catalog](https://www.rd.usda.gov/resources/regulations/bulletins),
[official PDF endpoint](https://www.rd.usda.gov/media/file/download/uep-bulletin-1728f-806.pdf).

The proposed family differs from existing project material on organization/
template, underground-distribution construction-unit convention, agency
generation process, and typography/layout system. Those are four meaningful
axes; discipline alone is not carrying the independence claim. Exact vector/
mixed composition, line weights, page count, and drawing font remain `UNKNOWN`
until controlled byte acquisition and are not fabricated here.

USDA Rural Development states that information presented on its site is public
information and may be distributed or copied, with credits requested. Together
with the federal agency authorship and no contrary source-level notice found,
the candidate is classified `PUBLIC_DOMAIN`. Referenced private standards do
not become part of this rights disposition. Actual bytes must be checked for
incorporated third-party drawings or conflicting notices before admission.
[USDA Rural Development reuse statement](https://www.rd.usda.gov/privacy-policy).

No fallback is necessary at discovery stage. One bulletin is planned; a second
USDA bulletin must not be added merely to increase volume or treated as an
independent family without a later family analysis.

## SF-V2-08 genuine modern degraded-scan qualification

The preferred NTRS record is NASA-CR-161594 / GDC-ASP-80-010, a General
Dynamics Convair low-thrust vehicle concept study published in 1980 and
digitized through NASA's Legacy CDMS/NTRS pipeline. Official indexed content
shows a rotated black-and-white technical drawing with many detail views,
primary/secondary structural-member labels, pipe/beam-like assemblies,
handwritten dimension arrows, section marks, dense hatch, and film-era marginal
artifacts. The degradation is part of the repository's real reproduction
lineage; it is not an artificial transform, screenshot, or derivative of H1,
H2, C1, or another V2 source. [NTRS record](https://ntrs.nasa.gov/citations/19810002593),
[official binary endpoint—not acquired in B1](https://ntrs.nasa.gov/api/citations/19810002593/downloads/19810002593.pdf).

The family is independent on General Dynamics/NASA template, aerospace
drafting convention, genuine scan/film process, degradation, and mixed
handwritten/typed typography. It is not H1-like merely because both are raster:
H1 is HAER measured-drawing imagery from a different organization, drafting
purpose, template, and archival master process.

The specific NTRS record says `Work of the US Gov. Public Use Permitted.` NASA's
STI terms state that U.S. Government works generally are not copyrighted and
that non-copyrighted documents may be reproduced and distributed. Because the
record is also cataloged as a contractor report, controlled acquisition must
reconcile actual-page notices and any component-level contractor copyright
before admission; a contradiction downgrades it to `RIGHTS_REVIEW_REQUIRED`.
NASA source acknowledgment and non-endorsement rules remain applicable.
[NASA STI copyright and use terms](https://sti.nasa.gov/disclaimers/).

The fallback NASA-CR-161557 record has the same candidate-specific U.S.-
Government-work designation and an indexed scanned as-built sheet with building
sections, dimensions, callouts, notes, and a title block. It is a distinct
building solar-installation document, not a second rendering of the preferred
report. Its exact drafting vendor and family independence require actual-byte
confirmation, so it remains fallback-only.

## Rights gate summary

| Candidate | Disposition | Raw retention | Derived crops | Labels | ML train/eval | Redistribution | Conditions |
|---|---|---|---|---|---|---|---|
| USACE EM 1110-2-2610 | `PUBLIC_DOMAIN` | allowed | allowed | allowed | allowed | allowed | source credit; actual-byte third-party/notice check |
| DLA MIL-DTL-83723/88E fallback | `RIGHTS_REVIEW_REQUIRED` | unknown | unknown | unknown | unknown | unknown | quarantine only; resolve before use |
| USDA RUS 1728F-806 | `PUBLIC_DOMAIN` | allowed | allowed | allowed | allowed | allowed | source credit; exclude referenced private standards; actual-byte check |
| NASA-CR-161594 | `PUBLIC_DOMAIN` | allowed | allowed | allowed | allowed | allowed | NASA credit/non-endorsement; reconcile contractor/page notices |
| NASA-CR-161557 fallback | `PUBLIC_DOMAIN` | allowed | allowed | allowed | allowed | allowed | NASA credit/non-endorsement; reconcile contractor/page notices |

The detailed, separate rights records are in `rights-review.json`. A clear
preferred source exists for every slot, so the rights-uncertain DLA fallback is
not selected. Discovery classifications are acquisition gates, not substitutes
for the V2-A document-level actual-byte provenance and rights recheck.

## Controlled acquisition constraints

The next task may attempt exactly the three preferred documents, one per slot.
It must verify official landing/binary resolution, file identity, MIME/magic,
byte size, SHA-256, page count, actual vector/raster/mixed composition,
duplicates/mirrors, title and organization, actual degradation for SF-V2-08,
and embedded/visible rights notices. It must stop or quarantine a source on any
material contradiction. It must not mine candidates, render review crops,
label cases, or run V1 merely because acquisition succeeds.

Intended roles remain unchanged: SF-V2-01 and SF-V2-03 are `TRAIN_POOL`;
SF-V2-08 is `DEV_COMPARISON`. Difficulty did not alter roles. H1/H2 remain
permanent reference holdouts, C1 is not reused, VALIDATION remains unused, and
LOCKED_BLIND remains `0 / 8`.

## Governance

Reference Baseline V1 was not run or exposed. No H1/H2 prediction, embedding,
margin, score, uncertainty value, or prior model-error ranking influenced
source selection. Production semantic delta is `NONE`; no detector,
reconstruction, ownership, support lifecycle, FinalStructure, CAD, GUI, model
dependency, dataset registry, or knowledge-pack artifact changed.

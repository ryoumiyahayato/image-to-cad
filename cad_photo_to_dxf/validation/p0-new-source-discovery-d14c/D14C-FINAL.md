# P0 new-source discovery and rights gate D14C

## Decision

All three P0 families have a bounded preferred candidate set that passes the source-independence, visual-suitability, and rights gates. **D14C is complete, and the shortlist is ready for a later controlled D14D acquisition.** No source binary was downloaded in this task.

The minimum preferred set is exactly four documents:

- **H1 historical holdout:** two Library of Congress Historic American Engineering Record (HAER) measured-drawing records, four qualified cases later.
- **H2 mechanical holdout:** one NIST fully-toleranced Product and Manufacturing Information (PMI) test drawing, six qualified cases later.
- **C1 civil development-transfer family:** one FHWA Western Federal Lands (WFL) plan/profile sample document, five qualified cases later.

The rights findings authorize only the later controlled DEV acquisition described by D14B. They do not authorize production use, dataset redistribution as a product, use of agency marks to imply endorsement, or acquisition in D14C.

## Method and scope controls

- Base checkpoint: `4cf5784fc4313c3896fda415af75c3e58dcb8d1f`; branch, HEAD, repository root, and clean status matched before research.
- Research was bounded to three serious H1 records, two serious H2 records, and one serious C1 record.
- Only official Library of Congress/National Park Service, NIST, and FHWA pages, catalog metadata, rights statements, and browser-provided previews were inspected.
- No PDF, TIFF, JPEG, CAD, or other candidate binary was saved to the worktree or local dataset.
- No model was run; no prediction, crop, candidate mining, or human labeling was performed.
- Existing registries, VALIDATION, and LOCKED_BLIND were not inspected or changed.

Access date for every web source below: **2026-09-14**.

## Acquisition decision matrix

| Family | Candidate | Organization | Discipline | Style independence | Expected structural value | Expected hard-negative value | Rights status | Rights risk | Disposition |
|---|---|---|---|---|---|---|---|---|---|
| H1 | HAER UT-14, *Denver & Rio Grande Western Railroad, Provo River Bridge* (4 measured drawings) | HAER / NPS; Library of Congress | Historic railroad bridge | Original large-format measured line drawings, later 400-dpi bitonal scans; historical bridge/delineation and title convention | Plan, plan-section, elevation, section, truss/object continuations | Sheet frames, title fields, dimensions, notes, section rules | `PUBLIC_DOMAIN` | LOW, provided D14D selects only original HAER measured drawings | **PREFERRED SET — document 1** |
| H1 | HAER NY-4, *Whipple Cast & Wrought Iron Bowstring Truss Bridge* (5 measured drawings) | HAER / NPS; Library of Congress | Historic highway bridge | Early HAER/Mohawk-Hudson survey, scanned archival line drawings, historic truss/detail notation | General arrangement, truss chords, elevations, connection details | Dimension/extension lines, detail leaders, sheet/title rules | `PUBLIC_DOMAIN` | LOW, provided D14D excludes copied-source photographs/data | **PREFERRED SET — document 2** |
| H1 | HAER NH-6, *Bellows Falls Arch Bridge* (3 measured drawings) | HAER / NPS; Library of Congress | Historic steel arch bridge | Archival measured-drawing scan, early HAER typography and bridge-detail convention | Long arch/chord/elevation and section strokes | Detail leaders, dimensions, title and frame rules | `PUBLIC_DOMAIN` | LOW, same measured-drawing-only condition | **FALLBACK** |
| H2 | NIST FTC 6, `nist_ftc_06_asme1_rd`, Rev D (3 pages/views) | NIST | Mechanical PMI/GD&T | 2014 clean CAD-generated, fully toleranced multi-view part drawing with ASME-style PMI | Dense part edges, sections/silhouettes, close parallel features | Dimension/witness lines, leaders, feature-control frames, datum lines | `PUBLIC_DOMAIN` | LOW | **PREFERRED** |
| H2 | NIST FTC 8, `nist_ftc_08_asme1_rc`, Rev C (4 pages/views) | NIST | Mechanical PMI/GD&T | Independent part geometry with four views and dense restraint/GD&T annotation | Part boundaries and feature edges across four views | Dimension chains, leaders, datum and control-frame rules | `PUBLIC_DOMAIN` | LOW | **FALLBACK** |
| C1 | *WFL Sample Plan Sheets — D Sheets — Plan and Profile Sheets*, revised January 2026 (21 pages; sample sheets D.1–D.12) | USDOT FHWA, Western Federal Lands Highway Division | Modern roadway/civil plan and profile | OpenRoads Designer workflow, WFL/NPS sheet template, Verdana annotation styles, U.S. survey-foot stationing | Road alignments, profile grade/existing ground, pavement/construction limits | Profile grids, stationing, dimensions, tabulation/title rules, panel divisions | `PUBLIC_DOMAIN` | LOW–MODERATE; D14D must confirm the acquired file contains no newly added third-party notice | **PREFERRED** |

Family dispositions:

| Family | Gate result | Preferred document count | Later qualified-case target | Governance |
|---|---|---:|---:|---|
| H1 | `READY_TO_ACQUIRE` | 2 | 4 | `NEW-SOURCE HOLDOUT H1` |
| H2 | `READY_TO_ACQUIRE` | 1 | 6 | `NEW-SOURCE HOLDOUT H2` |
| C1 | `READY_TO_ACQUIRE` | 1 | 5 | Untouched baseline first; DEV adaptation only after durable baseline |

## H1 — historical scanned engineering drawings

### Preferred H1 document 1: HAER UT-14

#### Source-evidence provenance

| Field | Record |
|---|---|
| Proposed `SOURCE_FAMILY_ID` | `D14C-H1-HAER-HISTORICAL-MEASURED-DRAWINGS` |
| Title | *Denver & Rio Grande Western Railroad, Provo River Bridge, Spanning Provo River, Orem Vicinity, Orem, Utah County, UT* |
| Identifier | Survey HAER UT-14; control number `ut0117`; call number `HAER UTAH,25-OLMS,1-` |
| Publisher / organization | Library of Congress Prints and Photographs Division; creator Historic American Engineering Record, National Park Service |
| Drafting vendor | HAER field/delineation team; named contributors in the catalog. No commercial drafting vendor identified. |
| Structure era | Initial construction 1884; moved/modified in 1901 and 1919 |
| Documentation era | Compiled after 1968; exact sheet dates must be read from the acquired measured drawings |
| Landing page | <https://www.loc.gov/item/ut0117/> |
| Drawing resource | <https://www.loc.gov/resource/hhh.ut0117.sheet/?st=gallery> |
| Direct binary URL | `UNKNOWN` until D14D resolves the selected LOC download option; do not substitute photos or data pages |
| Expected type / extent | LOC image/PDF service derivatives; 4 measured drawings (plus 4 photos and 5 data pages, which are out of scope) |
| Likely generation process | Original large-format HAER measured line drawings scanned by the LOC program; LOC documents 400-dpi, 1-bit TIFF capture for these originals |
| Visual suitability | Cataloged sheets include plan, plan section, elevation, and section. They plausibly supply long bridge/truss strokes and line-dominant dimensions, leaders, frames, and title fields. |

Independence from the current six groups is supported by at least four axes: (1) an archival raster pipeline rather than the current clean/recent drawing imagery, (2) late-twentieth-century HAER measured-drawing conventions documenting a nineteenth-century wrought-iron bridge, (3) bridge-truss elevations and details rather than building/electrical/civil-development sheets, and (4) historical lettering, title, and dimension conventions. The raster-generation difference is primary, not merely a subject change.

#### Data-rights provenance

| Field | Record |
|---|---|
| Rights status | `PUBLIC_DOMAIN` |
| Copyright owner | U.S. Government for the original HAER measured drawings; no U.S. copyright |
| Publisher | Library of Congress; originating federal program HAER/NPS |
| Rights statement | LOC says the collection is generally public domain and original HABS/HAER/HALS measured drawings were created for the U.S. Government and are considered public domain. |
| License / rights URL | <https://wwws.loc.gov/rr/print/res/114_habs.html> |
| Public-domain basis | Original federal-program measured drawings; 17 U.S.C. §105 basis. This conclusion does **not** extend to occasional copied-source photos or data pages. |
| Commercial-use implication | Copyright does not restrict U.S. commercial use; no endorsement may be implied. Other non-copyright restrictions remain the user's responsibility. |
| Redistribution | Permitted for the original measured drawings; retain source identification and rights record. |
| Raw-file retention | Permitted. |
| Derived-crop retention | Permitted. |
| Human-label retention | Permitted; labels/metadata are newly created project facts. |
| ML training/evaluation | Not stated specifically; no copyright permission is required for U.S. public-domain measured drawings. D14B governance limits use to DEV evaluation. |
| Attribution | LOC citation is strongly recommended even though not a U.S. copyright condition. |
| D14D condition | Acquire only the measured-drawing assets and recheck item/sheet metadata for a copied-source or third-party notice before admission. |

### Preferred H1 document 2: HAER NY-4

#### Source-evidence provenance

| Field | Record |
|---|---|
| Proposed `SOURCE_FAMILY_ID` | `D14C-H1-HAER-HISTORICAL-MEASURED-DRAWINGS` |
| Title | *Whipple Cast & Wrought Iron Bowstring Truss Bridge, Normans Kill Vicinity, Albany, Albany County, NY* |
| Identifier | Survey HAER NY-4; control number `ny0017`; call number `HAER NY,1-ALB,19-` |
| Publisher / organization | Library of Congress; creator HAER/NPS; prepared as part of the Mohawk-Hudson Area Survey |
| Drafting vendor | HAER delineators David L. Bouse, Eric N. DeLony, and Charles A. Parrott III are identified; no commercial drafting vendor identified |
| Structure era | Initial construction 1867; moved circa 1900 |
| Documentation era | Pilot survey records prepared from 1968 onward; exact sheet dates must be captured in D14D |
| Landing page | <https://www.loc.gov/item/ny0017/> |
| Drawing resource | <https://www.loc.gov/resource/hhh.ny0017.sheet/?st=gallery> |
| Direct binary URL | `UNKNOWN` until D14D resolves the official LOC drawing download option |
| Expected type / extent | Online image/PDF; 5 measured drawings (13 photos and 15 data pages are out of scope) |
| Likely generation process | Early HAER line drawings digitized through the LOC archival-scanning program |
| Visual suitability | Preview metadata identifies detail sheets (including panel-point details) and the record exposes five measured drawings. Expected content combines long truss/object strokes with dense details, leaders, dimensions, and sheet rules. |

This second document is in the same intentionally defined HAER source family but is an independent survey and drawing identity. It differs from current material through the archival scan process and early HAER engineering-delineation convention, and through historic truss general-arrangement/detail sheets with dense mechanical connection notation. It is not another revision, mirror, or sheet from UT-14.

#### Data-rights provenance

The rights disposition is the same as UT-14: `PUBLIC_DOMAIN` for **original HAER measured drawings only**, based on the LOC collection statement above. Copyright does not restrict U.S. commercial use, redistribution, raw retention, crop retention, label retention, or ML evaluation. No ML-specific permission is stated or needed for those public-domain drawings. Credit the Library of Congress and HAER/NPS. D14D must not acquire the cataloged historical photocopy or other copied-source image as a substitute, because the item-level advisory explicitly warns that copied-source material may be restricted.

### H1 fallback: HAER NH-6

| Field | Record |
|---|---|
| Title / identifier | *Bellows Falls Arch Bridge, Spanning Connecticut River, North Walpole, Cheshire County, NH*; HAER NH-6; control `nh0001`; call `HAER NH,3-WALPN,1-` |
| Organization | HAER/NPS; Library of Congress |
| Era / process | 1904–1905 bridge, documentation compiled after 1968; 3 archival measured drawings in the same scanned HAER pipeline |
| Landing / resource | <https://www.loc.gov/item/nh0001/>; <https://www.loc.gov/resource/hhh.nh0001.sheet/?st=gallery> |
| Direct binary URL | `UNKNOWN` until controlled acquisition |
| Suitability | Arch/elevation and detail geometry, historical title/dimension/leader rules; enough breadth to replace one failed preferred H1 document, not to enlarge the four-document plan |
| Rights | `PUBLIC_DOMAIN` under the same measured-drawing-only LOC basis; LOW risk with the same D14D notice check |

### H1 suitability conclusion

The preferred pair plausibly yields the planned two structural and two annotation/glyph cases without selecting by model behavior. It supplies true scanned-source variation: LOC states that 55,000 original measured drawings were scanned in 2000–2001 on an Océ 9800 at 400 dpi, one bit per pixel, with browser/print derivatives. This guarantees raster/bitonal reproduction characteristics; it does not guarantee severe staining or broken strokes on every sheet. D14D should record actual scan degradation after acquisition but must not reject clean sheets based on MobileNet output.

H1 result: **`READY_TO_ACQUIRE`**.

## H2 — dense vector mechanical fabrication/assembly drawing

### Preferred H2 document: NIST FTC 6

#### Source-evidence provenance

| Field | Record |
|---|---|
| Proposed `SOURCE_FAMILY_ID` | `D14C-H2-NIST-PMI-FTC` |
| Title | *NIST PMI Test Model — Fully-Toleranced Test Case 6* |
| Identifier / revision | `nist_ftc_06_asme1_rd`; Rev D; FTC 6 |
| Publisher / organization | National Institute of Standards and Technology |
| Drafting vendor | NIST test-system drawing; no external vendor identified on the drawing or project page |
| Date | 2014 drawing; project page created 2013 and updated 2025 |
| Landing page | <https://pages.nist.gov/CAD-PMI-Testing/models.html> |
| Project page | <https://www.nist.gov/ctl/smart-connected-systems-division/smart-connected-manufacturing-systems-group/mbe-pmi-validation> |
| Direct document | <https://www.nist.gov/document/nist-cad-model-ftc-06> |
| Expected type / extent | PDF, 3 pages: Views A, B, and C |
| Likely generation process | Clean CAD-authored 2D views of an annotated 3D mechanical model; NIST's project created the test cases and corresponding CAD models |
| Visual suitability | The preview and text expose fully toleranced views, datum references, feature-control frames, dimensions, notes, and rotated views. It is deliberately annotation-dense while retaining substantial part-edge structure. |

The family differs from the current six groups by (1) clean CAD-generated mechanical part views with dense colored/graphical PMI instead of building/electrical/civil sheet imagery, (2) ASME Y14.5/Y14.41 GD&T, datum, and feature-control-frame conventions, (3) close parallel object features and manufacturing line hierarchy, and (4) a NIST conformance-test layout rather than a construction-project title/layout system. Both drafting convention and generation process are independently different.

#### Data-rights provenance

| Field | Record |
|---|---|
| Rights status | `PUBLIC_DOMAIN` |
| Copyright owner | U.S. Government / NIST employee-authored test-system work; no U.S. copyright |
| Publisher | NIST |
| Rights statement | NIST states that works authored by its employees are not copyright-protected in the United States and grants a perpetual, paid-up, royalty-free worldwide right to reprint and make derivative works where NIST may assert foreign rights. |
| License / rights URL | <https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications> |
| Public-domain basis | NIST states it created the test system and test cases; the drawing is branded as a NIST PMI Test Model and identifies no third-party author or copyright notice. |
| Commercial-use implication | Permitted by the public-domain/royalty-free grant; no NIST endorsement may be implied. |
| Redistribution | Permitted; preserve NIST source credit and any notices. |
| Raw-file retention | Permitted. |
| Derived-crop retention | Permitted as a derivative/reprint use. |
| Human-label retention | Permitted. |
| ML training/evaluation | No ML-specific statement; public-domain status and the derivative-use grant remove the relevant copyright restriction. D14B still limits initial use to held-out DEV evaluation. |
| Attribution | Cite NIST; NIST recommends a courtesy credit and full source citation. |
| D14D condition | Recheck the acquired three pages for third-party copyright/embedded assets. Mere references to ASME standards do not license or add ASME standard text. |

### H2 fallback: NIST FTC 8

| Field | Record |
|---|---|
| Title / identifier | *NIST PMI Test Model — Fully-Toleranced Test Case 8*; `nist_ftc_08_asme1_rc`; Rev C |
| Organization / date | NIST; 2014 |
| Landing / direct document | <https://pages.nist.gov/CAD-PMI-Testing/models.html>; <https://www.nist.gov/document/nist-cad-model-ftc-08> |
| Expected type / extent | PDF, 4 pages: Views A–D |
| Suitability | Fully toleranced independent geometry with dense dimensions, datum simulators, restraints, leaders, and feature-control frames |
| Rights | `PUBLIC_DOMAIN`; LOW risk under the same NIST basis |

FTC 8 is a fallback, not a second acquisition. It may replace FTC 6 only if FTC 6 fails binary integrity or yields too little independent crop opportunity before predictions are exposed.

### H2 suitability conclusion

The preferred three-view document should naturally support roughly three structural and three hard-negative cases. Independent cases must come from distinct part-edge/annotation structures; repeated portions of the same dimension or view do not count twice.

H2 result: **`READY_TO_ACQUIRE`**.

## C1 — independent modern civil/site/profile family

### Preferred C1 document: FHWA WFL plan/profile samples

#### Source-evidence provenance

| Field | Record |
|---|---|
| Proposed `SOURCE_FAMILY_ID` | `D14C-C1-FHWA-WFL-ORD-PLAN-PROFILE` |
| Title | *WFL Sample Plan Sheets — D Sheets — Plan and Profile Sheets* |
| Identifier / revision | Sample WFL D Sheets; revised January 2026; landing filename `wfl-samples-plan-profile.pdf` |
| Publisher / organization | U.S. Department of Transportation, Federal Highway Administration, Western Federal Lands Highway Division |
| Drafting vendor | WFL internal sample/template; no contractor, consultant, or third-party drawing author is identified in the page or PDF text |
| Date / era | Revised 28 January 2026; example project/sheet timestamps 2025–2026 |
| Landing page | <https://highways.dot.gov/federal-lands/design/plan-prep/wfl/samples/plan-profile-sheets> |
| Direct document | <https://highways.dot.gov/federal-lands/design/plan-prep/wfl/samples/plan-profile.pdf> |
| Expected type / extent | PDF, 21 pages; guidance plus sample D.1–D.12 sheets |
| Likely generation process | OpenRoads Designer/MicroStation DGN sheet models and linked spreadsheet tables, published to PDF; the file text exposes internal WFL paths/templates and ORD instructions |
| Visual suitability | D.5 onward includes plan/profile sheets with roadway alignment, profile grade, existing ground, pavement and construction limits, stationing, curves, culverts, grids, dimensions, notes, panel/title rules, and tabulations. |

The WFL family is unrelated to the current weak `G0R2-C2D095E069663C17` development-transfer family on the evidence available: no shared organization, vendor, identifier, or template appears. Meaningful differences include (1) a documented 2025–2026 OpenRoads Designer/DGN-to-PDF workflow with named WFL annotation templates and Verdana styles, (2) FHWA/NPS U.S.-survey-foot roadway stationing and WFL plan-profile sheet order, and (3) a vertically paired road plan/profile with federal-land title conventions rather than the current `C2D0` multi-panel civil/trench/layout style described in D11–D14A. This is a generation/drafting difference, not merely another civil subject.

#### Data-rights provenance

| Field | Record |
|---|---|
| Rights status | `PUBLIC_DOMAIN` |
| Copyright owner | U.S. Government / FHWA for this WFL internal sample work; no U.S. copyright |
| Publisher | FHWA Western Federal Lands Highway Division |
| Rights statements | FHWA says information on its site is public information and may be distributed or copied. FHWA's copyright guide states that drawings created by FHWA employees in their official work are public domain, while warning that contractor material is not automatically public domain. |
| Rights URLs | <https://www.fhwa.dot.gov/disclaim.cfm>; <https://www.fhwa.dot.gov/publications/research/general/15058/024.cfm> |
| Public-domain basis | The official document identifies itself throughout as WFL Sample Plan Sheets, includes WFL-internal instructions and work paths, and exposes no contractor/consultant/copyright marker in the inspected 21-page text. On that evidence it is an agency work, not merely a third-party file hosted by government. |
| Commercial-use implication | U.S. copyright does not restrict use; agency names/logos cannot imply endorsement, and foreign copyright may apply. |
| Redistribution | The site expressly permits copying/distribution; preserve the source and disclaimer. |
| Raw-file retention | Permitted as copying. |
| Derived-crop retention | Permitted for this federal work; do not include any third-party element if a later notice check identifies one. |
| Human-label retention | Permitted. |
| ML training/evaluation | No ML-specific statement; no U.S. copyright permission is needed for the federal work. C1 is limited to untouched DEV baseline evaluation until durably recorded. |
| Attribution | Credit USDOT FHWA/WFL and link the landing page; avoid endorsement language. |
| D14D condition | After controlled acquisition, inspect all file notices/credits before hashing it into the usable registry. Any contractor or third-party claim changes status to `RIGHTS_REVIEW_REQUIRED` and blocks admission. |

This disposition explicitly does not rely on “government-hosted means public domain.” It relies on affirmative internal-authoring evidence in the document plus the FHWA federal-work rule. The residual risk is higher than H1/H2 because no named individual author appears, so D14D must fail closed if the downloaded bytes add contrary metadata or notices.

### C1 suitability conclusion

The single document contains multiple genuinely different sample sheet regions and naturally supports the planned two structural and three hard-negative cases. Case independence must exclude repeated title blocks and adjacent portions of one profile grid. Page selection and labeling must remain prediction-blind.

C1 result: **`READY_TO_ACQUIRE`**.

## Family-independence gate summary

| Gate | H1 HAER | H2 NIST FTC | C1 FHWA WFL |
|---|---|---|---|
| Different publisher/organization from current six | Yes: HAER/NPS/LOC | Yes: NIST | Yes: FHWA WFL; no current-family match found |
| Different discipline/template | Historic bridge measured records | Mechanical PMI/GD&T | Federal roadway plan/profile |
| Generation/drafting difference | 400-dpi bitonal archival scan of large-format drawings | Clean CAD 2D views derived from annotated 3D models | ORD/DGN and linked-table digital plan workflow |
| Additional independent difference | Historical lettering/title/detail convention | ASME dimension/datum/FCF convention | WFL typography, stationing, grids, sheet order |
| Mirror/revision/duplicate risk | Preferred records are distinct surveys; sheets within each stay one source family | FTC 8 is fallback only, not extra family | One official landing/direct pair, not two documents |
| Gate | PASS | PASS | PASS |

## Rights gate summary

| Family | Basis | Raw retention | Derived crops | Human labels | ML evaluation | Redistribution | Attribution | Gate |
|---|---|---|---|---|---|---|---|---|
| H1 | Original HAER measured drawings considered public domain by LOC | Yes | Yes | Yes | No ML-specific statement; permitted as PD | Yes | Recommended | PASS |
| H2 | NIST U.S. public domain plus worldwide royalty-free derivative grant | Yes | Yes | Yes | No ML-specific statement; permitted under PD/grant | Yes | Recommended by NIST | PASS |
| C1 | Evidence-backed FHWA employee work; federal-work rule; site copying/distribution permission | Yes | Yes, subject to notice check | Yes | No ML-specific statement; permitted for federal work | Yes | Credit and no endorsement | PASS with mandatory D14D notice check |

No rights conclusion applies to trademarks, privacy/personality rights, patent rights, export controls, or an implied government endorsement. Those issues are not expected to govern the selected technical line drawings, but D14D must retain the official disclaimers and attribution evidence.

## D14D controlled-acquisition gate

D14D may acquire **only** these four preferred documents. It must not download the fallbacks unless a preferred document fails before model predictions or human labels are exposed.

1. Resolve the official direct asset from the recorded landing page; reject mirrors.
2. Save original response URL, timestamp, MIME type, filename, byte length, and SHA-256.
3. Verify document/sheet identifiers and exact page counts against this report.
4. Inspect embedded/file-visible author, copyright, license, and third-party notices. A conflicting notice quarantines the file and changes its disposition to `RIGHTS_REVIEW_REQUIRED`.
5. For H1, acquire measured drawings only—never copied-source photographs or data pages.
6. Freeze page selection and candidate identities without MobileNet predictions. Human labeling remains prediction-blind.
7. H1 and H2 remain untouched new-source holdouts: no sample may affect representation, fitting, centroids, calibration, thresholds, preprocessing, or layer selection.
8. C1 receives an untouched baseline before any later DEV adaptation.
9. Do not allocate any new material to VALIDATION or LOCKED_BLIND.

If any preferred family fails its D14D identity/rights check, stop that family. The listed fallback may replace the failed candidate only within the same family and document budget; no P1/P2 substitution is authorized automatically.

## Final status

- P0 new-source discovery D14C: **COMPLETE**
- Production semantic delta: **NONE**
- H1 historical: **READY_TO_ACQUIRE** — preferred two-document HAER UT-14 + HAER NY-4 set; `PUBLIC_DOMAIN`
- H2 mechanical: **READY_TO_ACQUIRE** — preferred NIST FTC 6; `PUBLIC_DOMAIN`
- C1 civil: **READY_TO_ACQUIRE** — preferred FHWA WFL Plan and Profile Sheets; `PUBLIC_DOMAIN`
- Total preferred documents: **4**
- New-source holdouts: **H1, H2**
- All three P0 families ready: **YES**
- Ready for later D14D controlled acquisition: **YES**
- PDF binaries downloaded: **0**
- Model run: **NO**
- Human labeling: **NO**
- New PDF acquisition performed: **NO**
- Ready for production integration: **NO**
- Next production change candidate: **NONE**
- VALIDATION: **NO**
- LOCKED_BLIND: **0 / 8**

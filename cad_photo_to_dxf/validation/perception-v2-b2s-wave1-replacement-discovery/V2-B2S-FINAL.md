# PERCEPTION-V2-B2S — Wave-1 Replacement Discovery

## Outcome

Both blocked Wave-1 slots have model-independent replacements that pass suitability, source-family independence, rights, and current-environment accessibility screening. No source binary was downloaded.

| Slot | Preferred replacement | Rights | Access | Planned docs | Result |
|---|---|---|---|---:|---|
| SF-V2-01 | FAA AC 43.13-1B, *Aircraft Inspection and Repair* | `PUBLIC_DOMAIN` | `PASS` | 1 | `REPLACEMENT_READY_TO_ACQUIRE` |
| SF-V2-03 | FAA AC 150/5340-30J, *Design and Installation Details for Airport Visual Aids* | `PUBLIC_DOMAIN` | `PASS` | 1 | `REPLACEMENT_READY_TO_ACQUIRE` |

The next task is controlled acquisition of these two approved documents. This discovery does not admit either family and does not make Wave-1 ready for B3.

## SF-V2-01 decision

Preferred family: `V2-FAA-AIRCRAFT-STRUCTURAL-REPAIR-1998`.

FAA AC 43.13-1B is a real aircraft fabrication/repair source rather than a simplified educational schematic. Official indexed Figure 4-16 alone exposes dense repair-patch and stiffener boundaries, rivet arrays/circles, cutouts, inch dimensions, angles, feature letters, leaders, notes, and a dimension table. The broader active AC covers sheet-metal fabrication, structural repairs, fasteners, assemblies, and systems. Its FAA chapter/figure publishing system, riveted-airframe drafting idiom, legacy illustration process, and dimension convention are materially independent from H2 NIST FTC PMI.

The FAA landing page and direct PDF returned HTTP 200; the PDF endpoint reported `application/pdf` and 21,101,662 bytes. The National Transportation Library provides a second official landing/direct path, also HTTP 200, and explicitly records FAA as corporate creator and the work as `Public Domain`. DOT policy states DOT-produced information is free from U.S. copyright under 17 U.S.C. 105. Controlled acquisition must still inspect actual notices and exclude protected agency marks or specifically credited third-party material before admission.

No fallback is approved for SF-V2-01. Three alternatives were rejected:

- Bureau of Reclamation Design Standards No. 6 chapters 6 and 12 were substantively suitable but failed accessibility: current-environment HEAD requests reset and one-byte range requests returned HTML `Request Rejected` responses.
- NASA-STD-5020B had too few dense production-style drawings and its exposed revalidated PDF endpoint returned HTTP 403.
- DLA MIL-DTL-83723/88E had strong drawing density, but Quick Search failed current-environment DNS/access and public-release status did not resolve possible contractor technical-data ownership.

## SF-V2-03 decision

Preferred family: `V2-FAA-AIRPORT-VISUAL-AID-INSTALLATION-2018`.

FAA AC 150/5340-30J contains real airfield electrical installation details: cable and conduit paths, fixtures, junction boxes, transformers, supports, pavement/foundation sections, dimensions, leaders, detail labels, and dense notes. Its Airport Engineering template, multi-detail appendix figures, paired U.S./metric annotations, and FAA layout conventions are materially different from the rejected USDA/RUS construction-unit family and from existing project electrical material.

The official landing page and direct PDF returned HTTP 200; the PDF endpoint reported `application/pdf` and 12,484,227 bytes with no authentication. Federal corporate authorship is established by the FAA record and DOT policy supplies the public-domain basis. Actual-byte acquisition must exclude any specifically credited third-party figures or marks before admission.

Fallback family: `V2-DOD-ICT-INFRASTRUCTURE-STANDARD-DRAWINGS-2024`, UFC 3-580-01 (2024). The official WBDG landing page and redirected main PDF returned HTTP 200; the PDF reported `application/pdf`, 10,980,206 bytes, and 192 pages. Its Appendix A drawings provide cable/pathway, rack/cabinet, equipment-boundary, legend, revision-table, border, and title-block evidence. The official DoD/WBDG memorandum identifies WBDG as the distribution service for DoD public-domain facility criteria. Do not acquire the fallback unless the FAA preferred document fails controlled admission.

Bureau of Reclamation DS-4(3)-13 was rejected: indexed content is predominantly narrative/standards references rather than installation layouts, and current-environment range access returned `Request Rejected` HTML.

## Evidence and governance

Seven serious families were reviewed: four for SF-V2-01 and three for SF-V2-03, within the search budget. Detailed evidence, independence axes, generation/style fields, access results, and document plans are in `replacement-candidates.json`; rights permissions, exclusions, and dispositions are in `replacement-rights-review.json`.

Primary evidence:

- FAA AC 43.13-1B official record: <https://www.faa.gov/regulations_policies/advisory_circulars/index.cfm/go/document.information/documentid/99861>
- NTL AC 43.13-1B public-domain record: <https://rosap.ntl.bts.gov/view/dot/71377>
- FAA AC 150/5340-30J official record: <https://www.faa.gov/airports/resources/advisory_circulars/index.cfm/go/document.current/documentnumber/150_5340-30>
- DOT Data Management Policy: <https://www.transportation.gov/sites/dot.gov/files/docs/mission/128511/policy-data-management-s10-160926-001-d5-071317.pdf>
- UFC 3-580-01 official record: <https://legacy.wbdg.org/dod/ufc/ufc-3-580-01>
- DoD/WBDG public-domain facility-criteria memorandum: <https://www.wbdg.org/FFC/DOD/wbdg_moa.pdf>
- 17 U.S.C. 105: <https://usc-cdn.house.gov/view.xhtml?edition=prelim&num=0&req=granuleid%3AUSC-prelim-title17-section105>

SF-V2-08 remains `ACQUIRED_AND_ADMITTED` as NASA-CR-161594 with recorded SHA-256 `C79593F34938052BEB5E90349F32A2A577ED1EAA66CAA99BA4CBB128E94842B6`. It was not inspected, downloaded, rerendered, mined, or relabeled.

No source binary, TIFF, image, ZIP, CAD archive, crop, or render was acquired. No MobileNet, embedding, cosine score, active-learning logic, Reference Baseline V1, mining, labeling, validation, or locked-blind inspection ran. H1/H2 were not read or touched. V2-A and all production/CAD/GUI code remain unchanged. `PRODUCTION_SEMANTIC_DELTA: NONE`.

## Frozen task status

PERCEPTION_V2_B2S:
COMPLETE

BASE CHECKPOINT:
79bde883313212d21f13b067916d5fee551a26c9

DIAGNOSTIC CHECKPOINT:
RECORDED_IN_TASK_HANDOFF

PRODUCTION_SEMANTIC_DELTA:
NONE

SF-V2-01 ORIGINAL SOURCE:
USACE EM 1110-2-2610

SF-V2-01 ORIGINAL DISPOSITION:
OFFICIAL_SOURCE_ACCESS_BLOCKED

SF-V2-01 REPLACEMENT:
REPLACEMENT_READY_TO_ACQUIRE

SF-V2-01 PREFERRED REPLACEMENT:
U.S. Department of Transportation, Federal Aviation Administration — FAA AC 43.13-1B, Acceptable Methods, Techniques, and Practices - Aircraft Inspection and Repair

SF-V2-01 RIGHTS:
PUBLIC_DOMAIN

SF-V2-01 ACCESSIBILITY:
PASS

SF-V2-01 PLANNED DOCUMENTS:
1

SF-V2-03 ORIGINAL SOURCE:
USDA RUS Bulletin 1728F-806

SF-V2-03 ORIGINAL DISPOSITION:
RIGHTS_REVIEW_REQUIRED

SF-V2-03 REPLACEMENT:
REPLACEMENT_READY_TO_ACQUIRE

SF-V2-03 PREFERRED REPLACEMENT:
U.S. Department of Transportation, Federal Aviation Administration — FAA AC 150/5340-30J, Design and Installation Details for Airport Visual Aids

SF-V2-03 RIGHTS:
PUBLIC_DOMAIN

SF-V2-03 ACCESSIBILITY:
PASS

SF-V2-03 PLANNED DOCUMENTS:
1

SF-V2-08:
ACQUIRED_AND_ADMITTED

WAVE-1 ADMITTED FAMILIES CURRENT:
1/3

WAVE-1 REPLACEMENTS READY FOR ACQUISITION:
2/2

NEW SOURCE BINARIES DOWNLOADED:
0

REFERENCE BASELINE V1 RUN:
NO

MODEL RUN:
NO

HUMAN LABELING:
NO

H1/H2 HOLDOUT CONTAMINATION:
NO

READY FOR REPLACEMENT ACQUISITION:
YES

READY FOR PERCEPTION-V2-B3:
NO

READY FOR MODEL BAKE-OFF:
NO

READY FOR PRODUCTION INTEGRATION:
NO

VALIDATION:
NO

LOCKED_BLIND:
0 / 8

GIT STATUS:
clean

STOP.

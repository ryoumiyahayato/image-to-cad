# PERCEPTION-V2-B2R - Wave-1 Acquisition Remediation

## Outcome

Remediation is **BLOCKED**. Neither unresolved Wave-1 family could be admitted without lowering the frozen V2-A acquisition or rights standard. SF-V2-01 remains `DOWNLOAD_FAILED` because the exact official USACE binary is still inaccessible from this environment. SF-V2-03 remains `ACQUIRED_RIGHTS_BLOCKED` because its non-federal PDF authorship signal is not resolved by the bulletin, the incorporating rule, or official USDA copyright guidance. SF-V2-08 was preserved unchanged as frozen admitted data.

`READY FOR PERCEPTION-V2-B3: NO`

## Required B2 findings, preserved exactly

The source records reviewed before any network access were:

- `../perception-v2-b2-wave1-acquisition/V2-B2-FINAL.md`
- `../perception-v2-b2-wave1-acquisition/acquisition-registry.json`
- `../perception-v2-b2-wave1-acquisition/rights-registry.json`

### SF-V2-01 original `DOWNLOAD_FAILED` reason

The official host did not resolve normally in the shell environment. DNS-over-HTTPS identified the official host's delivery address, but a host-pinned request returned HTTP 403. Windows BITS transferred zero bytes and entered `TransientError` because it could not establish a server connection. A visible browser request to the same official URL returned `ERR_CONNECTION_CLOSED`. No file was created.

### SF-V2-03 original `RIGHTS_REVIEW_REQUIRED` trigger

The actual PDF XMP/document metadata identifies `Author: Emgarten, Bob` and `Company: Iowa Lakes Electric Cooperative`. That non-federal authorship signal is material because the intended dataset value is the drawing set. The B2 review found no evidence resolving whether those drawings were prepared by federal employees, assigned to the United States, licensed for the planned uses, or merely edited using a non-federal source file.

## SF-V2-01 - exact USACE manual

Target identity remained exactly:

- Document: EM 1110-2-2610
- Title: *Mechanical and Electrical Design for Civil Works Structures*
- Organization: Department of the Army / U.S. Army Corps of Engineers
- Publication date: 18 March 2025, official catalog evidence only
- Official catalog: <https://www.publications.usace.army.mil/USACE-Publications/Engineer-Manuals/>
- Exact official binary endpoint: <https://www.publications.usace.army.mil/Portals/76/Publications/EngineerManuals/EM%201110-2-2610_FINAL_18Mar2025.pdf>

The B2R shell retry used the exact recorded endpoint with redirect handling, retries, a browser-like user agent, and an absolute output path under the authorized ignored SF-V2-01 directory. It again failed at DNS resolution with `curl: (6) Could not resolve host: www.publications.usace.army.mil`; no PDF bytes were created. An in-app browser registered the same exact official URL, but PDF tab creation/binding timed out and yielded no local bytes. Official-only searches found the exact 2025 PDF only at the same USACE endpoint. The separately indexed older EM 1110-2-2610 is a superseded different revision and was not acquired or substituted.

The official catalog and indexed PDF text establish that the endpoint is the correct manual and that it states `Approved for public release; distribution is unlimited`. They do not provide actual bytes for the task-required MIME, byte size, SHA-256, page count, embedded metadata, visible-rights, or third-party-content checks. Therefore the family remains `DOWNLOAD_FAILED`, not `ACQUIRED_IDENTITY_BLOCKED` or admitted.

Rights remain `RIGHTS_REVIEW_REQUIRED` because actual-byte review could not occur. The public-release distribution statement is not promoted into a dataset-use disposition without inspection for contractor authorship, vendor material, standards excerpts, third-party figures, or reproduction restrictions.

Next action for SF-V2-01: `OFFICIAL_SOURCE_ACCESS_BLOCKED`. No replacement search was started.

## SF-V2-03 - RUS Bulletin 1728F-806

The existing official binary was not redownloaded and was not rehashed. Presence and the recorded byte size of 5,715,171 bytes were confirmed; Poppler/PDF metadata again reported 145 pages, PDF 1.6, and no encryption. The authoritative B2 SHA-256 remains `44B327A579BC5CCE7CB5F1CC11DAB7C300ABB2D15D39543A4CED822BF1085E15`.

The narrow B2R rights recheck found:

- XMP `dc:creator`: `Emgarten, Bob`.
- XMP `pdfx:Company`: `Iowa Lakes Electric Cooperative`.
- Creator/producer: Acrobat PDFMaker 15 for Word / Adobe PDF Library 15.0.
- The cover identifies USDA Rural Utilities Service, the exact bulletin and title, an effective date of 11 October 2018, an Electric Staff Division office of primary interest, and approval/incorporation by reference.
- Full searchable-text rights/authorship keyword review found no copyright, proprietary, permission, ownership-transfer, federal-employee authorship, or page-level third-party attribution statement. The non-federal names occur in metadata, not in the visible document text.
- The last page contains attachment/index explanatory text and no rights notice.

Official evidence narrows but does not cure the issue. The 6 November 2018 Federal Register rule says RUS maintains these bulletins as construction standards, describes revisions to many drawings, incorporates this bulletin into 7 CFR Part 1728, and identifies a USDA/RUS electrical engineer as the contact. It does not say who prepared the drawings, that Bob Emgarten acted as a federal employee, that Iowa Lakes transferred copyright, or that the public receives commercial, derivative, ML-training, or redistribution rights.

USDA Departmental Regulation 1410-001 and USDA copyright guidance confirm that material prepared by USDA employees as part of official duties is a U.S. Government work, while private-sector individuals and organizations may hold copyright in contracted or otherwise non-federal material. Title 17 defines a U.S. Government work by federal officer/employee authorship, not by agency publication or incorporation by reference. Consequently, the federal publisher and regulatory status cannot safely override the actual-byte non-federal authorship signal.

No `USABLE_PAGE_ALLOWLIST` is defensible. The metadata applies at document level, the bulletin contains no page-level authorship or ownership distinctions, and the drawing set is precisely the material intended for later use. Guessing that selected drawings are federal-authored would violate the frozen V2-A protocol. All construction-drawing pages therefore remain quarantined; raw retention is for rights review only, and crops, labels, ML training/evaluation, and redistribution remain disallowed.

Final disposition: `RIGHTS_REVIEW_REQUIRED`.

Next action for SF-V2-03: `RIGHTS_SPECIALIST_REVIEW_REQUIRED`. No substitute-family search was started.

## Evidence URLs

- USACE official catalog: <https://www.publications.usace.army.mil/USACE-Publications/Engineer-Manuals/>
- USACE exact official PDF endpoint: <https://www.publications.usace.army.mil/Portals/76/Publications/EngineerManuals/EM%201110-2-2610_FINAL_18Mar2025.pdf>
- USDA official bulletin landing page: <https://www.usda.gov/guidance-documents/electric/rus/specifications-and-drawings-underground-electric-distribution>
- USDA official binary endpoint recorded in B2: <https://www.rd.usda.gov/media/file/download/uep-bulletin-1728f-806.pdf>
- Federal Register rule, 83 FR 55465: <https://www.federalregister.gov/documents/2018/11/06/2018-24248/specifications-and-drawings-for-underground-electric-distribution>
- USDA Departmental Regulation 1410-001: <https://www.usda.gov/sites/default/files/documents/dr-1410-001.pdf>
- U.S. Copyright Office, Title 17 Chapter 1: <https://www.copyright.gov/title17/92chap1.html>
- Office of the Law Revision Counsel, 17 U.S.C. 105: <https://uscode.house.gov/view.xhtml?edition=prelim&num=0&req=granuleid%3AUSC-prelim-title17-section105>

## Governance and readiness

- SF-V2-08 remains `ACQUIRED_AND_ADMITTED`, hash `C79593F34938052BEB5E90349F32A2A577ED1EAA66CAA99BA4CBB128E94842B6`, with no redownload, rehash, rerender, candidate inspection, model use, or rights change.
- No model, embedding, Reference Baseline V1, Hough/LSD, candidate mining, page selection, crop generation, overlay generation, or labeling operation ran.
- H1/H2 were not read or touched.
- No production, CAD, GUI, `SourceSupportLifecycle`, or `FinalStructure` code changed.
- `PRODUCTION_SEMANTIC_DELTA: NONE`.
- `VALIDATION: NO`.
- `LOCKED_BLIND: 0 / 8`; no locked-blind manual inspection occurred.
- Wave-1 admitted families: `1/3`.
- Source-evidence provenance: `INCOMPLETE` because SF-V2-01 has no actual bytes.
- Data-rights provenance: `INCOMPLETE` because SF-V2-01 lacks byte review and SF-V2-03 ownership remains unresolved.
- `READY FOR PERCEPTION-V2-B3: NO`.
- `READY FOR MODEL BAKE-OFF: NO`.
- `READY FOR PRODUCTION INTEGRATION: NO`.

The machine-readable outcome deltas are in `remediation-registry.json` and `updated-rights-review.json`. Unchanged B2 provenance remains authoritative through the references above; it is not duplicated here.

## Frozen task status

PERCEPTION_V2_B2R:
BLOCKED

BASE CHECKPOINT:
d4787127a5fc96512e704b8a185494789977e647

DIAGNOSTIC CHECKPOINT:
RECORDED_IN_TASK_HANDOFF

PRODUCTION_SEMANTIC_DELTA:
NONE

SF-V2-01 ORIGINAL FAILURE:
Official host DNS resolution failed in the shell environment; DNS-over-HTTPS identified the host delivery address but a pinned request returned HTTP 403; BITS transferred zero bytes and entered TransientError because it could not establish a server connection; the visible browser returned ERR_CONNECTION_CLOSED.

SF-V2-01:
DOWNLOAD_FAILED

SF-V2-01 DOCUMENT:
EM 1110-2-2610 - Mechanical and Electrical Design for Civil Works Structures

SF-V2-01 OFFICIAL SOURCE:
https://www.publications.usace.army.mil/Portals/76/Publications/EngineerManuals/EM%201110-2-2610_FINAL_18Mar2025.pdf

SF-V2-01 SHA256:
N/A

SF-V2-01 SIZE:
N/A

SF-V2-01 PAGES:
N/A

SF-V2-01 RIGHTS:
RIGHTS_REVIEW_REQUIRED

SF-V2-03 ORIGINAL RIGHTS BLOCK:
Actual PDF metadata states Author: Emgarten, Bob and Company: Iowa Lakes Electric Cooperative; this non-federal authorship signal leaves ownership of the drawing set unresolved.

SF-V2-03:
ACQUIRED_RIGHTS_BLOCKED

SF-V2-03 SHA256:
44B327A579BC5CCE7CB5F1CC11DAB7C300ABB2D15D39543A4CED822BF1085E15

SF-V2-03 RIGHTS:
RIGHTS_REVIEW_REQUIRED

SF-V2-03 USABLE PAGE ALLOWLIST:
NO

SF-V2-03 EXCLUDED THIRD-PARTY MATERIAL:
All construction-drawing pages remain quarantined; no page-level ownership distinction is supported.

SF-V2-08:
ACQUIRED_AND_ADMITTED

WAVE-1 ADMITTED FAMILIES:
1/3

SOURCE EVIDENCE PROVENANCE:
INCOMPLETE

DATA RIGHTS PROVENANCE:
INCOMPLETE

MODEL RUN:
NO

CANDIDATE MINING:
NO

HUMAN LABELING:
NO

REFERENCE BASELINE V1 RUN:
NO

H1/H2 HOLDOUT CONTAMINATION:
NO

READY FOR PERCEPTION-V2-B3:
NO

IF NOT READY, NEXT REQUIRED ACTION:
OFFICIAL_SOURCE_ACCESS_BLOCKED; RIGHTS_SPECIALIST_REVIEW_REQUIRED

READY FOR MODEL BAKE-OFF:
NO

READY FOR PRODUCTION INTEGRATION:
NO

VALIDATION:
NO

LOCKED_BLIND:
0 / 8

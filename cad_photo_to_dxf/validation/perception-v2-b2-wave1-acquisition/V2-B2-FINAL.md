# PERCEPTION-V2-B2 — Wave-1 Controlled Source Acquisition

## Outcome

Wave 1 is **PARTIAL**. Two of the three approved source documents were acquired from their approved official infrastructure. NASA-CR-161594 passed identity, integrity, scan-character, and mandatory actual-byte rights review and is admitted. USDA RUS Bulletin 1728F-806 passed identity and integrity checks but is quarantined because its PDF metadata identifies a non-federal author and company whose rights in the drawing set are unresolved. The approved USACE binary could not be downloaded from the official USACE infrastructure and no substitute was attempted.

`READY FOR PERCEPTION-V2-B3: NO`

## Acquisition matrix

| Slot | Approved document | Official source result | SHA-256 | Pages | Actual-byte rights result | Admission status |
|---|---|---|---|---:|---|---|
| SF-V2-01 | USACE EM 1110-2-2610, *Mechanical and Electrical Design for Civil Works Structures* | Download failed; actual bytes unavailable | N/A | N/A | Not completed; `RIGHTS_REVIEW_REQUIRED` | `DOWNLOAD_FAILED` |
| SF-V2-03 | USDA RUS Bulletin 1728F-806, *Specifications and Drawings for Underground Electric Distribution* | Acquired, 5,715,171 bytes | `44B327A579BC5CCE7CB5F1CC11DAB7C300ABB2D15D39543A4CED822BF1085E15` | 145 | Non-federal PDF author/company signal requires ownership review | `ACQUIRED_RIGHTS_BLOCKED` |
| SF-V2-08 | NASA-CR-161594 / GDC-ASP-80-010, *Low Thrust Vehicle Concept Study, Final Report* | Acquired, 16,833,302 bytes | `C79593F34938052BEB5E90349F32A2A577ED1EAA66CAA99BA4CBB128E94842B6` | 292 | `PUBLIC_DOMAIN_CONFIRMED`; no contrary byte-level notice found | `ACQUIRED_AND_ADMITTED` |

## SF-V2-01 — USACE

The approved URL was used unchanged:

- Landing page: <https://www.publications.usace.army.mil/USACE-Publications/Engineer-Manuals/>
- Approved binary: <https://www.publications.usace.army.mil/Portals/76/Publications/EngineerManuals/EM%201110-2-2610_FINAL_18Mar2025.pdf>

The shell environment could not resolve the official host normally. DNS-over-HTTPS identified the official host's delivery address, but a host-pinned request returned HTTP 403. Windows BITS transferred zero bytes and entered `TransientError` because it could not establish a server connection. A visible browser request to the same official URL returned `ERR_CONNECTION_CLOSED`. No file was created, no mirror was used, and no other USACE document was substituted.

Official catalog metadata still identifies EM 1110-2-2610 dated 18 March 2025, but the task-required exact binary identity, page count, integrity, and embedded rights checks could not be performed. This is therefore `DOWNLOAD_FAILED`, not an identity or suitability substitution.

## SF-V2-03 — USDA RUS

The official PDF is openable, unencrypted, 145 pages, begins with `%PDF-1.6`, has a plausible PDF MIME/extension, and is not HTML, a Git-LFS pointer, or truncated. Its cover confirms:

- United States Department of Agriculture, Rural Utilities Service;
- RUS Bulletin 1728F-806 / RD-GD-2018-93;
- *Specifications and Drawings for Underground Electric Distribution*;
- effective 11 October 2018.

Selective inspection was limited to the cover, structural index/end material, and one representative drawing solely to verify identity and vector/drawing character. The document is a digitally published, predominantly vector/path construction-drawing set with mixed content. No candidate page was selected and no semantic case was labeled.

The searchable text and selectively inspected pages contain no explicit copyright, proprietary, restricted-distribution, export-control, or reproduction notice. However, actual PDF metadata states `Author: Emgarten, Bob` and `Company: Iowa Lakes Electric Cooperative`. That non-federal authorship signal is material because the planned DEV value is the drawing set itself. Federal publication and public downloadability do not resolve ownership. The complete file is retained only in Git-ignored quarantine; derived crops, labeling, ML use, and redistribution are prohibited pending explicit rights resolution.

Final disposition: `RIGHTS_REVIEW_REQUIRED`.

## SF-V2-08 — NASA / General Dynamics

The official NTRS PDF is openable, unencrypted, 292 PDF pages, begins with `%PDF-1.6`, has a plausible PDF MIME/extension, and is not HTML, a Git-LFS pointer, or truncated. The scanned cover/catalog material confirms:

- NASA-CR-161594 and GDC-ASP-80-010;
- *Low Thrust Vehicle Concept Study, Final Report*;
- General Dynamics Convair Division, Space Systems Group;
- Contract NAS8-33527;
- September 1980 / the NTRS record date of 26 September 1980.

The 292-page PDF includes a catalog/wrapper page plus the scanned report sequence, consistent with the catalog's 291-page notation. It is a genuine raster reproduction: 291 of 292 PDF pages contain a direct page image, with an OCR text layer and Adobe Acrobat 7.1 Paper Capture metadata. Selective inspection confirms rotation, edge darkening, uneven contrast, faint/broken strokes, and other genuine scan artifacts. No candidate page was selected.

The mandatory actual-byte review found General Dynamics contractor/corporate authorship but no copyright notice, proprietary legend, restricted-distribution language, export-control notice, reproduction restriction, government-purpose-only legend, or third-party ownership notice. This does not conflict with the candidate-specific NTRS designation, “Work of the US Gov. Public Use Permitted.” The file is admitted as `PUBLIC_DOMAIN`, with NASA/NTRS source credit, General Dynamics corporate-author attribution, and no implied endorsement.

Actual-byte rights recheck: `PASS`.

## Integrity and storage

Both complete binaries are under the repository's Git-ignored `local-artifacts/draftsman/perception-v2/wave1/` hierarchy. Their hashes differ, so no Wave-1 duplicate-byte collision exists. An incomplete concurrent NASA transport retry is an ignored runtime artifact, is not admitted, and is not counted as an acquired document. No source binary is Git-tracked.

Because SF-V2-01 has no bytes and SF-V2-03 has unresolved drawing ownership, overall source-evidence and data-rights provenance are marked `INCOMPLETE` for the three-document Wave-1 plan even though every outcome is explicitly recorded.

## Governance preserved

- Reference Baseline V1 was not run.
- No embedding, classifier, uncertainty, Hough/LSD, or candidate-mining process was run.
- No page was selected for labeling; no crop, overlay, or label was created.
- H1/H2 and C1 were not read, rerun, mixed, or adapted.
- VALIDATION was not used.
- LOCKED_BLIND remains `0 / 8`, with no manual inspection.
- No production source, dependency, CAD, GUI, `SourceSupportLifecycle`, or `FinalStructure` behavior changed.
- `PRODUCTION_SEMANTIC_DELTA: NONE`.

## Frozen task status

The diagnostic checkpoint is the commit containing this report and the two machine-readable registries; its hash is recorded in the task handoff because a Git commit cannot contain its own hash.

PERCEPTION_V2_B2:
PARTIAL

BASE CHECKPOINT:
f3b10c3b64c36ce2a2a96a8862edf58fa6054024

DIAGNOSTIC CHECKPOINT:
RECORDED_IN_TASK_HANDOFF

PRODUCTION_SEMANTIC_DELTA:
NONE

SF-V2-01:
DOWNLOAD_FAILED

SF-V2-03:
ACQUIRED_RIGHTS_BLOCKED

SF-V2-08:
ACQUIRED_AND_ADMITTED

SF-V2-08 ACTUAL-BYTE RIGHTS RECHECK:
PASS

TOTAL DOCUMENTS ACQUIRED:
2

TOTAL DOCUMENTS ADMITTED:
1

READY FOR PERCEPTION-V2-B3:
NO

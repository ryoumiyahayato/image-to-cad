# P0 controlled new-source acquisition D14D

## Outcome

The four D14C-approved P0 documents were acquired from official infrastructure, verified, rights-rechecked against the actual bytes, and admitted to the Git-ignored DEV artifact store. No fallback was used.

| Family/document | Admission | Files | Sheets/pages | Bytes | SHA-256 |
|---|---|---:|---:|---:|---|
| H1 — HAER UT-14, Provo River Bridge | `ACQUIRED_AND_ADMITTED` | 4 master TIFFs | 4 | 2,492,042 | `A9D5EFBF630A439A77F05A41FACB9DA96478D5AA644ADE0F1877781771600AA6` document-set digest |
| H1 — HAER NY-4, Whipple Bowstring Truss Bridge | `ACQUIRED_AND_ADMITTED` | 5 master TIFFs | 5 | 2,952,242 | `020DAB1202B63F9B28A9E41E934089440ED842C6FAA2C0CB97952772084D035A` document-set digest |
| H2 — NIST FTC 6, `nist_ftc_06_asme1_rd`, Rev D | `ACQUIRED_AND_ADMITTED` | 1 PDF | 3 | 167,608 | `501A976013CB1E2C13BFC998B5DFA010B064945A1F0A1EAA303A59D96DDC893C` |
| C1 — WFL Sample Plan Sheets, January 2026 | `ACQUIRED_AND_ADMITTED` | 1 PDF | 21 | 3,845,659 | `B9598C3689960F31D6C9B6BF4AD9859DED1796FD780B7AA44729FB41ADCD13E7` |

For the two multi-file HAER documents, the document-set digest is SHA-256 over the UTF-8 concatenation of sorted `filename<TAB>lowercase_file_sha256<TAB>byte_size<LF>` records. The registry preserves the SHA-256 and byte size of every original TIFF, so the set digest does not replace file-level evidence.

Acquisition access/verification timestamp: `2026-09-14T09:02:29.8889535Z`.

## Storage and tracking

All source binaries are stored below:

`C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\new-source-p0-d14`

The hierarchy is:

- `H1\haer-ut14\`: four original LOC master measured-drawing TIFFs.
- `H1\haer-ny4\`: five original LOC master measured-drawing TIFFs.
- `H2\nist_ftc_06_asme1_rd.pdf`.
- `C1\wfl-samples-plan-profile.pdf`.

`/local-artifacts/` is covered by the repository's `.gitignore`. Git ignore behavior was explicitly checked for H1, H2, and C1 paths before acquisition. No binary is staged or committed.

The complete tracked provenance and file-level hashes are in `acquisition-registry.json`.

## Source-evidence verification

### H1 document 1 — HAER UT-14

- Source family: `D14C-H1-HAER-HISTORICAL-MEASURED-DRAWINGS`.
- Governance role: `NEW-SOURCE HOLDOUT H1`.
- Landing page: <https://www.loc.gov/item/ut0117/>.
- Drawing resource: <https://www.loc.gov/resource/hhh.ut0117.sheet/?st=gallery>.
- Final binary URL pattern: `https://tile.loc.gov/storage-services/master/pnp/habshaer/ut/ut0100/ut0117/sheet/0000Na.tif`, for `N=1..4`.
- Identity: the title sheet visibly identifies the Denver & Rio Grande Western Railroad Pratt Truss Bridge, HAER UT-14, and `SHEET 1 OF 4 SHEETS`.
- Format: four non-zero, independently decoding, single-page TIFF files; 1-bit Group 4 raster; dimensions range from 7,616×9,632 to 9,646×7,616.
- Metadata: every file carries `Artist=Library of Congress` and a 2000 LOC scan timestamp.
- Relationship: one four-sheet survey document; not duplicate bytes of NY-4 or any other acquired file.

### H1 document 2 — HAER NY-4

- Source family: `D14C-H1-HAER-HISTORICAL-MEASURED-DRAWINGS`.
- Governance role: `NEW-SOURCE HOLDOUT H1`.
- Landing page: <https://www.loc.gov/item/ny0017/>.
- Drawing resource: <https://www.loc.gov/resource/hhh.ny0017.sheet/?st=gallery>.
- Final binary URL pattern: `https://tile.loc.gov/storage-services/master/pnp/habshaer/ny/ny0000/ny0017/sheet/0000Na.tif`, for `N=1..5`.
- Identity: the title sheet visibly identifies the Whipple Cast & Wrought-Iron Bowstring Truss Bridge, HAER NY-4, and `SHEET 1 OF 5 SHEETS`.
- Format: five non-zero, independently decoding, single-page TIFF files; 1-bit Group 4 raster; dimensions range from 9,248×7,584 to 9,288×7,584.
- Metadata: every file carries `Artist=Library of Congress` and a 2000 LOC scan timestamp.
- Relationship: one five-sheet survey document, independent of UT-14; no duplicate bytes.

Only the official `sheet` master assets were acquired. Photographs, copied-source photographs, data pages, and the separately cataloged historical photocopy were not downloaded or admitted.

### H2 — NIST FTC 6

- Source family: `D14C-H2-NIST-PMI-FTC`.
- Governance role: `NEW-SOURCE HOLDOUT H2`.
- Landing page: <https://pages.nist.gov/CAD-PMI-Testing/models.html>.
- Request URL: <https://www.nist.gov/document/nist-cad-model-ftc-06>.
- Final resolved binary URL: <https://www.nist.gov/system/files/documents/noindex/2022/04/06/nist_ftc_06_asme1_rd.pdf>.
- Identity: PDF metadata title `NIST PMI Test Model - FTC 6`, author `NIST`; all three pages contain `NIST PMI Test Models - 2014`, `nist_ftc_06_asme1_rd`, and `Rev D`.
- Format/integrity: valid unencrypted PDF 1.6, three letter-size pages, no JavaScript, zero image XObjects, fully traversed and text-extractable.
- Relationship: the request and resolved URL identify one official NIST file; its bytes are unique across the acquisition.

### C1 — FHWA WFL plan/profile samples

- Source family: `D14C-C1-FHWA-WFL-ORD-PLAN-PROFILE`.
- Governance role: untouched DEV baseline until its first frozen evaluation is recorded.
- Landing page: <https://highways.dot.gov/federal-lands/design/plan-prep/wfl/samples/plan-profile-sheets>.
- Final resolved binary URL: <https://highways.dot.gov/sites/fhwa.dot.gov/files/wfl-samples-plan-profile.pdf>.
- Identity: metadata title `Plan and Profile Sheets`, subject `WFL Sample Plan Sheets`, author `Vincent, Benjamin (FHWA)`, company `USDOT`.
- Content markers: revised January 2026, `WFL Internal`, OpenRoads/DGN workflow references, and sample sheet identifiers D.1 through D.12.
- Format/integrity: valid unencrypted PDF 1.7, 21 letter-size pages, no JavaScript, extractable text/vector content plus 23 image XObjects; therefore classified `mixed`.
- Acquisition: the official landing page resolved the canonical file URL. The host rejected ordinary scripted retrieval, while Windows Background Intelligent Transfer Service successfully acquired the same official URL without a mirror.
- Relationship: the landing and canonical file URLs are one official FHWA source; its bytes are unique across the acquisition.

## Actual-byte rights recheck

### H1

`PASS — PUBLIC_DOMAIN`.

The admitted files are the LOC master TIFFs from each record's measured-drawing `sheet` resource, not the `photos` or `data` resources. Their metadata attributes the scans to the Library of Congress. Both visible title sheets identify the Historic American Engineering Record under National Park Service / U.S. Department of the Interior direction and identify the expected surveys and sheet counts. No copyright, copied-source, or conflicting third-party rights notice appears.

The title sheets name survey sponsors and delineators; those credits do not contradict the LOC statement that original HAER measured drawings were created for the U.S. Government and are considered public domain. The admission applies only to these measured-drawing assets.

Rights basis: <https://wwws.loc.gov/rr/print/res/114_habs.html>.

### H2

`PASS — PUBLIC_DOMAIN`.

Actual metadata attributes the PDF to NIST. Extracted text contains no copyright, contractor, consultant, license-conflict, all-rights-reserved, or third-party notice. The document embeds no raster/image XObjects. References to ASME Y14.41 and Y14.5M are standards references and do not transfer authorship of the NIST drawing.

Rights basis: <https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications>.

### C1

`PASS — PUBLIC_DOMAIN`.

The mandatory C1 check strengthened rather than contradicted D14C: actual PDF metadata names an FHWA author and USDOT as company. A complete text extraction found no copyright, contractor, consultant, third-party-source, all-rights-reserved, or conflicting license notice. The mixed PDF contains 23 image XObjects, but no contrary document-level attribution is attached to them in the inspected bytes.

Rights basis: <https://www.fhwa.dot.gov/disclaim.cfm> and <https://www.fhwa.dot.gov/publications/research/general/15058/024.cfm>.

These dispositions concern copyright and the approved DEV evaluation. They do not permit implied agency endorsement or erase any separate trademark or foreign-jurisdiction obligations.

## Integrity and admission checks

| Check | Result |
|---|---|
| Official infrastructure only | PASS — LOC `tile.loc.gov`, NIST `nist.gov`, FHWA `highways.dot.gov` |
| Expected identities | PASS |
| Expected counts | PASS — H1 4 + 5 sheets, H2 3 pages, C1 21 pages |
| Non-zero plausible magic/MIME | PASS — little-endian TIFF and PDF 1.6/1.7 signatures |
| Complete decode/parse | PASS — all TIFFs verified; all PDF pages parsed |
| SHA-256 and exact bytes | COMPLETE |
| Duplicate bytes | PASS — zero duplicate SHA-256 groups among 11 files |
| Rights contradictions | NONE FOUND |
| Fallback needed | NO |
| Total usable documents | 4 |

## Governance freeze

- H1 and H2 remain new-source holdouts. No acquired sample has influenced representation selection, classifier fitting, class centroids, preprocessing, feature/layer selection, abstention, calibration, or thresholds.
- C1 remains untouched until its first frozen DEV baseline result is durably recorded.
- No MobileNet or other model was run.
- No Hough/LSD, `detect_lines`, reconstruction, gap mining, contact sheet, local/context crop, or human label was produced.
- No registry from D11/D13 was changed.
- No acquired material entered VALIDATION or LOCKED_BLIND.
- LOCKED_BLIND exposure remains `0 / 8`; manual inspection remains `NO`.
- Production semantic delta: `NONE`.

## Final decision

All three source families are admitted. The frozen acquisition registry is complete, the source binaries remain Git-ignored, and D14E blind candidate mining plus prediction-blind human labeling is ready for a separate task.

D14D stops here. D14E was not started.

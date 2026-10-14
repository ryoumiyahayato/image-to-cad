# Draftsman G0-B4R4 / G0-R3B Replacement Candidate Report

## Result

The 2026-09-09 Desktop intake produced 5 acquisition-verified, registry-distinct electrical SOURCE_GROUPS from 9 relevant PDF downloads. G0-R3B then acquired **exactly 2 additional acquisition-verified, registry- and pool-distinct electrical SOURCE_GROUPS** from official government sources. Search stopped when the replacement pool reached its target of **7 / 7**. No authoritative selection or acquisition manifest was changed.

All accepted source bytes were copied without modification to the Git-ignored `local-artifacts/draftsman/replacement-candidates/<source_group_id>/` root. The committed artifact contains metadata and hashes only.

## Intake and decisions

| Desktop file | Pages | Decision | SOURCE_GROUP / reason |
|---|---:|---|---|
| `0026_20260601.pdf` | 39 | `VERIFIED_REPLACEMENT_CANDIDATE` | `G0R3-829E8827D01F110E`; Yokohama Seya Ward Citizens Cultural Center electrical package, including index E-000–E-025 and feeder/grounding diagram E-007. |
| `20210416zumen.pdf` | 16 | `VERIFIED_REPLACEMENT_CANDIDATE` | `G0R3-4ABF9A7441A705A2`; Nagano Prefecture Ontake Visitor Center electrical package, including E-01 and distribution diagram E-02. |
| `dennkisetubi.pdf` | 1 | `VERIFIED_REPLACEMENT_CANDIDATE` | `G0R3-2EEB6C7BB30F78D1`; Hamamatsu City ToBiO main-pool lighting plan. |
| `2026dennkisetsubi.pdf` | 7 | `VERIFIED_REPLACEMENT_CANDIDATE` | `G0R3-428190EE2F469FB0`; Kadoma Municipal General Gymnasium electrical plans, including lighting plan E-26. |
| `52725.pdf` | 145 | `VERIFIED_REPLACEMENT_CANDIDATE` | `G0R3-29B859C52FC45AD1`; official Farmington meeting packet containing full electrical site plan E300 for the independent Town Hall renovation project. This is a mixed packet and should receive lower replacement preference than dedicated drawing packages. |
| `Addendum_2-Major_Renovation_&_Modernization_of_FEMS_Dept_Engine_House_No14.pdf` | 93 | `REJECT_NOT_ELECTRICAL_DRAWING` | DC DGS/FEMS identity is verified, but the downloaded addendum contains specifications. Its cover lists separately revised electrical sheets; those actual drawing sheets are not present in these bytes. |
| `32579.pdf` | 2 | `REJECT_NOT_ELECTRICAL_DRAWING` | Sakado former Kita-Sakado Elementary School meeting overview/Q&A; same project identity as existing `G0R2-2E9BDFFDD8C89AE7`, but not the registered electrical drawing package. |
| `32580.pdf` | 9 | `REJECT_NOT_ELECTRICAL_DRAWING` | Sakado construction explanation handout; same existing project/source group, not electrical drawings. |
| `32581.pdf` | 20 | `REJECT_NOT_ELECTRICAL_DRAWING` | Sakado project-meeting presentation; same existing project/source group, not electrical drawings. |

The two older July Desktop PDFs were outside this intake window and were not processed. No ZIP or image candidate was present in the relevant recent Desktop set.

## G0-R3B additional acquisitions

| Official source | Pages | Decision | SOURCE_GROUP / evidence |
|---|---:|---|---|
| Worcester County, Maryland — `Bid Set - 0085B005.A01_Agency Review-Bid Set_07-29-25_R_reduced size.pdf` | 26 | `VERIFIED_REPLACEMENT_CANDIDATE` | `G0R3-BE39EAEE97CA4210`; Isle of Wight Facility Renovation bid set for Worcester County Health Department. Sheets E-101, E-201, E-301, and E-401 contain electrical demolition, lighting, power, and schedule drawings. |
| City of Atlantic City, New Jersey — `Pop-Lloyd-Updated-Addendum-#3-040124-DRAWINGS.pdf` | 17 | `VERIFIED_REPLACEMENT_CANDIDATE` | `G0R3-746CDDBA829DD3FE`; Pop Lloyd Stadium Renovation drawing addendum. Sheets E-000, E-102, and E-300 contain electrical notes, new-work plans, schedules, and diagrams. |

Both direct official PDF URLs were opened and identity-checked in a normal browser. Because the in-app browser could display but not export the PDF bytes, each verified URL was saved once with a minimal local byte-transfer fallback; no portal automation, retry loop, or URL-only candidate was used. The downloaded bytes passed PDF parsing, MIME, page-count, byte-size, and SHA256 validation. The two accepted sources were the only new sources inspected in G0-R3B, so the phase accepted 2 and rejected 0 before stopping at 7 / 7.

## Provenance and identity

Each accepted PDF has a Windows `Zone.Identifier` alternate stream recording an official-government `HostUrl` and `ReferrerUrl`. The canonical source URL removes only the non-identity `utm_source=chatgpt.com` tracking parameter. The deterministic ID is `G0R3-` plus the first 16 uppercase hex characters of SHA256 over the registry-normalized canonical URL, preserving the existing registry identity algorithm while identifying the G0-R3 phase.

Identity was confirmed from the official host plus a rendered cover, title block, drawing index, or electrical sheet. Download time and filename were supporting evidence only.

## Registry deduplication and independence

All seven accepted URLs have no normalized URL match in the 99-record registry, and their organization-plus-project identities also have no match. They are also mutually distinct by normalized URL and organization-plus-project identity. Farmington already appears in `SGC-008`, but that record is the Senior Community Center HVAC and Roof Replacement; the new file is the 1928 Building/Farmington Town Hall renovation, with a different facility, project, package, and official document URL.

The three Sakado explanatory files map to the same project identity as existing `G0R2-2E9BDFFDD8C89AE7`; they neither replace its missing registered drawing bytes nor create new SOURCE_GROUPS. The DC FEMS addendum is registry-distinct but fails the electrical-drawing content gate.

## Diversity snapshot

- Regions: East Asia 4; North America 3.
- Rendering: confirmed raster/scanned 3; confirmed vector 1; confirmed mixed 3; unknown 0.
- Historical/archival: 0.
- Confirmed degraded: 0.
- Native image: 0.
- Drawing families: cultural center; visitor center; swimming facility; sports arena; town hall renovation; county health facility; stadium renovation.

The pool adds useful modern municipal raster and mixed-rendering diversity, but it does not add historical, degraded, or native-image coverage. Formal replacement selection must account for these deficits and should prefer dedicated electrical packages over the mixed Farmington meeting packet when equivalent candidates exist.

## Integrity and scope gates

- Candidate registry SHA256: `07e25d6d876c0d0416556aefe01267d688da495111eec69e521bb2c70803e780` (unchanged).
- Authoritative split SHA256: `05283c960096941ecac34f73e109fe9d850e8d2354b144387c00370755d288cd` (unchanged).
- Corpus V1 evaluation-ready: 23 / 30 (unchanged).
- LOCKED_BLIND evaluation-ready: 8 / 8.
- LOCKED_BLIND runtime executed: 0 / 8.
- LOCKED_BLIND manually inspected: NO.
- Reserve substitutions: 0.
- Source bytes committed: 0.
- Production semantic delta: NONE.

## Disposition

`READY_FOR_G0_B3R`: seven acquisition-verified independent SOURCE_GROUPS satisfy the replacement-pool target. G0-B3R replacement selection has not been started.

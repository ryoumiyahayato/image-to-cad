# PERCEPTION-V2-B2A — Wave-1 replacement acquisition

## Outcome

The two V2-B2S-approved FAA replacements were acquired from official FAA URLs, verified from their actual bytes, and admitted. No third-party ownership notice or page/asset attribution requiring an exclusion was found. With frozen SF-V2-08 unchanged, Wave-1 now has 3/3 admitted families and is ready for the separate V2-B3 task.

| Slot | Official document | SHA-256 | Bytes | Pages | Rights | Admission |
|---|---|---:|---:|---:|---|---|
| SF-V2-01 | FAA AC 43.13-1B with Change 1 | `8DC99DD41334381B287AE02D03DC29928D9EACB1035B67AA24C5A0525324EE73` | 21,101,662 | 646 | `PUBLIC_DOMAIN` | `ACQUIRED_AND_ADMITTED` |
| SF-V2-03 | FAA AC 150/5340-30J | `65D10B7CA60CAF4515574D995CA5AF3ACA34DE2D59FA07FC6E46C002E9AE54C5` | 12,484,227 | 396 | `PUBLIC_DOMAIN` | `ACQUIRED_AND_ADMITTED` |
| SF-V2-08 | NASA-CR-161594 (frozen reference only) | `C79593F34938052BEB5E90349F32A2A577ED1EAA66CAA99BA4CBB128E94842B6` | — | — | `PUBLIC_DOMAIN` | `ACQUIRED_AND_ADMITTED` |

## Official-source and identity checks

Both FAA landing pages and direct binaries were reachable without authentication. Each binary request resolved directly with HTTP 200, `application/pdf`, and no redirect. The acquired files open as PDF 1.6, are nonzero, are not HTML or redirect stubs, expose readable page trees, and have unique hashes relative to each other and frozen SF-V2-08.

- SF-V2-01 actual title page: U.S. DOT/FAA; AC 43.13-1B; 8 September 1998; Change 1; exact inspection-and-repair title. The bytes are the circular, not a supplement or change sheet.
- SF-V2-03 actual title page: U.S. DOT/FAA; AC 150/5340-30J; 12 February 2018; AAS-100; Revision J with no separate change number. The bytes are the requested airport visual-aids circular.

## Family-level suitability preservation

- SF-V2-01 is a mixed digital/vector-and-raster manual with dense aircraft sheet-metal repair and structural-detail drawings. Actual-byte inspection confirmed mechanical object edges, repair geometry, sections/details, dimensions and witness-like marks, leaders, callouts, notes, and line hierarchy.
- SF-V2-03 is predominantly digitally generated/vector. Actual-byte inspection confirmed installation details with cable/conduit paths, connectors, light and support placement, underground junction boxes, grounding/foundation details, dimensions, leaders, and dense layout annotations.

These were source-level checks only. No candidate pages were selected, no crops or overlays were created, and no semantic labels or model predictions were used.

## Actual-byte rights review

The FAA/DOT issuing identity, official National Transportation Library records, DOT public-access policy, and 17 U.S.C. 105 support `PUBLIC_DOMAIN` for both federal works. Neither PDF contains an identified copyright notice, reproduction restriction, externally attributed figure, proprietary legend, or page-specific non-federal authorship signal.

AC 43.13-1B acknowledges aviation contributors and an SAE division for assistance, and both documents refer to standards, manufacturers, or contractor duties. Those references do not assign ownership or identify copied material. Consequently no defensible page/asset exclusion is triggered, and a usable-page allowlist is not necessary. Later B3 inspection must still stop and escalate if previously undisclosed third-party ownership appears in a selected asset.

## Frozen provenance and governance

Detailed acquisition and rights evidence is frozen in `acquisition-registry.json` and `rights-registry.json`. Earlier history remains referenced through base checkpoint `f2822879ab1380afd836140166255e992a43874e`; prior registries were not duplicated. SF-V2-08 was neither inspected nor modified. Source PDFs remain under Git-ignored `local-artifacts/draftsman/perception-v2/wave1/` and were not staged.

No Reference Baseline V1, model, embeddings, candidate mining, human labeling, validation, or locked-blind inspection ran. H1/H2 holdouts were not inspected. Production semantics are unchanged. V2-B3 was not started.

## Official evidence

- FAA AC 43.13-1B landing page: <https://www.faa.gov/regulations_policies/advisory_circulars/index.cfm/go/document.information/documentid/99861>
- FAA AC 43.13-1B official binary: <https://www.faa.gov/documentlibrary/media/advisory_circular/ac_43.13-1b_w-chg1.pdf>
- FAA AC 150/5340-30 landing page: <https://www.faa.gov/airports/resources/advisory_circulars/index.cfm/go/document.current/documentnumber/150_5340-30>
- FAA AC 150/5340-30J official binary: <https://www.faa.gov/documentLibrary/media/Advisory_Circular/150-5340-30J.pdf>
- NTL public-domain record for AC 43.13-1B: <https://rosap.ntl.bts.gov/view/dot/71377>
- NTL FAA Advisory Circular collection: <https://rosap.ntl.bts.gov/cbrowse/?parentId=dot%3A65448&pid=dot%3A65448>
- DOT Data Management Policy: <https://www.transportation.gov/sites/dot.gov/files/docs/mission/128511/policy-data-management-s10-160926-001-d5-071317.pdf>
- 17 U.S.C. 105: <https://usc-cdn.house.gov/view.xhtml?edition=prelim&num=0&req=granuleid%3AUSC-prelim-title17-section105>

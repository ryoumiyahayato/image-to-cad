# G0-B4R Corpus V1 Access Remediation Report

Scope: access remediation for the seven unmaterialized Corpus V1 SOURCE_GROUPS only. This work did not amend selection or split membership and did not execute Draftsman, OCR, rendering, QA, evaluation, or LOCKED_BLIND runtime.

Checked at: `2026-09-09T08:16:19Z`

## Outcome

- Starting evaluation-ready: 23 / 30
- Automatic official-source recovery: 0
- Official portal/landing URL resolutions: 2
- Manual acquisitions completed: 0
- Manual downloads still required: 6
- Official source unavailable, not proven permanent: 1
- Permanently unmaterializable: 0
- Final evaluation-ready: 23 / 30

## Per-source remediation record

### `A2-SG-010` — `MANUAL_DOWNLOAD_REQUIRED`

- Original URL: <https://staff.digitalcollections.ohs.org/robert-park-residence-electrical-plan-and-fixture-schedule>
- Attempts: ordinary HTTP returned a 200 HTML browser-verification challenge; an ordinary interactive browser session reached the same verification page. No challenge bypass was attempted.
- Official alternative: the same OHS item landing page; no independently verifiable direct derivative URL was exposed to the ordinary client.
- Identity evidence: OHS item `Mss3077-3_21`, “Robert Park Residence electrical plan and fixture schedule”, master JPEG, 5.2 MiB.
- Manual action: use the official item page's **Access Copies** flow; download the master JPEG and retain its item identity. Suggested intake filename: `A2-SG-010-manual.jpg`. Import from an intake directory; the tool materializes it under `local-artifacts/draftsman/corpus-v1/dev/A2-SG-010/`.

### `G0R2-53C88494D6CE893C` — `MANUAL_DOWNLOAD_REQUIRED`

- Original URL: <https://eplanning.cityofsydney.nsw.gov.au/Common/Integration/FileDownload.ashx?ext=PDF&filesize=792563&id=%21%21MPqVeI7%2Bm%2FPC%2Bxps6Jd7%2Fi0VeJ%2BMH%2B579uowxQ%3D%3DFM%2BT8%2B%2FiyLw%3D&modified=2021-12-10T01%3A34%3A41Z>
- Attempts: ordinary automated access returned HTTP 403; no authorization, User-Agent, or anti-bot bypass was attempted.
- Official alternative: none; the registered City of Sydney ePlanning download endpoint remains indexed for the exact document.
- Identity evidence: Argyle Stores structural upgrade, project `301350511`, electrical services basement layout, expected PDF size 792,563 bytes from the registered official URL metadata.
- Manual action: open the registered official URL in a normal browser session and download the PDF. Suggested intake filename: `G0R2-53C88494D6CE893C-manual.pdf`; target directory is `local-artifacts/draftsman/corpus-v1/dev/G0R2-53C88494D6CE893C/`.

### `G0R2-AFE53C2A00EB7D8F` — `MANUAL_DOWNLOAD_REQUIRED`

- Original URL: <https://eplanning.cityofsydney.nsw.gov.au/Common/Integration/FileDownload.ashx?ext=PDF&filesize=3626682&id=%21%215SfcrhnSRSdllDIkVxG2Lj%2FMJS0%2Fd3oOstPPhA%3D%3DJNe6xI8AhDk%3D&modified=2023-08-03T04%3A26%3A28Z>
- Attempts: ordinary automated access returned HTTP 403; no authorization, User-Agent, or anti-bot bypass was attempted.
- Official alternative: none; the registered City of Sydney ePlanning download endpoint remains indexed for the exact document.
- Identity evidence: Sydney Park Brick Kiln Precinct Renewal, project `212710`, electrical power/lighting/communications/fire drawings, expected PDF size 3,626,682 bytes from the registered official URL metadata.
- Manual action: open the registered official URL in a normal browser session and download the PDF. Suggested intake filename: `G0R2-AFE53C2A00EB7D8F-manual.pdf`; target directory is `local-artifacts/draftsman/corpus-v1/dev/G0R2-AFE53C2A00EB7D8F/`.

### `SGC-007` — `MANUAL_DOWNLOAD_REQUIRED`

- Original URL: <https://govtribe.com/file/government-file/2-2026-02-25-titusville-ms-entry-reno-100-cd-submission-drawings-dot-pdf>
- Attempts: the registered file endpoint returned HTTP 403. Project bidding documents identify the ordinary official acquisition portal; no login control was bypassed.
- Official alternative: <https://pennbid.bonfirehub.com/>
- Identity evidence: “Titusville Middle School Entry Addition”, Titusville Area School District, project `225306`, `02.25.2026` 100% Construction Documents drawings, expected size approximately 18 MB.
- Manual action: use PennBid's normal project-search/login flow and download `2-2026 02 25 Titusville MS Entry Reno 100% CD Submission Drawings.pdf`. Suggested intake filename: `SGC-007-manual.pdf`; target directory is `local-artifacts/draftsman/corpus-v1/validation/SGC-007/`.

### `SGC-008` — `MANUAL_DOWNLOAD_REQUIRED`

- Original URL: <https://govtribe.com/file/government-file/25-dot-119-farmington-senior-community-center-hvac-upgrade-bid-dwgs-dot-pdf>
- Attempts: the GovTribe endpoint and the resolved Town of Farmington document endpoint returned HTTP 403 to the ordinary automated client; no access-control bypass was attempted.
- Official alternative: Town document endpoint <https://www.farmington-ct.org/home/showpublisheddocument/36556>, listed by the [official document landing page](https://www.farmington-ct.org/about-farmington/advanced-components/custom-pages/custom-documents-images-calendar/-item-10349/-folder-247/-sortn-EName/-sortd-asc/-toggle-allupcoming).
- Identity evidence: `25.119 Farmington Senior & Community Center HVAC Upgrade BID Dwgs`, Bid `#369`, electrical sheets E001/E002/E010/E011/E110/E111.
- Manual action: use the Town landing page in a normal browser and download the exact BID Dwgs PDF. Suggested intake filename: `SGC-008-manual.pdf`; target directory is `local-artifacts/draftsman/corpus-v1/dev/SGC-008/`.

### `SGC-024` — `MANUAL_DOWNLOAD_REQUIRED`

- Original URL: <https://govtribe.com/file/government-file/2-2026-150-g-1-1-bidding-documents-bid-drawings-dot-pdf>
- Attempts: the registered file endpoint returned HTTP 403. The official Washington project page was found and identifies DES Bonfire as the bidding-document flow; no login control was bypassed.
- Official alternative: <https://omwbe.wa.gov/bid-opportunities/2026-150-g-1-1-hvac-main-campus-%E2%80%93-oly-and-uni-%E2%80%93-boiler-replacements>, then <https://deswa.bonfirehub.com/>.
- Identity evidence: State project `2026-150 G (1-1)`, “South Seattle College HVAC on Main Campus – OLY and UNI – Boiler Replacements”, bid drawings package.
- Manual action: follow the official project page to DES Bonfire and download `2-2026-150 G (1-1) Bidding Documents- Bid Drawings.pdf`. Suggested intake filename: `SGC-024-manual.pdf`; target directory is `local-artifacts/draftsman/corpus-v1/dev/SGC-024/`.

### `G0R2-2E9BDFFDD8C89AE7` — `OFFICIAL_SOURCE_UNAVAILABLE`

- Original URL: <https://www.city.sakado.lg.jp/uploaded/attachment/31595.pdf>
- Attempts: the registered official attachment returned HTTP 404. An official-domain indexed candidate, `31604.pdf`, was fetched without a custom User-Agent and also returned HTTP 404 with an HTML error body; it was rejected as source bytes. Official-domain project-page and attachment searches did not establish a live equivalent document.
- Official alternative: none verified. Search-index title similarity was not treated as source identity proof.
- Identity evidence sought: 坂戸市 `旧坂戸市立北坂戸小学校校舎解体等工事`, drawing package containing high-voltage, exterior wiring, communications, and fire-alarm sheets.
- Manual action: none currently actionable. This is not marked `PERMANENTLY_UNMATERIALIZABLE`; continue official archive/municipal inquiry before any G0-B3R decision.

## Safe manual import

Use an intake file outside the final group directory, then run the acquisition tool with all standard path arguments plus:

```text
--manual-source-group-id SOURCE_GROUP_ID
--manual-file PATH_TO_DOWNLOADED_FILE
--manual-identity-evidence "specific official page, project/item identifier, title, and filename evidence"
```

The importer permits only the approved remediation set, rejects LOCKED_BLIND and non-manual states, validates file format/integrity, rejects duplicate hashes and existing targets, copies with exclusive creation, verifies SHA256 after copying, records byte metadata and identity evidence without recording the intake path, and updates the manifest/report deterministically.

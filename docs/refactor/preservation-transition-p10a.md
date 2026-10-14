# Compact preservation transition through P10-A

The original `preservation-baseline.json` and D-010 tag remain unchanged. Its original generation provenance is still unknown. A separate process using the archived local `20b2247` source exactly reproduces its three case IDs, every LINE coordinate and member count. The fixture function bodies match the current ones. Both replays use native input resolution, 300 DPI, OCR off and no PDF evidence.

The current production implementation is the published `6452828` tree, equivalent to local archive `eb8fe5a` for product source. The algorithm identity ends in `isolated-scan-stroke-v1`; FinalStructure is schema 4 and trace cache is format 11. These compact inputs are clean-digital, so P10-A makes no scan-stroke proposal.

Raw Hough/LSD candidates, filtering, endpoint and intersection observation stages are equal. The first changed admission is `ReconciliationLedger.consolidate_detector_aliases`: 20 candidates become 14 in processing-contract-page; 12 become 11 in reconciliation-gap-junction. Diagnostic replay of the same current code with only that method bypassed reproduces every old LINE payload, including width, layer and source history. This is cause isolation, not an alternative product entry.

The first case has six whole-observation consolidations. One formerly retained LSD observation later split into a tiny piece and a longer piece, so seven old output records disappear. The gap case has one consolidation and one removed output. All current LINE geometries already existed in the old result; no retained endpoint moves and no new geometry is added.

| Case / removed source | Old output records | Retained source observations | Source pixels per removed record | Unique source loss |
|---|---:|---|---|---:|
| processing / HOUGH-000003 | 1 | HOUGH-000003 + LSD-000004 | 477 | 0 |
| processing / HOUGH-000007 | 1 | HOUGH-000007 + LSD-000009 | 311 | 0 |
| processing / HOUGH-000010 | 1 | HOUGH-000010 + LSD-000005 | 297 | 0 |
| processing / LSD-000003 | 1 | HOUGH-000006 + LSD-000003 | 365 | 0 |
| processing / LSD-000008 | 2 | HOUGH-000004 + LSD-000008 | 17, 365 | 0 |
| processing / LSD-000010 | 1 | HOUGH-000002 + LSD-000010 | 497 | 0 |
| gap / LSD-000005 | 1 | HOUGH-000005 + LSD-000005 | 85 | 0 |

Widths are unchanged: 3.819999933242798 source pixels in the first case and 1.909999966621399 in the gap case. The existing single-source-band, complete-cap-containment and exact shared-node vetoes grant the observation consolidation. Reversing the complete candidate input gives the same geometry/source sets. Existing Tiny window, independent/faint second-band, gap, protected-ink and shared-endpoint tests retain their vetoes. Sample-test keeps all 229 LINE and 145 contour members. This is bounded regression evidence, not a new real-scan positive or original design CAD truth.

`preservation-current-p10a.json` is a separate reviewed version. It retains exact current IDs, geometry, member counts (including ARC), cache roundtrip and DXF counts. The existing check also accounts for every historical LINE difference and independently verifies each removed stroke's complete source claim against its named keeper. An unexplained removed/added LINE, changed keeper, source loss or algorithm/schema/cache identity change fails. The old `--baseline` overwrite operation now refuses to replace historical evidence.

Replays, actual DXFs, source images and the per-object proof remain in ignored `local-artifacts/pr34-ci-closeout-20261014/`. The 12 directly related transition and source-alias checks pass locally. The normal Linux preservation step must still pass on the final PR head. The frozen 94/50 split, engineering geometry rules, OCR, ARC policy and historical evidence are not changed.

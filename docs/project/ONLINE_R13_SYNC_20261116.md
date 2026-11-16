# Verified r13 synchronization and compatibility work — 2026-11-16

This is a staged update on PR #36, not a product release and not permission to bypass failing acceptance gates. Existing main `81f364fbe4eee1df00dadefabaef0d1a72993e6e`, historical baselines and product requirements remain intact.

## Source provenance

- Previous GitHub synchronization: `c40923a446547c1a41485c9256bb29db0c69b9fc` (verified r12 content).
- Locally integrated r13 provenance: `9ba5282514f593958c6b19501787c9abfb609d05`, based on local r12 `92b71cf62902668f14d56b1d8447782a672e7962`. These local IDs are provenance, not fabricated GitHub ancestry.
- Seven r13 source/test files were applied to the reconstructed r12 source and compared with the delivered source bytes. The GitHub import then checked all five new files and the before/after identities of ten edited files, including the compatibility repairs below.
- Source integration commit: `3017cdbedfe7fa79614a2f0440bd9b866e0b4373`. The one-shot import workflows have been removed; normal acceptance workflows were not relaxed.
- An initial transport attempt failed validation and was reverted without changing production source. A subsequent readable, hash-checked delta succeeded. No force-push was used.
- No private drawings, local CAD acceptance files, runtime fonts, models or credentials are included in this update.

## r13 target-software evidence

The private local acceptance report now records PASS for the tested open stroke after a +1 mm endpoint-X edit, DXF 2007 save, directory move and cold reopen: five vertices, open state and 0.50 mm entity lineweight retained; no visible old-outline ghost or adjacent-object movement. Independent DXF readback confirms the target endpoint change, other target vertices, pen and eight image dependencies. This is one representative operation, not acceptance of all 15 recovered strokes or whole-product quality. Known layer-state, XDATA and IMAGE save differences remain.

## Two reproduced production defects repaired

1. Confirmed dust dispatch: a clean-looking raster could suppress an independently authorized noise mask. Authorized masks now apply independently of the appearance heuristic. Unconfirmed ink is not authorized for deletion; matching visible mixed-page vectors remain protected, and explicit-threshold/vector-only contracts remain unchanged. The focused new test failed before the change and passed after it.
2. Manual source-frame matching: document export emits raster contours using pixel centers, while manual source matching incorrectly used the text/pixel-edge transform. The writer now passes an explicit source transform. Complete-boundary matching and tolerances are unchanged; an intentionally wrong transform still blocks export. The existing failing manual-recovery test passes unchanged after the fix.

## Test-isolation repairs, not weakened product expectations

GUI stubs now provide the page-size state and scale-refresh callback used by the real window; the callback is asserted. Source inspection explicitly uses UTF-8 for Windows. Root pytest configuration makes repository tools importable from the CI working directory.

144 selected tests passed on CPython 3.11.15 in the cloud workspace, including source-coordinate counterexamples, authorized-mask controls and r13 geometry controls. This is not a full-suite PASS. One broader local run was blocked by an unavailable jsonschema dependency; GitHub's standard CI environment is the authority for that full check.

## Remaining gates

Do not erase or regenerate frozen baselines simply to make CI green. The trusted-LINE coordinate contract, ellipse/arc expectation, preservation/version contract, historical drafting-rule differences and tracked generated reports require separate diagnosis. Await actual new CI results; main is not updated merely because source upload succeeded. No new full-page OCR conversion or accuracy improvement is claimed by this compatibility batch.

## Local work

No repeat of the accepted r13 LibreCAD operation is required. No new local algorithm experiment or high-load conversion is requested. Keep the accepted local branch and edited files; do not replace them with this draft integration branch until its repository gates have been resolved.

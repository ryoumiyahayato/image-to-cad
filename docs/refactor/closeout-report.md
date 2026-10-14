# IMAGE TO CAD — POST-REFACTOR CLOSEOUT REPORT

Date: 2026-10-05 (Asia/Taipei).
Scope: small closeout in `instrumented-e03`, after the completed architecture
refactor. Started on `codex/source-support-lifecycle-instrumentation` at
`fb42639d87aac71a20aa6bbd0ed218d540b84833`, with a clean worktree.

| Result | Value |
|---|---|
| PRODUCT_NAME | Image to CAD |
| HUMAN_VERSION | 0.3.0-dev |
| SCAN_UNDERLAY_REGRESSION | PASS |
| LEGACY_V1_FLAGS | REMOVED |
| OLD_V1_PIPELINE_RESTORED | NO |
| LAYER_CLASSIFIER_RESTORED | NO |
| SYMBOL_KNOWLEDGE_RESTORED | NO |
| AUXILIARY_LEGACY_DETECTOR_RESTORED | NO |
| TEST_ONLY_PRODUCTION_MODULES | 0 |
| OPTIONAL_PRODUCTION_DIAGNOSTICS | 6 |
| OLD_BASELINE_PROVENANCE_DOCUMENTED_AS | UNPROVEN / UNKNOWN |
| TRUE_PRE_CURRENT_HISTORICAL_EVIDENCE_DOCUMENTED | YES |
| TERMINOLOGY_CLEANUP | app/authority → app/geometry_rules; junction_v2_trusted_authority_v1.json → junction_v2_geometry_rules_v1.json |
| VERSION_SINGLE_SOURCE | YES — app/version.py |
| CURRENT_TEST_SUITE | PASS — 530 passed in 63.50s (0:01:03) |
| CLI_SMOKE | PASS — help, version, current source CLI and Windows smoke script |
| GUI_SMOKE | PASS — real startup, display name, offscreen event loop/show/close |
| RUNTIME_INDEPENDENCE | PASS — fresh-process CPU OCR + processing + export |
| IMPORT_CYCLES | 0 |
| MAX_THIN_WRAPPER_CHAIN | 1 (unchanged) |
| PROVEN_PRODUCT_REGRESSION_AFTER_CLOSEOUT | NONE |
| ARCHITECTURE_REFACTOR_PHASE | CLOSED |
| PRODUCT_WORK_CAN_RESUME | YES |

The scan regression directly calls `export_final_structure_dxf` with
`raster_image`. It verifies DXF/file creation, one expected LINE and TEXT,
one linked scan IMAGE, image linkage, returned counts, scan pixels and zero
ezdxf audit errors/fixes. The focused suite passed 67 tests; the final full
suite includes the runtime-independence and unchanged review/save regressions.

All 74 production-reachable modules imported successfully. Compile smoke,
Ruff, the existing four-file mypy check, architecture verification and the
three-input compact preservation check passed. YAML workflows and PowerShell
scripts parsed; both Windows build workflows derive the numeric installer
version from the same existing `parse_version` function. Windows smoke was
executed through a temporary launcher of the actual source CLI. This does not
claim a local PyInstaller/Inno installer build or CAD-application validation.

The human version remains in one maintained source. PyInstaller still imports
`app.version`; Windows resource numbers discard the `-dev` suffix and append
a fourth zero (0.3.0.0), while display strings retain it. The installer uses
the same conversion for numeric resource fields and the human version for
display. Inno requires dotted numeric binary versions; see its
[VersionInfoVersion documentation](https://jrsoftware.org/ishelp/topic_setup_versioninfoversion.htm).
README/CHANGELOG point to the version source; numbers here are recorded results,
not additional runtime/build version definitions.

Active script callers no longer pass the retired CLI flags. Release smoke
steps now forward their required ExpectedVersion argument. The Windows smoke
script checks the current member_counts.straight_lines field and current
corrected.png/contours.png debug outputs. CLI reports include the source-derived
application_version required by that smoke check.

The two moved Junction JSON resources were compared byte-for-byte with their
original committed contents. Consumer and packaging resource paths changed;
serialized identifiers, digests and existing consumer validation semantics did
not. No geometry algorithm, reconciliation source, wrapper chain or product
feature was added or redesigned.

The external `architecture-audit-v1/DRAFTSMAN-REFACTOR-COMPLETION-REPORT.md`
was corrected in place. The original compact baseline remains intact with
its generation provenance documented as UNPROVEN / UNKNOWN. Genuine archived
PRE/current evidence and its three-input, 300 DPI, OCR-off limits are documented
in [historical-evidence.md](historical-evidence.md) and retained in
[historical-verification-summary.json](historical-verification-summary.json).
This cannot prove all OCR output or all engineering drawings mathematically
equivalent. The external historical directory is not a startup, processing,
export or test dependency; the fresh-process guard also rejects access to it.
No Git/current commit hash/SHA manifest/local-artifacts runtime dependency was
introduced. No parent Git metadata was operated on or repaired.

Validation outputs: [full pytest](closeout-full-tests.txt),
[CLI help/version](closeout-cli-smoke.txt),
[architecture](architecture-after.json),
[current compact preservation check](closeout-preservation.json).

Code commits:

- `385f87b`: test: restore scan-underlay export regression coverage
- `898075adaee9031c05a91cd8bf0da3d0329d37c6`: maintenance: finalize Image to CAD naming, versioning and terminology

Validated code revision is the second commit above. A third, documentation-only
commit records this report and evidence; its final revision and clean worktree
status are reported in the closing chat message. Git revisions are developer
locators, not human product versions. Closeout is complete; further architecture
refactoring is not required by the retained algorithm size or metrics.

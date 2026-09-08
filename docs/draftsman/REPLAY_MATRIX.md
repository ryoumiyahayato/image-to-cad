# Draftsman fresh-clone replay matrix

This is the canonical command index for the shadow Draftsman architecture.
Read [CURRENT_STATE.md](CURRENT_STATE.md) first. All inputs below are tracked;
`local-artifacts` is an optional disposable output location, never an input.

## Bootstrap

From the repository root on any Python 3.11 host:

```text
cd cad_photo_to_dxf
python -m venv .venv
# activate .venv using the host shell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-test.txt
python -m pytest -q tests/test_draftsman_cloud_readiness.py
```

On Linux CI, Qt requires the system libraries listed in `.github/workflows/ci.yml`.
Use any disposable `<out>` directory. JSON is authoritative for machine checks;
PNG/DXF previews are diagnostic or final-UAT aids.

## Replays

Commands run from `cad_photo_to_dxf/`.

| Slice | Purpose | Tracked input | Command / test target | Expected structured artifacts | Visual inspection | Cloud suitability |
|---|---|---|---|---|---|---|
| VS1 | Vector table rule Evidence -> Logical -> CAD IR | `tests/real_regression/assets/sources/warehouse-electrical-vector.pdf`, page 1 | `python scripts/generate_draftsman_vs1.py --source tests/real_regression/assets/sources/warehouse-electrical-vector.pdf --source-document-id warehouse-electrical-vector-pdf --page 1 --expected-logical-count 19 --output-dir <out>` | Evidence summary, logical entities, CAD IR, report | Not required for development gate; preview is diagnostic | CLOUD_READY |
| VS2 | Vector electrical C1 symbol and four connections | same PDF, page 2 | `python scripts/generate_draftsman_vs2.py --source tests/real_regression/assets/sources/warehouse-electrical-vector.pdf --source-document-id warehouse-electrical-vector-pdf --page 2 --output-dir <out>` | Domain decision, logical entities, CAD IR, report | Not required for focused machine gate | CLOUD_READY |
| VS3 | Raster electrical five-instance slice | `tests/real_regression/assets/environment-page-003.png`, page 3 | `python scripts/generate_draftsman_vs3.py --source tests/real_regression/assets/environment-page-003.png --source-document-id environment-plan-page-003-150dpi --page 3 --output-dir <out>` | Evidence, domain decision, logical entities, CAD IR, report | Not required for focused machine gate | CLOUD_READY |
| family audit | Evaluate the frozen VS3 rule over 38 reference instances | 150 DPI raster plus `tests/real_regression/assets/references/environment-page-003-smoke-family-v1.json` | `python scripts/generate_draftsman_vs3_family_audit.py --source tests/real_regression/assets/environment-page-003.png --reference tests/real_regression/assets/references/environment-page-003-smoke-family-v1.json --output-dir <out>` | Family audit, exceptions, logical entities, CAD IR, report | Not required to reproduce counts; final semantic review remains human | CLOUD_READY |
| E1 | Validate high-recall domain-neutral raster Evidence and frozen downstream | 150 DPI raster, smoke reference, and tracked evidence baseline | `python -m pytest -q tests/test_draftsman_vs3_e1.py` | Test validates evidence-family audit, candidates, comparison, exceptions, and report in temporary output | Not required | CLOUD_READY; no dedicated persistent generator CLI |
| T1 | Orientation-neutral degree 1/2/3 topology | 150 DPI raster plus smoke reference | `python scripts/generate_draftsman_vs3_t1.py --source tests/real_regression/assets/environment-page-003.png --reference tests/real_regression/assets/references/environment-page-003-smoke-family-v1.json --output-dir <out>` | Hypotheses, topology decisions, logical entities, CAD IR, family audit, comparison | Not required for machine gate | CLOUD_READY |
| U1 | Preserve source-backed geometry with unverified semantics | 150 DPI raster plus smoke reference | `python scripts/generate_draftsman_vs3_u1.py --source tests/real_regression/assets/environment-page-003.png --reference tests/real_regression/assets/references/environment-page-003-smoke-family-v1.json --output-dir <out>` | Unverified entities, review items, CAD IR, family audit, comparison | Not required for machine gate; preview is diagnostic | CLOUD_READY |
| QA1 | Reference-free disposition and lineage audit, with separate post-hoc evaluation | 150 DPI raster plus smoke reference | `python scripts/generate_draftsman_qa1.py --source tests/real_regression/assets/environment-page-003.png --source-document-id environment-plan-page-003-150dpi --source-page 3 --reference tests/real_regression/assets/references/environment-page-003-smoke-family-v1.json --output-dir <out>` | Disposition ledger, findings, lineage summary, measurement-only signals, separate reference evaluation | Not required | CLOUD_READY |
| QA2-S1 | Independent source-coverage measurement | 150 DPI raster plus smoke reference | `python scripts/generate_draftsman_qa2_s1.py --source tests/real_regression/assets/environment-page-003.png --source-document-id environment-plan-page-003-150dpi --source-page 3 --reference tests/real_regression/assets/references/environment-page-003-smoke-family-v1.json --output-dir <out>` | Source regions, explained map, residual regions, baseline comparison, separate reference evaluation | Not required; output is measurement-only | CLOUD_READY |
| QA2-S2 | Frozen reference-free source-risk triage | 150 DPI raster plus smoke reference | `python scripts/generate_draftsman_qa2_s2.py --source tests/real_regression/assets/environment-page-003.png --source-document-id environment-plan-page-003-150dpi --source-page 3 --reference tests/real_regression/assets/references/environment-page-003-smoke-family-v1.json --output-dir <out>` | Frozen config, controls, feature audit, residual clusters, tiered signals, comparison, separate reference evaluation | Not required; output is measurement-only and not actionable | CLOUD_READY on the Golden fixture; cross-drawing guard limitation documented in current state |

## Representative fresh-clone path

VS1 is the smallest complete representative architecture slice. A successful
run writes deterministic JSON describing source Evidence, 19 Logical table
rules, and 19 editable CAD IR lines. Read the JSON first; the generated DXF/PNG
does not replace structured validation or final local CAD UAT.

The following distinctions are mandatory when interpreting output:

- runtime result versus post-hoc reference evaluation;
- accepted result versus provisional/unresolved result;
- actionable QA1 finding versus QA1/QA2 measurement-only signal;
- evaluated-subset denominator versus full-source coverage.

LibreCAD, ODA/DWG, final visual Golden acceptance, and final workflow timing
remain local UAT. They are not prerequisites for changing and testing the
shadow architecture online.

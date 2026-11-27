# Acceptance gates

A phase may pass only when every gate in its declared scope passes. “Not tested” is not “pass.”

## G1 — Automated test gate

Required evidence:

- focused tests for the changed contract;
- full relevant unit suite;
- lint/static checks;
- exact command, commit, result, warnings, and artifact path;
- no update to a regression baseline merely to absorb deterioration.

Automated tests cannot close a human UAT failure by themselves.

## G2 — DXF entity audit gate

Each final DXF is audited independently for:

- readability by the audit library;
- native `TEXT` counts and text contents;
- invalid geometry and non-finite values;
- layer existence/default state;
- `SOURCE_TEXT_OUTLINE` off and frozen;
- entity-type preservation;
- duplicate visible text representations;
- semantic ownership conflicts;
- unexpected repaired-line or large-span entities;
- read-save-read persistence.

Aggregate totals supplement, but never replace, per-DXF results.

## G3 — LibreCAD edit/save gate

Representative real DXFs must be opened in the target LibreCAD version.

Required operation:

1. select native Chinese, numeric, and English text where present;
2. confirm entity type is `TEXT`;
3. edit content;
4. save a copy;
5. close LibreCAD completely;
6. reopen the copy;
7. confirm entity type and edited Unicode content persist.

Current evidence: passed on two real DXFs for Chinese edit persistence. P1 and later phases must repeat this on changed outputs.

## G4 — Per-page visual gate

Every real page and final DXF receives an independent visual result for:

- global position, scale, and clipping;
- text height, width, insertion, baseline, rotation, and overlap;
- cell/border overflow;
- vertical and rotated text;
- ordinary text in symbol layers;
- source-outline default visibility;
- structure completeness;
- repaired-line accuracy and protected-region crossings;
- formal versus diagnostic display.

Coverage must identify exactly which pages were human-inspected.

## G5 — Regression safety gate

The following contracts are non-negotiable:

- no full-page topology repair;
- no endpoint-only bridge acceptance;
- full candidate repair path remains inside a valid structural region/corridor;
- no text/logo/signature/protected-object crossing;
- native text count does not decline without documented OCR evidence;
- trusted native `TEXT` does not become outline/image geometry;
- `replacement_safe` does not block text emission;
- GUI, cache, and DXF use the same `FinalStructure`;
- phase-12 baseline is not moved;
- regression fixtures are not rewritten to conceal failure.

## G6 — P1 geometry gate

P1 additionally requires:

- one audited geometry-creation path or an explicitly documented reason for multiple paths;
- per-entity OCR content, bbox/quad, direction, confidence, metric source, height, width factor, insertion/alignment, rotation, predicted DXF bounds, overflow, center, and baseline diagnostics;
- no systematic oversized text;
- no broad text overlap;
- no systematic cell/border overflow;
- horizontal, 90°, and 270° samples pass;
- abnormal boxes have explicit fallback/reason codes;
- eligible native-text count and entity type are preserved;
- user LibreCAD confirmation.

## G7 — Structure-repair gate

P4 additionally requires per-page:

- precision, recall, and F1;
- number and span of added lines;
- text/logo/signature crossings;
- open-space and page-wide erroneous bridges;
- `REPAIRED_STRUCTURE` isolation and visibility control;
- generation reason and source support for every repair.

Recall improvement never permits a safety-contract failure.

## G8 — Release gate

Release requires all of the following:

- P1 through P5 accepted;
- complete P6 per-page and per-DXF evidence;
- user approval;
- clean repository/worktree evidence from a tag-capable Git client;
- exact release commit and immutable tag;
- CI/check-suite result verified;
- installer and portable-package tests;
- no open release blocker in [ISSUE_REGISTER.md](ISSUE_REGISTER.md).

GitHub “mergeable” is not a release gate.

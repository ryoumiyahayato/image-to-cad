# Current task

## Authorized scope

**Establish the project-management and audit system. Do not modify production code.**

Phase: P0  
Branch: `fix/non-destructive-editable-text`  
Task-start HEAD: `7b5592e249aa9146660caec07ce8fa0293cfdb2e`  
PR: [#23](https://github.com/ryoumiyahayato/image-to-cad/pull/23)

## Allowed changes

Only the ten Markdown governance files under `docs/project/`.

## Prohibited changes

- production Python;
- OCR content or thresholds;
- DXF entity generation or text geometry;
- GUI and PDF export behavior;
- `FinalStructure`;
- source-outline, ownership, logo, or signature logic;
- structure detection or line repair;
- colors and layer behavior;
- tests and regression baselines;
- large generated artifacts.

## Deliverable

Create the status, UAT, roadmap, decisions, issues, acceptance gates, protocol, current task, next task, and checkpoint records; validate their internal links and basic Markdown formatting; commit them together; stop.

## Stop condition

P0 documentation commit exists on the authorized branch. P1 is not started.

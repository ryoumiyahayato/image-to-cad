# CAD and FreeCAD Requirements Migrated from Badge Relief Maker

## Purpose

This document records the CAD-specific requirements found during a repository-wide audit of
[`ryoumiyahayato/badge-relief-maker`](https://github.com/ryoumiyahayato/badge-relief-maker)
and assigns them to this repository.

No Badge Relief Maker application code, mesh-generation code, or CNC/mould release evidence is
copied here. The audited source repository did not contain a photo-to-DXF implementation or native
DXF/DWG/STEP/IGES converter that could be migrated as code.

## Source audit

Reviewed on 2026-07-11:

- `badge-relief-maker/docs/RELEASE_POLICY.md`: declares that Badge Relief Maker version numbers
  are independent of the CAD Photo to DXF project.
- `badge-relief-maker/docs/REQUIREMENTS_TRACEABILITY.md`: contains requirement
  `BRM-CAM-017`, “two-tool FreeCAD workflow”, with status `pending`.

These two references are the only explicit cross-project CAD/FreeCAD items identified. General
OBJ/STL/GLB output, slicer checks, CNC machining, mould, and physical-part validation remain owned
by Badge Relief Maker because they validate its relief-manufacturing workflow rather than
photo-to-DXF conversion.

## Migrated requirements

### CAD-MIG-001 — Independent version namespace

This project's releases, tags, changelog, artifacts, and compatibility claims must use the
`cad_photo_to_dxf_mvp` version namespace. They must not inherit, mirror, or imply compatibility
from a Badge Relief Maker version number.

Acceptance criteria:

1. Release tags and displayed versions are generated only from this repository.
2. Documentation never describes a Badge Relief Maker version as this project's version.
3. Cross-project references identify both repository name and exact commit or release.
4. A Badge Relief Maker release in progress is not modified or reused by this project.

### CAD-MIG-002 — Optional two-tool FreeCAD validation

Provide a reproducible FreeCAD-based validation path for generated DXF files. This is an optional
independent-tool check, not a claim that FreeCAD is the runtime engine of the converter.

The validation must:

1. Import a generated DXF into a pinned and recorded FreeCAD version.
2. Verify document units and intended scale.
3. Verify overall extents against the source fixture's expected dimensions and tolerance.
4. Verify required layers and entities are present.
5. Report open versus closed geometry and flag unexpected gaps, self-intersections, duplicate
   entities, or zero-length segments.
6. Save machine-readable results and enough provenance to reproduce the check.
7. Fail with a non-zero exit status when a mandatory criterion is not met.

Minimum evidence for each run:

- source image fixture path and SHA-256;
- generated DXF path and SHA-256;
- application version and Git commit;
- operating system, FreeCAD version, and validator version;
- command line or workflow run URL;
- measured units, extents, layer/entity counts, topology findings, pass/fail status, and timestamp.

Status: **pending** until both the validator and retained execution evidence exist in this
repository. Documentation alone does not satisfy this requirement.

## Ownership boundary

| Concern | Owning repository |
| --- | --- |
| Photo/vector input to DXF conversion | `cad_photo_to_dxf_mvp` |
| DXF units, layers, entities, geometry, and FreeCAD validation | `cad_photo_to_dxf_mvp` |
| Relief mesh generation and OBJ/STL/GLB export | `badge-relief-maker` |
| Relief slicer, CNC, mould, and physical-part validation | `badge-relief-maker` |
| Versioning, releases, and evidence | Each repository independently |

A downstream workflow may consume artifacts from both repositories, but that integration must pin
each artifact to an immutable commit or release and must not blur ownership or version numbers.

## Implementation path

1. Add a small deterministic DXF fixture set with expected units, dimensions, layers, entity
   counts, and known topology failures.
2. Add a headless FreeCAD validator under this repository's validation tooling.
3. Emit a versioned JSON report using the evidence fields listed above.
4. Add unit tests for report parsing and failure thresholds.
5. Add an optional CI/manual workflow that installs a pinned FreeCAD version, runs the validator,
   uploads the JSON report and tested DXF files, and records artifact hashes.
6. Link the retained workflow run or release artifact from the requirement traceability document.
7. Change `CAD-MIG-002` from `pending` only after the evidence is reviewed.

## Notes

- Do not treat successful DXF parsing as proof of dimensional or manufacturing correctness.
- Keep tolerances explicit and fixture-specific.
- Do not commit generated build directories, credentials, local FreeCAD preferences, or
  machine-specific absolute paths.
- Do not modify an active Release workflow merely to attach this migration document.

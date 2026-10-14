# Repository hygiene inventory

Base HEAD: `80be85aba985e457bc7bff1e9ece49f50e7a46d2`; findings: **94**.

## 1. `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/#environment-page-003-full-v2.dxf`

- Original finding: `generated output file is tracked`; size `2633289` bytes; extension `.dxf`.
- Git blob SHA-1: `57a9bae14658e20caa0358d3b21d78873829846d`; worktree SHA256: `4ada9d75e30fc28e805612a8845b9fb5dab3a957262da0d392db01375cc47196`; canonical Git blob SHA256: `7911136b10af2b6af6f9942d3b145053b9e9265f56edc64014a07b8d58d34bed`; canonical size: `2389227`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 2. `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/#warehouse-page-001-full-v2.dxf`

- Original finding: `generated output file is tracked`; size `307506` bytes; extension `.dxf`.
- Git blob SHA-1: `6925ea0de5dd6169cb2b7a030e58cdb862b60593`; worktree SHA256: `1ef0577a81103aabda0b3843254d7ae1e91479dfe3014c9f58cfca0bbb34d0e8`; canonical Git blob SHA256: `119a3bfd668dde46a86964e113081bc0c01c3ffde7e14b91277dd41ae43df75b`; canonical size: `277650`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 3. `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/#warehouse-page-001-full.dxf`

- Original finding: `generated output file is tracked`; size `443797` bytes; extension `.dxf`.
- Git blob SHA-1: `f18b46ca1a7d30258c6dd37a83428eeb284569f2`; worktree SHA256: `63b0272b67b6da131fea52b1a2a14b90f08ec8c1b7ad807310ff7b8082dc6cf3`; canonical Git blob SHA256: `e8ecee1c1e0bbd89a4df3a54dab2acc079b22f8bd9b043c33548b6a89057bff6`; canonical size: `401741`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 4. `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/environment-page-003-full-v2.dxf`

- Original finding: `generated output file is tracked`; size `2662209` bytes; extension `.dxf`.
- Git blob SHA-1: `08695469afe81e64ba9c73f5e6f0bcf235e40ff4`; worktree SHA256: `b2a6a232e379d9ab8425cb574e7fe1bdf42f96c2220f4407d3f3c6fd2acaf0a8`; canonical Git blob SHA256: `7a2230aa4df28e86e899168fb5a0408b71b4b829ae8305d54599a8f3c178649f`; canonical size: `2419357`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/environment-page-003-full-v2.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 5. `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/warehouse-page-001-full-v2.dxf`

- Original finding: `generated output file is tracked`; size `336302` bytes; extension `.dxf`.
- Git blob SHA-1: `4bc7207266358b1567c8ca1ec71416bc44fe4863`; worktree SHA256: `6755248098d691e2136dbb3b3ecfcfcecf3c80dc3555c5f823fc49a0912846d0`; canonical Git blob SHA256: `b5e42297ea40a13e75e9b6738712d34f4ad9077eb5817d1abd1fa50500f157b2`; canonical size: `302054`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/warehouse-page-001-full-v2.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 6. `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/warehouse-page-001-full.dxf`

- Original finding: `generated output file is tracked`; size `471916` bytes; extension `.dxf`.
- Git blob SHA-1: `a8515670ff99b75595d29a3a462dd465fa36fc4e`; worktree SHA256: `7d947d008e8f6aed70c90cca2b45e6bf61e67da2aa8d28646db4819ae1cb8fb7`; canonical Git blob SHA256: `f8d0072ad43b60e603389c89ed2568515dc80e8898c1f9773d7fc4da627da5b4`; canonical size: `425956`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/warehouse-page-001-full.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 7. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-plan-page-003-150dpi.dxf`

- Original finding: `generated output file is tracked`; size `1951803` bytes; extension `.dxf`.
- Git blob SHA-1: `24b49c5d3c42e9207272808157ad4b02ff0b7dac`; worktree SHA256: `3d8abd9aa5747a36b4f2a274e286792ed458488a0a239cfe63568b79427db177`; canonical Git blob SHA256: `3f5596537524539431127ba66e02200b961c6e935ed04fc26e6418f069780314`; canonical size: `1645755`.
- First introduced commit: `None` (None); subject: None.
- References (16 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:310:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:310:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-plan-page-003-150dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:115:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:92:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:30:      "path": "validation/editable-text-recovery/before/dxf/environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:335:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:310:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:310:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:310:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:335:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\environment-plan-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:92:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\environment-plan-page-003-150dpi.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 8. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-001-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1735834` bytes; extension `.dxf`.
- Git blob SHA-1: `bc75697c68b861435f45f7e95016cdf95d9284ad`; worktree SHA256: `b9c95d5d51cdd6c7af4bd494c7e9ef71636f12c0f508b93902733d28f80109f7`; canonical Git blob SHA256: `1a58cee0e7706e2669eb24901cc0c3bcb1577007526c607e7dbb469d2db589ca`; canonical size: `1461572`.
- First introduced commit: `None` (None); subject: None.
- References (32 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:682:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:682:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-001-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:240:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:190:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:64:      "path": "validation/editable-text-recovery/before/dxf/environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:742:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:682:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:682:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:682:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:742:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\environment-scan-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:190:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\environment-scan-page-001-120dpi.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 9. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-002-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1489502` bytes; extension `.dxf`.
- Git blob SHA-1: `e5974980b2af74d1492f62fee419ad2c7550976a`; worktree SHA256: `3ed6202d106eeac6f5cea864c5416e9d55bf2aca04423e842bb856937a9e35c2`; canonical Git blob SHA256: `bce897eb8bfd665c5d179c61e1da0789878d5bb1dbdfe8e7d5f19f7a0b6937be`; canonical size: `1253258`.
- First introduced commit: `None` (None); subject: None.
- References (16 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:845:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:845:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-002-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:304:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:240:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:98:      "path": "validation/editable-text-recovery/before/dxf/environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:923:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:845:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:845:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:845:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:923:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\environment-scan-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:240:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\environment-scan-page-002-120dpi.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 10. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-004-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1709392` bytes; extension `.dxf`.
- Git blob SHA-1: `a0efb93db33c1aaf364fbdf3b34b945e22f7fc84`; worktree SHA256: `72d556215eb428d7517525eb86f00da75d41c9f958a7edf54007ef6c2b436c15`; canonical Git blob SHA256: `844f7bc3af422dd3d20191503851610b30d526b66957aa569f51218a340c9770`; canonical size: `1438800`.
- First introduced commit: `None` (None); subject: None.
- References (16 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:1032:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:1032:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-004-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:365:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:289:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:131:      "path": "validation/editable-text-recovery/before/dxf/environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:1127:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:1032:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:1032:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:1032:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:1127:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\environment-scan-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:289:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\environment-scan-page-004-120dpi.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 11. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-008-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1251244` bytes; extension `.dxf`.
- Git blob SHA-1: `b889314e456931fe09f91eb20a1b576403ccfa56`; worktree SHA256: `ad3d22505fa8a95edf92ec8778e83539245ab3a9b392e29d56c306d671389e12`; canonical Git blob SHA256: `14ec35a3020d62adc41e2573e26daea72e28309a6491f1e54e70e2ffc69863cd`; canonical size: `1053852`.
- First introduced commit: `None` (None); subject: None.
- References (16 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:1195:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:1195:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-008-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:429:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:338:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:165:      "path": "validation/editable-text-recovery/before/dxf/environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:1307:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:1195:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:1195:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:1195:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:1307:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\environment-scan-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:338:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\environment-scan-page-008-120dpi.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 12. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-014-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1795135` bytes; extension `.dxf`.
- Git blob SHA-1: `58f896386a614fd8757da1e054386cdbac9c038a`; worktree SHA256: `112f51c95ccc732d0d8d09aa2a91b3b5cff21fdda12768c9fc45abd52ca2fb43`; canonical Git blob SHA256: `b8dae40fe4b76492c0d87ea059c0c33e9de100f7cedde05f41ca6c67f909cc41`; canonical size: `1510671`.
- First introduced commit: `None` (None); subject: None.
- References (16 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:1406:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:1406:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-014-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:490:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:387:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:198:      "path": "validation/editable-text-recovery/before/dxf/environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:1535:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:1406:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:1406:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:1406:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:1535:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\environment-scan-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:387:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\environment-scan-page-014-120dpi.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 13. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/perspective-sample-plan.dxf`

- Original finding: `generated output file is tracked`; size `268338` bytes; extension `.dxf`.
- Git blob SHA-1: `2a89a3ef0581f21f60adc9de85afa6087167c4c1`; worktree SHA256: `4df98a54b7f6116c096f280fa878c880fe9008789b76681ec708d9feb873b758`; canonical Git blob SHA256: `193c0dea885e1cee539db651aa5c5b059deb30d19491f2fa8570f1281889dfe0`; canonical size: `226148`.
- First introduced commit: `None` (None); subject: None.
- References (15 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:121:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:121:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:54:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:45:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:229:      "path": "validation/editable-text-recovery/before/dxf/perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:130:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:121:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:121:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:121:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:130:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:45:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\perspective-sample-plan.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-real-regression.json:130:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-real-regression-artifacts\\perspective-sample-plan.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 14. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/warehouse-index-page-001-150dpi.dxf`

- Original finding: `generated output file is tracked`; size `571044` bytes; extension `.dxf`.
- Git blob SHA-1: `72cc3cd3478596c9f825825b06389cf3a3b2f126`; worktree SHA256: `e4b4a62ede0412466a5c310527d11ff6ab9807b0afbc4fee77f93273b3fe7715`; canonical Git blob SHA256: `8794f4514effd0eea5a941018f6d2f4eb652e15b196a498d8b43a4540a5d527b`; canonical size: `482508`.
- First introduced commit: `None` (None); subject: None.
- References (16 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:472:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:472:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/warehouse-index-page-001-150dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:176:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:141:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:262:      "path": "validation/editable-text-recovery/before/dxf/warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:514:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:472:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:472:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:472:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:514:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\warehouse-index-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:141:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\warehouse-index-page-001-150dpi.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 15. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/warehouse-plan-page-003-72dpi.dxf`

- Original finding: `generated output file is tracked`; size `1118604` bytes; extension `.dxf`.
- Git blob SHA-1: `2b500f05d55c2fb51b924f21a352b3d9b2004548`; worktree SHA256: `a237b4a06b503366f428da16049f02c0a9331f8a08ebd267e15b46071f0a59a0`; canonical Git blob SHA256: `d1153b19f349542bb4d902f5356b9ca0e63a634bb0fc4522938a300c39860659`; canonical size: `944410`.
- First introduced commit: `None` (None); subject: None.
- References (16 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:1733:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:1733:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/warehouse-plan-page-003-72dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:618:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:486:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:296:      "path": "validation/editable-text-recovery/before/dxf/warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:1897:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:1733:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:1733:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:1733:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:1897:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\warehouse-plan-page-003-72dpi.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:486:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\warehouse-plan-page-003-72dpi.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 16. `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/warehouse-system-page-002-72dpi.dxf`

- Original finding: `generated output file is tracked`; size `794781` bytes; extension `.dxf`.
- Git blob SHA-1: `a05b2b6b777a4ef8a56911032638722be5bbbc3b`; worktree SHA256: `5a4ba0e2f745913ff875e442b3f7d1cbee33102d218f2742f0cabb3241bd4451`; canonical Git blob SHA256: `8e7b6b72fe4aa5a47caa369411f33e3f2fbf65a17a904cf6026d143b48577ddb`; canonical size: `671103`.
- First introduced commit: `None` (None); subject: None.
- References (16 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/connectivity/phase7-real-regression.json:1569:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase7-final-strict-artifacts\\warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/content-ownership/phase8-real-regression.json:1569:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase8-strict-current-artifacts\\warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/warehouse-system-page-002-72dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/formal-dxf-inventory.json:554:      "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/before/text-contract.json:436:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\before\\dxf\\warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:330:      "path": "validation/editable-text-recovery/before/dxf/warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/final-acceptance/phase12-real-regression.json:1715:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase12-real-regression-artifacts\\warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-real-regression.json:1569:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-real-regression-artifacts\\warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/logo-signature/phase9-recording.json:1569:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase9-recording-artifacts\\warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/structural-roi/phase6-real-regression.json:1569:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase6-real-regression-artifacts\\warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/template-cache-gui/phase11-real-regression.json:1715:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase11-real-regression-artifacts\\warehouse-system-page-002-72dpi.dxf",`; `cad_photo_to_dxf/validation/text-output-contract/phase10-after.json:436:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\output\\ci\\phase10-text-contract-artifacts\\warehouse-system-page-002-72dpi.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 17. `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit1-page001.dxf`

- Original finding: `generated output file is tracked`; size `3171205` bytes; extension `.dxf`.
- Git blob SHA-1: `1b1f67ae892e0086e981847a4d029c03a2922626`; worktree SHA256: `39fb2f81c6263a864de1d8a0cdcd2dd0ec8fc9ccc440f21cc034060016dd58d8`; canonical Git blob SHA256: `e69d91ccf2be0610d97c1372e039c3aa04ba94ac2d801cde49d89e9f6994729f`; canonical size: `2678835`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit1-git-status-before.txt:12:added=validation/editable-text-recovery/checkpoints/commit1-page001.dxf`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit1-page001.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit1-page001.json:5621:  "dxf": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\checkpoints\\commit1-page001.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:363:      "path": "validation/editable-text-recovery/checkpoints/commit1-page001.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 18. `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit2-page001.dxf`

- Original finding: `generated output file is tracked`; size `3176838` bytes; extension `.dxf`.
- Git blob SHA-1: `e59e2aee2c4861c080b370f937243a759321bbf5`; worktree SHA256: `7e7652c750230fa43401ad5405124e754d0d5bbb5e538b1672a400958c3ceb8e`; canonical Git blob SHA256: `dcd4dd7999e263a3269692c9d2b821c7bea03b1d359d878576372f577dfc8546`; canonical size: `2684444`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit2-git-status-before.txt:14:added=validation/editable-text-recovery/checkpoints/commit2-page001.dxf`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit2-page001.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit2-page001.json:5621:  "dxf": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\checkpoints\\commit2-page001.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:397:      "path": "validation/editable-text-recovery/checkpoints/commit2-page001.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 19. `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit3-page001.dxf`

- Original finding: `generated output file is tracked`; size `3300010` bytes; extension `.dxf`.
- Git blob SHA-1: `4424c5f93507513a3b8789ff8f1c99502ff66fec`; worktree SHA256: `0261181ad38659524775b8e63ea27f53db16222fc9977b315e81c6d82b869cf2`; canonical Git blob SHA256: `5335edeaf74b3b181f38a6566d21f8ab2b5f09f5bc81f2301718e969eb27fd7a`; canonical size: `2788208`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit3-git-status-before.txt:18:?? validation/editable-text-recovery/checkpoints/commit3-page001.dxf`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit3-page001.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit3-page001.json:5831:  "dxf": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\checkpoints\\commit3-page001.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:431:      "path": "validation/editable-text-recovery/checkpoints/commit3-page001.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 20. `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-librecad-editability-edited.dxf`

- Original finding: `generated output file is tracked`; size `22802` bytes; extension `.dxf`.
- Git blob SHA-1: `a82e8c9d60309c64e36fd44761f9b2ad6b8b5d68`; worktree SHA256: `1e5a712cee9a46f3aa0b4c512fa9c4eb443d0f441d85c9cdcb30543d71546900`; canonical Git blob SHA256: `a7f0067d90d6596bb948b1dee6f6492f442c546a19cb5dacaba8252a2bf58f43`; canonical size: `19512`.
- First introduced commit: `fc6cd80d794a9557485fb6d59fb63a376a6deeef` (2026-07-31T00:43:46+08:00); subject: 'fix: fit native text geometry to OCR bounds'.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-git-status-before.txt:13:?? validation/editable-text-recovery/checkpoints/commit4-librecad-editability-edited.dxf`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-librecad-editability.json:33:    "saved_as": "commit4-librecad-editability-edited.dxf"`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-librecad-editability.json:36:    "path": "commit4-librecad-editability-edited.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:460:      "path": "validation/editable-text-recovery/checkpoints/commit4-librecad-editability-edited.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 21. `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-librecad-editability-original.dxf`

- Original finding: `generated output file is tracked`; size `46137` bytes; extension `.dxf`.
- Git blob SHA-1: `869b01f238b4f58f46bd094d57f8adb8bdb5b089`; worktree SHA256: `694be3a8350fccdc01d5a4178ed94f7adf53079ee27789b47c609e884489f953`; canonical Git blob SHA256: `b3d601650ff358e859a44540666ce8322f08c77eeadb395edef4750e6097e7bd`; canonical size: `38615`.
- First introduced commit: `fc6cd80d794a9557485fb6d59fb63a376a6deeef` (2026-07-31T00:43:46+08:00); subject: 'fix: fit native text geometry to OCR bounds'.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-git-status-before.txt:14:?? validation/editable-text-recovery/checkpoints/commit4-librecad-editability-original.dxf`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-librecad-editability-original.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-librecad-editability.json:18:    "path": "commit4-librecad-editability-original.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:489:      "path": "validation/editable-text-recovery/checkpoints/commit4-librecad-editability-original.dxf",`
- Generated: `True`; test input: `True`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 22. `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-librecad-editability-roundtrip.dxf`

- Original finding: `generated output file is tracked`; size `29352` bytes; extension `.dxf`.
- Git blob SHA-1: `9d7551dd8d595c621cb65b5682056dd6be1aca85`; worktree SHA256: `53714c91f41065de04999f0b7807b04e650e353019193185afd06504cc19849a`; canonical Git blob SHA256: `94a1f4b4d37cdfbfa4a8a4099f66636897c5fb9ef83b134ed95885065fb793fc`; canonical size: `24732`.
- First introduced commit: `fc6cd80d794a9557485fb6d59fb63a376a6deeef` (2026-07-31T00:43:46+08:00); subject: 'fix: fit native text geometry to OCR bounds'.
- References (3 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-git-status-before.txt:15:?? validation/editable-text-recovery/checkpoints/commit4-librecad-editability-roundtrip.dxf`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-librecad-editability.json:46:    "path": "commit4-librecad-editability-roundtrip.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:518:      "path": "validation/editable-text-recovery/checkpoints/commit4-librecad-editability-roundtrip.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 23. `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-page001.dxf`

- Original finding: `generated output file is tracked`; size `3366214` bytes; extension `.dxf`.
- Git blob SHA-1: `9fc355d401af9d25cae9968b83178496f714cc15`; worktree SHA256: `6348332a95cd442827778ed6f78925cd7f57ce4827893a83dfec61b7be2ce4a7`; canonical Git blob SHA256: `9dc375b18f99a4642079569c3cf8ae99ca73bd69bb709e68121641bff88ebb9f`; canonical size: `2848218`.
- First introduced commit: `None` (None); subject: None.
- References (3 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-git-status-before.txt:16:?? validation/editable-text-recovery/checkpoints/commit4-page001.dxf`; `cad_photo_to_dxf/validation/editable-text-recovery/checkpoints/commit4-page001.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:552:      "path": "validation/editable-text-recovery/checkpoints/commit4-page001.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 24. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-001-120dpi/environment-formal-page-001-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1939410` bytes; extension `.dxf`.
- Git blob SHA-1: `3c291b8c874126e6d379506513555c0ad556a02a`; worktree SHA256: `45dbf6ffd4976d6363a99b78ef5db5741d32d4431827112e159a9140cd6e41ea`; canonical Git blob SHA256: `dff2c3dd3e7e1bcbc21ffbecfa3459d0d1837105229922667fd48f686e9308a5`; canonical size: `1637294`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:586:      "path": "validation/editable-text-recovery/pages/environment-formal-page-001-120dpi/environment-formal-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-001-120dpi/environment-formal-page-001-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-001-120dpi\\environment-formal-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-001-120dpi/environment-formal-page-001-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:136:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-001-120dpi\\environment-formal-page-001-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 25. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-002-120dpi/environment-formal-page-002-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1575684` bytes; extension `.dxf`.
- Git blob SHA-1: `ea09268fbd1dabf127b5b3cda76278f2880d2bfd`; worktree SHA256: `04767d352939b2abd15e22c4ab87c649c2444867b6f2ad3f23e2e072270287c9`; canonical Git blob SHA256: `2b9d829de5bf33a1a04a9791d3334853f9cc0509817e19a269a49162f6604e0b`; canonical size: `1328428`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:620:      "path": "validation/editable-text-recovery/pages/environment-formal-page-002-120dpi/environment-formal-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-002-120dpi/environment-formal-page-002-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-002-120dpi\\environment-formal-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-002-120dpi/environment-formal-page-002-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:145:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-002-120dpi\\environment-formal-page-002-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 26. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-003-150dpi/environment-formal-page-003-150dpi.dxf`

- Original finding: `generated output file is tracked`; size `2098978` bytes; extension `.dxf`.
- Git blob SHA-1: `b7e53d9b6a558049fb09debc612b4aa9178123da`; worktree SHA256: `1243f3d198b207371281fc54cc25368d4b384be57773809ee93c856c1d719e81`; canonical Git blob SHA256: `c58736c6d28edaa9b18ed6145933f16e5bdba400c1406f1310c7ae06ff04bd11`; canonical size: `1774314`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:653:      "path": "validation/editable-text-recovery/pages/environment-formal-page-003-150dpi/environment-formal-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-003-150dpi/environment-formal-page-003-150dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-003-150dpi\\environment-formal-page-003-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-003-150dpi/environment-formal-page-003-150dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:253:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-003-150dpi\\environment-formal-page-003-150dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 27. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-004-120dpi/environment-formal-page-004-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1957922` bytes; extension `.dxf`.
- Git blob SHA-1: `c0d10aac80ecc3c6e593b573bbe04fbe4df7e045`; worktree SHA256: `d482f4eb898eeaa1766672a4211dd60a9f61a2580bb3e6b6028df55d19f989a3`; canonical Git blob SHA256: `78d2dfa9a9c2c60f8d57fa2bf0339aebad7a7efd6bd6c983381094c7b59bdb7d`; canonical size: `1653048`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:686:      "path": "validation/editable-text-recovery/pages/environment-formal-page-004-120dpi/environment-formal-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-004-120dpi/environment-formal-page-004-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-004-120dpi\\environment-formal-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-004-120dpi/environment-formal-page-004-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:154:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-004-120dpi\\environment-formal-page-004-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 28. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-008-120dpi/environment-formal-page-008-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1314525` bytes; extension `.dxf`.
- Git blob SHA-1: `881ced67f7a22eb2c7fa6959ab0a2eea9528b99b`; worktree SHA256: `f2292499dea8422527bc64f9905206f6ff86e603efaf6a95b0d76d118302e004`; canonical Git blob SHA256: `9d4e39eff91081b39444221baca240bb4fd047e9d344defb75757fdb161e289b`; canonical size: `1109193`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:720:      "path": "validation/editable-text-recovery/pages/environment-formal-page-008-120dpi/environment-formal-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-008-120dpi/environment-formal-page-008-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-008-120dpi\\environment-formal-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-008-120dpi/environment-formal-page-008-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:163:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-008-120dpi\\environment-formal-page-008-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 29. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-014-120dpi/environment-formal-page-014-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1983874` bytes; extension `.dxf`.
- Git blob SHA-1: `c51094a8d4a3eaf0dd97b7cd312b9295da35b106`; worktree SHA256: `69c48b02484136f11ef49f34beb26f9c5501f17e5cda2135fe1e45c41eb674eb`; canonical Git blob SHA256: `9c53e4b2d5a6f9a9825370d2427e024be906839858692682f74e2244416b9d14`; canonical size: `1674496`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:753:      "path": "validation/editable-text-recovery/pages/environment-formal-page-014-120dpi/environment-formal-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-014-120dpi/environment-formal-page-014-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-014-120dpi\\environment-formal-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-formal-page-014-120dpi/environment-formal-page-014-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:172:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-formal-page-014-120dpi\\environment-formal-page-014-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 30. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-001-120dpi/environment-source-page-001-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1912489` bytes; extension `.dxf`.
- Git blob SHA-1: `284e871cb3a9bdc78faa476137404ee4fa9ed421`; worktree SHA256: `0b5fa71326c0495ad1d0d20725ba6dc2b4390466832dc50e8bb7d8a2f3988796`; canonical Git blob SHA256: `2ee01abba30f97824b27872d55c923ed875c503d6ebc80fae977c8298823ab9a`; canonical size: `1614985`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:788:      "path": "validation/editable-text-recovery/pages/environment-source-page-001-120dpi/environment-source-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-001-120dpi/environment-source-page-001-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-001-120dpi\\environment-source-page-001-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-001-120dpi/environment-source-page-001-120dpi.dxf:3354:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:10:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-001-120dpi\\environment-source-page-001-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 31. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-002-120dpi/environment-source-page-002-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1545660` bytes; extension `.dxf`.
- Git blob SHA-1: `88c85c72689860e5076d185fd1f4a2ab8cfe110d`; worktree SHA256: `3b9eea09a51a09b2ae500bdeeb9aa3bb638d8e5c4ca3401635ad5dfdcffe83cf`; canonical Git blob SHA256: `955915af46649d961737186365276211d6a1c910b3f41eca49beea29d48075e0`; canonical size: `1303540`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:822:      "path": "validation/editable-text-recovery/pages/environment-source-page-002-120dpi/environment-source-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-002-120dpi/environment-source-page-002-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-002-120dpi\\environment-source-page-002-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-002-120dpi/environment-source-page-002-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:19:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-002-120dpi\\environment-source-page-002-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 32. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-003-120dpi/environment-source-page-003-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1751768` bytes; extension `.dxf`.
- Git blob SHA-1: `1bfc0c57e40d00189d22db07a678187f39e9f167`; worktree SHA256: `24b0e8bfbd2531e46f3a9406d3dcdab14d7ed2da0239ebc7d91620987814ea3a`; canonical Git blob SHA256: `f1ace54f9417544e5338f51d982518b961494d0d01ac710c32eaf53a8d1da31d`; canonical size: `1479860`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:856:      "path": "validation/editable-text-recovery/pages/environment-source-page-003-120dpi/environment-source-page-003-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-003-120dpi/environment-source-page-003-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-003-120dpi\\environment-source-page-003-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-003-120dpi/environment-source-page-003-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:28:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-003-120dpi\\environment-source-page-003-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 33. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-004-120dpi/environment-source-page-004-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1888484` bytes; extension `.dxf`.
- Git blob SHA-1: `9b7e845e54c56035701bf37cbb8027199f9f5feb`; worktree SHA256: `3139e7ab2f70ffdf86d1f18ffb289a85debc8de6859b22fd2460a7d54c51d9b4`; canonical Git blob SHA256: `c363ef36a697141ec7009a21980f0a45aec86e97c4d26e563e09a2584065f36d`; canonical size: `1594672`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:890:      "path": "validation/editable-text-recovery/pages/environment-source-page-004-120dpi/environment-source-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-004-120dpi/environment-source-page-004-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-004-120dpi\\environment-source-page-004-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-004-120dpi/environment-source-page-004-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:37:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-004-120dpi\\environment-source-page-004-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 34. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-005-120dpi/environment-source-page-005-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1701385` bytes; extension `.dxf`.
- Git blob SHA-1: `d5d6c33525ad411d847c304d4cef0c96e8506029`; worktree SHA256: `d9038e52ae5550c61b82cd94f0567462525354d94f8efaacdf0d955e6bd20c0a`; canonical Git blob SHA256: `f0d1fa3a40e49ba872b9f42429fb742d08b079f16ce82ac1cee0fa4ba8b45dd7`; canonical size: `1437057`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:923:      "path": "validation/editable-text-recovery/pages/environment-source-page-005-120dpi/environment-source-page-005-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-005-120dpi/environment-source-page-005-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-005-120dpi\\environment-source-page-005-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-005-120dpi/environment-source-page-005-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:46:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-005-120dpi\\environment-source-page-005-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 35. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-006-120dpi/environment-source-page-006-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1761256` bytes; extension `.dxf`.
- Git blob SHA-1: `566d53ef902edc82434411c07bd104320ba2765e`; worktree SHA256: `fa4242c5e6beae543328d948f5b74955ddb69b477d119a0dc855a73d8095a71c`; canonical Git blob SHA256: `a55cc3efff81444d4a9aa8c6b625d6592b0acb896cdb1074822b7ec58aaea2d2`; canonical size: `1487554`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:957:      "path": "validation/editable-text-recovery/pages/environment-source-page-006-120dpi/environment-source-page-006-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-006-120dpi/environment-source-page-006-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-006-120dpi\\environment-source-page-006-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-006-120dpi/environment-source-page-006-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:55:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-006-120dpi\\environment-source-page-006-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 36. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-007-120dpi/environment-source-page-007-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1782894` bytes; extension `.dxf`.
- Git blob SHA-1: `538d6d849cf3e80c4e1e9bc5d23da276f97515a4`; worktree SHA256: `75938e2e6db935c4875fcfb6e9c9c5fd7af8f21f4003e552b6e2fc677de07691`; canonical Git blob SHA256: `5eb959f1eadf93306698a0ca592423286b3f55fbde95ce7efe5726cf0130c260`; canonical size: `1504902`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:993:      "path": "validation/editable-text-recovery/pages/environment-source-page-007-120dpi/environment-source-page-007-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-007-120dpi/environment-source-page-007-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-007-120dpi\\environment-source-page-007-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-007-120dpi/environment-source-page-007-120dpi.dxf:3354:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:64:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-007-120dpi\\environment-source-page-007-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 37. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-008-120dpi/environment-source-page-008-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1262464` bytes; extension `.dxf`.
- Git blob SHA-1: `129abff54eb61ca46ce8b01604a99134b6aa5950`; worktree SHA256: `07073278ca83ce6f228417c3a1a443dc8ff106ed72ab0a95f1b414126d303d43`; canonical Git blob SHA256: `cba2b79153bc99323dcfc73aba045821f06495e328883ea2ad4942ffd7d38a73`; canonical size: `1065596`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1027:      "path": "validation/editable-text-recovery/pages/environment-source-page-008-120dpi/environment-source-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-008-120dpi/environment-source-page-008-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-008-120dpi\\environment-source-page-008-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-008-120dpi/environment-source-page-008-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:73:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-008-120dpi\\environment-source-page-008-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 38. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-009-120dpi/environment-source-page-009-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1660759` bytes; extension `.dxf`.
- Git blob SHA-1: `978ac185e422f5675f5dec00b5d1b6326625708a`; worktree SHA256: `cca81d7a509c80c29cef8a4beacd466f725e3bb0cac1cdd4c5db8a6f45d3b665`; canonical Git blob SHA256: `741ebbfa2e11c31cbd6d9e5c9046039141859c6cdfa365fedff90dc096a0ccc6`; canonical size: `1402795`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1061:      "path": "validation/editable-text-recovery/pages/environment-source-page-009-120dpi/environment-source-page-009-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-009-120dpi/environment-source-page-009-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-009-120dpi\\environment-source-page-009-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-009-120dpi/environment-source-page-009-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:82:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-009-120dpi\\environment-source-page-009-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 39. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-010-120dpi/environment-source-page-010-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1742956` bytes; extension `.dxf`.
- Git blob SHA-1: `3a791d0d80d6a873d01430a5a83a54ba9f352d50`; worktree SHA256: `6caf8944a8f6da9b8242b5fdb8172ffe67f9c721eeba96cafd5b898e9908b006`; canonical Git blob SHA256: `d4d2e64a22abee4bcb91a9c3fb9171b822f867a07ff0a9542d00a95ac178a8ce`; canonical size: `1471216`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1095:      "path": "validation/editable-text-recovery/pages/environment-source-page-010-120dpi/environment-source-page-010-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-010-120dpi/environment-source-page-010-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-010-120dpi\\environment-source-page-010-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-010-120dpi/environment-source-page-010-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:91:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-010-120dpi\\environment-source-page-010-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 40. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-011-120dpi/environment-source-page-011-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1678678` bytes; extension `.dxf`.
- Git blob SHA-1: `eaf4e2402e9a8c52f02c1eb05e944e1f4e0dd03a`; worktree SHA256: `9121d68b06484dfee1466e741489054e4743aed9286f6e69b5c4e0888533adb8`; canonical Git blob SHA256: `dc4edc2c3afcd88266fd4120a325c26b435bca0e737184783ca724302c182ca0`; canonical size: `1418214`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1129:      "path": "validation/editable-text-recovery/pages/environment-source-page-011-120dpi/environment-source-page-011-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-011-120dpi/environment-source-page-011-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-011-120dpi\\environment-source-page-011-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-011-120dpi/environment-source-page-011-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:100:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-011-120dpi\\environment-source-page-011-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 41. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-012-120dpi/environment-source-page-012-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1856515` bytes; extension `.dxf`.
- Git blob SHA-1: `4688c3a229b7379d18ec1c604f2503f1d8c93b1f`; worktree SHA256: `9e5fbcc24b6a751ade299934ba92f1a19e65711adeb40f3c4f85335b20561ef7`; canonical Git blob SHA256: `7ec8d33525eac90a008a4c83b884118053a9b8187e6eee3280ac0eef4b990ddb`; canonical size: `1567659`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1163:      "path": "validation/editable-text-recovery/pages/environment-source-page-012-120dpi/environment-source-page-012-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-012-120dpi/environment-source-page-012-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-012-120dpi\\environment-source-page-012-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-012-120dpi/environment-source-page-012-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:109:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-012-120dpi\\environment-source-page-012-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 42. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-013-120dpi/environment-source-page-013-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1721272` bytes; extension `.dxf`.
- Git blob SHA-1: `b51514349287367d1b0a317da7298e86ad23b2e1`; worktree SHA256: `dd56a0d0f2d07b0c5b6075d703fc43678f9ca8b2afa5aba75fab3d036e78fcb8`; canonical Git blob SHA256: `8f33102a2cacd77fb830ca37e979dd7d9b1b979c2358520cff02d624dadb0534`; canonical size: `1453352`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1197:      "path": "validation/editable-text-recovery/pages/environment-source-page-013-120dpi/environment-source-page-013-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-013-120dpi/environment-source-page-013-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-013-120dpi\\environment-source-page-013-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-013-120dpi/environment-source-page-013-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:118:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-013-120dpi\\environment-source-page-013-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 43. `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-014-120dpi/environment-source-page-014-120dpi.dxf`

- Original finding: `generated output file is tracked`; size `1915332` bytes; extension `.dxf`.
- Git blob SHA-1: `4c28443b2a504daac4bb37d56ad7981678f71eb0`; worktree SHA256: `6e28c69ed4a076eff2faa1c97982b9c0fd8f8c0e0ab794183a38492779d18c36`; canonical Git blob SHA256: `d131bd9474ca81aa46045259984ba75da1506995f141c30247322b6ee16ab265`; canonical size: `1616964`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1230:      "path": "validation/editable-text-recovery/pages/environment-source-page-014-120dpi/environment-source-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-014-120dpi/environment-source-page-014-120dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-014-120dpi\\environment-source-page-014-120dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/environment-source-page-014-120dpi/environment-source-page-014-120dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:127:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\environment-source-page-014-120dpi\\environment-source-page-014-120dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 44. `cad_photo_to_dxf/validation/editable-text-recovery/pages/page-001-d9fbda7-comparison-300dpi/page-001-d9fbda7-comparison-300dpi.dxf`

- Original finding: `generated output file is tracked`; size `4166873` bytes; extension `.dxf`.
- Git blob SHA-1: `e0e3051d771d4ca484eaa5debb1a71547d67ffee`; worktree SHA256: `8aded304670142d1c9c53726c69fa674cb9e46dea5b6057003571083e7a939c9`; canonical Git blob SHA256: `9431034f90fee1d91bdeee16160856bd8b621599dfe6b17ab901bcf797a537a3`; canonical size: `3526409`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1263:      "path": "validation/editable-text-recovery/pages/page-001-d9fbda7-comparison-300dpi/page-001-d9fbda7-comparison-300dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/page-001-d9fbda7-comparison-300dpi/page-001-d9fbda7-comparison-300dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\page-001-d9fbda7-comparison-300dpi\\page-001-d9fbda7-comparison-300dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/page-001-d9fbda7-comparison-300dpi/page-001-d9fbda7-comparison-300dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:289:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\page-001-d9fbda7-comparison-300dpi\\page-001-d9fbda7-comparison-300dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 45. `cad_photo_to_dxf/validation/editable-text-recovery/pages/page-001-fixed-failure-240dpi/page-001-fixed-failure-240dpi.dxf`

- Original finding: `generated output file is tracked`; size `3366215` bytes; extension `.dxf`.
- Git blob SHA-1: `c40b041873de30b0bb1a50c6fefc0db2aa7dc7da`; worktree SHA256: `b3d39d37bd62e7f5d7bfc3201313e8c574ee0ab9d4752f95040984117d84a69c`; canonical Git blob SHA256: `ba140d6b7aca7f7eec0989eaf1b4b3e79593410f7f73e8dde8affc20b0d93670`; canonical size: `2848219`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1297:      "path": "validation/editable-text-recovery/pages/page-001-fixed-failure-240dpi/page-001-fixed-failure-240dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/page-001-fixed-failure-240dpi/page-001-fixed-failure-240dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\page-001-fixed-failure-240dpi\\page-001-fixed-failure-240dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/page-001-fixed-failure-240dpi/page-001-fixed-failure-240dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:298:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\page-001-fixed-failure-240dpi\\page-001-fixed-failure-240dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 46. `cad_photo_to_dxf/validation/editable-text-recovery/pages/perspective-sample-plan-096dpi/perspective-sample-plan-096dpi.dxf`

- Original finding: `generated output file is tracked`; size `271345` bytes; extension `.dxf`.
- Git blob SHA-1: `9161a38484f319c592b7acb2a06dcd06bc564033`; worktree SHA256: `f427837dd8f74236cc92af3e6a6776230355341728c05d996eac69b35edc73a9`; canonical Git blob SHA256: `07b3c41745c5d33f230e4363f11bc1f9c151d4ec619349e988927ad5cc8009d4`; canonical size: `228777`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1330:      "path": "validation/editable-text-recovery/pages/perspective-sample-plan-096dpi/perspective-sample-plan-096dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/perspective-sample-plan-096dpi/perspective-sample-plan-096dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\perspective-sample-plan-096dpi\\perspective-sample-plan-096dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/perspective-sample-plan-096dpi/perspective-sample-plan-096dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:244:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\perspective-sample-plan-096dpi\\perspective-sample-plan-096dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 47. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-formal-page-001-150dpi/warehouse-formal-page-001-150dpi.dxf`

- Original finding: `generated output file is tracked`; size `625626` bytes; extension `.dxf`.
- Git blob SHA-1: `81f874fe56201e940b2f8f085c8db4f880ce6569`; worktree SHA256: `941342ef67cb23bd18bb26090f7822a8f280ea735236ec119066821a40c90797`; canonical Git blob SHA256: `c7fdaf795a0ad8ded236e57b8106fd237f5256f1b30cfb816d867c4482f99cb2`; canonical size: `530428`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1363:      "path": "validation/editable-text-recovery/pages/warehouse-formal-page-001-150dpi/warehouse-formal-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-formal-page-001-150dpi/warehouse-formal-page-001-150dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-formal-page-001-150dpi\\warehouse-formal-page-001-150dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-formal-page-001-150dpi/warehouse-formal-page-001-150dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:262:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-formal-page-001-150dpi\\warehouse-formal-page-001-150dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 48. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-001-072dpi/warehouse-source-page-001-072dpi.dxf`

- Original finding: `generated output file is tracked`; size `414991` bytes; extension `.dxf`.
- Git blob SHA-1: `f88b18d2d45e6e3434a444110eecbfdf48f3b84f`; worktree SHA256: `76d413586126c3f77d6c09476a794083a39f23656bf7e70b54686225fdacc201`; canonical Git blob SHA256: `0f9c12668626cda9804c9f2baa229bb11787884eb8178c83156a59152ae4cf5d`; canonical size: `351425`.
- First introduced commit: `c7269b1dee8eaf84c386e97759d56064de3dac1b` (2026-07-31T02:27:12+08:00); subject: 'test: validate editable text recovery on every page'.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1396:      "path": "validation/editable-text-recovery/pages/warehouse-source-page-001-072dpi/warehouse-source-page-001-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-001-072dpi/warehouse-source-page-001-072dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-001-072dpi\\warehouse-source-page-001-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-001-072dpi/warehouse-source-page-001-072dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:181:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-001-072dpi\\warehouse-source-page-001-072dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 49. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-001-300dpi/warehouse-source-page-001-300dpi.dxf`

- Original finding: `generated output file is tracked`; size `802165` bytes; extension `.dxf`.
- Git blob SHA-1: `9832359ebd8d8c946abf904582756d3f25e7c8bd`; worktree SHA256: `02186c83b8f15fdecee9d2ac97b3e8032d54a8d966d4d1b9651c32ce70b8811b`; canonical Git blob SHA256: `3d6b43f7d92ae5f921280a2daef720130158856a5bdbc539f42f04341139942d`; canonical size: `680135`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1429:      "path": "validation/editable-text-recovery/pages/warehouse-source-page-001-300dpi/warehouse-source-page-001-300dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-001-300dpi/warehouse-source-page-001-300dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-001-300dpi\\warehouse-source-page-001-300dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-001-300dpi/warehouse-source-page-001-300dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:271:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-001-300dpi\\warehouse-source-page-001-300dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 50. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-001-600dpi/warehouse-source-page-001-600dpi.dxf`

- Original finding: `generated output file is tracked`; size `1407997` bytes; extension `.dxf`.
- Git blob SHA-1: `b35dab9725fc84c58fdcbf788d3e9508d2956aba`; worktree SHA256: `05e5c1f91e85ca9e49800b4425b7b56072a4b073db17e962f3f022b863065cd7`; canonical Git blob SHA256: `66097746725fe528582463b3f2d694368676e3539a52b6eb80f0efc878e528f9`; canonical size: `1194847`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1463:      "path": "validation/editable-text-recovery/pages/warehouse-source-page-001-600dpi/warehouse-source-page-001-600dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-001-600dpi/warehouse-source-page-001-600dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-001-600dpi\\warehouse-source-page-001-600dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-001-600dpi/warehouse-source-page-001-600dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:280:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-001-600dpi\\warehouse-source-page-001-600dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 51. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-002-072dpi/warehouse-source-page-002-072dpi.dxf`

- Original finding: `generated output file is tracked`; size `903085` bytes; extension `.dxf`.
- Git blob SHA-1: `c7c2a1b05bf346d62212c5aa3d1455b50016ef5d`; worktree SHA256: `47b529271d1714bc288a2c4af600aa345d445564e845c0b3cc7c6fa91e473a2f`; canonical Git blob SHA256: `e4295fc14c9ebc739340b73aa4c55b147dba39219cb1dff1875846320649be5e`; canonical size: `766075`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1497:      "path": "validation/editable-text-recovery/pages/warehouse-source-page-002-072dpi/warehouse-source-page-002-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-002-072dpi/warehouse-source-page-002-072dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-002-072dpi\\warehouse-source-page-002-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-002-072dpi/warehouse-source-page-002-072dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:190:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-002-072dpi\\warehouse-source-page-002-072dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 52. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-003-072dpi/warehouse-source-page-003-072dpi.dxf`

- Original finding: `generated output file is tracked`; size `1260535` bytes; extension `.dxf`.
- Git blob SHA-1: `db9a8e9baa1e8d740313d559621392f9a7f935d7`; worktree SHA256: `c27f66b8415ff26188c01e65d306cbc8820e1e1d7222e2c6a49bb05f8a4b5b92`; canonical Git blob SHA256: `451d964523d039a31e7cc22d424424311e8fb769324f9756e5ac9a110e1372e9`; canonical size: `1068341`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1531:      "path": "validation/editable-text-recovery/pages/warehouse-source-page-003-072dpi/warehouse-source-page-003-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-003-072dpi/warehouse-source-page-003-072dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-003-072dpi\\warehouse-source-page-003-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-003-072dpi/warehouse-source-page-003-072dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:199:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-003-072dpi\\warehouse-source-page-003-072dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 53. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-004-072dpi/warehouse-source-page-004-072dpi.dxf`

- Original finding: `generated output file is tracked`; size `876467` bytes; extension `.dxf`.
- Git blob SHA-1: `8de78d56e2a25c2c877b7a7b4e5e4d27952e62fc`; worktree SHA256: `8f8cd39d5d240892a67dc74c4428f20572a5ff6bf09353572c30b9805b45284f`; canonical Git blob SHA256: `8a6b1ef766ab51c0f66ce8c0b8b905755b137a1323d27bdc82ff2a6ceb8f7ef2`; canonical size: `742959`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1565:      "path": "validation/editable-text-recovery/pages/warehouse-source-page-004-072dpi/warehouse-source-page-004-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-004-072dpi/warehouse-source-page-004-072dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-004-072dpi\\warehouse-source-page-004-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-004-072dpi/warehouse-source-page-004-072dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:208:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-004-072dpi\\warehouse-source-page-004-072dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 54. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-005-072dpi/warehouse-source-page-005-072dpi.dxf`

- Original finding: `generated output file is tracked`; size `877676` bytes; extension `.dxf`.
- Git blob SHA-1: `f9d2a35db6e62f8b9a1423b1cc11529d0227dd58`; worktree SHA256: `ca9944bbb2e8403bfa8ad46a24b96a7e80f13eb81410b899320f5e30d344b175`; canonical Git blob SHA256: `4f4c53c6d5ba18fc5619f6b42e1b1aba119c16465de1b7a5b27e6476e15c17f5`; canonical size: `744162`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1599:      "path": "validation/editable-text-recovery/pages/warehouse-source-page-005-072dpi/warehouse-source-page-005-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-005-072dpi/warehouse-source-page-005-072dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-005-072dpi\\warehouse-source-page-005-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-005-072dpi/warehouse-source-page-005-072dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:217:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-005-072dpi\\warehouse-source-page-005-072dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 55. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-006-072dpi/warehouse-source-page-006-072dpi.dxf`

- Original finding: `generated output file is tracked`; size `839639` bytes; extension `.dxf`.
- Git blob SHA-1: `b555457d3370b2d6cf4903ca0a09a9381ee67ff2`; worktree SHA256: `28140306989eb030f35aee57ba025df20a210682cb150fbc84de489bd332230c`; canonical Git blob SHA256: `48e65d97b0a397d9a8ff0296c529ed792c219817aa9447504ad375f3b922c388`; canonical size: `712167`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1633:      "path": "validation/editable-text-recovery/pages/warehouse-source-page-006-072dpi/warehouse-source-page-006-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-006-072dpi/warehouse-source-page-006-072dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-006-072dpi\\warehouse-source-page-006-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-006-072dpi/warehouse-source-page-006-072dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:226:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-006-072dpi\\warehouse-source-page-006-072dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 56. `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-007-072dpi/warehouse-source-page-007-072dpi.dxf`

- Original finding: `generated output file is tracked`; size `1046631` bytes; extension `.dxf`.
- Git blob SHA-1: `05498718e7c63e8ff48ea0cb20e56d2f4ecdef9a`; worktree SHA256: `4cd24c01a33a5418a99f6d0d8cb9ff0267021f71853253f54faf26d1b7095305`; canonical Git blob SHA256: `f469b292f4176088fa52d4013c3f952903d0053404b30c746950486bee1be310`; canonical size: `887355`.
- First introduced commit: `None` (None); subject: None.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/entity-type-audit.json:1667:      "path": "validation/editable-text-recovery/pages/warehouse-source-page-007-072dpi/warehouse-source-page-007-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-007-072dpi/warehouse-source-page-007-072dpi-entity-audit.json:24:  "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-007-072dpi\\warehouse-source-page-007-072dpi.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/pages/warehouse-source-page-007-072dpi/warehouse-source-page-007-072dpi.dxf:3306:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/per-page-index.json:235:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\editable-text-recovery\\pages\\warehouse-source-page-007-072dpi\\warehouse-source-page-007-072dpi.dxf",`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied PDF/image inputs and historical editable-text validation harness; internal evidence only; source/rights notes remain in validation manifests.
- Deletion impact: Historical reports reference these paths; current CI regenerates outputs in temporary directories and contract evidence is compact.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python validation/editable-text-recovery/run_full_validation.py --manifest validation/editable-text-recovery/full-validation-manifest.json --output-root <external-output-root>`
- Acceptance test: Recovery archive round-trip restores every byte; source manifests/compact summaries remain; editable-text contract uses compact evidence and no tracked generated DXF.

## 57. `cad_photo_to_dxf/validation/low-quality-blue-line-fix-2026-07-28/environment-page-003-full-v3.dxf`

- Original finding: `generated output file is tracked`; size `2830343` bytes; extension `.dxf`.
- Git blob SHA-1: `e4cc1746a3c58349f9c12ee70070c217f0e5321c`; worktree SHA256: `cb716d91aa47908c57cf7e16a8b1e3dc39494b8ee7a91fc0ce2231f7a1c62a87`; canonical Git blob SHA256: `ac588c0de1c4a34432b61e998a57ecf1f74ede0daa9628cd2ea1dece07bd5684`; canonical size: `2571435`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/low-quality-blue-line-fix-2026-07-28/environment-page-003-full-v3.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 58. `cad_photo_to_dxf/validation/observability/phase3-sample/final/final-structure.dxf`

- Original finding: `generated output file is tracked`; size `278582` bytes; extension `.dxf`.
- Git blob SHA-1: `3195e59f7d6bff67c7fe2a42b5ef6e035f971fd5`; worktree SHA256: `de2cfa88ead4d8d6aa5a97f8229b7f527aea9542e1cc2ae7010db25ec620f737`; canonical Git blob SHA256: `de2cfa88ead4d8d6aa5a97f8229b7f527aea9542e1cc2ae7010db25ec620f737`; canonical size: `278582`.
- First introduced commit: `bea9cd8f318875f3a17d5caaff5979fc6d7f336b` (2026-07-28T22:25:06+08:00); subject: 'chore: add 26-stage observability (phase 3)'.
- References (5 search hits):
  - code: `cad_photo_to_dxf/app/debug_bundle.py:511:    dxf_path = final_dir / "final-structure.dxf"`
  - documentation_or_validation: `cad_photo_to_dxf/validation/observability/phase3-sample/artifacts/26-actual-dxf-render/artifact-001.svg.metadata.json:32:    "source_dxf": "final-structure.dxf"`; `cad_photo_to_dxf/validation/observability/phase3-sample/artifacts/26-actual-dxf-render/data.json:13:      "source_dxf": "final-structure.dxf"`; `cad_photo_to_dxf/validation/observability/phase3-sample/manifest.json:21:    "path": "final/final-structure.dxf",`; `docs/OBSERVABILITY_DEBUG_BUNDLE.md:39:│   └── final-structure.dxf`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project test image and capture_debug_bundle.py; internal debug evidence; manifest records source image hash and provenance.
- Deletion impact: Tracked manifest records the historical output hash; unit tests generate a fresh debug bundle in tmp_path and do not require this file.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python scripts/capture_debug_bundle.py tests/real_regression/assets/test.jpg --output <external-bundle> --page-index 0 --dpi 300`
- Acceptance test: Recovery archive round-trip restores every byte; manifest hash remains recorded; test_observability generates/audits a temporary DXF; hygiene is clean.

## 59. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#environment-page-003-full-v10.dxf`

- Original finding: `generated output file is tracked`; size `2027024` bytes; extension `.dxf`.
- Git blob SHA-1: `d678375a50baa20d9444d82e7eab024acb95387c`; worktree SHA256: `ada564ebb43593d4b6bb9a6f8266b5395a0fba55007d2e7051edc7e6a7d64b9c`; canonical Git blob SHA256: `f1ecbeadab19997ffac8cc28bd56a0d909af7e3bd4e74964609bfe24cd2f2992`; canonical size: `1836914`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 60. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#environment-page-003-full-v11.dxf`

- Original finding: `generated output file is tracked`; size `3771736` bytes; extension `.dxf`.
- Git blob SHA-1: `05b7e6769668e2bb4de6f8c3bcf5da53aca3b91d`; worktree SHA256: `e610bde43b2bee9a1af21463844e3168719198cbc1c6eb756449feeb46d26407`; canonical Git blob SHA256: `e58cb24375169719e87e4455bffa6394e07b73b6c34ebe305b78cf4a6d3f3718`; canonical size: `3426732`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 61. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#environment-page-003-full-v12.dxf`

- Original finding: `generated output file is tracked`; size `3883298` bytes; extension `.dxf`.
- Git blob SHA-1: `77e3304d47ed9c3e6494d17b52d083ba5d23db9b`; worktree SHA256: `06e105b6f9b78a9474a91cfa4ccd9b90a4c248f53ce6e2fc803cbaba24bf1490`; canonical Git blob SHA256: `fe47b3f9c2580867304c8d028865f1bc1c6efa3237543d9941d571b261383c1f`; canonical size: `3531700`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 62. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#environment-page-003-full-v15.dxf`

- Original finding: `generated output file is tracked`; size `3890688` bytes; extension `.dxf`.
- Git blob SHA-1: `4945f1d1e7c9a6e1c136ebe8afbec0deca8c6191`; worktree SHA256: `d4d52349e84232059a47833a6e261dabf480adab667e9ec0b446e63d281eb6e8`; canonical Git blob SHA256: `85b8d20626fbd835a8b605e1cf26f688f8f9ea24687d9328b60ddc38fdb99f45`; canonical size: `3537480`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 63. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#environment-page-003-full-v4.dxf`

- Original finding: `generated output file is tracked`; size `2725796` bytes; extension `.dxf`.
- Git blob SHA-1: `eb51655aab5a464fc96c3de90d78a68a244b64bf`; worktree SHA256: `cf9c11d0377464b7d9cf9ec062910bc343138f25a8cacb451096bbb47c42cc58`; canonical Git blob SHA256: `47a800981adefa01bebee93baac01ddeea28fc04786d957358224305bba9fde6`; canonical size: `2472132`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 64. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#environment-page-003-full-v5.dxf`

- Original finding: `generated output file is tracked`; size `2286707` bytes; extension `.dxf`.
- Git blob SHA-1: `698926fd8feb75c4c1b3f9d761e72bf13df550ca`; worktree SHA256: `9c87baadd95c82d010327eac691b890b2b29dfd1e24a46e0dbcd5e4a044a89eb`; canonical Git blob SHA256: `86e658c1bdf27972175dd308f885b7d6755dbb8a299f89bf2c2adcc65b132750`; canonical size: `2073053`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 65. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#environment-page-003-full-v6.dxf`

- Original finding: `generated output file is tracked`; size `2068604` bytes; extension `.dxf`.
- Git blob SHA-1: `9f8d86622cd6dbaf4314b34ff85ad84f34bcf0c1`; worktree SHA256: `1271a07a6f4d6428293794a8ffac58fc8cf70905fa497f9929fe0d0701c8fd1a`; canonical Git blob SHA256: `b67f24bdc368caed08efabe72414e20dfc20797d4519e57cda459ac5c86a2a01`; canonical size: `1874140`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 66. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#environment-page-003-full-v7.dxf`

- Original finding: `generated output file is tracked`; size `2046075` bytes; extension `.dxf`.
- Git blob SHA-1: `9cbde222b9d43d3a75f614a13db678e3a4e80188`; worktree SHA256: `720e5b4fa45299251a5578ac5f65f249ee7b2486d1d62ef4dce8dff8429609a3`; canonical Git blob SHA256: `71e43920ec1c3a997bd1e06b498e8edd7675138644e91b3351184cbcd4fdb2ac`; canonical size: `1853839`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 67. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#environment-page-003-ownership-v16.dxf`

- Original finding: `generated output file is tracked`; size `3524009` bytes; extension `.dxf`.
- Git blob SHA-1: `2d6d8d081e3cc263bfe0174588d1b22c1c0bff25`; worktree SHA256: `d90e58e782a789b684d00841ad939dc26992d0c16530dfe7c32a5bed200b7659`; canonical Git blob SHA256: `11ad85823c9025259694ab0cdbc85b350f71fee878455cf27ea25b6c8245ba21`; canonical size: `3202699`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 68. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/#warehouse-page-002-ownership-v16.dxf`

- Original finding: `generated output file is tracked`; size `3208741` bytes; extension `.dxf`.
- Git blob SHA-1: `ef1649442a8298a5da10a4a033b195b011d127b9`; worktree SHA256: `56aae9488d9060f1c67de482479c3f69c35e92c6bd6cec24ca4dbac4266c8aca`; canonical Git blob SHA256: `9be1a853a6addc0791637790da9a3dbe35213ebad7f73cee2b6bfaf0da1ec37d`; canonical size: `2916015`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 69. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v10.dxf`

- Original finding: `generated output file is tracked`; size `2061712` bytes; extension `.dxf`.
- Git blob SHA-1: `55bdde8b434ff69ec195ab69a99f5b3f9d05b01a`; worktree SHA256: `00a5739b8054a4a6e4ba704b0ff2afc89088ad0c323d568a5fa0cee2f983de17`; canonical Git blob SHA256: `2e528f731fb4e8b3a423268978ce805b5e19f3d28632b5c52b98bb7be933707c`; canonical size: `1871038`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v10.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 70. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v11.dxf`

- Original finding: `generated output file is tracked`; size `3779033` bytes; extension `.dxf`.
- Git blob SHA-1: `c9cabecf57610b222cb611e1c387534c813a9c3f`; worktree SHA256: `63524715ac48606f38e4bc2792f135b6667f1f969550e9aab7c2e68cf3a8bb3f`; canonical Git blob SHA256: `6ee46ea59cdde92e697c29c4ff0e38445db06e0ff16b37bf155c52eebf0ce956`; canonical size: `3440203`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v11.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 71. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v12.dxf`

- Original finding: `generated output file is tracked`; size `3906202` bytes; extension `.dxf`.
- Git blob SHA-1: `c399d589bf178adc9b082393a1f7db0b045d0172`; worktree SHA256: `abc0c68dff4eb7236e69e7130b78c726b86e901f7a77734d7d80778506fc2fca`; canonical Git blob SHA256: `e5a8d8f7cfd1fc2df6d86c59839fce39cdabdbe5eeb52a678d06068c5a29bac5`; canonical size: `3559452`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v12.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 72. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v13.dxf`

- Original finding: `generated output file is tracked`; size `3903276` bytes; extension `.dxf`.
- Git blob SHA-1: `5b137c5ef98720f650aaf21f9bc2f62f1db6e5b0`; worktree SHA256: `5896e11bb072ad82f55e1845401e56a3ad5392c96255dd340fb64fcb98667016`; canonical Git blob SHA256: `80161e30d9ca56e5ddeef0d0135a7fc9362388e37f63282a6e27c7aa2988bc5e`; canonical size: `3556556`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v13.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 73. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v14.dxf`

- Original finding: `generated output file is tracked`; size `3888395` bytes; extension `.dxf`.
- Git blob SHA-1: `25a6659e3cbffdf91ee8eaacdf9da0b4f6c52643`; worktree SHA256: `a2d6a830dcb2674232d0ec2a686c1de948784d8ddd66ee7a2c2e5c58487c0867`; canonical Git blob SHA256: `5ed6088663a92031bb34a8991741fc2c0935faea3233f683bb6f9b23901ee6ce`; canonical size: `3542449`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v14.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 74. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v15.dxf`

- Original finding: `generated output file is tracked`; size `3914903` bytes; extension `.dxf`.
- Git blob SHA-1: `c853c58763e024b4d9753551013c3bf5e23251c5`; worktree SHA256: `0283b42eb3bc13cc6a25c8b900a44705f599d5e9fe33d8d8b046f5e77233c6c3`; canonical Git blob SHA256: `5cf59607aef20cd182d0edddd7e3e228745f42d6196a4571207bc03a23ba58fe`; canonical size: `3566485`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v15.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 75. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v4.dxf`

- Original finding: `generated output file is tracked`; size `2754390` bytes; extension `.dxf`.
- Git blob SHA-1: `79acb4ef9cefbe6b4fa3da725a78d95b9ad0d597`; worktree SHA256: `fd16c001ea58fe50eea11fee9068c663476f75ece8055fb713f343d3a2d27c17`; canonical Git blob SHA256: `82e4a03d97d7a84b8c7bdeaab4fe89fdf761142626a588c2f2940107e2b1e604`; canonical size: `2502024`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v4.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 76. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v5.dxf`

- Original finding: `generated output file is tracked`; size `2320605` bytes; extension `.dxf`.
- Git blob SHA-1: `3db892db2bd367fd4c0c3baa4bfc40b14227f0cf`; worktree SHA256: `7ce158aaeda5a7f3438a7c32fe197697f93f1ef61583a905489252b6cda1da34`; canonical Git blob SHA256: `4331136b3e6104460e130198c4376de34dc213d028c0b0f3f25487e39ebdf8e8`; canonical size: `2106829`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v5.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 77. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v6.dxf`

- Original finding: `generated output file is tracked`; size `2102034` bytes; extension `.dxf`.
- Git blob SHA-1: `3165c2f3871a3790f9f5d5e87e1fcd70784250df`; worktree SHA256: `3ba2a5683dda9504f85dd8388e74dae921faa3bf3b74c56c15809b0996848477`; canonical Git blob SHA256: `a1a3f8b0d82df571ab25e341fa72911b3adc4662591ccd0420d2a3a639359ded`; canonical size: `1907044`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v6.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 78. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v7.dxf`

- Original finding: `generated output file is tracked`; size `2080647` bytes; extension `.dxf`.
- Git blob SHA-1: `a299e13356a37cfd080d95be705d6ad020e64a35`; worktree SHA256: `a3ac0850c9ecfb3b0f89f3623c90b127be9bc1b3e24d32681b4daeca73e64afa`; canonical Git blob SHA256: `0882a86e1425a04698922e4611d5e93dd3c3a84550a2e4c8f5f644d3c3b85b31`; canonical size: `1887733`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v7.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 79. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v8.dxf`

- Original finding: `generated output file is tracked`; size `2063413` bytes; extension `.dxf`.
- Git blob SHA-1: `8cebb11bebb7dd32a68e9bf1e5c9fc5a62eb9e2c`; worktree SHA256: `aab6c9ba77719b8fce43217cc3a459ba2b67a71300f2ec38e7a05d851757110a`; canonical Git blob SHA256: `a85934e474eedd5f6a2b1403fef6a9ae2ed4e5a1cf4128147113cc442e870b00`; canonical size: `1872499`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v8.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 80. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v9.dxf`

- Original finding: `generated output file is tracked`; size `2065940` bytes; extension `.dxf`.
- Git blob SHA-1: `327b9bf09cdadc965e06954bb3b9719338998ad7`; worktree SHA256: `91af10ec7df021d17b223a825f9a65340d16eb74c63c521b31227aae1083e4a8`; canonical Git blob SHA256: `722a86a55064925a5a4d3db977d52874e2d85b2539347d297b79c39f1222a2bb`; canonical size: `1874804`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-full-v9.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 81. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-ownership-v16.dxf`

- Original finding: `generated output file is tracked`; size `3545088` bytes; extension `.dxf`.
- Git blob SHA-1: `10716d26fed8ac0210dc1ee1f0099325e1231147`; worktree SHA256: `da71e6027e09253ec1778064fa226c2680a4fd0a99209290623d9888b545ea55`; canonical Git blob SHA256: `9287608cb82510782539873b16e2567e521eab9625ed653ccae1d4bb3ab03050`; canonical size: `3227756`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (2 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/environment-page-003-ownership-v16.dxf:3234:wqy-unicode.lff`
  - other: `cad_photo_to_dxf/tmp/run_page3_v4_validation.py:29:OUTPUT_DXF = OUTPUT_DIRECTORY / "environment-page-003-ownership-v16.dxf"`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 82. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/warehouse-page-001-ownership-v16.dxf`

- Original finding: `generated output file is tracked`; size `1141610` bytes; extension `.dxf`.
- Git blob SHA-1: `a764e6b7c4af474baa03183005ec79941771dc8b`; worktree SHA256: `87f18c6d1991dca41506eff7142507f538473785c737f8b55454424e12ff518f`; canonical Git blob SHA256: `21c34a2c20d6473df25a7a50ecd6ced1caa2bcf2ec61c66101c41d1f581e9c83`; canonical size: `1035908`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (2 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/warehouse-page-001-ownership-v16.dxf:3234:wqy-unicode.lff`
  - other: `cad_photo_to_dxf/tmp/run_warehouse_v16_validation.py:29:OUTPUT_DXF = OUTPUT_DIRECTORY / "warehouse-page-001-ownership-v16.dxf"`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 83. `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/warehouse-page-002-ownership-v16.dxf`

- Original finding: `generated output file is tracked`; size `3205491` bytes; extension `.dxf`.
- Git blob SHA-1: `0691704f3df47c82e2172569f27cb82cbd561410`; worktree SHA256: `e6d82e76f5a3bf1495d8aa2addff8276a6c5a9846c5a114c3e692faf35d73bc6`; canonical Git blob SHA256: `9c27bf32fc81004f29460b84ff2c2805de39487ec9641834df67bca675184dd7`; canonical size: `2916613`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/scan-artifact-visual-fix-2026-07-28/warehouse-page-002-ownership-v16.dxf:3282:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 84. `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/environment-page-003.dxf`

- Original finding: `generated output file is tracked`; size `1192385` bytes; extension `.dxf`.
- Git blob SHA-1: `243e87acfc4b34957fb459270e948f5ba9b94ee6`; worktree SHA256: `3b5c7a086cc64879cefeea3cc97ee209bad78e0da27b190779bf744dd1324425`; canonical Git blob SHA256: `3b5c7a086cc64879cefeea3cc97ee209bad78e0da27b190779bf744dd1324425`; canonical size: `1192385`.
- First introduced commit: `d898400b69f86b625ce71e9689b5d5f8e877d66a` (2026-07-28T21:46:20+08:00); subject: 'test: record dual frozen baselines (phase 1)'.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/system-refactor-baselines/current/baseline-result.json:38:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\current\\outputs\\environment-page-003.dxf",`; `cad_photo_to_dxf/validation/system-refactor-baselines/old/baseline-result.json:38:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\old\\outputs\\environment-page-003.dxf",`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:185:- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/environment-page-003.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:191:- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/environment-page-003.dxf`（新增）`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project real-regression inputs and recorded baseline harness; internal historical evidence; source/rights notes remain in tests/real_regression/manifest.json and validation documentation.
- Deletion impact: Historical baseline JSON refers to these output paths; compact hashes/metrics remain in Git and the phase-12 immutable anchor is independent.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python scripts/run_performance_baseline.py --manifest tests/real_regression/manifest.json --output <external-output.json> --artifacts <external-artifacts-dir>`
- Acceptance test: Recovery archive round-trip restores every byte; compact baseline reports remain; phase-12 commit/blob anchor verification passes; hygiene reports no tracked DXF.

## 85. `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/test.dxf`

- Original finding: `generated output file is tracked`; size `234118` bytes; extension `.dxf`.
- Git blob SHA-1: `9ad3b7f32dd9df9e66b4f8cfc79048174bf84131`; worktree SHA256: `f0c345799f72f6edda5b0169bb610957283197d52ca92f7115f69a5749e8eaad`; canonical Git blob SHA256: `f0c345799f72f6edda5b0169bb610957283197d52ca92f7115f69a5749e8eaad`; canonical size: `234118`.
- First introduced commit: `d898400b69f86b625ce71e9689b5d5f8e877d66a` (2026-07-28T21:46:20+08:00); subject: 'test: record dual frozen baselines (phase 1)'.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/system-refactor-baselines/current/baseline-result.json:11:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\current\\outputs\\test.dxf",`; `cad_photo_to_dxf/validation/system-refactor-baselines/old/baseline-result.json:11:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\old\\outputs\\test.dxf",`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:186:- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/test.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:192:- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/test.dxf`（新增）`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project real-regression inputs and recorded baseline harness; internal historical evidence; source/rights notes remain in tests/real_regression/manifest.json and validation documentation.
- Deletion impact: Historical baseline JSON refers to these output paths; compact hashes/metrics remain in Git and the phase-12 immutable anchor is independent.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python scripts/run_performance_baseline.py --manifest tests/real_regression/manifest.json --output <external-output.json> --artifacts <external-artifacts-dir>`
- Acceptance test: Recovery archive round-trip restores every byte; compact baseline reports remain; phase-12 commit/blob anchor verification passes; hygiene reports no tracked DXF.

## 86. `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/warehouse-page-001.dxf`

- Original finding: `generated output file is tracked`; size `671813` bytes; extension `.dxf`.
- Git blob SHA-1: `f4f76118bbd3a80b9ca58f6c0e0ea433433d4b6a`; worktree SHA256: `138aec6b40eca947e6f99f4114a99590f6aa671464f3a6d59cb1443100fd6c53`; canonical Git blob SHA256: `138aec6b40eca947e6f99f4114a99590f6aa671464f3a6d59cb1443100fd6c53`; canonical size: `671813`.
- First introduced commit: `d898400b69f86b625ce71e9689b5d5f8e877d66a` (2026-07-28T21:46:20+08:00); subject: 'test: record dual frozen baselines (phase 1)'.
- References (6 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/system-refactor-baselines/current/baseline-result.json:65:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\current\\outputs\\warehouse-page-001.dxf",`; `cad_photo_to_dxf/validation/system-refactor-baselines/old/baseline-result.json:65:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\old\\outputs\\warehouse-page-001.dxf",`; `cad_photo_to_dxf/validation/user-pdf-check/warehouse-page-001.dxf:3234:wqy-unicode.lff`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:116:- `cad_photo_to_dxf/validation/user-pdf-check/warehouse-page-001.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:187:- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/warehouse-page-001.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:193:- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/warehouse-page-001.dxf`（新增）`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project real-regression inputs and recorded baseline harness; internal historical evidence; source/rights notes remain in tests/real_regression/manifest.json and validation documentation.
- Deletion impact: Historical baseline JSON refers to these output paths; compact hashes/metrics remain in Git and the phase-12 immutable anchor is independent.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python scripts/run_performance_baseline.py --manifest tests/real_regression/manifest.json --output <external-output.json> --artifacts <external-artifacts-dir>`
- Acceptance test: Recovery archive round-trip restores every byte; compact baseline reports remain; phase-12 commit/blob anchor verification passes; hygiene reports no tracked DXF.

## 87. `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/environment-page-003.dxf`

- Original finding: `generated output file is tracked`; size `1828570` bytes; extension `.dxf`.
- Git blob SHA-1: `4b812685b57cb40571b7176f1b1fbdb80d9d3595`; worktree SHA256: `83334244f77d8262f9b06752511e758b751ec35ed98d49fb7f0da138a4d59c73`; canonical Git blob SHA256: `83334244f77d8262f9b06752511e758b751ec35ed98d49fb7f0da138a4d59c73`; canonical size: `1828570`.
- First introduced commit: `d898400b69f86b625ce71e9689b5d5f8e877d66a` (2026-07-28T21:46:20+08:00); subject: 'test: record dual frozen baselines (phase 1)'.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/system-refactor-baselines/current/baseline-result.json:38:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\current\\outputs\\environment-page-003.dxf",`; `cad_photo_to_dxf/validation/system-refactor-baselines/old/baseline-result.json:38:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\old\\outputs\\environment-page-003.dxf",`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:185:- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/environment-page-003.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:191:- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/environment-page-003.dxf`（新增）`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project real-regression inputs and recorded baseline harness; internal historical evidence; source/rights notes remain in tests/real_regression/manifest.json and validation documentation.
- Deletion impact: Historical baseline JSON refers to these output paths; compact hashes/metrics remain in Git and the phase-12 immutable anchor is independent.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python scripts/run_performance_baseline.py --manifest tests/real_regression/manifest.json --output <external-output.json> --artifacts <external-artifacts-dir>`
- Acceptance test: Recovery archive round-trip restores every byte; compact baseline reports remain; phase-12 commit/blob anchor verification passes; hygiene reports no tracked DXF.

## 88. `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/test.dxf`

- Original finding: `generated output file is tracked`; size `251956` bytes; extension `.dxf`.
- Git blob SHA-1: `bb17ec81267362c0a57feec5ac78d6e862c7c58e`; worktree SHA256: `297c47b9a9a989d26ff0ed6b621481da1b7526968cae76c2245676e4cce19884`; canonical Git blob SHA256: `297c47b9a9a989d26ff0ed6b621481da1b7526968cae76c2245676e4cce19884`; canonical size: `251956`.
- First introduced commit: `d898400b69f86b625ce71e9689b5d5f8e877d66a` (2026-07-28T21:46:20+08:00); subject: 'test: record dual frozen baselines (phase 1)'.
- References (4 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/system-refactor-baselines/current/baseline-result.json:11:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\current\\outputs\\test.dxf",`; `cad_photo_to_dxf/validation/system-refactor-baselines/old/baseline-result.json:11:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\old\\outputs\\test.dxf",`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:186:- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/test.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:192:- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/test.dxf`（新增）`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project real-regression inputs and recorded baseline harness; internal historical evidence; source/rights notes remain in tests/real_regression/manifest.json and validation documentation.
- Deletion impact: Historical baseline JSON refers to these output paths; compact hashes/metrics remain in Git and the phase-12 immutable anchor is independent.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python scripts/run_performance_baseline.py --manifest tests/real_regression/manifest.json --output <external-output.json> --artifacts <external-artifacts-dir>`
- Acceptance test: Recovery archive round-trip restores every byte; compact baseline reports remain; phase-12 commit/blob anchor verification passes; hygiene reports no tracked DXF.

## 89. `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/warehouse-page-001.dxf`

- Original finding: `generated output file is tracked`; size `728504` bytes; extension `.dxf`.
- Git blob SHA-1: `690a9c1bfcf8b91f2e2bdeff3bc62464763c040a`; worktree SHA256: `2e37d234db39fe7fc408e402097d31ff7de14815dbd84b5a4063cca49d2e3c12`; canonical Git blob SHA256: `2e37d234db39fe7fc408e402097d31ff7de14815dbd84b5a4063cca49d2e3c12`; canonical size: `728504`.
- First introduced commit: `d898400b69f86b625ce71e9689b5d5f8e877d66a` (2026-07-28T21:46:20+08:00); subject: 'test: record dual frozen baselines (phase 1)'.
- References (6 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/system-refactor-baselines/current/baseline-result.json:65:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\current\\outputs\\warehouse-page-001.dxf",`; `cad_photo_to_dxf/validation/system-refactor-baselines/old/baseline-result.json:65:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\old\\outputs\\warehouse-page-001.dxf",`; `cad_photo_to_dxf/validation/user-pdf-check/warehouse-page-001.dxf:3234:wqy-unicode.lff`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:116:- `cad_photo_to_dxf/validation/user-pdf-check/warehouse-page-001.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:187:- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/warehouse-page-001.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:193:- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/warehouse-page-001.dxf`（新增）`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project real-regression inputs and recorded baseline harness; internal historical evidence; source/rights notes remain in tests/real_regression/manifest.json and validation documentation.
- Deletion impact: Historical baseline JSON refers to these output paths; compact hashes/metrics remain in Git and the phase-12 immutable anchor is independent.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **C. ?????????????? Git ????? manifest/hash** ? Historical validation evidence, not a source fixture; preserve exact bytes externally and retain compact manifests/hashes in Git.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `python scripts/run_performance_baseline.py --manifest tests/real_regression/manifest.json --output <external-output.json> --artifacts <external-artifacts-dir>`
- Acceptance test: Recovery archive round-trip restores every byte; compact baseline reports remain; phase-12 commit/blob anchor verification passes; hygiene reports no tracked DXF.

## 90. `cad_photo_to_dxf/validation/user-fix-2026-07-27/#titleblock-fixed.dxf`

- Original finding: `generated output file is tracked`; size `341953` bytes; extension `.dxf`.
- Git blob SHA-1: `50b828f94b8d8efddc752e4cb92f792a8dfad465`; worktree SHA256: `ae0c9112b0d16d358b0507c0f4a647728c2159248b0b2130ef9f44a682b8ad1a`; canonical Git blob SHA256: `d411dbe55bb618b3e7b15554f2e79cf7875c8f73ee25e9de8323f52d4bddb0d6`; canonical size: `308407`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (0 search hits):
  - none found
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 91. `cad_photo_to_dxf/validation/user-fix-2026-07-27/titleblock-fixed.dxf`

- Original finding: `generated output file is tracked`; size `368469` bytes; extension `.dxf`.
- Git blob SHA-1: `09c9b82bdf55f5eb6b21e1504a5734fe694baed7`; worktree SHA256: `7e0f6ac8f26e2280945231a2cd32dcb7af3941a7de450f41cbe09ac3cfeed9dc`; canonical Git blob SHA256: `2e51740c7433b2d20633f9a144ce7d6685ebb95d07dd1ccd1cdc91b6398d5bf1`; canonical size: `330927`.
- First introduced commit: `aa1e7cd0b5cb383879aace65b494be36eef23d70` (2026-07-30T15:15:32+08:00); subject: '1'.
- References (1 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/user-fix-2026-07-27/titleblock-fixed.dxf:3234:wqy-unicode.lff`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 92. `cad_photo_to_dxf/validation/user-pdf-check/environment-page-001.dxf`

- Original finding: `generated output file is tracked`; size `1046131` bytes; extension `.dxf`.
- Git blob SHA-1: `089b687dfad8af4c08e81e58f67ff6111be1ecef`; worktree SHA256: `a2f3e537b508cb303a277c8fd5715740eb99aae37743aed8a59406f56c69daf2`; canonical Git blob SHA256: `e41af74ace9141c4e4c4e96751cb1da4c2ca61d3b5890a3bfa8283e738b62512`; canonical size: `887883`.
- First introduced commit: `d9fbda763e95c6dd7154934b801b59dbf034e711` (2026-07-27T19:27:48+08:00); subject: '1'.
- References (9 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/editable-text-recovery/before-after-summary.json:231:      "path": "cad_photo_to_dxf/validation/user-pdf-check/environment-page-001.dxf",`; `cad_photo_to_dxf/validation/editable-text-recovery/build_final_delivery.py:154:        "environment-page-001.dxf"`; `cad_photo_to_dxf/validation/uat-page001-failure/audit_page001.py:65:    / "environment-page-001.dxf"`; `cad_photo_to_dxf/validation/uat-page001-failure/audit_page001.py:1905:`validation/user-pdf-check/environment-page-001.dxf`。该文件可观察到`; `cad_photo_to_dxf/validation/uat-page001-failure/commit-regression-analysis.md:32:`validation/user-pdf-check/environment-page-001.dxf`。该文件可观察到`; `cad_photo_to_dxf/validation/uat-page001-failure/layer-entity-counts.json:319:    "path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\user-pdf-check\\environment-page-001.dxf",`; `cad_photo_to_dxf/validation/uat-page001-failure/native-text-geometry.json:4097:    "historical_dxf": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\user-pdf-check\\environment-page-001.dxf",`; `cad_photo_to_dxf/validation/user-pdf-check/environment-page-001.dxf:3282:wqy-unicode.lff`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:112:- `cad_photo_to_dxf/validation/user-pdf-check/environment-page-001.dxf`（新增）`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 93. `cad_photo_to_dxf/validation/user-pdf-check/warehouse-page-001.dxf`

- Original finding: `generated output file is tracked`; size `131308` bytes; extension `.dxf`.
- Git blob SHA-1: `446e29b014bd2efd6ca3eeabcc45722e8230e8cb`; worktree SHA256: `b7a9243a36b64f60d1d813867f180123fec60dfc18a8f2e4a52b78e672ae94e4`; canonical Git blob SHA256: `1c92f28c332166670b043c94d06dc1b4c7032dab787992d6898c10f1f59d0152`; canonical size: `111768`.
- First introduced commit: `d9fbda763e95c6dd7154934b801b59dbf034e711` (2026-07-27T19:27:48+08:00); subject: '1'.
- References (6 search hits):
  - documentation_or_validation: `cad_photo_to_dxf/validation/system-refactor-baselines/current/baseline-result.json:65:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\current\\outputs\\warehouse-page-001.dxf",`; `cad_photo_to_dxf/validation/system-refactor-baselines/old/baseline-result.json:65:      "dxf_path": "C:\\Users\\agcrf\\Desktop\\image-to-cad\\cad_photo_to_dxf\\validation\\system-refactor-baselines\\old\\outputs\\warehouse-page-001.dxf",`; `cad_photo_to_dxf/validation/user-pdf-check/warehouse-page-001.dxf:3234:wqy-unicode.lff`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:116:- `cad_photo_to_dxf/validation/user-pdf-check/warehouse-page-001.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:187:- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/warehouse-page-001.dxf`（新增）`; `docs/IMPLEMENTATION_SEQUENCE_MATRIX.md:193:- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/warehouse-page-001.dxf`（新增）`
- Generated: `True`; test input: `False`; test output: `True`; runtime asset: `False`; font: `False`; real scan fixture: `False`; historical evidence: `True`.
- License/source: Source: project-supplied validation input and repository validation code; generated internal evidence, not a source PDF/PNG fixture.
- Deletion impact: No current runtime/test/installer dependency; paths are historical validation output references only.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **A. ??????? Git ??** ? Generated validation output; source input and validation code are retained, so the binary is not required in the current Git tree.
- Proposed action: copy exact bytes to external recovery package, record all hashes/blob/commit metadata, delete from current Git tree, retain compact manifest/hash only
- Regeneration command: `Use the source-specific validation command recorded in the historical validation report; output remains outside Git.`
- Acceptance test: Recovery archive round-trip restores every byte; source validation command remains documented; full hygiene reports no tracked generated DXF.

## 94. `cad_photo_to_dxf/resources/fonts/wqy-unicode.lff`

- Original finding: `tracked file exceeds repository size limit`; size `43717474` bytes; extension `.lff`.
- Git blob SHA-1: `b4b4a17f3b3d18dd007655973618c9802f18740f`; worktree SHA256: `dead7199fba22075c5e263f8e61c72accef7c6a28dc542afb21913c62a9a13e1`; canonical Git blob SHA256: `3c97e1dc9732578fe42fca6329bd2369d17b798405b14443b0b9d41e0bacc201`; canonical size: `43436980`.
- First introduced commit: `d9fbda763e95c6dd7154934b801b59dbf034e711` (2026-07-27T19:27:48+08:00); subject: '1'.
- References (523 search hits):
  - code: `cad_photo_to_dxf/app/librecad_lff.py:19:LIBRECAD_FONT_FILENAME = "wqy-unicode.lff"`; `cad_photo_to_dxf/app/librecad_ocr_review.py:66:                "LibreCAD 中文字体：wqy-unicode.lff（预览与 DXF 完全同源）",`; `cad_photo_to_dxf/app/librecad_ocr_review.py:86:                "本窗口的紫色笔画直接由 wqy-unicode.lff 解析，导出后的 TEXT 也引用同一字体。",`; `cad_photo_to_dxf/scripts/prepare_librecad_font.py:138:            "Could not extract wqy-unicode.lff. The SourceForge package did not "`; `cad_photo_to_dxf/scripts/prepare_librecad_font.py:155:    filename = Path(str(manifest.get("filename", "wqy-unicode.lff"))).name`
  - documentation_or_validation: `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/environment-page-003-full-v2.dxf:3234:wqy-unicode.lff`; `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/warehouse-page-001-full-v2.dxf:3234:wqy-unicode.lff`; `cad_photo_to_dxf/validation/actual-pdf-fix-2026-07-27/warehouse-page-001-full.dxf:3234:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/CHECKPOINT.md:60:- Confirmed the project and installed LibreCAD `wqy-unicode.lff` files are`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-plan-page-003-150dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-001-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-002-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-004-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-008-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/environment-scan-page-014-120dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/warehouse-index-page-001-150dpi.dxf:3282:wqy-unicode.lff`; `cad_photo_to_dxf/validation/editable-text-recovery/before/dxf/warehouse-plan-page-003-72dpi.dxf:3282:wqy-unicode.lff`
  - other: `cad_photo_to_dxf/resources/fonts/librecad-font.json:5:  "filename": "wqy-unicode.lff",`; `cad_photo_to_dxf/resources/fonts/librecad-font.lock.json:5:  "filename": "wqy-unicode.lff",`
  - tests: `cad_photo_to_dxf/tests/test_font_aware_ocr_export.py:47:    assert style.dxf.font == "wqy-unicode.lff"`; `cad_photo_to_dxf/tests/test_librecad_lff_export.py:67:    assert document.styles.get("wqy-unicode").dxf.font == "wqy-unicode.lff"`
- Generated: `False`; test input: `False`; test output: `False`; runtime asset: `True`; font: `True`; real scan fixture: `False`; historical evidence: `False`.
- License/source: Source: LibreCAD Resources / WenQuanYi archive in cad_photo_to_dxf/resources/fonts/librecad-font.json; license: Apache-2.0 OR GPL-3.0-or-later; license text: cad_photo_to_dxf/resources/fonts/WQY-LICENSE-Apache-2.0.txt.
- Deletion impact: Deleting or changing this file would break native Unicode TEXT metrics, DXF STYLE resolution and LibreCAD read-save-read behavior.
- Replacement method: Retain exact bytes in external recovery package; retain compact manifest/hash and regenerate from source where applicable.
- Classification: **E. ?????????? Unicode LFF ??** ? Formal native TEXT/LibreCAD runtime asset; retain in Git and bind to exact canonical Git blob SHA, size, license and required code paths.
- Proposed action: retain and strictly approve as runtime asset; do not delete, replace, rename or alter
- Regeneration command: `Not generated; scripts/prepare_librecad_font.py downloads/extracts the pinned LibreCAD Resources archive.`
- Acceptance test: Approved-asset tests pass for exact path/blob SHA/canonical size/license; mutation tests reject SHA/path/size/license changes; font hash and STYLE/metrics regression remain unchanged.

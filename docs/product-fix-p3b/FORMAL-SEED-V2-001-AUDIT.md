# P3B formal human seed 001 — completed audit

**Distribution-only script output.** The complete manual recovery audit, including independent nomination-quality flags and the final **PASS_WITH_REVIEW_SUBSET** decision, is [FORMAL-SEED-AUDIT.md](FORMAL-SEED-AUDIT.md). Its only next-action recommendation is a bounded review of 13 samples; no training or validation work has begun.

Final human decisions only. No training or validation/blind source access.

```text
TOTAL_REVIEWED: 100
VALID_TARGET: 95
INVALID_NOMINATION: 4
UNCLEAR_TARGET: 1
SINGLE_PHYSICAL_STROKE: 38
TRUE_PARALLEL_STRUCTURE: 21
OTHER: 36
AMBIGUOUS: 0
VALID_BUT_UNCLASSIFIED: 0
SKIPPED: 0
NO_STAGE0_STATUS: 0
FORMAL_SEED_HEALTH: PASS
TRAINING_AUTHORIZED: NO
```

Proposed diagnostic thresholds for this 100-sample seed: V2 nomination quality >=95%, each structural class >=20 across >=3 drawings / >=2 families, OTHER <=60%, no unclassified V or missing Stage 0, drawing <=25%, family <=35%. These are not learned-model safety or training entry criteria.

## Assessment

The proposed seed-distribution checks pass.

Distribution supports proposing an independent validation batch; sources remain unopened and approval is still required

## source_drawing_id

| Group | Reviewed | V | X | U | Single | Parallel | Other | Ambiguous | V unclassified | Skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A2-SG-009 | 10 | 8 | 1 | 1 | 2 | 6 | 0 | 0 | 0 | 0 |
| A2-SG-022 | 10 | 10 | 0 | 0 | 4 | 6 | 0 | 0 | 0 | 0 |
| G0R2-15EE2398726E8037 | 5 | 5 | 0 | 0 | 0 | 1 | 4 | 0 | 0 | 0 |
| G0R2-3560D9BEBEAA3543 | 10 | 10 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 |
| G0R2-3B970FD759C6026F | 9 | 9 | 0 | 0 | 8 | 0 | 1 | 0 | 0 | 0 |
| G0R2-4A34D1B8D93B1B06 | 4 | 4 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 0 |
| G0R2-6C9464FA73A2A027 | 9 | 9 | 0 | 0 | 4 | 1 | 4 | 0 | 0 | 0 |
| G0R2-7E30C7F445081F40 | 8 | 6 | 2 | 0 | 1 | 1 | 4 | 0 | 0 | 0 |
| G0R2-B441E5911528F402 | 4 | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| G0R2-C2D095E069663C17 | 8 | 8 | 0 | 0 | 4 | 1 | 3 | 0 | 0 | 0 |
| environment-building | 9 | 9 | 0 | 0 | 5 | 3 | 1 | 0 | 0 | 0 |
| sample-plan-photo | 5 | 5 | 0 | 0 | 4 | 1 | 0 | 0 | 0 | 0 |
| warehouse-electrical | 9 | 8 | 1 | 0 | 5 | 1 | 2 | 0 | 0 | 0 |

## source_family_id

| Group | Reviewed | V | X | U | Single | Parallel | Other | Ambiguous | V unclassified | Skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AU_NSW_P5_2023_61 | 8 | 6 | 2 | 0 | 1 | 1 | 4 | 0 | 0 | 0 |
| AU_NSW_P5_2024_93 | 8 | 8 | 0 | 0 | 4 | 1 | 3 | 0 | 0 | 0 |
| CAN_BELLEVILLE_SCHOOL_ARCHIVE | 10 | 8 | 1 | 1 | 2 | 6 | 0 | 0 | 0 | 0 |
| CN_ZHEJIANG_PUBLIC_ELECTRICAL_0C1671 | 4 | 4 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 0 |
| JP_IGA_2020000378 | 9 | 9 | 0 | 0 | 4 | 1 | 4 | 0 | 0 | 0 |
| JP_IGA_4291000114 | 5 | 5 | 0 | 0 | 0 | 1 | 4 | 0 | 0 | 0 |
| JP_YOKOHAMA_HIYOSHIDAI_TEMP_CLASSROOM | 9 | 9 | 0 | 0 | 8 | 0 | 1 | 0 | 0 | 0 |
| TW_NTPC_INDIGENOUS_HOME_STANDARD_2016 | 10 | 10 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 |
| UK_BANBURY_TRAMWAY_ASBUILT | 10 | 10 | 0 | 0 | 4 | 6 | 0 | 0 | 0 | 0 |
| US_LOC_HABS_FL0790 | 4 | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| sample-plan-photo | 5 | 5 | 0 | 0 | 4 | 1 | 0 | 0 | 0 | 0 |
| user-project-haiyang | 18 | 17 | 1 | 0 | 10 | 4 | 3 | 0 | 0 | 0 |

## target_kind

| Group | Reviewed | V | X | U | Single | Parallel | Other | Ambiguous | V unclassified | Skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 20 | 19 | 0 | 1 | 3 | 0 | 16 | 0 | 0 | 0 |
| PAIR | 60 | 59 | 1 | 0 | 22 | 21 | 16 | 0 | 0 | 0 |
| SINGLE | 20 | 17 | 3 | 0 | 13 | 0 | 4 | 0 | 0 | 0 |

Full history/schema/identity audit: `FORMAL-SEED-V2-001-AUDIT.json`.

The user's and reviewer's seed-distribution approval is still required before any training. No validation batch was opened or generated. STOP.

# Draftsman Generalization Corpus V1

Status: `AUTHORITATIVE — FROZEN`

Corpus V1 freezes SOURCE_GROUP identity and split assignment only. It does not
contain, acquire, hash, execute, or redistribute third-party source files.

## Frozen inputs and outputs

- Candidate registry: `g0_candidate_registry.jsonl`
- Candidate count: 99
- Candidate registry SHA256:
  `07e25d6d876c0d0416556aefe01267d688da495111eec69e521bb2c70803e780`
- Selection policy: `draftsman-g0-b3-selection-v1`
- Authoritative split: `g0_corpus_v1_split.json`
- Authoritative split SHA256:
  `05283c960096941ecac34f73e109fe9d850e8d2354b144387c00370755d288cd`
- Selection audit: `g0_selection_report.json`

The authoritative allocation is exactly 15 DEV, 7 VALIDATION, 8
LOCKED_BLIND, and 15 RESERVE SOURCE_GROUPS. DEV, VALIDATION, and LOCKED_BLIND
form the 30-source Corpus V1; RESERVE is outside that evaluation corpus until a
documented deterministic replacement is required.

## Governance gate

The gate is evaluated before selection. Explicitly license-restricted records
are ineligible. Records with unresolved SOURCE_GROUP/parent-package relations
or `REVIEW_REQUIRED` access are excluded. Public access with unclear
redistribution is eligible only with an advisory because this phase freezes
identities and does not redistribute source material.

The registry contained 17 explicit ineligible records, 13 `REVIEW_REQUIRED`
flags, and 12 unresolved dedup flags. The policy also detected two related Fort
McPherson standardized mess-hall records and excluded both pending family
resolution. The report preserves an exclusive primary decision for every one
of the 99 candidates and the overlapping raw gate counts.

## Deterministic selection

The policy uses a greedy marginal diversity score over quality tier,
governance suitability, macro-region, rendering class, historical/degraded/
native-image evidence, and evidenced drawing families. Split order is
LOCKED_BLIND, VALIDATION, DEV, then RESERVE. Every weight, target, filter, and
tie-break is embedded in the split artifact. Equal scores use ascending stable
`source_group_id`; no runtime result or model performance is an input.

The selected 30 contain 7 confirmed raster/scanned, 3 confirmed vector, 4
confirmed mixed, and 16 unknown groups; 11 historical/archival, 6 confirmed
degraded, and 5 native-image groups. Macro-region distribution is East Asia 9,
Europe 1, North America 11, and Oceania 9. Europe has only one candidate that
passes the current governance and dedup gates, so the policy does not fabricate
additional European eligibility.

## Blind-set protection

All eight LOCKED_BLIND groups are newly discovered G0-R2 STRONG candidates,
were absent from the old provisional proposal and development fixtures, and
have `blind_exposure_status = NEVER_EXECUTED`. Ordinary code calling
`load_locked_blind_ids` fails closed unless explicit opt-in is supplied. This
freeze did not run Draftsman, inspect model performance, or execute any blind
source.

Any future execution must record exposure. A source targeted by rule changes
can no longer be represented as unexposed validation/blind data; replacement
must come from RESERVE under a separately reviewed deterministic policy.

## Replay and next phase

Run the checked-in selector with `--check` to recompute selection from the
bound registry, compare the full split and selection report byte-for-byte, and
replay the authoritative digest. A registry digest mismatch, count mismatch,
overlap, family leakage, exposure, or ineligible selection fails closed.

The next phase may acquire and materialize the selected sources. Evaluation,
LOCKED_BLIND execution, G1, and QA2-S3 remain outside this freeze.

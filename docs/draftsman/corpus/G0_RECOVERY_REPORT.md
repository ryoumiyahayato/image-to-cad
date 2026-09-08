# DRAFTSMAN G0-R1 Candidate Registry Recovery

Status: `PARTIAL_RECOVERY — TARGETED_REDISCOVERY_REQUIRED`

## Scope and baseline

- Repository branch: `fix/p1-uat-rc3-structure-protection-20260811`
- Recovery base: `6b9777f21d313ba13d71fcdc7ad459523eb1196e`
- Historical viable SOURCE_GROUP expectation: 96
- Production semantic delta: none
- Corpus acquisition, Draftsman runtime, G0-B2, G1, and QA2-S3 were not run.

## Evidence audit

The audit checked the current tracked tree, `docs/draftsman`, tests, fixtures,
reports, repo-local ignored artifacts, reasonable Desktop and Downloads
locations, Codex attachments/session logs, every local/remote Git ref, Git log,
and reflog. Git history contains no committed-then-deleted G0 registry.

One substantive recovery artifact was found:

- Artifact: `draftsman_g0b_repository_import_pending.zip`
- Location at recovery: `C:\Users\agcrf\Downloads`
- SHA256: `5e5da8010c6a9a5c37f2ec47f503ec2737410f6aed5a5cd921a3d1f2d2cc386e`
- Selected manifest records: 30
- Reserve records: 15
- Unique recovered SOURCE_GROUPS: 45

The recovered records contain 19 G0-A and 26 G0-A2 candidates. No other
local evidence contained additional complete candidate records. The remaining
51 historical candidates were not reconstructed from aggregate counts,
identifier gaps, regional totals, or inferred URLs.

## Registry result

`g0_candidate_registry.jsonl` is the durable registry for the 45 real records
that were recoverable. It is not Corpus V1 and contains no authoritative split.
Every record carries the recovery artifact name, archive SHA256, archive member,
candidate ID, legacy role, and a non-authoritative legacy split value when one
was present.

Canonical serialization is UTF-8 JSON Lines, one compact object per line,
object keys sorted lexicographically, records sorted by `source_group_id`, LF
line endings, and one final LF. Its SHA256 is stored separately in
`g0_registry_digest.txt`.

Future discovery work must add only evidence-backed records, retain discovery
and recovery provenance, run the registry validator, rewrite the complete file
in canonical order, and update `g0_registry_digest.txt` in the same commit.
Aggregate counts, identifier gaps, and inferred URLs are never valid records.

Counts in the durable registry:

- Total: 45
- G0-A: 19
- G0-A2: 26
- Legacy selected: 30
- Legacy reserve: 15
- Confirmed raster: 10
- Confirmed vector: 5
- Historical/archival: 19
- Confirmed degraded scans: 2
- Native images: 10

The per-record STRONG/SECONDARY classification was absent from the recovered
artifact, so `quality_tier` remains `UNKNOWN`. Missing landing/download URLs and
unverified degradation states remain `null`; they were not guessed.

## Duplicate and source-family review

Exact canonical URLs and SOURCE_GROUP IDs are unique in the recovered set.
Three legacy source-family labels are shared by multiple records, affecting
nine SOURCE_GROUP records:

- `TAIWAN_GAO_ER_PAN_OFFICE`: 2 records
- `TAIWAN_EAST_CATHOLIC_ARCHIVE_FAMILY`: 2 records
- `HISTORIC_ENGLAND_ARCHIVE_FAMILY`: 5 records

Those records are retained with `dedup_status = UNRESOLVED`. Shared family
membership is evidence of possible relation, not sufficient evidence for an
automatic merge.

## Legacy G0-B proposal

The exact old 30-entry split member is preserved as
`legacy_g0b_provisional_split.json`. It remains explicitly not frozen and has
no authoritative digest.

- Declared old provisional digest:
  `725b71a5e645b35f6cd1ebf13c913a367e90089468eff1af456aca3cd8d74dc6`
- SHA256 of the exact recovered member bytes:
  `84c8d26c089f22bef21a4617a0e406ab47aaaca4ec4d541dfdb8e392a2617cae`
- Verification result: `NOT_REPLAYABLE`

The declared value does not match the recovered raw bytes or tested compact
and pretty-printed stable-key JSON serializations. The original canonicalization
procedure was not preserved, so no replacement digest is presented as the old
digest.

## Decision

The registry is real, version-controlled, schema-constrained, and deterministic,
but it contains only 45 of the historically reported 96 viable SOURCE_GROUPS.
G0-B selection replay and G0-B2 acquisition remain blocked. The next action is
targeted rediscovery of 51 independent, diverse, authentic candidate groups;
new findings must be appended to this registry with provenance immediately.

# Numerical replay commands and verdict boundaries

`replay_numerical_contract.py` provides three explicit operations. It uses the
repository's existing native dependencies and Python 3.12; the interval module
itself uses only the standard library. No operation invokes OCR, modifies the
input evidence or generates a DXF. Both the output and its `.execution.json`
receipt must be new files.

## 1. Legacy v1 compatibility, after the original exact verifier

First run the archived A replay entry against an unchanged A checkout and
the original drawing/source evidence. Keep its real strict FAIL and separately
reconstruct the full old plan using that same frozen producer. Do not substitute
two newly generated same-environment plans for the original saved plan.

Then, using this checkout, run:

```sh
python experiments/issue60_common_acceptance/replay_numerical_contract.py \
  legacy-compatibility \
  --saved-plan "$ORIGINAL_A_PLAN" \
  --replayed-plan "$INDEPENDENT_FROZEN_A_REPLAYED_PLAN" \
  --strict-failure "$ORIGINAL_STRICT_FAILURE_REPORT" \
  --expected-producer-sha256 "$FROZEN_A_GRAPH_MODULE_SHA256" \
  --output "$NEW_RUN/legacy_compatibility.json"
```

The expected producer SHA is an independently established 64-character
SHA-256, not a missing value or an identity inferred from an untrusted plan.
`LEGACY_DIAGNOSTIC_COMPATIBILITY_PASS` is a new, separately versioned judgment.
Its `legacy_original_strict_status` and all differing original numeric values
remain visible. It does not turn the original strict verifier's FAIL into PASS,
relabel the old DXF's producer or approve its raw-ink ownership.

## 2. Generate a genuinely new v2 source plan

The prior plan supplies the ROI and preceding-stage object bindings. The new
planner rebuilds its graph from the image. These bindings are inputs to the
new source proof; their presence alone does not establish saved-object or
attached-end ownership acceptance.

```sh
python experiments/issue60_common_acceptance/replay_numerical_contract.py \
  generate-plan \
  --input "$ORIGINAL_IMAGE" \
  --expected-source-sha256 "$VERIFIED_IMAGE_SHA256" \
  --prior-plan "$ORIGINAL_A_PLAN" \
  --output "$NEW_RUN/v2_plan.json"
```

The plan retains the producer's original raw diagnostics and adds a separately
derived interval certificate. It has new schemas and exact code identities.
The numerical change does not replace the attached-end geometry or original
source-responsibility model. A proposed path count is not a count of newly
delivered, independently accepted CAD objects.

## 3. Cold-rebuild that saved v2 plan

Use a separate invocation after the preceding process exits:

```sh
python experiments/issue60_common_acceptance/replay_numerical_contract.py \
  verify-plan \
  --input "$ORIGINAL_IMAGE" \
  --expected-source-sha256 "$VERIFIED_IMAGE_SHA256" \
  --plan "$NEW_RUN/v2_plan.json" \
  --output "$NEW_RUN/v2_cold_replay.json"
```

The verifier reconstructs from current source pixels again, requires the
correct producer/contract identity and checks the entire plan. Only the exact
diagnostic paths declared in the frozen contract may differ, and both raw
values must fit their independently derived interval. All other leaves,
including geometry, actual intersection points, endpoints, pixel ownership,
IDs, hashes and discrete decisions, remain strict. The separate saved-DXF cold
audit repeats the path comparison under the already verified certificate and
retains all existing actual-file/hash/object checks.

Each command records the actual Git checkout, whether it was dirty, input and
module SHA-256 values before and after execution, result SHA and elapsed time.
`--repo /path/to/checkout` may be supplied before the operation name if the
script and imported checkout are in different locations. Shared inputs remain
read-only; use distinct output files and isolated writable caches as usual.

## Numerical ambiguity and validation scope

All competing decompositions, possible finite segment contacts and parallel
companions are examined. An uncertain competitor cannot disappear in order to
make another explanation unique. A numerically unresolved component remains
PENDING and has no adopted paths. Its raw candidate geometry/evidence is
retained separately and receives strict-only replay; a matched negative plan
reports `numeric_adoption_status=PENDING`.

The certificate records final enclosures, key conditioning intervals, gate
checks and complete contact/companion checks. It does not claim to store every
arithmetic intermediate or to guarantee a universal error bound for all
SVD/LAPACK/libm builds. The attached-end construction and native-fit gates are
unchanged. A numeric replay PASS cannot override a saved-geometry failure,
an unexplained original-ink extension or a failed independent ownership audit.

The design history is preserved in `NUMERICAL_CONTRACT_FROZEN.md` and its two
explicit implementation clarifications. Actual evidence and exact execution
commits are recorded separately; these command examples are not execution
receipts.

# CURRENT PRIMITIVE ELIGIBLE SET V1

Status: `CURRENT_PRIMITIVE_ELIGIBLE_SET_V1: FROZEN_DERIVED_SET`

Base checkpoint: `ac9606608af438412210b9b51ccb9825cdc3a3a2`
Frozen provenance pool: `147`
Current eligible: `122`
Current ineligible: `25`
Digest: `966a26a3cfc4974eccd36bf4a6453a6b22c800046465611ccb40596ff86e9075`
Deterministic replay: `PASS`

Derivation order:
`FROZEN147 → span eligibility → axis eligibility → text/glyph integrity → straight primitive validity → existing admissibility`.

All 147 provenance records remain in the JSON manifest. An upstream rejection is monotonic; text-uncertain and straight-uncertain records remain eligible because no existing guard rejects uncertainty at this stage.

## Exclusion counts

| reason | count |
|---|---:|
| STRAIGHT_VALIDITY_REJECTED | 22 |
| TEXT_GLYPH_REJECTED | 9 |

## Governance

- No guard, threshold, feature, admissibility semantic, production code, model, remine, VALIDATION, LOCKED_BLIND, or H1/H2 activity occurred.
- This derived set is the only downstream replacement universe for SOURCE_GAP_REVIEW_V1_2.

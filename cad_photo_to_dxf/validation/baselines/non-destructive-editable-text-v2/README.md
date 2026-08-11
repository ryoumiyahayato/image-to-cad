# Non-destructive editable text V2

`non-destructive-editable-text-v2` is an explicit additive-restoration
contract. It inherits the V1 anchors and semantic protections, but does not
reuse V1's whole-partition equality rule for the RC3 structure restoration.

V2 permits only a deterministic, source-backed candidate-minus-base delta in
the declared structure partition. Every restoration must carry source,
pre-mask, mask, decision, ownership-negative, duplicate, transform, entity,
and aggregate evidence hashes. The validator computes the candidate-minus-base
counted multiset itself; the manifest cannot authorize an entity that is not
present in that computed delta.

The V1 contract remains immutable. In particular, callers must pass the
explicit V2 name to select this validator; passing V2 to the historical V1
validator continues to fail closed.

The schema is [`schema.json`](schema.json). The implementation validator is:

```text
python cad_photo_to_dxf/scripts/editable_text_v2_contract.py validate \
  --repository-root . \
  --manifest cad_photo_to_dxf/validation/baselines/non-destructive-editable-text-v2/manifest.json \
  --output local-artifacts/review/p1-v2-implementation/v2-validation.json
```

The package is intentionally separate from `local-artifacts`; generated
review packages and LibreCAD UAT copies are not committed as baseline source.

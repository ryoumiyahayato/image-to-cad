from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.g0_candidate_registry import (
    RegistryValidationError,
    canonical_registry_bytes,
    load_registry,
    normalize_canonical_url,
    rediscovered_source_group_id,
    registry_stats,
    registry_sha256,
    validate_record,
    validate_registry,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _record(source_group_id: str = "SG-001") -> dict[str, object]:
    return {
        "schema_version": "draftsman-g0-candidate-registry-v1",
        "source_group_id": source_group_id,
        "candidate_ids": ["G0A-001"],
        "canonical_source_url": "https://example.invalid/drawing.pdf",
        "landing_page_url": None,
        "retrieval_url": None,
        "organization": "Example authority",
        "project_or_package": "Example project",
        "region": "Example region",
        "country_or_area": "Example country",
        "source_type": "engineering drawing",
        "file_format": "PDF",
        "vector_raster_status": "UNKNOWN",
        "historical_archival": False,
        "degraded_scan": None,
        "native_image": False,
        "era": "UNKNOWN",
        "discipline": "electrical",
        "drawing_type": "plan",
        "discovery_phase": "G0-A",
        "quality_tier": "UNKNOWN",
        "quality_flags": [],
        "governance_status": "PUBLIC_ACCESS_REUSE_UNCLEAR",
        "governance_or_access_notes": "No redistribution permission inferred.",
        "source_family_id": "EXAMPLE_PROJECT",
        "source_group_independence_notes": "One project/package.",
        "recovery_provenance": [
            {
                "kind": "TEST",
                "artifact_name": "fixture.json",
                "artifact_sha256": "0" * 64,
                "member_path": "fixture.json",
            }
        ],
        "record_status": "RECOVERED_REAL_CANDIDATE",
        "split_eligibility": "PROVISIONAL_PENDING_ACQUISITION",
        "identity_scope": "SOURCE_GROUP",
        "dedup_status": "DISTINCT",
        "legacy_proposal_role": "RESERVE",
        "legacy_planned_split": None,
        "legacy_proposal_authoritative": False,
    }


class G0CandidateRegistryTests(unittest.TestCase):
    def test_schema_validation_accepts_complete_record(self) -> None:
        validate_record(_record())

    def test_malformed_record_is_rejected(self) -> None:
        record = _record()
        del record["canonical_source_url"]
        with self.assertRaisesRegex(RegistryValidationError, "missing required fields"):
            validate_record(record)

    def test_duplicate_source_group_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(RegistryValidationError, "duplicate source_group_id"):
            validate_registry([_record(), _record()])

    def test_page_cannot_be_an_independent_source_group(self) -> None:
        record = _record("PROJECT-PAGE-003")
        with self.assertRaisesRegex(RegistryValidationError, "page-derived"):
            validate_record(record)

    def test_provenance_is_required(self) -> None:
        record = _record()
        record["recovery_provenance"] = []
        with self.assertRaisesRegex(RegistryValidationError, "recovery_provenance"):
            validate_record(record)

    def test_legacy_proposal_cannot_be_authoritative(self) -> None:
        record = _record()
        record["legacy_proposal_authoritative"] = True
        with self.assertRaisesRegex(RegistryValidationError, "non-authoritative"):
            validate_record(record)

    def test_serialization_and_digest_are_deterministic(self) -> None:
        first = _record("SG-001")
        second = _record("SG-002")
        reordered_second = dict(reversed(list(second.items())))
        forward = [first, reordered_second]
        reverse = [copy.deepcopy(second), copy.deepcopy(first)]
        self.assertEqual(canonical_registry_bytes(forward), canonical_registry_bytes(reverse))
        self.assertEqual(registry_sha256(forward), registry_sha256(reverse))

    def test_g0_r2_identity_is_deterministic_after_url_normalization(self) -> None:
        first = "HTTPS://Example.COM:443/drawing.pdf?b=2&a=1#page=2"
        second = "https://example.com/drawing.pdf?a=1&b=2"
        self.assertEqual(normalize_canonical_url(first), second)
        self.assertEqual(rediscovered_source_group_id(first), rediscovered_source_group_id(second))

    def test_g0_r2_record_requires_deterministic_id_and_web_provenance(self) -> None:
        record = _record(rediscovered_source_group_id("https://example.invalid/new.pdf"))
        record.update(
            {
                "canonical_source_url": "https://example.invalid/new.pdf",
                "discovery_phase": "G0-R2",
                "record_status": "REDISCOVERED_REAL_CANDIDATE",
                "legacy_proposal_role": None,
                "legacy_planned_split": None,
                "recovery_provenance": [
                    {
                        "kind": "PUBLIC_WEB_REDISCOVERY",
                        "source_url": "https://example.invalid/new.pdf",
                        "observed_at": "2026-09-08",
                    }
                ],
            }
        )
        validate_record(record)
        record["source_group_id"] = "G0R2-NOT-DETERMINISTIC"
        with self.assertRaisesRegex(RegistryValidationError, "non-deterministic"):
            validate_record(record)

    def test_duplicate_normalized_url_is_rejected(self) -> None:
        first = _record("SG-001")
        second = _record("SG-002")
        second["canonical_source_url"] = "HTTPS://EXAMPLE.INVALID:443/drawing.pdf#fragment"
        with self.assertRaisesRegex(RegistryValidationError, "duplicate canonical_source_url"):
            validate_registry([first, second])

    def test_loader_rejects_noncanonical_or_invalid_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.jsonl"
            path.write_text(json.dumps({"source_group_id": "SG-001"}) + "\n", encoding="utf-8")
            with self.assertRaises(RegistryValidationError):
                load_registry(path)

    def test_checked_in_registry_matches_schema_and_digest(self) -> None:
        registry_path = REPOSITORY_ROOT / "docs/draftsman/corpus/g0_candidate_registry.jsonl"
        schema_path = REPOSITORY_ROOT / "docs/draftsman/corpus/g0_candidate_registry.schema.json"
        digest_path = REPOSITORY_ROOT / "docs/draftsman/corpus/g0_registry_digest.txt"
        records = load_registry(registry_path)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), set(records[0]))
        for record in records:
            self.assertEqual(set(record), set(schema["required"]))
            for field, specification in schema["properties"].items():
                if "enum" in specification:
                    self.assertIn(record[field], specification["enum"])
        self.assertEqual(registry_path.read_bytes(), canonical_registry_bytes(records))
        self.assertEqual(registry_sha256(records), digest_path.read_text(encoding="utf-8").strip())

    def test_checked_in_registry_reaches_g0_r2_pool_target(self) -> None:
        registry_path = REPOSITORY_ROOT / "docs/draftsman/corpus/g0_candidate_registry.jsonl"
        stats = registry_stats(load_registry(registry_path))
        self.assertEqual(stats["total_real_source_groups"], 99)
        self.assertEqual(stats["new_g0_r2_source_groups"], 54)
        self.assertGreaterEqual(stats["total_viable_source_groups"], 96)

    def test_legacy_proposal_is_preserved_but_not_frozen(self) -> None:
        path = REPOSITORY_ROOT / "docs/draftsman/corpus/legacy_g0b_provisional_split.json"
        proposal = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(proposal["freeze_status"], "NOT_FROZEN_ACQUISITION_PENDING")
        self.assertIsNone(proposal["authoritative_frozen_digest"])
        self.assertEqual(len(proposal["entries"]), 30)
        self.assertEqual(
            proposal["provisional_manifest_sha256"],
            "725b71a5e645b35f6cd1ebf13c913a367e90089468eff1af456aca3cd8d74dc6",
        )
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            "84c8d26c089f22bef21a4617a0e406ab47aaaca4ec4d541dfdb8e392a2617cae",
        )
        self.assertNotEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            proposal["provisional_manifest_sha256"],
        )


if __name__ == "__main__":
    unittest.main()

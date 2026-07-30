from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.final_structure import FINAL_STRUCTURE_SCHEMA_VERSION
from app.processing_contract import (
    DISABLED_LAYOUT_PROFILE,
    LayoutProfileSelection,
    ProcessingCacheKey,
    ProductionProcessingConfig,
    ProductionProcessingService,
    build_processing_cache_key,
    cache_key_matches,
    file_content_sha256,
)
from app.trace_storage import load_trace_cache, save_trace_cache


def _page() -> np.ndarray:
    image = np.full((120, 180), 255, dtype=np.uint8)
    cv2.rectangle(image, (12, 12), (168, 108), 0, 2)
    cv2.line(image, (30, 60), (150, 60), 0, 2)
    return image


def _key(
    content_hash: str,
    config: ProductionProcessingConfig | None = None,
) -> ProcessingCacheKey:
    return build_processing_cache_key(
        input_content_sha256=content_hash,
        page_index=0,
        config=config
        or ProductionProcessingConfig(
            source_dpi=300.0,
            enable_ocr=False,
        ),
    )


def test_default_layout_profile_is_explicit_and_disabled() -> None:
    config = ProductionProcessingConfig()

    assert not config.layout_profile.enabled
    assert config.layout_profile.name == DISABLED_LAYOUT_PROFILE
    assert config.payload()["layout_profile"] == {
        "enabled": False,
        "name": "disabled",
    }
    with pytest.raises(ValueError):
        LayoutProfileSelection(enabled=False, name="title-block-a")


def test_cache_key_contains_every_required_reproducibility_field() -> None:
    content_hash = "a" * 64
    key = _key(content_hash)

    assert key.payload().keys() == {
        "input_content_sha256",
        "page_number",
        "dpi",
        "enable_ocr",
        "algorithm_version",
        "model_version",
        "config_summary",
        "layout_profile",
        "final_structure_schema_version",
        "critical_threshold_summary",
    }
    assert key.input_content_sha256 == content_hash
    assert key.page_number == 1
    assert key.final_structure_schema_version == (
        FINAL_STRUCTURE_SCHEMA_VERSION
    )
    assert ProcessingCacheKey.from_payload(key.payload()) == key


def test_every_cache_contract_change_produces_a_distinct_key() -> None:
    content_hash = "b" * 64
    base_config = ProductionProcessingConfig(
        source_dpi=300.0,
        enable_ocr=False,
    )
    base = _key(content_hash, base_config)
    variants = (
        _key("c" * 64, base_config),
        _key(content_hash, replace(base_config, source_dpi=600.0)),
        _key(content_hash, replace(base_config, enable_ocr=True)),
        _key(
            content_hash,
            replace(base_config, foreground_threshold=170),
        ),
        _key(
            content_hash,
            replace(base_config, algorithm_version="other-algorithm"),
        ),
        _key(
            content_hash,
            replace(base_config, model_version="other-model"),
        ),
        _key(
            content_hash,
            replace(
                base_config,
                layout_profile=LayoutProfileSelection(
                    enabled=True,
                    name="explicit-test-profile",
                ),
            ),
        ),
    )

    assert all(item != base for item in variants)
    assert len({base.digest, *(item.digest for item in variants)}) == 8


def test_same_path_with_changed_content_changes_input_hash_and_key(
    tmp_path: Path,
) -> None:
    source = tmp_path / "same-name.pdf"
    source.write_bytes(b"first content")
    first_hash = file_content_sha256(source)
    first = _key(first_hash)
    source.write_bytes(b"second content")
    second_hash = file_content_sha256(source)
    second = _key(second_hash)

    assert first_hash != second_hash
    assert first.digest != second.digest


def test_production_service_is_deterministic_and_records_configuration() -> None:
    config = ProductionProcessingConfig(
        source_dpi=300.0,
        enable_ocr=False,
    )

    first = ProductionProcessingService.process_page(_page(), config)
    second = ProductionProcessingService.process_page(_page(), config)

    assert first.final_structure is not None
    assert second.final_structure is not None
    assert (
        first.final_structure.structure_id
        == second.final_structure.structure_id
    )
    assert (
        first.final_structure.provenance["processing_contract"]
        == config.payload()
    )
    assert not first.final_structure.contour_binary.flags.writeable
    with pytest.raises(TypeError):
        first.final_structure.provenance["mutate"] = True  # type: ignore[index]


def test_cache_roundtrip_requires_exact_embedded_key(
    tmp_path: Path,
) -> None:
    config = ProductionProcessingConfig(
        source_dpi=300.0,
        enable_ocr=False,
    )
    key = _key("d" * 64, config)
    result = ProductionProcessingService.process_page(_page(), config)
    cache_path = save_trace_cache(
        tmp_path / "page.npz",
        result,
        cache_key=key.payload(),
    )

    stored = load_trace_cache(cache_path)

    assert cache_key_matches(stored.cache_key, key)
    assert not cache_key_matches(
        stored.cache_key,
        _key("e" * 64, config),
    )


def test_enabled_layout_profile_cannot_enter_generic_pipeline() -> None:
    config = ProductionProcessingConfig(
        source_dpi=300.0,
        enable_ocr=False,
        layout_profile=LayoutProfileSelection(
            enabled=True,
            name="not-installed",
        ),
    )

    with pytest.raises(ValueError, match="No layout profile is installed"):
        ProductionProcessingService.process_page(_page(), config)

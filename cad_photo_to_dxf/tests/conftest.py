"""Explicit fixtures; importing the test suite changes no production behavior."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def native_geometry_export_context():
    """Isolate font packaging only for explicitly requested path-only tests.

    These tests exercise saved CONNECTION_PATH geometry and its cold source
    audit. Exported REVIEW labels are never rendered or measured. No fake
    font file is created, and the metadata cannot be mistaken for a tested
    font or license. Real CLI/resource and text-rendering tests must use the
    unmodified production gate with legitimate resources.
    """

    @contextmanager
    def use_for_paths(objects):
        assert objects and all(obj["kind"] == "CONNECTION_PATH" for obj in objects)
        # Delay the production import until a test explicitly enters this
        # narrow context; unrelated collection needs no native dependencies.
        from app.native_objects import cad_io

        def unused_font_resources(_out):
            return {
                "test_scope": "CONNECTION_PATH_SERIALIZATION_AND_COLD_SOURCE_AUDIT",
                "font_resource": "NOT_EXERCISED",
                "license_resource": "NOT_EXERCISED",
                "text_metrics_and_rendering": "NOT_RUN",
                "production_font_gate_unchanged": True,
            }

        with patch.object(cad_io, "_font", unused_font_resources):
            yield

    return use_for_paths

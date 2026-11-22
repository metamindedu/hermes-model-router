"""Shared fixtures.

Fake homes carry no managed (administrator) config overlay. Service reads the managed provenance of
the model role keys through Hermes' effective-config helpers, which a test interpreter may lack; that
read fails closed (every role unverified), so fake-home tests pin it to "verified, no overlay" here.
Tests of managed, unavailable or changed provenance patch `Service._read_model_overlay` themselves;
tests of the production reader restore `real_model_overlay_reader()`.
"""
from __future__ import annotations

import pytest

NO_MANAGED_OVERLAY = {"available": True, "managed": {}, "digest": "fixture-no-managed-model-config"}
_REAL_READER: list = []


def real_model_overlay_reader():
    return _REAL_READER[0]


@pytest.fixture(autouse=True)
def _no_managed_model_overlay(monkeypatch):
    # Imported lazily: some suites check what importing the package loads.
    from model_router.service import Service
    if not _REAL_READER:
        _REAL_READER.append(Service.__dict__["_read_model_overlay"])
    monkeypatch.setattr(Service, "_read_model_overlay", lambda self, profile: dict(NO_MANAGED_OVERLAY, managed={}))
    yield

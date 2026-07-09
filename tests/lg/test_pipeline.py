"""Tests for pipeline fallback and route tiers."""

from __future__ import annotations

import pytest

from log_guard.lg.pipeline import compress_for_lg
from log_guard.pipeline.config import build_v3_config
from tests.fixtures.lg import full_route_synth_text, medium_cicd_text, tiny_trace_text


def test_v3_config_invariants():
    built = build_v3_config()
    assert built["length_route_v23"] is True
    assert built["payload_mode"] == "ghost_projection"


def test_pipeline_fallback_on_error(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))

    def _boom(*_a, **_k):
        raise RuntimeError("pipeline down")

    monkeypatch.setattr("log_guard.lg.pipeline.run_v23_stages", _boom)
    raw = "keep me\n"
    result = compress_for_lg(raw, "fail", dry_run=True)
    assert result.compressed == raw
    assert result.route == "fallback"


def test_very_short_route_dry(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    raw = tiny_trace_text()
    result = compress_for_lg(raw, "tiny", dry_run=True, preliminary=True)
    assert "[T" in result.compressed or "AttributeError" in result.compressed
    assert result.route in ("very_short", "short", "medium", "full")
    assert not result.distill_called


def test_medium_route_dry(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    raw = medium_cicd_text()
    result = compress_for_lg(raw, "med1", dry_run=True)
    assert len(result.compressed) < len(raw)
    distill = result.phases.get("distill", {})
    assert distill.get("skipped") or distill.get("reason")


def test_full_route_dry(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    raw = full_route_synth_text()
    assert len(raw) >= 15_000
    result = compress_for_lg(raw, "full", dry_run=True)
    assert result.route == "full"
    assert not result.distill_called

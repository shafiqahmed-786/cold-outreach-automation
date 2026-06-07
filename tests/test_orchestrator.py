"""
Integration tests for pipeline/orchestrator.py.

Strategy: mock all four service classes so no real HTTP calls occur and
no .env is required. Tests verify:
- All four stages run end-to-end in mock mode.
- Completed stages are skipped on re-run (resume logic).
- Pipeline aborts gracefully when no contacts are found (Stage 3 empty).
- State is persisted after each stage.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.schemas import (
    OceanResult,
    ProspeoResult,
    EazyreachResult,
    BrevoResult,
    SentEmail,
    SimilarCompany,
    DecisionMaker,
    VerifiedContact,
    PipelineState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_state_file(tmp_path, monkeypatch):
    """Redirect state persistence to a temp file for each test."""
    state_path = tmp_path / "pipeline_state.json"
    monkeypatch.setattr("core.state.get_config", lambda: _cfg(str(state_path)))
    monkeypatch.setattr("pipeline.orchestrator.load_state", _load_from(state_path))
    monkeypatch.setattr("pipeline.orchestrator.save_state", _save_to(state_path))
    return state_path


def _cfg(state_file: str):
    """Minimal config stub."""
    cfg = MagicMock()
    cfg.STATE_FILE = state_file
    cfg.LOG_FILE = "logs/pipeline.log"
    return cfg


def _load_from(path: Path):
    """load_state that reads from our temp path."""
    from core.state import load_state as _real_load
    def _load(domain: str) -> PipelineState:
        if path.exists():
            import json
            data = json.loads(path.read_text())
            state = PipelineState.model_validate(data)
            if state.seed_domain == domain:
                return state
        return PipelineState(seed_domain=domain)
    return _load


def _save_to(path: Path):
    """save_state that writes to our temp path."""
    def _save(state: PipelineState) -> None:
        path.write_text(state.model_dump_json(indent=2))
    return _save


# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------

def _mock_ocean_result() -> OceanResult:
    return OceanResult(
        seed_domain="stripe.com",
        companies=[SimilarCompany(domain="adyen.com", name="Adyen")],
    )

def _mock_prospeo_result() -> ProspeoResult:
    return ProspeoResult(
        decision_makers=[
            DecisionMaker(
                domain="adyen.com",
                full_name="Elena Rossi",
                linkedin_url="https://linkedin.com/in/elenarossi",
                title="CPO",
                company_name="Adyen",
            )
        ]
    )

def _mock_eazyreach_result() -> EazyreachResult:
    return EazyreachResult(
        contacts=[
            VerifiedContact(
                full_name="Elena Rossi",
                email="elena.rossi@adyen.com",
                company_name="Adyen",
                domain="adyen.com",
            )
        ]
    )

def _mock_brevo_result() -> BrevoResult:
    return BrevoResult(
        emails_sent=[
            SentEmail(
                recipient_email="elena.rossi@adyen.com",
                recipient_name="Elena Rossi",
                company_name="Adyen",
                message_id="mock-123",
            )
        ]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_mock_pipeline_runs_all_stages(tmp_path, monkeypatch):
    """All four stages complete successfully in mock mode."""
    state_path = tmp_path / "pipeline_state.json"

    # Patch state I/O
    monkeypatch.setattr(
        "pipeline.orchestrator.load_state",
        lambda domain: PipelineState(seed_domain=domain),
    )
    saved_states: list[PipelineState] = []
    monkeypatch.setattr(
        "pipeline.orchestrator.save_state",
        lambda s: saved_states.append(s),
    )

    # Patch services
    with (
        patch("pipeline.orchestrator.OceanService") as MockOcean,
        patch("pipeline.orchestrator.ProspeoService") as MockProspeo,
        patch("pipeline.orchestrator.EazyreachService") as MockEazyreach,
        patch("pipeline.orchestrator.BrevoService") as MockBrevo,
    ):
        _setup_service_mock(MockOcean, "get_similar_companies_mock", _mock_ocean_result())
        _setup_service_mock(MockProspeo, "get_decision_makers_mock", _mock_prospeo_result())
        _setup_service_mock(MockEazyreach, "get_verified_emails_mock", _mock_eazyreach_result())
        _setup_service_mock(MockBrevo, "send_emails_mock", _mock_brevo_result())

        from pipeline.orchestrator import run_pipeline
        state = await run_pipeline(
            domain="stripe.com",
            mock=True,
            auto_confirm=True,
        )

    assert state.stage1_complete
    assert state.stage2_complete
    assert state.stage3_complete
    assert state.stage4_complete
    assert state.ocean_result is not None
    assert state.prospeo_result is not None
    assert state.eazyreach_result is not None
    assert state.brevo_result is not None
    assert len(state.brevo_result.emails_sent) == 1
    # save_state should have been called 4 times (once per stage)
    assert len(saved_states) == 4


@pytest.mark.asyncio
async def test_stage1_skipped_when_cached(monkeypatch):
    """Stage 1 is not re-run when state shows it complete."""
    preloaded = PipelineState(seed_domain="stripe.com")
    preloaded.ocean_result = _mock_ocean_result()
    preloaded.stage1_complete = True

    monkeypatch.setattr(
        "pipeline.orchestrator.load_state",
        lambda domain: preloaded,
    )
    monkeypatch.setattr("pipeline.orchestrator.save_state", lambda s: None)

    ocean_called = {"n": 0}

    with (
        patch("pipeline.orchestrator.OceanService") as MockOcean,
        patch("pipeline.orchestrator.ProspeoService") as MockProspeo,
        patch("pipeline.orchestrator.EazyreachService") as MockEazyreach,
        patch("pipeline.orchestrator.BrevoService") as MockBrevo,
    ):
        # Stage 1 mock – we'll track if it's called
        def _ocean_mock_method(*args, **kwargs):
            ocean_called["n"] += 1
            return _mock_ocean_result()

        _setup_service_mock(MockOcean, "get_similar_companies_mock", _mock_ocean_result())
        _setup_service_mock(MockProspeo, "get_decision_makers_mock", _mock_prospeo_result())
        _setup_service_mock(MockEazyreach, "get_verified_emails_mock", _mock_eazyreach_result())
        _setup_service_mock(MockBrevo, "send_emails_mock", _mock_brevo_result())

        # Override Stage 1 to track calls
        MockOcean.return_value.__aenter__.return_value.get_similar_companies_mock = AsyncMock(
            side_effect=lambda d: (_ for _ in ()).throw(AssertionError("Stage 1 called when it should be skipped"))
        )

        from pipeline.orchestrator import run_pipeline
        # Should not raise — Stage 1 uses cached result
        state = await run_pipeline(domain="stripe.com", mock=True, auto_confirm=True)

    assert state.stage1_complete


@pytest.mark.asyncio
async def test_pipeline_graceful_when_no_contacts(monkeypatch):
    """Pipeline continues gracefully when Stage 3 returns no contacts."""
    monkeypatch.setattr(
        "pipeline.orchestrator.load_state",
        lambda domain: PipelineState(seed_domain=domain),
    )
    monkeypatch.setattr("pipeline.orchestrator.save_state", lambda s: None)

    with (
        patch("pipeline.orchestrator.OceanService") as MockOcean,
        patch("pipeline.orchestrator.ProspeoService") as MockProspeo,
        patch("pipeline.orchestrator.EazyreachService") as MockEazyreach,
        patch("pipeline.orchestrator.BrevoService") as MockBrevo,
    ):
        _setup_service_mock(MockOcean, "get_similar_companies_mock", _mock_ocean_result())
        _setup_service_mock(MockProspeo, "get_decision_makers_mock", _mock_prospeo_result())
        # Empty contacts
        _setup_service_mock(
            MockEazyreach, "get_verified_emails_mock", EazyreachResult(contacts=[])
        )
        _setup_service_mock(MockBrevo, "send_emails_mock", _mock_brevo_result())

        from pipeline.orchestrator import run_pipeline
        state = await run_pipeline(domain="stripe.com", mock=True, auto_confirm=True)

    # Stage 4 should be skipped but pipeline should not crash
    assert state.stage3_complete
    assert not state.stage4_complete
    assert state.brevo_result is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_service_mock(MockClass, method_name: str, return_value):
    """Wire up an async context manager mock for a service class."""
    instance = MagicMock()
    setattr(instance, method_name, AsyncMock(return_value=return_value))
    MockClass.return_value.__aenter__ = AsyncMock(return_value=instance)
    MockClass.return_value.__aexit__ = AsyncMock(return_value=None)
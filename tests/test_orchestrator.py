"""
Integration tests for pipeline/orchestrator.py  (3-stage pipeline).

Strategy: mock all three service classes so no real HTTP calls occur.
Tests verify:
- All three stages run end-to-end in mock mode.
- State is persisted after each stage (save_state called 3 times).
- Stage 1 is skipped when cached.
- Pipeline aborts gracefully when Stage 2 returns no contacts.
- Resume flags are set correctly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.schemas import (
    OceanResult,
    ProspeoResult,
    BrevoResult,
    SentEmail,
    SimilarCompany,
    VerifiedContact,
    PipelineState,
)


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
        contacts=[
            VerifiedContact(
                full_name="Elena Rossi",
                email="elena.rossi@adyen.com",
                company_name="Adyen",
                domain="adyen.com",
                title="CPO",
                linkedin_url="https://linkedin.com/in/elenarossi",
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
async def test_full_mock_pipeline_runs_all_stages(monkeypatch):
    """All three stages complete successfully in mock mode."""
    monkeypatch.setattr(
        "pipeline.orchestrator.load_state",
        lambda domain: PipelineState(seed_domain=domain),
    )
    saved_states: list[PipelineState] = []
    monkeypatch.setattr(
        "pipeline.orchestrator.save_state",
        lambda s: saved_states.append(s),
    )

    with (
        patch("pipeline.orchestrator.OceanService") as MockOcean,
        patch("pipeline.orchestrator.ProspeoService") as MockProspeo,
        patch("pipeline.orchestrator.BrevoService") as MockBrevo,
    ):
        _setup_service_mock(MockOcean,   "get_similar_companies_mock", _mock_ocean_result())
        _setup_service_mock(MockProspeo, "get_contacts_mock",           _mock_prospeo_result())
        _setup_service_mock(MockBrevo,   "send_emails_mock",            _mock_brevo_result())

        from pipeline.orchestrator import run_pipeline
        state = await run_pipeline(domain="stripe.com", mock=True, auto_confirm=True)

    assert state.stage1_complete
    assert state.stage2_complete
    assert state.stage3_complete
    assert state.ocean_result    is not None
    assert state.prospeo_result  is not None
    assert state.brevo_result    is not None
    assert len(state.brevo_result.emails_sent) == 1
    # save_state called once per completed stage = 3 times
    assert len(saved_states) == 3


@pytest.mark.asyncio
async def test_stage1_skipped_when_cached(monkeypatch):
    """Stage 1 is not re-run when state shows it complete."""
    preloaded = PipelineState(seed_domain="stripe.com")
    preloaded.ocean_result = _mock_ocean_result()
    preloaded.stage1_complete = True

    monkeypatch.setattr("pipeline.orchestrator.load_state", lambda domain: preloaded)
    monkeypatch.setattr("pipeline.orchestrator.save_state", lambda s: None)

    with (
        patch("pipeline.orchestrator.OceanService") as MockOcean,
        patch("pipeline.orchestrator.ProspeoService") as MockProspeo,
        patch("pipeline.orchestrator.BrevoService") as MockBrevo,
    ):
        _setup_service_mock(MockOcean,   "get_similar_companies_mock", _mock_ocean_result())
        _setup_service_mock(MockProspeo, "get_contacts_mock",           _mock_prospeo_result())
        _setup_service_mock(MockBrevo,   "send_emails_mock",            _mock_brevo_result())

        # Override Stage 1 to raise if called — it must not be called
        MockOcean.return_value.__aenter__.return_value.get_similar_companies_mock = AsyncMock(
            side_effect=AssertionError("Stage 1 called when it should be skipped")
        )

        from pipeline.orchestrator import run_pipeline
        state = await run_pipeline(domain="stripe.com", mock=True, auto_confirm=True)

    assert state.stage1_complete


@pytest.mark.asyncio
async def test_stage2_skipped_when_cached(monkeypatch):
    """Stage 2 is not re-run when state shows it complete."""
    preloaded = PipelineState(seed_domain="stripe.com")
    preloaded.ocean_result = _mock_ocean_result()
    preloaded.stage1_complete = True
    preloaded.prospeo_result = _mock_prospeo_result()
    preloaded.stage2_complete = True

    monkeypatch.setattr("pipeline.orchestrator.load_state", lambda domain: preloaded)
    monkeypatch.setattr("pipeline.orchestrator.save_state", lambda s: None)

    with (
        patch("pipeline.orchestrator.OceanService") as MockOcean,
        patch("pipeline.orchestrator.ProspeoService") as MockProspeo,
        patch("pipeline.orchestrator.BrevoService") as MockBrevo,
    ):
        _setup_service_mock(MockOcean,   "get_similar_companies_mock", _mock_ocean_result())
        _setup_service_mock(MockProspeo, "get_contacts_mock",           _mock_prospeo_result())
        _setup_service_mock(MockBrevo,   "send_emails_mock",            _mock_brevo_result())

        MockProspeo.return_value.__aenter__.return_value.get_contacts_mock = AsyncMock(
            side_effect=AssertionError("Stage 2 called when it should be skipped")
        )

        from pipeline.orchestrator import run_pipeline
        state = await run_pipeline(domain="stripe.com", mock=True, auto_confirm=True)

    assert state.stage2_complete


@pytest.mark.asyncio
async def test_pipeline_graceful_when_no_contacts(monkeypatch):
    """Stage 3 is skipped gracefully when Stage 2 returns no contacts."""
    monkeypatch.setattr(
        "pipeline.orchestrator.load_state",
        lambda domain: PipelineState(seed_domain=domain),
    )
    monkeypatch.setattr("pipeline.orchestrator.save_state", lambda s: None)

    with (
        patch("pipeline.orchestrator.OceanService") as MockOcean,
        patch("pipeline.orchestrator.ProspeoService") as MockProspeo,
        patch("pipeline.orchestrator.BrevoService") as MockBrevo,
    ):
        _setup_service_mock(MockOcean,   "get_similar_companies_mock", _mock_ocean_result())
        _setup_service_mock(MockProspeo, "get_contacts_mock", ProspeoResult(contacts=[]))
        _setup_service_mock(MockBrevo,   "send_emails_mock",  _mock_brevo_result())

        from pipeline.orchestrator import run_pipeline
        state = await run_pipeline(domain="stripe.com", mock=True, auto_confirm=True)

    assert state.stage2_complete
    assert not state.stage3_complete
    assert state.brevo_result is None


@pytest.mark.asyncio
async def test_state_saved_after_each_stage(monkeypatch):
    """Verify save_state is called exactly once per completed stage."""
    monkeypatch.setattr(
        "pipeline.orchestrator.load_state",
        lambda domain: PipelineState(seed_domain=domain),
    )
    save_calls: list[PipelineState] = []
    monkeypatch.setattr("pipeline.orchestrator.save_state", lambda s: save_calls.append(s))

    with (
        patch("pipeline.orchestrator.OceanService") as MockOcean,
        patch("pipeline.orchestrator.ProspeoService") as MockProspeo,
        patch("pipeline.orchestrator.BrevoService") as MockBrevo,
    ):
        _setup_service_mock(MockOcean,   "get_similar_companies_mock", _mock_ocean_result())
        _setup_service_mock(MockProspeo, "get_contacts_mock",           _mock_prospeo_result())
        _setup_service_mock(MockBrevo,   "send_emails_mock",            _mock_brevo_result())

        from pipeline.orchestrator import run_pipeline
        await run_pipeline(domain="stripe.com", mock=True, auto_confirm=True)

    # 3 stages → 3 saves
    assert len(save_calls) == 3
    # Flags set in order
    assert save_calls[0].stage1_complete
    assert save_calls[1].stage2_complete
    assert save_calls[2].stage3_complete


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_service_mock(MockClass, method_name: str, return_value):
    """Wire up an async context manager mock for a service class."""
    instance = MagicMock()
    setattr(instance, method_name, AsyncMock(return_value=return_value))
    MockClass.return_value.__aenter__ = AsyncMock(return_value=instance)
    MockClass.return_value.__aexit__ = AsyncMock(return_value=None)
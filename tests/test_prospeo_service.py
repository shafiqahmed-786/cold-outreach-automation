"""
Unit tests for the Prospeo service (services/prospeo.py).

Tests cover:
- Response parsing helpers (_extract_contact)
- Mock mode returns correct ProspeoResult shape
- Dedup runs on mock results (duplicate email in PROSPEO_CONTACTS)
- No HTTP calls made in mock mode
- is_valid_email gate inside _extract_contact
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from models.schemas import ProspeoResult, SimilarCompany, VerifiedContact
from services.prospeo import ProspeoService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _svc() -> ProspeoService:
    """Return a service instance without starting an HTTP session."""
    return ProspeoService.__new__(ProspeoService)


def _company(domain: str = "adyen.com") -> SimilarCompany:
    return SimilarCompany(domain=domain, name="Adyen")


def _enrich_result(
    *,
    person_id: str = "pid-001",
    full_name: str = "Elena Rossi",
    email: str = "elena.rossi@adyen.com",
    revealed: bool = True,
    linkedin_url: str = "https://www.linkedin.com/in/elenarossi",
    title: str = "CPO",
    company_name: str = "Adyen",
) -> dict:
    """Build a minimal /bulk-enrich-person result entry."""
    return {
        "person": {
            "person_id": person_id,
            "full_name": full_name,
            "first_name": full_name.split()[0],
            "last_name": full_name.split()[-1],
            "linkedin_url": linkedin_url,
            "current_job_title": title,
            "email": {
                "revealed": revealed,
                "email": email if revealed else None,
                "status": "VERIFIED" if revealed else "UNAVAILABLE",
            },
        },
        "company": {"name": company_name},
    }


# ---------------------------------------------------------------------------
# _extract_contact
# ---------------------------------------------------------------------------

class TestExtractContact:
    def test_returns_contact_when_email_revealed(self):
        svc = _svc()
        result = svc._extract_contact(_enrich_result(), domain="adyen.com", search_meta={})
        assert result is not None
        assert result.email == "elena.rossi@adyen.com"
        assert result.full_name == "Elena Rossi"

    def test_returns_none_when_not_revealed(self):
        svc = _svc()
        er = _enrich_result(revealed=False)
        result = svc._extract_contact(er, domain="adyen.com", search_meta={})
        assert result is None

    def test_returns_none_when_email_invalid(self):
        svc = _svc()
        er = _enrich_result(email="not-an-email")
        result = svc._extract_contact(er, domain="adyen.com", search_meta={})
        assert result is None

    def test_linkedin_url_preserved(self):
        svc = _svc()
        result = svc._extract_contact(
            _enrich_result(linkedin_url="https://www.linkedin.com/in/elenarossi"),
            domain="adyen.com",
            search_meta={},
        )
        assert result.linkedin_url == "https://www.linkedin.com/in/elenarossi"

    def test_title_falls_back_to_search_meta(self):
        """If enrich response has no current_job_title, use search_meta."""
        svc = _svc()
        er = _enrich_result()
        er["person"]["current_job_title"] = None  # no title in enrich
        search_meta = {"person": {"current_job_title": "Chief People Officer"}}
        result = svc._extract_contact(er, domain="adyen.com", search_meta=search_meta)
        assert result.title == "Chief People Officer"

    def test_company_name_falls_back_to_search_meta(self):
        svc = _svc()
        er = _enrich_result()
        er["company"] = {}  # no company in enrich
        search_meta = {"company": {"name": "Adyen BV"}}
        result = svc._extract_contact(er, domain="adyen.com", search_meta=search_meta)
        assert result.company_name == "Adyen BV"

    def test_domain_assigned_correctly(self):
        svc = _svc()
        result = svc._extract_contact(_enrich_result(), domain="checkout.com", search_meta={})
        assert result.domain == "checkout.com"

    def test_person_id_stored(self):
        svc = _svc()
        result = svc._extract_contact(_enrich_result(person_id="pid-xyz"), domain="adyen.com", search_meta={})
        assert result.person_id == "pid-xyz"

    def test_malformed_entry_returns_none_not_raises(self):
        """A completely broken enrich entry must be absorbed, not crash."""
        svc = _svc()
        # Pass empty dict — person key missing
        result = svc._extract_contact({}, domain="adyen.com", search_meta={})
        assert result is None


# ---------------------------------------------------------------------------
# Mock mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_contacts_mock_returns_prospeo_result():
    svc = ProspeoService()
    companies = [
        _company("adyen.com"),
        _company("braintreepayments.com"),
    ]
    result = await svc.get_contacts_mock(companies)
    assert isinstance(result, ProspeoResult)
    assert len(result.contacts) > 0


@pytest.mark.asyncio
async def test_get_contacts_mock_deduplicates():
    """
    PROSPEO_CONTACTS contains a duplicate entry for oliver.grant@checkout.com.
    After mock + dedup, only one entry must appear.
    """
    svc = ProspeoService()
    companies = [_company("checkout.com")]
    result = await svc.get_contacts_mock(companies)
    emails = [c.email for c in result.contacts]
    assert len(emails) == len(set(emails)), "Duplicate emails found after dedup"


@pytest.mark.asyncio
async def test_get_contacts_mock_filters_by_domain():
    """Mock must only return contacts whose domain matches one of the input companies."""
    svc = ProspeoService()
    # Only request a domain that has exactly one entry
    companies = [_company("chargebee.com")]
    result = await svc.get_contacts_mock(companies)
    assert all(c.domain == "chargebee.com" for c in result.contacts)


@pytest.mark.asyncio
async def test_mock_does_not_open_http_session():
    """get_contacts_mock must never open an aiohttp session."""
    svc = ProspeoService()
    with patch.object(svc, "_get_session", new_callable=AsyncMock) as mock_sess:
        await svc.get_contacts_mock([_company("adyen.com")])
    mock_sess.assert_not_called()


@pytest.mark.asyncio
async def test_contacts_have_valid_emails():
    """Every contact from mock mode must have a syntactically valid email."""
    from utils.validators import is_valid_email
    svc = ProspeoService()
    companies = [_company(d) for d in ["adyen.com", "braintreepayments.com", "zuora.com"]]
    result = await svc.get_contacts_mock(companies)
    for contact in result.contacts:
        assert is_valid_email(contact.email), f"Invalid email: {contact.email}"
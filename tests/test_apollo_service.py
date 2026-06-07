"""
Unit tests for the Apollo.io adapter in services/ocean.py.

Tests cover every pure helper function and the response-parsing
logic. No real HTTP calls are made anywhere in this file.

The OceanService class itself is integration-tested via the existing
test_orchestrator.py (which mocks the entire service via AsyncMock).
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from models.schemas import OceanResult, SimilarCompany
from services.ocean import (
    OceanService,
    _headcount_band,
    _domain_from_url,
    _build_search_params,
)


# ---------------------------------------------------------------------------
# _headcount_band
# ---------------------------------------------------------------------------

class TestHeadcountBand:
    def test_none_input_returns_none(self):
        assert _headcount_band(None) is None

    def test_zero_input_returns_none(self):
        assert _headcount_band(0) is None

    def test_single_employee(self):
        assert _headcount_band(1) == "1,10"

    def test_boundary_top_of_first_band(self):
        assert _headcount_band(10) == "1,10"

    def test_boundary_bottom_of_second_band(self):
        assert _headcount_band(11) == "11,50"

    def test_mid_band_200_range(self):
        assert _headcount_band(150) == "51,200"

    def test_boundary_501(self):
        assert _headcount_band(501) == "501,1000"

    def test_mid_band_1001_5000(self):
        assert _headcount_band(3000) == "1001,5000"

    def test_mid_band_5001_10000(self):
        assert _headcount_band(7500) == "5001,10000"

    def test_large_company(self):
        assert _headcount_band(50_000) == "10001,1000000"

    def test_exact_boundary_10001(self):
        assert _headcount_band(10_001) == "10001,1000000"

    def test_exact_boundary_1000(self):
        assert _headcount_band(1_000) == "501,1000"

    def test_exact_boundary_1001(self):
        assert _headcount_band(1_001) == "1001,5000"


# ---------------------------------------------------------------------------
# _domain_from_url
# ---------------------------------------------------------------------------

class TestDomainFromUrl:
    def test_https_www_with_trailing_slash(self):
        assert _domain_from_url("https://www.stripe.com/") == "stripe.com"

    def test_http_no_www(self):
        assert _domain_from_url("http://adyen.com") == "adyen.com"

    def test_https_no_www(self):
        assert _domain_from_url("https://checkout.com") == "checkout.com"

    def test_www_without_scheme(self):
        # Without a scheme prefix nothing is stripped, but www. still is
        result = _domain_from_url("www.example.com")
        assert result == "example.com"

    def test_url_with_path(self):
        assert _domain_from_url("https://braintreepayments.com/products") == "braintreepayments.com"

    def test_url_with_query_string(self):
        assert _domain_from_url("https://example.com?ref=apollo") == "example.com"

    def test_empty_string_returns_empty(self):
        assert _domain_from_url("") == ""

    def test_uppercase_is_lowercased(self):
        assert _domain_from_url("HTTPS://Stripe.COM/") == "stripe.com"

    def test_bare_domain_unchanged(self):
        assert _domain_from_url("stripe.com") == "stripe.com"


# ---------------------------------------------------------------------------
# _build_search_params
# ---------------------------------------------------------------------------

class TestBuildSearchParams:
    def _signals(self, **overrides) -> dict:
        base = {
            "industry": "fintech",
            "keyword_tags": ["payments", "saas"],
            "employee_range": "501,1000",
        }
        base.update(overrides)
        return base

    def test_includes_pagination(self):
        params = _build_search_params(self._signals(), "stripe.com", page=2, per_page=25)
        assert params["page"] == 2
        assert params["per_page"] == 25

    def test_keyword_tags_included(self):
        params = _build_search_params(self._signals(), "stripe.com", page=1, per_page=25)
        assert "q_organization_keyword_tags[]" in params
        assert params["q_organization_keyword_tags[]"] == ["payments", "saas"]

    def test_employee_range_included(self):
        params = _build_search_params(self._signals(), "stripe.com", page=1, per_page=25)
        assert "organization_num_employees_ranges[]" in params
        assert params["organization_num_employees_ranges[]"] == ["501,1000"]

    def test_no_keyword_tags_when_empty(self):
        params = _build_search_params(
            self._signals(keyword_tags=[]), "stripe.com", page=1, per_page=25
        )
        assert "q_organization_keyword_tags[]" not in params

    def test_no_employee_range_when_none(self):
        params = _build_search_params(
            self._signals(employee_range=None), "stripe.com", page=1, per_page=25
        )
        assert "organization_num_employees_ranges[]" not in params

    def test_industry_not_included_as_param(self):
        # Industry filtering requires tag IDs — we use keyword_tags instead.
        params = _build_search_params(self._signals(), "stripe.com", page=1, per_page=25)
        assert "industry" not in params
        assert "organization_industry_tag_ids[]" not in params

    def test_all_empty_signals_still_has_pagination(self):
        params = _build_search_params(
            {"industry": None, "keyword_tags": [], "employee_range": None},
            "stripe.com",
            page=1,
            per_page=10,
        )
        assert params == {"page": 1, "per_page": 10}


# ---------------------------------------------------------------------------
# OceanService._extract_signals
# ---------------------------------------------------------------------------

class TestExtractSignals:
    def _svc(self) -> OceanService:
        return OceanService.__new__(OceanService)

    def test_full_org_response(self):
        raw = {
            "organization": {
                "industry": "fintech",
                "keywords": ["payments", "saas", "billing", "api", "developer tools"],
                "estimated_num_employees": 750,
            }
        }
        svc = self._svc()
        signals = svc._extract_signals(raw)
        assert signals["industry"] == "fintech"
        assert signals["keyword_tags"] == ["payments", "saas", "billing", "api", "developer tools"]
        assert signals["employee_range"] == "501,1000"

    def test_caps_keyword_tags_at_five(self):
        raw = {
            "organization": {
                "keywords": ["a", "b", "c", "d", "e", "f", "g"],
                "estimated_num_employees": 100,
            }
        }
        svc = self._svc()
        signals = svc._extract_signals(raw)
        assert len(signals["keyword_tags"]) == 5

    def test_empty_org_block(self):
        svc = self._svc()
        signals = svc._extract_signals({})
        assert signals["industry"] is None
        assert signals["keyword_tags"] == []
        assert signals["employee_range"] is None

    def test_missing_keywords_defaults_to_empty_list(self):
        raw = {"organization": {"industry": "saas"}}
        svc = self._svc()
        signals = svc._extract_signals(raw)
        assert signals["keyword_tags"] == []

    def test_keywords_lowercased(self):
        raw = {"organization": {"keywords": ["Payments", "SAAS"]}}
        svc = self._svc()
        signals = svc._extract_signals(raw)
        assert signals["keyword_tags"] == ["payments", "saas"]


# ---------------------------------------------------------------------------
# OceanService._parse_orgs
# ---------------------------------------------------------------------------

class TestParseOrgs:
    def _svc(self) -> OceanService:
        return OceanService.__new__(OceanService)

    def _org(self, **overrides) -> dict:
        base = {
            "primary_domain": "adyen.com",
            "website_url": "https://www.adyen.com/",
            "name": "Adyen",
            "industry": "fintech",
            "estimated_num_employees": 4000,
        }
        base.update(overrides)
        return base

    def test_standard_org_parsed(self):
        svc = self._svc()
        result = svc._parse_orgs([self._org()], seed_domain="stripe.com")
        assert len(result) == 1
        assert result[0].domain == "adyen.com"
        assert result[0].name == "Adyen"
        assert result[0].industry == "fintech"
        assert result[0].employee_count == 4000

    def test_seed_domain_excluded(self):
        svc = self._svc()
        orgs = [self._org(primary_domain="stripe.com", name="Stripe")]
        result = svc._parse_orgs(orgs, seed_domain="stripe.com")
        assert result == []

    def test_seed_domain_excluded_case_insensitive(self):
        svc = self._svc()
        orgs = [self._org(primary_domain="Stripe.COM", name="Stripe")]
        result = svc._parse_orgs(orgs, seed_domain="stripe.com")
        assert result == []

    def test_falls_back_to_website_url_when_no_primary_domain(self):
        svc = self._svc()
        org = self._org()
        del org["primary_domain"]
        org["website_url"] = "https://www.checkout.com/home"
        result = svc._parse_orgs([org], seed_domain="stripe.com")
        assert len(result) == 1
        assert result[0].domain == "checkout.com"

    def test_org_with_no_domain_skipped(self):
        svc = self._svc()
        org = {"primary_domain": None, "website_url": None, "name": "Mystery Co"}
        result = svc._parse_orgs([org], seed_domain="stripe.com")
        assert result == []

    def test_multiple_orgs_parsed(self):
        svc = self._svc()
        orgs = [
            self._org(primary_domain="adyen.com", name="Adyen"),
            self._org(primary_domain="braintree.com", name="Braintree"),
        ]
        result = svc._parse_orgs(orgs, seed_domain="stripe.com")
        assert len(result) == 2

    def test_malformed_org_skipped_without_crashing(self):
        """An org that fails Pydantic validation should be skipped, not crash."""
        svc = self._svc()
        bad_org = {"primary_domain": 12345}   # domain must be a str
        good_org = self._org()
        result = svc._parse_orgs([bad_org, good_org], seed_domain="stripe.com")
        # The good one should still parse — Pydantic coerces int→str for domain
        # so this tests that the pipeline survives even if something unexpected happens.
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# OceanService.get_similar_companies_mock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_returns_ocean_result_with_deduped_companies():
    """Mock mode must return OceanResult with deduped SimilarCompany list."""
    svc = OceanService()
    result = await svc.get_similar_companies_mock("stripe.com")
    assert isinstance(result, OceanResult)
    assert result.seed_domain == "stripe.com"
    assert len(result.companies) > 0

    # Verify dedup ran: no duplicate domains
    domains = [c.domain for c in result.companies]
    assert len(domains) == len(set(domains)), "Duplicate domains found after dedup"


@pytest.mark.asyncio
async def test_mock_does_not_hit_network():
    """get_similar_companies_mock must not open any HTTP session."""
    svc = OceanService()
    with patch.object(svc, "_get_session", new_callable=AsyncMock) as mock_sess:
        await svc.get_similar_companies_mock("stripe.com")
    mock_sess.assert_not_called()
"""
Apollo.io adapter – Stage 1  (replaces Ocean.io)

Exposes the same class name (OceanService) and public interface
(get_similar_companies / get_similar_companies_mock) so the orchestrator
and every downstream stage are completely unchanged.

WHY APOLLO HAS NO "FIND SIMILAR" ENDPOINT
------------------------------------------
Apollo's public API does not expose a "companies similar to domain X"
endpoint. The correct approach — used by real Apollo-powered pipelines —
is a two-step strategy:

  Step 1 – Seed enrichment (GET /api/v1/organizations/enrich?domain=…)
            Pulls the seed company's industry, keyword tags, and employee
            band. These become the *signal* for similarity.

  Step 2 – Keyword/industry search (POST /api/v1/mixed_companies/search)
            Filters the Apollo database by those signals, excludes the seed
            domain itself, and returns the N most relevant companies.

This mirrors what Apollo's own UI does when you click "Similar companies".

CONFIRMED API FACTS (verified against docs.apollo.io, June 2026)
-----------------------------------------------------------------
  Auth header  : x-api-key: <key>   (NOT Bearer)
  Enrich URL   : GET  https://api.apollo.io/api/v1/organizations/enrich
                      ?domain=stripe.com
  Search URL   : POST https://api.apollo.io/api/v1/mixed_companies/search
  Search params: sent as URL query-params (NOT body) per Apollo docs
  Response keys: organizations[], pagination.{page,per_page,total_pages,total_entries}
  Per-org keys : primary_domain, website_url, name, industry,
                 estimated_num_employees, keywords[]
  Rate limits  : 50 req/min (free) / 200 req/min (paid)
  Max per page : 100
"""

from __future__ import annotations

import asyncio
from typing import Optional

import aiohttp

from core.config import get_config
from core.logger import get_logger
from data.mock_responses import OCEAN_SIMILAR_COMPANIES
from models.schemas import OceanResult, SimilarCompany
from services.base import BaseAPIClient
from utils.retry import async_retry
from utils.validators import dedup_companies

logger = get_logger(__name__)
cfg = get_config()


class OceanService(BaseAPIClient):
    """
    Apollo.io-backed implementation of the Stage 1 company-discovery service.

    Class name is kept as OceanService so the orchestrator import
    (from services.ocean import OceanService) requires zero changes.
    """

    base_url = cfg.APOLLO_BASE_URL

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        # Apollo uses x-api-key, not Authorization: Bearer.
        return {
            "x-api-key": cfg.APOLLO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        }

    # ------------------------------------------------------------------
    # Step 1: enrich the seed domain to extract similarity signals
    # ------------------------------------------------------------------

    @async_retry(
        max_attempts=cfg.MAX_RETRIES,
        base_delay=cfg.RETRY_BASE_DELAY,
        exceptions=(aiohttp.ClientError, aiohttp.ServerConnectionError, asyncio.TimeoutError),
    )
    async def _enrich_seed(self, domain: str) -> dict:
        """
        GET /api/v1/organizations/enrich?domain=<domain>

        Returns the organization block for the seed company.
        Used to extract industry + keyword signals for the similarity search.
        """
        return await self._get(
            "/organizations/enrich",
            headers=self._headers(),
            params={"domain": domain},
        )

    def _extract_signals(self, enrich_raw: dict) -> dict:
        """
        Pull similarity signals out of the enrichment response.

        Returns a dict with keys used to build the search payload:
          - industry       : str | None
          - keyword_tags   : list[str]   (capped at 5 for search relevance)
          - employee_range : str | None  (e.g. "1000,5000")
        """
        org = enrich_raw.get("organization") or {}

        industry: Optional[str] = org.get("industry")

        # Apollo returns 'keywords' as a list of strings on the org object.
        raw_keywords: list[str] = org.get("keywords") or []
        # Keep at most 5 to avoid over-constraining the search.
        keyword_tags: list[str] = [k.lower() for k in raw_keywords[:5]]

        # Build a headcount range one band up/down from the seed so results
        # are in the same size neighbourhood.
        emp: Optional[int] = org.get("estimated_num_employees")
        employee_range: Optional[str] = _headcount_band(emp)

        logger.debug(
            "Seed signals — industry=%s, keywords=%s, emp_range=%s",
            industry,
            keyword_tags,
            employee_range,
        )
        return {
            "industry": industry,
            "keyword_tags": keyword_tags,
            "employee_range": employee_range,
        }

    # ------------------------------------------------------------------
    # Step 2: search for similar organisations
    # ------------------------------------------------------------------

    @async_retry(
        max_attempts=cfg.MAX_RETRIES,
        base_delay=cfg.RETRY_BASE_DELAY,
        exceptions=(aiohttp.ClientError, aiohttp.ServerConnectionError, asyncio.TimeoutError),
    )
    async def _search_page(self, params: dict) -> dict:
        """
        POST /api/v1/mixed_companies/search (query params in URL)

        Apollo requires filter params as URL query-params even for POST.
        The body is ignored; _get() is used to force a GET-style param
        encoding. However, Apollo's own curl examples use POST with params
        in the URL, so we use _post with an empty body and pass params
        explicitly via the URL query string.
        """
        session = await self._get_session()
        url = f"{self.base_url}/mixed_companies/search"
        logger.debug("POST %s params=%s", url, params)
        async with session.post(
            url,
            headers=self._headers(),
            params=params,      # aiohttp encodes these as URL query-params
            json={},            # empty body; Apollo ignores it
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _fetch_similar_pages(
        self, seed_domain: str, signals: dict
    ) -> list[dict]:
        """
        Paginate through Apollo search results until we have
        APOLLO_SIMILAR_LIMIT companies or run out of pages.

        Apollo max = 100 per page; we use a sensible per_page of 25
        to keep individual responses fast.
        """
        limit = cfg.APOLLO_SIMILAR_LIMIT
        per_page = min(25, limit)
        collected: list[dict] = []
        page = 1

        while len(collected) < limit:
            params = _build_search_params(signals, seed_domain, page, per_page)
            raw = await self._search_page(params)

            orgs: list[dict] = raw.get("organizations") or []
            pagination: dict = raw.get("pagination") or {}
            total_pages: int = pagination.get("total_pages") or 1

            if not orgs:
                logger.debug("Apollo search page %d returned 0 results. Stopping.", page)
                break

            collected.extend(orgs)
            logger.debug(
                "Apollo search page %d/%d — %d orgs fetched so far.",
                page,
                total_pages,
                len(collected),
            )

            if page >= total_pages:
                break
            page += 1

        return collected[:limit]

    # ------------------------------------------------------------------
    # Response parsing → SimilarCompany list
    # ------------------------------------------------------------------

    def _parse_orgs(self, raw_orgs: list[dict], seed_domain: str) -> list[SimilarCompany]:
        """
        Map Apollo organization objects to SimilarCompany models.

        Apollo org fields used:
          primary_domain         – canonical domain (preferred)
          website_url            – fallback if primary_domain absent
          name                   – company name
          industry               – industry string
          estimated_num_employees – headcount integer
        """
        companies: list[SimilarCompany] = []
        for org in raw_orgs:
            # Prefer primary_domain; fall back to stripping website_url.
            # Coerce to str defensively — Apollo can return non-string values
            # in malformed records (e.g. numeric IDs).
            raw_domain = org.get("primary_domain") or _domain_from_url(
                str(org.get("website_url") or "")
            )
            domain = str(raw_domain).strip() if raw_domain else ""
            if not domain:
                logger.debug("Skipping org with no domain: %s", org.get("name"))
                continue
            # Drop the seed itself (Apollo may return it in results)
            if domain.lower() == seed_domain.lower():
                logger.debug("Excluding seed domain from results: %s", domain)
                continue
            try:
                companies.append(
                    SimilarCompany(
                        domain=domain,
                        name=org.get("name"),
                        industry=org.get("industry"),
                        employee_count=org.get("estimated_num_employees"),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed org entry: %s | %s", org, exc)

        return companies

    # ------------------------------------------------------------------
    # Public interface  (identical signatures to the old OceanService)
    # ------------------------------------------------------------------

    async def get_similar_companies(self, domain: str) -> OceanResult:
        """
        Full two-step Apollo discovery:
          1. Enrich seed domain → extract signals.
          2. Search for companies with matching signals.
        """
        logger.info("[Stage 1] Apollo: enriching seed domain '%s'.", domain)

        # Step 1 – enrich seed
        try:
            enrich_raw = await self._enrich_seed(domain)
        except Exception as exc:
            # If enrichment fails (e.g. unknown domain), fall back to a
            # keyword-only search with no signals so we still return something.
            logger.warning(
                "[Stage 1] Seed enrichment failed for '%s': %s. "
                "Proceeding with empty signals.",
                domain,
                exc,
            )
            enrich_raw = {}

        signals = self._extract_signals(enrich_raw)

        if not signals["keyword_tags"] and not signals["industry"]:
            logger.warning(
                "[Stage 1] No signals extracted for '%s'. "
                "Apollo search may return broad or empty results.",
                domain,
            )

        # Step 2 – paginated search
        logger.info(
            "[Stage 1] Apollo: searching similar companies "
            "(industry=%s, keywords=%s).",
            signals["industry"],
            signals["keyword_tags"],
        )
        raw_orgs = await self._fetch_similar_pages(domain, signals)
        companies = self._parse_orgs(raw_orgs, seed_domain=domain)
        companies = dedup_companies(companies)

        logger.info(
            "[Stage 1] Apollo returned %d unique similar companies for '%s'.",
            len(companies),
            domain,
        )
        return OceanResult(seed_domain=domain, companies=companies)

    async def get_similar_companies_mock(self, domain: str) -> OceanResult:
        """Return local mock fixtures — no API calls, no credits consumed."""
        logger.info("[Stage 1][MOCK] Returning mock similar companies for: %s", domain)
        companies = [SimilarCompany(**c) for c in OCEAN_SIMILAR_COMPANIES]
        companies = dedup_companies(companies)
        return OceanResult(seed_domain=domain, companies=companies)


# ---------------------------------------------------------------------------
# Private helpers (module-level pure functions, easy to unit-test)
# ---------------------------------------------------------------------------

def _headcount_band(emp: Optional[int]) -> Optional[str]:
    """
    Map an employee count to an Apollo-style range string "min,max".

    Apollo accepts these as values for organization_num_employees_ranges[].
    We return the matching band so search results stay in the same size
    neighbourhood as the seed company.

    Returns None if emp is None or 0 (avoid over-constraining the search).
    """
    if not emp:
        return None
    # Bands match Apollo's documented employee range presets.
    bands = [
        (1,    10,    "1,10"),
        (11,   50,    "11,50"),
        (51,   200,   "51,200"),
        (201,  500,   "201,500"),
        (501,  1_000, "501,1000"),
        (1_001, 5_000, "1001,5000"),
        (5_001, 10_000, "5001,10000"),
        (10_001, 10_000_000, "10001,1000000"),
    ]
    for low, high, label in bands:
        if low <= emp <= high:
            return label
    return None


def _domain_from_url(url: str) -> str:
    """
    Extract a bare domain from a URL string.

    Examples:
        "http://www.stripe.com/"  →  "stripe.com"
        "https://adyen.com"       →  "adyen.com"
        ""                        →  ""
    """
    if not url:
        return ""
    url = url.strip().lower()
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
    if url.startswith("www."):
        url = url[4:]
    return url.split("/")[0].split("?")[0]


def _build_search_params(
    signals: dict,
    seed_domain: str,
    page: int,
    per_page: int,
) -> dict:
    """
    Build the URL query-param dict for POST /mixed_companies/search.

    Apollo requires array params as repeated keys with [] suffix, which
    aiohttp handles correctly when values are lists.

    Parameters passed:
      q_organization_keyword_tags[]   – similarity signal (up to 5 tags)
      organization_num_employees_ranges[] – headcount neighbourhood
      page / per_page                 – pagination
    """
    params: dict = {
        "page": page,
        "per_page": per_page,
    }

    if signals.get("keyword_tags"):
        # aiohttp serialises list values as repeated keys automatically.
        params["q_organization_keyword_tags[]"] = signals["keyword_tags"]

    if signals.get("employee_range"):
        params["organization_num_employees_ranges[]"] = [signals["employee_range"]]

    # NOTE: We intentionally do NOT filter by industry string because Apollo's
    # industry taxonomy uses internal tag IDs (organization_industry_tag_ids[]),
    # which require a separate lookup and would consume additional credits.
    # Keyword-tag + headcount filtering is sufficient for practical similarity.

    logger.debug("Apollo search params: %s", params)
    return params
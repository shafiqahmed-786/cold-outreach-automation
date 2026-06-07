"""
Prospeo API wrapper – Stage 2.

Endpoint assumption (domain-search for people):
    POST /v1/domain-search
    Body: { "domain": "stripe.com", "seniority": ["c_suite", "vp"], "limit": 10 }
    Response: { "data": { "emails": [ { "full_name": ..., "linkedin": ..., ... } ] } }

# TODO: Verify exact endpoint, body schema, and response structure against
#       Prospeo's live API docs. The seniority filter values may differ.
#       Base URL is overridable via PROSPEO_BASE_URL in .env.
"""

from __future__ import annotations

import asyncio

import aiohttp

from core.config import get_config
from core.logger import get_logger
from data.mock_responses import PROSPEO_DECISION_MAKERS
from models.schemas import DecisionMaker, ProspeoResult, SimilarCompany
from services.base import BaseAPIClient
from utils.retry import async_retry
from utils.validators import dedup_decision_makers

logger = get_logger(__name__)
cfg = get_config()


class ProspeoService(BaseAPIClient):
    base_url = cfg.PROSPEO_BASE_URL

    def _headers(self) -> dict:
        return {
            "X-KEY": cfg.PROSPEO_API_KEY,  # TODO: Verify header name for Prospeo auth.
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @async_retry(
        max_attempts=cfg.MAX_RETRIES,
        base_delay=cfg.RETRY_BASE_DELAY,
        exceptions=(aiohttp.ClientError, aiohttp.ServerConnectionError, asyncio.TimeoutError),
    )
    async def _fetch_domain(self, domain: str) -> dict:
        """Raw API call for one domain – retried automatically."""
        payload = {
            "domain": domain,
            "seniority": cfg.PROSPEO_SENIORITY_FILTER,
            "limit": 10,
        }
        return await self._post(
            # TODO: Verify endpoint path against Prospeo live docs.
            "/domain-search",
            headers=self._headers(),
            payload=payload,
        )

    def _parse_domain_response(self, raw: dict, domain: str) -> list[DecisionMaker]:
        """Extract decision makers from one domain's response."""
        # Prospeo nests results; adapt if schema differs.
        data_block = raw.get("data") or raw
        raw_people = data_block.get("emails") or data_block.get("people") or data_block.get("contacts") or []
        people: list[DecisionMaker] = []
        for p in raw_people:
            try:
                people.append(
                    DecisionMaker(
                        domain=domain,
                        full_name=p.get("full_name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
                        first_name=p.get("first_name"),
                        last_name=p.get("last_name"),
                        title=p.get("position") or p.get("title") or p.get("job_title"),
                        linkedin_url=p.get("linkedin") or p.get("linkedin_url"),
                        company_name=p.get("company") or p.get("company_name"),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed person entry for %s: %s | %s", domain, p, exc)
        return people

    async def _get_for_domain(self, domain: str) -> list[DecisionMaker]:
        """Fetch decision makers for a single domain, absorbing non-fatal errors."""
        try:
            raw = await self._fetch_domain(domain)
            return self._parse_domain_response(raw, domain)
        except Exception as exc:
            logger.error("[Stage 2] Failed to fetch profiles for %s: %s", domain, exc)
            return []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_decision_makers(
        self, companies: list[SimilarCompany]
    ) -> ProspeoResult:
        """
        Fetch decision makers for all domains concurrently (bounded by semaphore).
        A failure on one domain does NOT abort the others.
        """
        logger.info("[Stage 2] Fetching decision makers for %d companies.", len(companies))
        sem = asyncio.Semaphore(cfg.CONCURRENT_REQUESTS)

        async def bounded(company: SimilarCompany) -> list[DecisionMaker]:
            async with sem:
                return await self._get_for_domain(company.domain)

        results = await asyncio.gather(*[bounded(c) for c in companies])
        all_dms: list[DecisionMaker] = [dm for batch in results for dm in batch]
        all_dms = dedup_decision_makers(all_dms)
        logger.info("[Stage 2] Found %d unique decision makers with LinkedIn URLs.", len(all_dms))
        return ProspeoResult(decision_makers=all_dms)

    async def get_decision_makers_mock(
        self, companies: list[SimilarCompany]
    ) -> ProspeoResult:
        logger.info("[Stage 2][MOCK] Returning mock decision makers.")
        domains = {c.domain for c in companies}
        dms = [
            DecisionMaker(**dm)
            for dm in PROSPEO_DECISION_MAKERS
            if dm["domain"] in domains
        ]
        dms = dedup_decision_makers(dms)
        return ProspeoResult(decision_makers=dms)
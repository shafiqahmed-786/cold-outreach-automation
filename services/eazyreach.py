"""
Eazyreach API wrapper – Stage 3.

Endpoint assumption:
    POST /v1/enrich
    Body: { "linkedin_url": "https://www.linkedin.com/in/..." }
    Response: { "email": "...", "verified": true, "full_name": "..." }

Eazyreach is called one LinkedIn URL at a time (no batch endpoint documented),
so we fan out concurrently with a semaphore to stay within rate limits.

# TODO: Verify endpoint path, auth header name, and response schema against
#       Eazyreach's live API docs.  Base URL overridable via EAZYREACH_BASE_URL.
"""

from __future__ import annotations

import asyncio

import aiohttp

from core.config import get_config
from core.logger import get_logger
from data.mock_responses import EAZYREACH_CONTACTS
from models.schemas import DecisionMaker, EazyreachResult, VerifiedContact
from services.base import BaseAPIClient
from utils.retry import async_retry
from utils.validators import dedup_contacts, is_valid_email

logger = get_logger(__name__)
cfg = get_config()


class EazyreachService(BaseAPIClient):
    base_url = cfg.EAZYREACH_BASE_URL

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {cfg.EAZYREACH_API_KEY}",  # TODO: Verify auth scheme.
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @async_retry(
        max_attempts=cfg.MAX_RETRIES,
        base_delay=cfg.RETRY_BASE_DELAY,
        exceptions=(aiohttp.ClientError, aiohttp.ServerConnectionError, asyncio.TimeoutError),
    )
    async def _enrich_single(self, linkedin_url: str) -> dict:
        return await self._post(
            # TODO: Verify endpoint path against Eazyreach live docs.
            "/enrich",
            headers=self._headers(),
            payload={"linkedin_url": linkedin_url},
        )

    def _parse_enrich(self, raw: dict, dm: DecisionMaker) -> VerifiedContact | None:
        """Map raw enrich response back to a VerifiedContact."""
        email = raw.get("email") or raw.get("work_email")
        if not email or not is_valid_email(email):
            logger.debug("No valid email returned for %s (%s).", dm.full_name, dm.linkedin_url)
            return None
        verified = raw.get("verified", True)
        if not verified:
            logger.debug("Email not verified for %s – skipping.", dm.full_name)
            return None

        return VerifiedContact(
            full_name=raw.get("full_name") or dm.full_name,
            first_name=raw.get("first_name") or dm.first_name,
            last_name=raw.get("last_name") or dm.last_name,
            title=raw.get("position") or raw.get("title") or dm.title,
            email=email,
            company_name=raw.get("company") or dm.company_name,
            domain=dm.domain,
            linkedin_url=dm.linkedin_url,
            email_verified=True,
        )

    async def _enrich_one(self, dm: DecisionMaker) -> VerifiedContact | None:
        """Enrich a single decision maker, absorbing per-record errors."""
        try:
            raw = await self._enrich_single(dm.linkedin_url)
            return self._parse_enrich(raw, dm)
        except Exception as exc:
            logger.error(
                "[Stage 3] Failed to enrich %s (%s): %s",
                dm.full_name,
                dm.linkedin_url,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_verified_emails(
        self, decision_makers: list[DecisionMaker]
    ) -> EazyreachResult:
        """Fan-out enrichment across all decision makers, bounded by semaphore."""
        logger.info(
            "[Stage 3] Enriching emails for %d decision makers.", len(decision_makers)
        )
        sem = asyncio.Semaphore(cfg.CONCURRENT_REQUESTS)

        async def bounded(dm: DecisionMaker) -> VerifiedContact | None:
            async with sem:
                return await self._enrich_one(dm)

        raw_contacts = await asyncio.gather(*[bounded(dm) for dm in decision_makers])
        contacts: list[VerifiedContact] = [c for c in raw_contacts if c is not None]
        contacts = dedup_contacts(contacts)
        logger.info("[Stage 3] Found %d unique verified emails.", len(contacts))
        return EazyreachResult(contacts=contacts)

    async def get_verified_emails_mock(
        self, decision_makers: list[DecisionMaker]
    ) -> EazyreachResult:
        logger.info("[Stage 3][MOCK] Returning mock verified emails.")
        linkedin_set = {dm.linkedin_url for dm in decision_makers if dm.linkedin_url}
        contacts = [
            VerifiedContact(**c)
            for c in EAZYREACH_CONTACTS
            if c.get("linkedin_url") in linkedin_set
        ]
        contacts = dedup_contacts(contacts)
        return EazyreachResult(contacts=contacts)
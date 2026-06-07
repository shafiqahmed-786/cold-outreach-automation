"""
Prospeo API wrapper – Stage 2.

Replaces both the old Prospeo domain-search (deprecated/removed March 2026)
and the removed EazyReach stage.  A single Prospeo call-chain now delivers:
  • decision-maker profiles  (name, title, LinkedIn URL)
  • verified work emails

CONFIRMED LIVE ENDPOINTS  (prospeo.io/api-docs, last updated May 2026)
-----------------------------------------------------------------------
Auth header : X-KEY: <api_key>
Base URL    : https://api.prospeo.io   (no /v1 prefix on new API)

Step 1 – Search Person
  POST /search-person
  Body: {
      "page": 1,
      "filters": {
          "company": { "websites": { "include": ["adyen.com"] } },
          "person_seniority": { "include": ["C-Suite", "VP"] }
      }
  }
  Response: { "results": [{ "person": { person_id, full_name,
              linkedin_url, current_job_title, ... }, "company": {...} }],
              "pagination": { "current_page", "total_page", ... } }
  NOTE: email is intentionally absent from search results.

Step 2 – Bulk Enrich Person (up to 50 person_ids per request)
  POST /bulk-enrich-person
  Body: {
      "only_verified_email": true,
      "persons": [
          { "person_id": "abc123" },
          ...
      ]
  }
  Response: { "results": [
      { "person": { ..., "email": { "revealed": true,
                                    "email": "name@co.com",
                                    "status": "VERIFIED" } } }
  ] }

FLOW PER DOMAIN
  1. Call /search-person with seniority filter → collect person_ids
  2. Fan-out /bulk-enrich-person (batches of 50) → collect verified emails
  3. Build VerifiedContact objects; drop anyone without a revealed email
  4. Dedup by email across all domains

CREDIT MODEL
  Search: 1 credit per page of 25 results (deduped within 30 days)
  Enrich: 1 credit per email found (never charged for same record twice)
"""

from __future__ import annotations

import asyncio
from typing import Optional

import aiohttp

from core.config import get_config
from core.logger import get_logger
from data.mock_responses import PROSPEO_CONTACTS
from models.schemas import ProspeoResult, SimilarCompany, VerifiedContact
from services.base import BaseAPIClient
from utils.retry import async_retry
from utils.validators import dedup_contacts, is_valid_email

logger = get_logger(__name__)
cfg = get_config()

# Prospeo's new API does not use a /v1 prefix.
_BASE_URL = cfg.PROSPEO_BASE_URL


class ProspeoService(BaseAPIClient):
    base_url = _BASE_URL

    def _headers(self) -> dict:
        # Confirmed auth scheme: X-KEY header (not Bearer).
        return {
            "X-KEY": cfg.PROSPEO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Step 1 – Search Person (one page at a time)
    # ------------------------------------------------------------------

    @async_retry(
        max_attempts=cfg.MAX_RETRIES,
        base_delay=cfg.RETRY_BASE_DELAY,
        exceptions=(aiohttp.ClientError, aiohttp.ServerConnectionError, asyncio.TimeoutError),
    )
    async def _search_page(self, domain: str, page: int) -> dict:
        """
        POST /search-person for one domain, one page.

        Filters applied:
          company.websites  – restricts results to the target domain
          person_seniority  – C-Suite and VP only (configurable via config)
        """
        payload = {
            "page": page,
            "filters": {
                "company": {
                    "websites": {"include": [domain]},
                },
                "person_seniority": {
                    "include": cfg.PROSPEO_SENIORITY_FILTER,
                },
            },
        }
        return await self._post("/search-person", headers=self._headers(), payload=payload)

    async def _search_domain(self, domain: str) -> list[dict]:
        """
        Paginate through /search-person for one domain.
        Returns raw person dicts (no email yet) each containing person_id.
        """
        all_persons: list[dict] = []
        page = 1
        limit = cfg.PROSPEO_SEARCH_LIMIT

        while len(all_persons) < limit:
            try:
                raw = await self._search_page(domain, page)
            except Exception as exc:
                logger.error("[Stage 2] search failed for %s page %d: %s", domain, page, exc)
                break

            if raw.get("error"):
                error_code = raw.get("error_code", "UNKNOWN")
                # NO_RESULTS is not a real error — just an empty domain.
                if error_code == "NO_RESULTS":
                    logger.debug("[Stage 2] No results for domain %s.", domain)
                else:
                    logger.warning("[Stage 2] search error for %s: %s", domain, error_code)
                break

            results: list[dict] = raw.get("results") or []
            if not results:
                break

            all_persons.extend(results)

            pagination = raw.get("pagination") or {}
            total_pages = pagination.get("total_page") or 1
            logger.debug(
                "[Stage 2] search %s page %d/%d — %d persons so far.",
                domain, page, total_pages, len(all_persons),
            )

            if page >= total_pages:
                break
            page += 1

        return all_persons[:limit]

    # ------------------------------------------------------------------
    # Step 2 – Bulk Enrich Person (batches of 50)
    # ------------------------------------------------------------------

    @async_retry(
        max_attempts=cfg.MAX_RETRIES,
        base_delay=cfg.RETRY_BASE_DELAY,
        exceptions=(aiohttp.ClientError, aiohttp.ServerConnectionError, asyncio.TimeoutError),
    )
    async def _bulk_enrich(self, person_ids: list[str]) -> dict:
        """
        POST /bulk-enrich-person for up to 50 person_ids.

        only_verified_email=true: we only pay for records where an email
        is found and verified — avoids credits on dead-end lookups.
        """
        payload = {
            "only_verified_email": True,
            "persons": [{"person_id": pid} for pid in person_ids],
        }
        return await self._post("/bulk-enrich-person", headers=self._headers(), payload=payload)

    async def _enrich_batch(self, person_ids: list[str]) -> list[dict]:
        """
        Enrich a batch, absorbing errors so a single bad batch does not
        abort the whole domain's results.
        """
        if not person_ids:
            return []
        try:
            raw = await self._bulk_enrich(person_ids)
            if raw.get("error"):
                logger.error(
                    "[Stage 2] bulk-enrich error: %s", raw.get("error_code", "UNKNOWN")
                )
                return []
            return raw.get("results") or []
        except Exception as exc:
            logger.error("[Stage 2] bulk-enrich failed for batch of %d: %s", len(person_ids), exc)
            return []

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _extract_contact(
        self,
        enrich_result: dict,
        domain: str,
        search_meta: dict,
    ) -> Optional[VerifiedContact]:
        """
        Map one /bulk-enrich-person result entry to a VerifiedContact.

        `search_meta` is the original search result dict (person + company)
        used to back-fill fields not present in the enrich response (e.g.
        current_job_title when the enrich response omits it).
        """
        person: dict = enrich_result.get("person") or {}
        company: dict = enrich_result.get("company") or {}

        # Email sub-object from enrich response
        email_obj: dict = person.get("email") or {}
        revealed: bool = email_obj.get("revealed", False)
        email_str: Optional[str] = email_obj.get("email")

        if not revealed or not email_str or not is_valid_email(email_str):
            logger.debug(
                "[Stage 2] No verified email for person_id=%s (%s).",
                person.get("person_id"),
                person.get("full_name"),
            )
            return None

        # Back-fill title from search metadata if enrich doesn't have it
        title = (
            person.get("current_job_title")
            or (search_meta.get("person") or {}).get("current_job_title")
        )
        company_name = (
            company.get("name")
            or (search_meta.get("company") or {}).get("name")
        )

        try:
            return VerifiedContact(
                full_name=person.get("full_name") or "",
                first_name=person.get("first_name"),
                last_name=person.get("last_name"),
                title=title,
                email=email_str,
                company_name=company_name,
                domain=domain,
                linkedin_url=person.get("linkedin_url"),
                person_id=person.get("person_id"),
                email_verified=True,
            )
        except Exception as exc:
            logger.warning(
                "[Stage 2] Skipping malformed enrich entry: %s | %s",
                person.get("full_name"),
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Per-domain orchestration
    # ------------------------------------------------------------------

    async def _process_domain(self, domain: str) -> list[VerifiedContact]:
        """
        Full Search → BulkEnrich pipeline for one domain.
        Any failure at the domain level is absorbed; other domains continue.
        """
        # Step 1: search
        search_results = await self._search_domain(domain)
        if not search_results:
            logger.debug("[Stage 2] No search results for domain %s.", domain)
            return []

        # Build a lookup: person_id → original search result (for metadata back-fill)
        meta_by_id: dict[str, dict] = {}
        person_ids: list[str] = []
        for result in search_results:
            person_dict = result.get("person") or {}
            pid = person_dict.get("person_id")
            if pid:
                person_ids.append(pid)
                meta_by_id[pid] = result

        if not person_ids:
            return []

        # Step 2: bulk enrich in batches of 50
        _BATCH_SIZE = 50
        all_enrich_results: list[dict] = []
        sem = asyncio.Semaphore(cfg.CONCURRENT_REQUESTS)

        async def enrich_bounded(batch: list[str]) -> list[dict]:
            async with sem:
                return await self._enrich_batch(batch)

        batches = [
            person_ids[i : i + _BATCH_SIZE]
            for i in range(0, len(person_ids), _BATCH_SIZE)
        ]
        enrich_batches = await asyncio.gather(*[enrich_bounded(b) for b in batches])
        for batch_result in enrich_batches:
            all_enrich_results.extend(batch_result)

        # Step 3: parse into VerifiedContact objects
        contacts: list[VerifiedContact] = []
        for er in all_enrich_results:
            person_dict = er.get("person") or {}
            pid = person_dict.get("person_id")
            search_meta = meta_by_id.get(pid, {}) if pid else {}
            contact = self._extract_contact(er, domain, search_meta)
            if contact:
                contacts.append(contact)

        logger.debug(
            "[Stage 2] domain %s → %d search hits, %d with verified email.",
            domain,
            len(search_results),
            len(contacts),
        )
        return contacts

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_contacts(self, companies: list[SimilarCompany]) -> ProspeoResult:
        """
        Search for and enrich decision makers across all discovered companies.

        Uses concurrent domain processing (bounded by semaphore), so a
        failure on any single domain does NOT block the rest.
        """
        logger.info(
            "[Stage 2] Prospeo: searching + enriching across %d companies.",
            len(companies),
        )
        sem = asyncio.Semaphore(cfg.CONCURRENT_REQUESTS)

        async def bounded(company: SimilarCompany) -> list[VerifiedContact]:
            async with sem:
                return await self._process_domain(company.domain)

        batches = await asyncio.gather(*[bounded(c) for c in companies])
        all_contacts: list[VerifiedContact] = [c for batch in batches for c in batch]
        all_contacts = dedup_contacts(all_contacts)

        logger.info(
            "[Stage 2] Prospeo: found %d unique verified contacts.",
            len(all_contacts),
        )
        return ProspeoResult(contacts=all_contacts)

    async def get_contacts_mock(self, companies: list[SimilarCompany]) -> ProspeoResult:
        """Return local mock fixtures — no API calls, no credits consumed."""
        logger.info("[Stage 2][MOCK] Returning mock Prospeo contacts.")
        domains = {c.domain for c in companies}
        contacts = [
            VerifiedContact(**c)
            for c in PROSPEO_CONTACTS
            if c.get("domain") in domains
        ]
        contacts = dedup_contacts(contacts)
        return ProspeoResult(contacts=contacts)

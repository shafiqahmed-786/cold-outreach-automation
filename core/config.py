"""
Centralised configuration loaded once at startup via python-dotenv.
All API credentials and tuneable knobs live here.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Config:
    # ------------------------------------------------------------------
    # Apollo.io  (Stage 1 – similar company discovery)
    #
    # Confirmed endpoints (docs.apollo.io, June 2026):
    #   Enrichment : GET  /api/v1/organizations/enrich?domain=…
    #   Search     : POST /api/v1/mixed_companies/search  (params in URL)
    # Auth         : x-api-key header (not Bearer)
    # ------------------------------------------------------------------
    APOLLO_API_KEY: str = os.getenv("APOLLO_API_KEY", "")
    APOLLO_BASE_URL: str = os.getenv(
        "APOLLO_BASE_URL", "https://api.apollo.io/api/v1"
    )
    APOLLO_SIMILAR_LIMIT: int = int(os.getenv("APOLLO_SIMILAR_LIMIT", "10"))

    # ------------------------------------------------------------------
    # Prospeo  (Stage 2 – decision-maker discovery + email enrichment)
    #
    # Confirmed endpoints (prospeo.io/api-docs, May 2026):
    #   Search  : POST https://api.prospeo.io/search-person
    #   Enrich  : POST https://api.prospeo.io/bulk-enrich-person
    # Auth      : X-KEY header
    # Note      : New API has NO /v1 prefix; old /domain-search removed March 2026.
    # ------------------------------------------------------------------
    PROSPEO_API_KEY: str = os.getenv("PROSPEO_API_KEY", "")
    PROSPEO_BASE_URL: str = os.getenv("PROSPEO_BASE_URL", "https://api.prospeo.io")

    # Seniority filter values – must match Prospeo's enum exactly.
    PROSPEO_SENIORITY_FILTER: list[str] = ["C-Suite", "VP"]

    # Max persons to collect per company domain.
    PROSPEO_SEARCH_LIMIT: int = int(os.getenv("PROSPEO_SEARCH_LIMIT", "25"))

    # ------------------------------------------------------------------
    # Brevo  (Stage 3 – transactional email sending)
    # ------------------------------------------------------------------
    BREVO_API_KEY: str = os.getenv("BREVO_API_KEY", "")
    BREVO_BASE_URL: str = os.getenv("BREVO_BASE_URL", "https://api.brevo.com/v3")
    BREVO_SENDER_NAME: str = os.getenv("BREVO_SENDER_NAME", "Alex Carter")
    BREVO_SENDER_EMAIL: str = os.getenv("BREVO_SENDER_EMAIL", "alex@yourcompany.com")

    # ------------------------------------------------------------------
    # Pipeline tunables
    # ------------------------------------------------------------------
    STATE_FILE: str = os.getenv("STATE_FILE", "pipeline_state.json")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/pipeline.log")
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_BASE_DELAY: float = float(os.getenv("RETRY_BASE_DELAY", "1.0"))
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    CONCURRENT_REQUESTS: int = int(os.getenv("CONCURRENT_REQUESTS", "5"))


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
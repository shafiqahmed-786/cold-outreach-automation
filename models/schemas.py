"""
Pydantic schemas for all pipeline stages.
Each model is the contract between stages, enforcing data integrity end-to-end.

Architecture (3-stage pipeline):
  Stage 1  Apollo    → OceanResult      (similar companies)
  Stage 2  Prospeo   → ProspeoResult    (decision makers + verified emails)
  Stage 3  Brevo     → BrevoResult      (sent emails)

EazyReach has been removed. Prospeo now owns the full enrichment
responsibility: person discovery, LinkedIn URLs, and email addresses,
using its Search Person + Bulk Enrich Person endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Stage 1 – Apollo output (class name kept as OceanResult for state compat)
# ---------------------------------------------------------------------------

class SimilarCompany(BaseModel):
    domain: str
    name: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None

    @field_validator("domain")
    @classmethod
    def normalise_domain(cls, v: str) -> str:
        return (
            v.strip()
            .lower()
            .removeprefix("https://")
            .removeprefix("http://")
            .strip("/")
        )


class OceanResult(BaseModel):
    seed_domain: str
    companies: list[SimilarCompany]
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Stage 2 – Prospeo output
#
# Prospeo's Search Person + Bulk Enrich Person flow returns:
# - Decision maker profile
# - LinkedIn URL
# - Verified email
#
# VerifiedContact becomes the unified output object for Stage 2.
# ---------------------------------------------------------------------------

class VerifiedContact(BaseModel):
    """
    A decision maker with a verified work email.

    Produced by ProspeoService after Search → Bulk Enrich.
    Consumed directly by BrevoService.
    """

    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    email: str
    company_name: Optional[str] = None
    domain: Optional[str] = None
    linkedin_url: Optional[str] = None
    person_id: Optional[str] = None
    email_verified: bool = True

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("linkedin_url", mode="before")
    @classmethod
    def clean_linkedin(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None

        v = v.strip()

        if v.startswith("http"):
            return v

        return f"https://www.linkedin.com/in/{v}"

    @model_validator(mode="after")
    def split_name(self) -> "VerifiedContact":
        if self.full_name and not self.first_name:
            parts = self.full_name.strip().split(" ", 1)

            self.first_name = parts[0]
            self.last_name = parts[1] if len(parts) > 1 else None

        return self


class ProspeoResult(BaseModel):
    """
    Output of Stage 2.

    Contains only contacts that have verified emails
    and are eligible for outreach.
    """

    contacts: list[VerifiedContact]
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Stage 3 – Brevo output
# ---------------------------------------------------------------------------

class SentEmail(BaseModel):
    recipient_email: str
    recipient_name: str
    company_name: Optional[str] = None
    message_id: Optional[str] = None
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "sent"


class BrevoResult(BaseModel):
    emails_sent: list[SentEmail]
    emails_failed: list[dict] = Field(default_factory=list)
    sent_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Top-level pipeline state (persisted to disk)
#
# Stage numbering:
#
# Stage 1 = Apollo company discovery
# Stage 2 = Prospeo people + LinkedIn + email enrichment
# Stage 3 = Brevo outreach
# ---------------------------------------------------------------------------

class PipelineState(BaseModel):
    seed_domain: str

    started_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Stage outputs
    ocean_result: Optional[OceanResult] = None
    prospeo_result: Optional[ProspeoResult] = None
    brevo_result: Optional[BrevoResult] = None

    # Completion flags
    stage1_complete: bool = False
    stage2_complete: bool = False
    stage3_complete: bool = False
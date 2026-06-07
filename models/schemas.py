"""
Pydantic schemas for all pipeline stages.
Each model is the contract between stages, enforcing data integrity end-to-end.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, HttpUrl, field_validator, model_validator


# ---------------------------------------------------------------------------
# Stage 1 – Ocean.io output
# ---------------------------------------------------------------------------

class SimilarCompany(BaseModel):
    domain: str
    name: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None

    @field_validator("domain")
    @classmethod
    def normalise_domain(cls, v: str) -> str:
        return v.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")


class OceanResult(BaseModel):
    seed_domain: str
    companies: list[SimilarCompany]
    fetched_at: datetime = datetime.utcnow()


# ---------------------------------------------------------------------------
# Stage 2 – Prospeo output
# ---------------------------------------------------------------------------

class DecisionMaker(BaseModel):
    domain: str
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    company_name: Optional[str] = None

    @field_validator("linkedin_url", mode="before")
    @classmethod
    def clean_linkedin(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v if v.startswith("http") else f"https://www.linkedin.com/in/{v}"

    @model_validator(mode="after")
    def split_name(self) -> "DecisionMaker":
        if self.full_name and not self.first_name:
            parts = self.full_name.strip().split(" ", 1)
            self.first_name = parts[0]
            self.last_name = parts[1] if len(parts) > 1 else None
        return self


class ProspeoResult(BaseModel):
    decision_makers: list[DecisionMaker]
    fetched_at: datetime = datetime.utcnow()


# ---------------------------------------------------------------------------
# Stage 3 – Eazyreach output
# ---------------------------------------------------------------------------

class VerifiedContact(BaseModel):
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    email: str
    company_name: Optional[str] = None
    domain: Optional[str] = None
    linkedin_url: Optional[str] = None
    email_verified: bool = True

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.strip().lower()


class EazyreachResult(BaseModel):
    contacts: list[VerifiedContact]
    fetched_at: datetime = datetime.utcnow()


# ---------------------------------------------------------------------------
# Stage 4 – Brevo output
# ---------------------------------------------------------------------------

class SentEmail(BaseModel):
    recipient_email: str
    recipient_name: str
    company_name: Optional[str]
    message_id: Optional[str] = None
    sent_at: datetime = datetime.utcnow()
    status: str = "sent"


class BrevoResult(BaseModel):
    emails_sent: list[SentEmail]
    emails_failed: list[dict] = []
    sent_at: datetime = datetime.utcnow()


# ---------------------------------------------------------------------------
# Top-level pipeline state (persisted to disk)
# ---------------------------------------------------------------------------

class PipelineState(BaseModel):
    seed_domain: str
    started_at: datetime = datetime.utcnow()
    last_updated: datetime = datetime.utcnow()

    # Each stage writes its results here when complete
    ocean_result: Optional[OceanResult] = None
    prospeo_result: Optional[ProspeoResult] = None
    eazyreach_result: Optional[EazyreachResult] = None
    brevo_result: Optional[BrevoResult] = None

    # Stage completion flags for fast resume checks
    stage1_complete: bool = False
    stage2_complete: bool = False
    stage3_complete: bool = False
    stage4_complete: bool = False
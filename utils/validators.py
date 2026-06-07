"""
Deduplication and validation utilities used across pipeline stages.

Strategy:
- Domains:   normalised lowercase string set  (Stage 1 / Apollo).
- Contacts:  lowercase email string set       (Stage 2 / Prospeo output).
"""

from __future__ import annotations

import re

from models.schemas import SimilarCompany, VerifiedContact


def dedup_companies(companies: list[SimilarCompany]) -> list[SimilarCompany]:
    """Remove duplicate companies by normalised domain."""
    seen: set[str] = set()
    result: list[SimilarCompany] = []

    for company in companies:
        key = company.domain.lower()

        if key not in seen:
            seen.add(key)
            result.append(company)

    return result


def dedup_contacts(contacts: list[VerifiedContact]) -> list[VerifiedContact]:
    """Remove duplicate verified contacts by email (case-insensitive)."""
    seen: set[str] = set()
    result: list[VerifiedContact] = []

    for contact in contacts:
        key = contact.email.lower()

        if key not in seen:
            seen.add(key)
            result.append(contact)

    return result


def is_valid_email(email: str) -> bool:
    """Lightweight syntactic email validation (not DNS validation)."""
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email.strip()))
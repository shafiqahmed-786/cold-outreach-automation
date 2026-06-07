"""
Deduplication and validation utilities used across pipeline stages.

Strategy:
- Domains:   normalised lowercase string set.
- Profiles:  (domain, full_name) tuple set – same person can appear under
             multiple domains if they recently changed companies, so we keep
             the most specific combination.
- Emails:    lowercase string set – single global dedup across all contacts.
"""

from __future__ import annotations

from models.schemas import SimilarCompany, DecisionMaker, VerifiedContact


def dedup_companies(companies: list[SimilarCompany]) -> list[SimilarCompany]:
    """Remove duplicate companies by normalised domain."""
    seen: set[str] = set()
    result: list[SimilarCompany] = []
    for c in companies:
        key = c.domain.lower()
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def dedup_decision_makers(dms: list[DecisionMaker]) -> list[DecisionMaker]:
    """
    Remove duplicate decision makers.
    Key: (domain, normalised full_name).
    Also drops entries with no linkedin_url (unusable by Stage 3).
    """
    seen: set[tuple[str, str]] = set()
    result: list[DecisionMaker] = []
    for dm in dms:
        if not dm.linkedin_url:
            continue
        key = (dm.domain.lower(), dm.full_name.strip().lower())
        if key not in seen:
            seen.add(key)
            result.append(dm)
    return result


def dedup_contacts(contacts: list[VerifiedContact]) -> list[VerifiedContact]:
    """Remove duplicate verified contacts by email (case-insensitive)."""
    seen: set[str] = set()
    result: list[VerifiedContact] = []
    for c in contacts:
        key = c.email.lower()
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def is_valid_email(email: str) -> bool:
    """Lightweight syntactic email check (not DNS)."""
    import re
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email.strip()))
"""
Unit tests for utils/validators.py.

These tests exercise the three deduplication helpers and the email
syntax validator in isolation — no external I/O involved.
"""

import pytest

from models.schemas import SimilarCompany, DecisionMaker, VerifiedContact
from utils.validators import (
    dedup_companies,
    dedup_decision_makers,
    dedup_contacts,
    is_valid_email,
)


# ---------------------------------------------------------------------------
# dedup_companies
# ---------------------------------------------------------------------------

class TestDedupCompanies:
    def _make(self, domain: str, name: str = "Co") -> SimilarCompany:
        return SimilarCompany(domain=domain, name=name)

    def test_removes_exact_duplicate_domains(self):
        companies = [self._make("adyen.com"), self._make("adyen.com", "Adyen Clone")]
        result = dedup_companies(companies)
        assert len(result) == 1
        assert result[0].domain == "adyen.com"

    def test_preserves_first_occurrence(self):
        companies = [
            self._make("adyen.com", "Adyen Original"),
            self._make("adyen.com", "Adyen Clone"),
        ]
        result = dedup_companies(companies)
        assert result[0].name == "Adyen Original"

    def test_normalises_case_before_dedup(self):
        companies = [self._make("Adyen.COM"), self._make("adyen.com")]
        result = dedup_companies(companies)
        assert len(result) == 1

    def test_preserves_unique_domains(self):
        companies = [self._make("adyen.com"), self._make("stripe.com"), self._make("braintree.com")]
        result = dedup_companies(companies)
        assert len(result) == 3

    def test_empty_input_returns_empty(self):
        assert dedup_companies([]) == []


# ---------------------------------------------------------------------------
# dedup_decision_makers
# ---------------------------------------------------------------------------

class TestDedupDecisionMakers:
    def _make(self, domain: str, name: str, linkedin: str | None = "https://linkedin.com/in/x") -> DecisionMaker:
        return DecisionMaker(domain=domain, full_name=name, linkedin_url=linkedin)

    def test_removes_same_domain_and_name(self):
        dms = [
            self._make("adyen.com", "Elena Rossi"),
            self._make("adyen.com", "Elena Rossi"),
        ]
        result = dedup_decision_makers(dms)
        assert len(result) == 1

    def test_keeps_same_name_different_domain(self):
        dms = [
            self._make("adyen.com", "Elena Rossi"),
            self._make("stripe.com", "Elena Rossi"),
        ]
        result = dedup_decision_makers(dms)
        assert len(result) == 2

    def test_drops_entries_without_linkedin(self):
        dms = [
            self._make("adyen.com", "Elena Rossi", linkedin=None),
            self._make("stripe.com", "Marcus Wei", linkedin="https://linkedin.com/in/mw"),
        ]
        result = dedup_decision_makers(dms)
        assert len(result) == 1
        assert result[0].full_name == "Marcus Wei"

    def test_name_normalised_case_insensitive(self):
        dms = [
            self._make("adyen.com", "Elena Rossi"),
            self._make("adyen.com", "ELENA ROSSI"),
        ]
        result = dedup_decision_makers(dms)
        assert len(result) == 1

    def test_empty_input_returns_empty(self):
        assert dedup_decision_makers([]) == []


# ---------------------------------------------------------------------------
# dedup_contacts
# ---------------------------------------------------------------------------

class TestDedupContacts:
    def _make(self, email: str, name: str = "John Doe") -> VerifiedContact:
        return VerifiedContact(full_name=name, email=email)

    def test_removes_duplicate_emails(self):
        contacts = [
            self._make("oliver.grant@checkout.com"),
            self._make("oliver.grant@checkout.com"),
        ]
        result = dedup_contacts(contacts)
        assert len(result) == 1

    def test_case_insensitive_dedup(self):
        contacts = [
            self._make("Oliver.Grant@Checkout.COM"),
            self._make("oliver.grant@checkout.com"),
        ]
        result = dedup_contacts(contacts)
        assert len(result) == 1

    def test_preserves_different_emails(self):
        contacts = [
            self._make("a@example.com"),
            self._make("b@example.com"),
            self._make("c@example.com"),
        ]
        result = dedup_contacts(contacts)
        assert len(result) == 3

    def test_empty_input_returns_empty(self):
        assert dedup_contacts([]) == []


# ---------------------------------------------------------------------------
# is_valid_email
# ---------------------------------------------------------------------------

class TestIsValidEmail:
    def test_valid_standard(self):
        assert is_valid_email("user@example.com") is True

    def test_valid_subdomain(self):
        assert is_valid_email("user@mail.example.co.uk") is True

    def test_valid_plus_address(self):
        assert is_valid_email("user+tag@example.com") is True

    def test_invalid_no_at(self):
        assert is_valid_email("userexample.com") is False

    def test_invalid_no_domain(self):
        assert is_valid_email("user@") is False

    def test_invalid_no_tld(self):
        assert is_valid_email("user@example") is False

    def test_invalid_empty(self):
        assert is_valid_email("") is False

    def test_strips_whitespace_before_check(self):
        assert is_valid_email("  user@example.com  ") is True
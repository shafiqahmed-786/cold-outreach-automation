"""
Unit tests for services/brevo.py – email template generation.

_build_email_body is a pure function so tests require no HTTP mocking.
"""

import pytest

from models.schemas import VerifiedContact
from services.brevo import _build_email_body


def _contact(**kwargs) -> VerifiedContact:
    defaults = {
        "full_name": "Elena Rossi",
        "first_name": "Elena",
        "last_name": "Rossi",
        "email": "elena.rossi@adyen.com",
        "title": "Chief People Officer",
        "company_name": "Adyen",
    }
    defaults.update(kwargs)
    return VerifiedContact(**defaults)


class TestBuildEmailBody:
    def test_returns_three_tuple(self):
        subject, html, plain = _build_email_body(_contact())
        assert isinstance(subject, str)
        assert isinstance(html, str)
        assert isinstance(plain, str)

    def test_subject_contains_company(self):
        subject, _, _ = _build_email_body(_contact(company_name="Adyen"))
        assert "Adyen" in subject

    def test_plain_contains_first_name(self):
        _, _, plain = _build_email_body(_contact(first_name="Elena"))
        assert "Elena" in plain

    def test_plain_contains_title(self):
        _, _, plain = _build_email_body(_contact(title="Chief People Officer"))
        assert "Chief People Officer" in plain

    def test_plain_contains_company(self):
        _, _, plain = _build_email_body(_contact(company_name="Adyen"))
        assert "Adyen" in plain

    def test_html_contains_first_name(self):
        _, html, _ = _build_email_body(_contact(first_name="Elena"))
        assert "Elena" in html

    def test_html_is_valid_structure(self):
        _, html, _ = _build_email_body(_contact())
        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_fallback_when_first_name_absent(self):
        """When first_name is None, the function falls back to full_name.split()[0]."""
        contact = _contact(first_name=None, full_name="Elena Rossi")
        _, _, plain = _build_email_body(contact)
        assert "Elena" in plain

    def test_fallback_company_name_absent(self):
        """When company_name is None, fallback string 'your company' is used."""
        contact = _contact(company_name=None)
        subject, _, plain = _build_email_body(contact)
        assert "your company" in plain

    def test_unsubscribe_link_present(self):
        _, html, plain = _build_email_body(_contact())
        assert "unsubscribe" in html.lower()
        assert "unsubscribe" in plain.lower()

    def test_no_empty_subject(self):
        subject, _, _ = _build_email_body(_contact())
        assert len(subject.strip()) > 0
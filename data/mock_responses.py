"""
Static mock data for --mock mode.

Reflects the 3-stage pipeline:
  Stage 1  Apollo   → OCEAN_SIMILAR_COMPANIES
  Stage 2  Prospeo  → PROSPEO_CONTACTS  (people + verified emails in one list)
  Stage 3  Brevo    → (no fixtures needed; Brevo mock logs what it would send)

PROSPEO_CONTACTS merges what were previously two separate lists
(PROSPEO_DECISION_MAKERS + EAZYREACH_CONTACTS) into a single list of
VerifiedContact-compatible dicts, reflecting Prospeo's actual Search →
BulkEnrich two-step which returns emails alongside profile data.

Intentional edge cases preserved for testing:
  - Domain with no LinkedIn URL entry (filtered by dedup)
  - Duplicate email entry (filtered by dedup_contacts)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Stage 1 – Apollo: similar companies for stripe.com
# ---------------------------------------------------------------------------
OCEAN_SIMILAR_COMPANIES = [
    {"domain": "braintreepayments.com", "name": "Braintree",    "industry": "Fintech", "employee_count": 500},
    {"domain": "adyen.com",             "name": "Adyen",         "industry": "Fintech", "employee_count": 4000},
    {"domain": "square.com",            "name": "Square",        "industry": "Fintech", "employee_count": 9000},
    {"domain": "payoneer.com",          "name": "Payoneer",      "industry": "Fintech", "employee_count": 2500},
    {"domain": "checkout.com",          "name": "Checkout.com",  "industry": "Fintech", "employee_count": 1800},
    {"domain": "recurly.com",           "name": "Recurly",       "industry": "SaaS",    "employee_count": 300},
    {"domain": "chargebee.com",         "name": "Chargebee",     "industry": "SaaS",    "employee_count": 1200},
    {"domain": "zuora.com",             "name": "Zuora",         "industry": "SaaS",    "employee_count": 1500},
    # Intentional duplicate domain to exercise Stage 1 dedup
    {"domain": "adyen.com",             "name": "Adyen Duplicate", "industry": "Fintech", "employee_count": 4000},
]

# ---------------------------------------------------------------------------
# Stage 2 – Prospeo: decision makers with verified emails (combined output
# of Search Person + Bulk Enrich Person endpoints).
#
# Each entry maps directly to a VerifiedContact constructor call.
# ---------------------------------------------------------------------------
PROSPEO_CONTACTS = [
    {
        "domain": "braintreepayments.com",
        "full_name": "Sarah Mitchell",
        "title": "Chief Technology Officer",
        "email": "sarah.mitchell@braintreepayments.com",
        "linkedin_url": "https://www.linkedin.com/in/sarahmitchell-cto",
        "company_name": "Braintree",
        "person_id": "mock-person-001",
        "email_verified": True,
    },
    {
        "domain": "braintreepayments.com",
        "full_name": "James Okafor",
        "title": "VP of Engineering",
        "email": "james.okafor@braintreepayments.com",
        "linkedin_url": "https://www.linkedin.com/in/jamesokafor",
        "company_name": "Braintree",
        "person_id": "mock-person-002",
        "email_verified": True,
    },
    {
        "domain": "adyen.com",
        "full_name": "Elena Rossi",
        "title": "Chief People Officer",
        "email": "elena.rossi@adyen.com",
        "linkedin_url": "https://www.linkedin.com/in/elenarossi-cpo",
        "company_name": "Adyen",
        "person_id": "mock-person-003",
        "email_verified": True,
    },
    {
        "domain": "adyen.com",
        "full_name": "Marcus Wei",
        "title": "VP of Talent Acquisition",
        "email": "marcus.wei@adyen.com",
        "linkedin_url": "https://www.linkedin.com/in/marcuswei-talent",
        "company_name": "Adyen",
        "person_id": "mock-person-004",
        "email_verified": True,
    },
    {
        "domain": "square.com",
        "full_name": "Priya Nair",
        "title": "Chief HR Officer",
        "email": "priya.nair@squareup.com",
        "linkedin_url": "https://www.linkedin.com/in/priyanair-chro",
        "company_name": "Square",
        "person_id": "mock-person-005",
        "email_verified": True,
    },
    {
        "domain": "recurly.com",
        "full_name": "Daniel Torres",
        "title": "VP of Engineering",
        "email": "daniel.torres@recurly.com",
        "linkedin_url": "https://www.linkedin.com/in/danieltorres-eng",
        "company_name": "Recurly",
        "person_id": "mock-person-006",
        "email_verified": True,
    },
    {
        "domain": "chargebee.com",
        "full_name": "Aiko Tanaka",
        "title": "CTO",
        "email": "aiko.tanaka@chargebee.com",
        "linkedin_url": "https://www.linkedin.com/in/aikotanaka-cto",
        "company_name": "Chargebee",
        "person_id": "mock-person-007",
        "email_verified": True,
    },
    {
        "domain": "zuora.com",
        "full_name": "Robert Kim",
        "title": "VP of Product",
        "email": "robert.kim@zuora.com",
        "linkedin_url": "https://www.linkedin.com/in/robertkim-vp",
        "company_name": "Zuora",
        "person_id": "mock-person-008",
        "email_verified": True,
    },
    {
        "domain": "checkout.com",
        "full_name": "Oliver Grant",
        "title": "CTO",
        "email": "oliver.grant@checkout.com",
        "linkedin_url": "https://www.linkedin.com/in/olivergrant-cto",
        "company_name": "Checkout.com",
        "person_id": "mock-person-009",
        "email_verified": True,
    },
    # Intentional duplicate email to exercise Stage 2 dedup
    {
        "domain": "checkout.com",
        "full_name": "Oliver Grant",
        "title": "CTO",
        "email": "oliver.grant@checkout.com",
        "linkedin_url": "https://www.linkedin.com/in/olivergrant-cto",
        "company_name": "Checkout.com",
        "person_id": "mock-person-009-dup",
        "email_verified": True,
    },
]

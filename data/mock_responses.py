"""
Static mock data for --mock mode.

These fixtures represent realistic API responses so the full pipeline
(including dedup, validation, email generation) can be exercised without
spending a single API credit.

To extend: add more entries to any list below.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Stage 1 – Ocean.io: similar companies for stripe.com
# ---------------------------------------------------------------------------
OCEAN_SIMILAR_COMPANIES = [
    {"domain": "braintreepayments.com", "name": "Braintree", "industry": "Fintech", "employee_count": 500},
    {"domain": "adyen.com", "name": "Adyen", "industry": "Fintech", "employee_count": 4000},
    {"domain": "square.com", "name": "Square", "industry": "Fintech", "employee_count": 9000},
    {"domain": "payoneer.com", "name": "Payoneer", "industry": "Fintech", "employee_count": 2500},
    {"domain": "checkout.com", "name": "Checkout.com", "industry": "Fintech", "employee_count": 1800},
    {"domain": "recurly.com", "name": "Recurly", "industry": "SaaS", "employee_count": 300},
    {"domain": "chargebee.com", "name": "Chargebee", "industry": "SaaS", "employee_count": 1200},
    {"domain": "zuora.com", "name": "Zuora", "industry": "SaaS", "employee_count": 1500},
    # Intentional duplicate to test dedup
    {"domain": "adyen.com", "name": "Adyen Duplicate", "industry": "Fintech", "employee_count": 4000},
]

# ---------------------------------------------------------------------------
# Stage 2 – Prospeo: decision makers per domain
# ---------------------------------------------------------------------------
PROSPEO_DECISION_MAKERS = [
    {
        "domain": "braintreepayments.com",
        "full_name": "Sarah Mitchell",
        "title": "Chief Technology Officer",
        "linkedin_url": "https://www.linkedin.com/in/sarahmitchell-cto",
        "company_name": "Braintree",
    },
    {
        "domain": "braintreepayments.com",
        "full_name": "James Okafor",
        "title": "VP of Engineering",
        "linkedin_url": "https://www.linkedin.com/in/jamesokafor",
        "company_name": "Braintree",
    },
    {
        "domain": "adyen.com",
        "full_name": "Elena Rossi",
        "title": "Chief People Officer",
        "linkedin_url": "https://www.linkedin.com/in/elenarossi-cpo",
        "company_name": "Adyen",
    },
    {
        "domain": "adyen.com",
        "full_name": "Marcus Wei",
        "title": "VP of Talent Acquisition",
        "linkedin_url": "https://www.linkedin.com/in/marcuswei-talent",
        "company_name": "Adyen",
    },
    {
        "domain": "square.com",
        "full_name": "Priya Nair",
        "title": "Chief HR Officer",
        "linkedin_url": "https://www.linkedin.com/in/priyanair-chro",
        "company_name": "Square",
    },
    {
        "domain": "recurly.com",
        "full_name": "Daniel Torres",
        "title": "VP of Engineering",
        "linkedin_url": "https://www.linkedin.com/in/danieltorres-eng",
        "company_name": "Recurly",
    },
    {
        "domain": "chargebee.com",
        "full_name": "Aiko Tanaka",
        "title": "CTO",
        "linkedin_url": "https://www.linkedin.com/in/aikotanaka-cto",
        "company_name": "Chargebee",
    },
    {
        "domain": "zuora.com",
        "full_name": "Robert Kim",
        "title": "VP of Product",
        "linkedin_url": "https://www.linkedin.com/in/robertkim-vp",
        "company_name": "Zuora",
    },
    # No linkedin_url – should be filtered by dedup
    {
        "domain": "payoneer.com",
        "full_name": "Lisa Chen",
        "title": "CEO",
        "linkedin_url": None,
        "company_name": "Payoneer",
    },
    # Duplicate email contact to test dedup in stage 3
    {
        "domain": "checkout.com",
        "full_name": "Oliver Grant",
        "title": "CTO",
        "linkedin_url": "https://www.linkedin.com/in/olivergrant-cto",
        "company_name": "Checkout.com",
    },
]

# ---------------------------------------------------------------------------
# Stage 3 – Eazyreach: verified emails from LinkedIn URLs
# ---------------------------------------------------------------------------
EAZYREACH_CONTACTS = [
    {
        "full_name": "Sarah Mitchell",
        "title": "Chief Technology Officer",
        "email": "sarah.mitchell@braintreepayments.com",
        "company_name": "Braintree",
        "domain": "braintreepayments.com",
        "linkedin_url": "https://www.linkedin.com/in/sarahmitchell-cto",
        "email_verified": True,
    },
    {
        "full_name": "James Okafor",
        "title": "VP of Engineering",
        "email": "james.okafor@braintreepayments.com",
        "company_name": "Braintree",
        "domain": "braintreepayments.com",
        "linkedin_url": "https://www.linkedin.com/in/jamesokafor",
        "email_verified": True,
    },
    {
        "full_name": "Elena Rossi",
        "title": "Chief People Officer",
        "email": "elena.rossi@adyen.com",
        "company_name": "Adyen",
        "domain": "adyen.com",
        "linkedin_url": "https://www.linkedin.com/in/elenarossi-cpo",
        "email_verified": True,
    },
    {
        "full_name": "Marcus Wei",
        "title": "VP of Talent Acquisition",
        "email": "marcus.wei@adyen.com",
        "company_name": "Adyen",
        "domain": "adyen.com",
        "linkedin_url": "https://www.linkedin.com/in/marcuswei-talent",
        "email_verified": True,
    },
    {
        "full_name": "Priya Nair",
        "title": "Chief HR Officer",
        "email": "priya.nair@squareup.com",
        "company_name": "Square",
        "domain": "square.com",
        "linkedin_url": "https://www.linkedin.com/in/priyanair-chro",
        "email_verified": True,
    },
    {
        "full_name": "Daniel Torres",
        "title": "VP of Engineering",
        "email": "daniel.torres@recurly.com",
        "company_name": "Recurly",
        "domain": "recurly.com",
        "linkedin_url": "https://www.linkedin.com/in/danieltorres-eng",
        "email_verified": True,
    },
    {
        "full_name": "Aiko Tanaka",
        "title": "CTO",
        "email": "aiko.tanaka@chargebee.com",
        "company_name": "Chargebee",
        "domain": "chargebee.com",
        "linkedin_url": "https://www.linkedin.com/in/aikotanaka-cto",
        "email_verified": True,
    },
    {
        "full_name": "Robert Kim",
        "title": "VP of Product",
        "email": "robert.kim@zuora.com",
        "company_name": "Zuora",
        "domain": "zuora.com",
        "linkedin_url": "https://www.linkedin.com/in/robertkim-vp",
        "email_verified": True,
    },
    {
        "full_name": "Oliver Grant",
        "title": "CTO",
        "email": "oliver.grant@checkout.com",
        "company_name": "Checkout.com",
        "domain": "checkout.com",
        "linkedin_url": "https://www.linkedin.com/in/olivergrant-cto",
        "email_verified": True,
    },
    # Duplicate email to exercise Stage 3 dedup
    {
        "full_name": "Oliver Grant",
        "title": "CTO",
        "email": "oliver.grant@checkout.com",
        "company_name": "Checkout.com",
        "domain": "checkout.com",
        "linkedin_url": "https://www.linkedin.com/in/olivergrant-cto",
        "email_verified": True,
    },
]
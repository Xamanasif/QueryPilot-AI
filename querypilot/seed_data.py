"""Deterministic simulated M&A diligence dataset.

Two tenants run separate deals. All companies, people and figures are fictional.
"""

TENANTS = [
    {"tenant_id": "acme", "name": "Acme Capital Partners",
     "deal_name": "Project Falcon - acquisition of Northwind Components Ltd"},
    {"tenant_id": "globex", "name": "Globex Advisory",
     "deal_name": "Project Orion - acquisition of Brightline Logistics"},
]

# Demo keys only. They are stored as SHA-256 hashes, never in plaintext.
API_KEYS = [
    {"key": "qp_acme_analyst_demo", "tenant_id": "acme", "principal": "ana.analyst", "role": "analyst"},
    {"key": "qp_acme_reviewer_demo", "tenant_id": "acme", "principal": "rui.reviewer", "role": "reviewer"},
    {"key": "qp_globex_analyst_demo", "tenant_id": "globex", "principal": "gus.analyst", "role": "analyst"},
]

DOCUMENTS = [
    {
        "doc_id": "ACME-MSA-001", "tenant_id": "acme", "category": "contract",
        "title": "Master Supply Agreement - Helios Motors",
        "versions": [
            {"version": 1, "status": "approved", "approved_by": "rui.reviewer", "content": (
                "Parties. This Master Supply Agreement is between Northwind Components Ltd (Supplier) and "
                "Helios Motors GmbH (Customer), effective 1 March 2022 for an initial term of five years.\n\n"
                "Change of control. Either party may terminate this agreement on 90 days written notice if the "
                "other party undergoes a change of control without prior written consent. Consent shall not be "
                "unreasonably withheld.\n\n"
                "Pricing. Unit prices are fixed for 24 months and thereafter indexed annually to the eurozone "
                "producer price index, capped at 4 percent.\n\n"
                "Exclusivity. Supplier grants Customer exclusivity for brake sensor assemblies within the "
                "European Union."
            )},
            {"version": 2, "status": "draft", "content": (
                "Parties. This Master Supply Agreement is between Northwind Components Ltd (Supplier) and "
                "Helios Motors GmbH (Customer), effective 1 March 2022 for an initial term of five years.\n\n"
                "Change of control. Customer may terminate immediately and without notice upon any change of "
                "control of Supplier.\n\n"
                "Pricing. Unit prices are fixed for 24 months and thereafter indexed annually to the eurozone "
                "producer price index, capped at 4 percent."
            )},
        ],
    },
    {
        "doc_id": "ACME-FIN-002", "tenant_id": "acme", "category": "financial",
        "title": "FY2024 Audited Financial Summary",
        "versions": [
            {"version": 1, "status": "approved", "approved_by": "rui.reviewer", "content": (
                "Revenue. Audited revenue for FY2024 was EUR 48.2 million, up 11 percent year on year. The top "
                "three customers represented 58 percent of revenue.\n\n"
                "EBITDA. Adjusted EBITDA was EUR 9.1 million, an adjusted margin of 18.9 percent, after "
                "normalising EUR 0.4 million of one-off relocation costs.\n\n"
                "Auditor opinion. The statutory auditor issued an unqualified opinion on the FY2024 accounts."
            )},
        ],
    },
    {
        "doc_id": "ACME-IP-003", "tenant_id": "acme", "category": "legal",
        "title": "Intellectual Property Register",
        "versions": [
            {"version": 1, "status": "superseded", "approved_by": "rui.reviewer", "content": (
                "Patents. Northwind owns 11 granted patents covering sensor calibration.\n\n"
                "Assignments. All inventors have executed invention assignment agreements."
            )},
            {"version": 2, "status": "approved", "approved_by": "rui.reviewer", "content": (
                "Patents. Northwind owns 14 granted patents covering sensor calibration and signal filtering, "
                "registered in the EU, UK and US.\n\n"
                "Assignments. All employee inventors have executed invention assignment agreements, except two "
                "contractors engaged in 2021 whose assignments remain outstanding."
            )},
        ],
    },
    {
        "doc_id": "ACME-LIT-004", "tenant_id": "acme", "category": "legal",
        "title": "Litigation and Claims Schedule",
        "versions": [
            {"version": 1, "status": "approved", "approved_by": "rui.reviewer", "content": (
                "Pending litigation. One pending claim: a former distributor alleges wrongful termination and "
                "seeks EUR 1.3 million in damages. Counsel assesses the probability of material loss as remote.\n\n"
                "Regulatory matters. No regulatory investigations are open."
            )},
        ],
    },
    {
        "doc_id": "ACME-PRIV-005", "tenant_id": "acme", "category": "compliance",
        "title": "Data Protection Compliance Memo",
        "versions": [
            {"version": 1, "status": "draft", "content": (
                "GDPR. Northwind has appointed a data protection officer and maintains records of processing "
                "activities for customer and employee personal data.\n\n"
                "Breaches. No personal data breaches were notified to a supervisory authority since 2021."
            )},
        ],
    },
    {
        "doc_id": "ACME-HR-006", "tenant_id": "acme", "category": "hr",
        "title": "Key Employee Retention Plan",
        "versions": [
            {"version": 1, "status": "approved", "approved_by": "rui.reviewer", "content": (
                "Retention. Five key engineers are covered by retention bonuses totalling EUR 600,000, payable "
                "12 months after closing subject to continued employment.\n\n"
                "Non-compete. Key engineers are bound by 12-month post-employment non-compete covenants."
            )},
        ],
    },
    {
        "doc_id": "GLX-LEASE-001", "tenant_id": "globex", "category": "contract",
        "title": "Fleet Lease Agreement - Brightline Logistics",
        "versions": [
            {"version": 1, "status": "approved", "approved_by": "gus.analyst", "content": (
                "Change of control. The lessor may accelerate all outstanding lease payments upon a change of "
                "control of Brightline Logistics.\n\n"
                "Fleet. The lease covers 220 refrigerated trailers on a seven-year term."
            )},
        ],
    },
    {
        "doc_id": "GLX-FIN-002", "tenant_id": "globex", "category": "financial",
        "title": "Brightline Management Accounts",
        "versions": [
            {"version": 1, "status": "approved", "approved_by": "gus.analyst", "content": (
                "Revenue. Unaudited revenue for FY2024 was EUR 112 million.\n\n"
                "Debt. A senior term loan facility of EUR 40 million carries a leverage covenant of 3.0x."
            )},
        ],
    },
]

# (tenant_id, item_id, workstream, requirement, retrieval query)
CHECKLIST = [
    ("acme", "CL-01", "legal", "Identify change-of-control termination rights in material customer contracts",
     "change of control terminate consent"),
    ("acme", "CL-02", "financial", "Confirm audited revenue and customer concentration",
     "audited revenue top customers percent"),
    ("acme", "CL-03", "legal", "Verify ownership and assignment of intellectual property",
     "patents invention assignment"),
    ("acme", "CL-04", "legal", "Schedule pending litigation and estimated exposure",
     "pending litigation claim damages"),
    ("acme", "CL-05", "compliance", "Confirm GDPR and data protection compliance",
     "gdpr data protection officer processing"),
    ("acme", "CL-06", "financial", "Review debt facilities and covenant compliance",
     "debt facility leverage lender"),
    ("acme", "CL-07", "hr", "Assess key employee retention arrangements",
     "key engineers retention bonuses"),
    ("globex", "CL-01", "legal", "Identify change-of-control provisions in material contracts",
     "change of control accelerate"),
    ("globex", "CL-02", "financial", "Review debt facilities and covenant compliance",
     "debt facility leverage covenant"),
]

CUSTOMERS = [
    ("acme", "C001", "Helios Motors", "Automotive", "EU"),
    ("acme", "C002", "Vantor Rail", "Rail", "EU"),
    ("acme", "C003", "Kestrel Aero", "Aerospace", "UK"),
    ("acme", "C004", "Orbis Agritech", "Agriculture", "NA"),
    ("acme", "C005", "Lumen Trucks", "Automotive", "EU"),
    ("acme", "C006", "Sable Marine", "Marine", "APAC"),
    ("globex", "G001", "FreshCo Retail", "Grocery", "EU"),
    ("globex", "G002", "Polar Pharma", "Healthcare", "EU"),
    ("globex", "G003", "Nordic Dairy", "Grocery", "EU"),
]

# (tenant_id, order_id, customer_id, order_date, product, quantity, unit_price)
ORDERS = [
    ("acme", "O1001", "C001", "2025-01-15", "BS-100", 500, "42.00"),
    ("acme", "O1002", "C001", "2025-04-10", "BS-100", 650, "41.50"),
    ("acme", "O1003", "C001", "2025-07-22", "CU-300", 120, "310.00"),
    ("acme", "O1004", "C001", "2025-11-30", "BS-100", 700, "41.00"),
    ("acme", "O1005", "C002", "2025-02-03", "TS-200", 300, "18.75"),
    ("acme", "O1006", "C002", "2025-06-18", "CU-300", 80, "325.00"),
    ("acme", "O1007", "C002", "2025-12-05", "TS-200", 350, "18.50"),
    ("acme", "O1008", "C003", "2025-03-12", "CU-300", 60, "340.00"),
    ("acme", "O1009", "C003", "2025-09-09", "CU-300", 40, "335.00"),
    ("acme", "O1010", "C004", "2025-05-20", "TS-200", 200, "19.25"),
    ("acme", "O1011", "C005", "2025-01-28", "BS-100", 300, "43.00"),
    ("acme", "O1012", "C005", "2025-08-14", "BS-100", 250, "42.50"),
    ("acme", "O1013", "C005", "2025-10-02", "TS-200", 150, "19.00"),
    ("acme", "O1014", "C006", "2025-04-25", "TS-200", 100, "20.00"),
    ("acme", "O1015", "C006", "2025-12-20", "BS-100", 90, "44.00"),
    ("globex", "X2001", "G001", "2025-03-01", "COLD-PALLET", 1200, "35.00"),
    ("globex", "X2002", "G002", "2025-06-15", "PHARMA-RUN", 40, "900.00"),
    ("globex", "X2003", "G003", "2025-09-30", "COLD-PALLET", 800, "34.00"),
]

# Fixed reference date for recency so analytics are reproducible.
ANALYSIS_AS_OF = "2025-12-31"

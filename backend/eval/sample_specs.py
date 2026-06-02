"""Curated catalogue for the upload-tab sample gallery (see eval/sample_gallery.py).

Each example pairs realistic documents with the exact form values a member would enter, so
that running it through the LIVE pipeline (a) passes the claim/document consistency + patient
checks (amount = bill total, date = document date, patient = the chosen member) and (b) lands
on its intended outcome. Outcomes mirror the verified test-case logic (eval 12/12):

  APPROVED      consultation (co-pay) · network-hospital discount · dental partial (cosmetic excluded)
  REJECTED      diabetes waiting period · excluded bariatric · per-claim limit · MRI without pre-auth
  HUMAN REVIEW  high-value auto-review (>₹25k) · same-day velocity (seeds 2 prior same-day claims)
"""

from __future__ import annotations

from typing import Any

# ── providers (letterheads) ────────────────────────────────────────────────────────
CITY = {
    "name": "City Care Clinic",
    "address": "12 MG Road, Bengaluru 560001",
    "gstin": "GSTIN 29AABCC1234C1Z9",
    "phone": "+91 80 4123 7788",
    "accent": (31, 73, 125),
}
APOLLO = {  # on the policy network_hospitals list → triggers the network discount
    "name": "Apollo Hospitals",
    "address": "154 Bannerghatta Rd, Bengaluru 560076",
    "gstin": "GSTIN 29AAACA1234A1Z5",
    "phone": "+91 80 4612 4000",
    "accent": (0, 86, 163),
}
SUNRISE = {
    "name": "Sunrise Diagnostics",
    "address": "44 Residency Rd, Bengaluru 560025",
    "gstin": "GSTIN 29AAGCS9921P1ZK",
    "phone": "+91 80 2599 1200",
    "accent": (109, 40, 140),
}
SMILE = {
    "name": "Smile Dental Care",
    "address": "7 Indiranagar 100ft Rd, Bengaluru 560038",
    "gstin": "GSTIN 29AAFCS3344Q1Z2",
    "phone": "+91 80 4555 9090",
    "accent": (180, 83, 9),
}

EXAMPLES: list[dict[str, Any]] = [
    # ── APPROVED ───────────────────────────────────────────────────────────────────
    {
        "id": "approved_consultation",
        "bucket": "approved",
        "label": "Clean consultation",
        "description": "A straightforward GP visit + basic tests — fully covered after the 10% co-pay.",
        "form": {"member_id": "EMP002", "claim_category": "CONSULTATION", "treatment_date": "2024-11-01",
                 "claimed_amount": 1500, "hospital_name": ""},
        "docs": [
            {"kind": "prescription", "file": "prescription.png", "provider": CITY, "patient": "Priya Singh",
             "date": "01 Nov 2024", "doctor": {"name": "Dr. Anil Sharma", "reg": "KMC/12345/2011"},
             "diagnosis": "Viral fever with throat infection",
             "medicines": ["Paracetamol 650mg — 1-1-1 (5 days)", "Azithromycin 500mg — 1-0-0 (3 days)",
                           "Cough syrup — 10ml twice daily"], "advice": "Rest, fluids, review if fever persists."},
            {"kind": "invoice", "file": "hospital_bill.png", "provider": CITY, "patient": "Priya Singh",
             "date": "01 Nov 2024", "doc_no": "INV-4471", "uhid": "CC-220194",
             "items": [("Consultation — General Medicine", 1, 1000), ("CBC (Complete Blood Count)", 1, 300),
                       ("Dengue NS1 Antigen", 1, 200)], "total": 1500},
        ],
    },
    {
        "id": "approved_network",
        "bucket": "approved",
        "label": "Network hospital discount",
        "description": "Treated at a network hospital (Apollo) — a 20% network discount applies before co-pay.",
        "form": {"member_id": "EMP003", "claim_category": "CONSULTATION", "treatment_date": "2024-11-03",
                 "claimed_amount": 4500, "hospital_name": "Apollo Hospitals"},
        "docs": [
            {"kind": "prescription", "file": "prescription.png", "provider": APOLLO, "patient": "Amit Verma",
             "date": "03 Nov 2024", "doctor": {"name": "Dr. Meera Iyer", "reg": "KMC/33421/2009"},
             "diagnosis": "Acute bronchitis", "medicines": ["Augmentin 625mg — 1-0-1 (7 days)",
                           "Montair-LC — 0-0-1 (10 days)", "Steam inhalation twice daily"]},
            {"kind": "invoice", "file": "hospital_bill.png", "provider": APOLLO, "patient": "Amit Verma",
             "date": "03 Nov 2024", "doc_no": "APX-77310", "uhid": "APX-220194",
             "items": [("Specialist Consultation — Pulmonology", 1, 1500), ("Chest X-Ray (PA view)", 1, 1200),
                       ("Nebulisation + Day-care charges", 1, 1800)], "total": 4500},
        ],
    },
    {
        "id": "approved_dental_partial",
        "bucket": "approved",
        "label": "Dental — partial (cosmetic excluded)",
        "description": "Root canal is covered; teeth whitening is cosmetic and excluded — so it partially approves.",
        "form": {"member_id": "EMP004", "claim_category": "DENTAL", "treatment_date": "2024-10-15",
                 "claimed_amount": 12000, "hospital_name": ""},
        "docs": [
            {"kind": "invoice", "file": "hospital_bill.png", "provider": SMILE, "patient": "Sneha Reddy",
             "date": "15 Oct 2024", "doc_no": "SDC-3320", "uhid": "SDC-1190", "title": "DENTAL TREATMENT INVOICE",
             "items": [("Root Canal Treatment (molar)", 1, 8000), ("Teeth Whitening", 1, 4000)],
             "total": 12000},
        ],
    },
    # ── REJECTED ───────────────────────────────────────────────────────────────────
    {
        "id": "rejected_waiting_diabetes",
        "bucket": "rejected",
        "label": "Diabetes within waiting period",
        "description": "A new joiner's diabetes claim falls inside the 90-day condition waiting period.",
        "form": {"member_id": "EMP005", "claim_category": "CONSULTATION", "treatment_date": "2024-10-15",
                 "claimed_amount": 3000, "hospital_name": ""},
        "docs": [
            {"kind": "prescription", "file": "prescription.png", "provider": CITY, "patient": "Vikram Joshi",
             "date": "15 Oct 2024", "doctor": {"name": "Dr. Sunil Mehta", "reg": "GJ/56789/2014"},
             "diagnosis": "Type 2 Diabetes Mellitus", "medicines": ["Metformin 500mg — 1-0-1",
                           "Glimepiride 1mg — 1-0-0", "Lifestyle & diet counselling"]},
            {"kind": "invoice", "file": "hospital_bill.png", "provider": CITY, "patient": "Vikram Joshi",
             "date": "15 Oct 2024", "doc_no": "INV-5521", "uhid": "CC-330512",
             "items": [("Endocrinology Consultation", 1, 1200), ("HbA1c", 1, 700),
                       ("Fasting Blood Sugar Panel", 1, 1100)], "total": 3000},
        ],
    },
    {
        "id": "rejected_excluded_bariatric",
        "bucket": "rejected",
        "label": "Excluded treatment (bariatric)",
        "description": "Obesity / weight-loss treatment is explicitly excluded under the policy.",
        "form": {"member_id": "EMP001", "claim_category": "CONSULTATION", "treatment_date": "2024-10-18",
                 "claimed_amount": 8000, "hospital_name": ""},
        "docs": [
            {"kind": "prescription", "file": "prescription.png", "provider": CITY, "patient": "Rajesh Kumar",
             "date": "18 Oct 2024", "doctor": {"name": "Dr. R. Khanna", "reg": "KMC/77120/2007"},
             "diagnosis": "Obesity (BMI 38)", "advice": "Bariatric Consultation and Customised Diet Plan",
             "medicines": ["Multivitamin — 1-0-0", "Customised weight-loss diet plan",
                           "Bariatric surgery counselling"]},
            {"kind": "invoice", "file": "hospital_bill.png", "provider": CITY, "patient": "Rajesh Kumar",
             "date": "18 Oct 2024", "doc_no": "INV-6190", "uhid": "CC-220194",
             "items": [("Bariatric Consultation", 1, 5000), ("Customised Diet Plan", 1, 3000)], "total": 8000},
        ],
    },
    {
        "id": "rejected_per_claim_limit",
        "bucket": "rejected",
        "label": "Over the per-claim limit",
        "description": "₹7,500 on one consultation exceeds the ₹5,000 per-claim limit — the whole claim is rejected.",
        "form": {"member_id": "EMP006", "claim_category": "CONSULTATION", "treatment_date": "2024-10-20",
                 "claimed_amount": 7500, "hospital_name": ""},
        "docs": [
            {"kind": "prescription", "file": "prescription.png", "provider": CITY, "patient": "Kavita Nair",
             "date": "20 Oct 2024", "doctor": {"name": "Dr. R. Gupta", "reg": "DL/34567/2016"},
             "diagnosis": "Acute gastroenteritis", "medicines": ["Antibiotics — 1-0-1 (5 days)",
                           "Probiotics — 1-1-1", "ORS — as needed"]},
            {"kind": "invoice", "file": "hospital_bill.png", "provider": CITY, "patient": "Kavita Nair",
             "date": "20 Oct 2024", "doc_no": "INV-7044", "uhid": "CC-220194",
             "items": [("Consultation Fee", 1, 2000), ("Medicines & IV fluids", 1, 5500)], "total": 7500},
        ],
    },
    {
        "id": "rejected_mri_no_preauth",
        "bucket": "rejected",
        "label": "MRI without pre-authorization",
        "description": "A ₹15,000 MRI needs pre-authorization (>₹10k) — none was obtained, so it's rejected.",
        "form": {"member_id": "EMP007", "claim_category": "DIAGNOSTIC", "treatment_date": "2024-11-02",
                 "claimed_amount": 15000, "hospital_name": ""},
        "docs": [
            {"kind": "prescription", "file": "prescription.png", "provider": SUNRISE, "patient": "Suresh Patil",
             "date": "02 Nov 2024", "doctor": {"name": "Dr. N. Rao", "reg": "KMC/41200/2005"},
             "diagnosis": "Persistent headache — rule out intracranial cause",
             "medicines": ["Advised: MRI Brain (plain)", "Analgesics — SOS"]},
            {"kind": "report", "file": "lab_report.png", "provider": SUNRISE, "patient": "Suresh Patil",
             "date": "02 Nov 2024", "doc_no": "SDX-9981", "title": "MRI DIAGNOSTIC REPORT",
             "doctor": {"name": "Dr. P. Banerjee"}, "diagnosis": "MRI Brain (plain) — no acute abnormality",
             "findings": [("MRI Brain (plain study)", "No acute abnormality", "—"),
                          ("Ventricular system", "Normal", "Normal"), ("Mass effect", "None", "Absent")]},
            {"kind": "invoice", "file": "hospital_bill.png", "provider": SUNRISE, "patient": "Suresh Patil",
             "date": "02 Nov 2024", "doc_no": "SDX-9981-B", "uhid": "SD-771230", "title": "DIAGNOSTIC INVOICE",
             "items": [("MRI Brain Scan (plain)", 1, 15000)], "total": 15000},
        ],
    },
    # ── HUMAN REVIEW ─────────────────────────────────────────────────────────────────
    {
        "id": "review_high_value",
        "bucket": "hitl",
        "label": "High-value claim",
        "description": "A ₹28,000 claim exceeds the ₹25,000 auto-review threshold — routed to a human reviewer.",
        "form": {"member_id": "EMP009", "claim_category": "DIAGNOSTIC", "treatment_date": "2024-10-28",
                 "claimed_amount": 28000, "hospital_name": ""},
        "docs": [
            {"kind": "prescription", "file": "prescription.png", "provider": SUNRISE, "patient": "Anita Desai",
             "date": "28 Oct 2024", "doctor": {"name": "Dr. K. Subramanian", "reg": "KMC/22980/2003"},
             "diagnosis": "Executive health evaluation", "medicines": ["Advised: comprehensive health check-up",
                           "Fasting required prior to sampling"]},
            {"kind": "report", "file": "lab_report.png", "provider": SUNRISE, "patient": "Anita Desai",
             "date": "28 Oct 2024", "doc_no": "SDX-8820", "title": "HEALTH CHECK-UP REPORT",
             "doctor": {"name": "Dr. P. Banerjee"}, "diagnosis": "Within normal limits overall",
             "findings": [("Lipid profile", "Borderline", "Desirable < 200"), ("Thyroid (TSH)", "2.4 mIU/L", "0.4–4.0"),
                          ("Ultrasound abdomen", "Normal study", "—"), ("2D Echo", "Normal LV function", "—")]},
            {"kind": "invoice", "file": "hospital_bill.png", "provider": SUNRISE, "patient": "Anita Desai",
             "date": "28 Oct 2024", "doc_no": "SDX-8820-B", "uhid": "SD-771230", "title": "DIAGNOSTIC INVOICE",
             "items": [("Master Health Check-up Package", 1, 18000), ("2D Echocardiography", 1, 4000),
                       ("Ultrasound Abdomen", 1, 3000), ("Lipid + Thyroid Panel", 1, 3000)], "total": 28000},
        ],
    },
    {
        "id": "review_same_day",
        "bucket": "hitl",
        "label": "Multiple same-day claims",
        "description": "Selecting this seeds 2 earlier same-day claims for this member; running it is the 3rd "
                       "that day, which trips the same-day velocity rule → human review. (Needs the ledger on.)",
        "form": {"member_id": "EMP010", "claim_category": "CONSULTATION", "treatment_date": "2024-11-05",
                 "claimed_amount": 1500, "hospital_name": ""},
        "seed": {"member_id": "EMP010", "treatment_date": "2024-11-05", "count": 2},
        "docs": [
            {"kind": "prescription", "file": "prescription.png", "provider": CITY, "patient": "Deepak Shah",
             "date": "05 Nov 2024", "doctor": {"name": "Dr. Anil Sharma", "reg": "KMC/12345/2011"},
             "diagnosis": "Migraine", "medicines": ["Sumatriptan 50mg — SOS", "Naproxen 250mg — 1-0-1"]},
            {"kind": "invoice", "file": "hospital_bill.png", "provider": CITY, "patient": "Deepak Shah",
             "date": "05 Nov 2024", "doc_no": "INV-8852", "uhid": "CC-220194",
             "items": [("Neurology Consultation", 1, 1500)], "total": 1500},
        ],
    },
]

from __future__ import annotations

from app.engine.gate import verify_claim_consistency, verify_documents
from app.engine.view import build_claim_view
from app.extraction.eval_extractor import EvalExtractor
from app.graph import run_claim
from app.schemas.claim import ClaimInput, DocumentInput
from app.schemas.enums import DocumentProblemType, TraceStatus
from app.schemas.extraction import ExtractedDocument

ex = EvalExtractor()


async def _classify(claim: ClaimInput):
    return [await ex.classify(d) for d in claim.documents]


async def test_presence_fail(cases, make_claim, policy) -> None:
    claim = make_claim(cases["TC001"])
    g = verify_documents(claim, await _classify(claim), policy)
    assert not g.passed
    assert g.problem.problem_type == DocumentProblemType.DOCUMENT_PRESENCE
    assert "hospital bill" in g.problem.message.lower()
    assert "prescription" in g.problem.message.lower()


async def test_readability_fail(cases, make_claim, policy) -> None:
    claim = make_claim(cases["TC002"])
    g = verify_documents(claim, await _classify(claim), policy)
    assert not g.passed
    assert g.problem.problem_type == DocumentProblemType.DOCUMENT_READABILITY
    assert "blurry_bill.jpg" in g.problem.message


async def test_identity_fail(cases, make_claim, policy) -> None:
    claim = make_claim(cases["TC003"])
    g = verify_documents(claim, await _classify(claim), policy)
    assert not g.passed
    assert g.problem.problem_type == DocumentProblemType.PATIENT_IDENTITY_MISMATCH
    assert "Rajesh Kumar" in g.problem.message
    assert "Arjun Mehta" in g.problem.message


async def test_gate_pass(cases, make_claim, policy) -> None:
    claim = make_claim(cases["TC004"])
    g = verify_documents(claim, await _classify(claim), policy)
    assert g.passed
    assert g.problem is None


async def test_patient_not_covered(policy) -> None:
    # the document's patient is on NObody on the policy → "not a covered member", and the
    # message still names the member the claim was filed for so the mismatch is explicit.
    claim = ClaimInput(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=[
            DocumentInput(file_id="a", actual_type="PRESCRIPTION", patient_name_on_doc="Stranger Person"),
            DocumentInput(file_id="b", actual_type="HOSPITAL_BILL", patient_name_on_doc="Stranger Person"),
        ],
    )
    g = verify_documents(claim, await _classify(claim), policy)
    assert not g.passed
    assert g.problem.problem_type == DocumentProblemType.PATIENT_IDENTITY_MISMATCH
    assert "Rajesh Kumar" in g.problem.message  # the member the claim was filed for
    assert "Stranger Person" in g.problem.message  # the patient on the documents
    assert "not Rajesh Kumar or a covered dependent" in g.problem.message


async def test_patient_is_wrong_member_on_claim(policy) -> None:
    # the document's patient (Vikram Joshi, EMP005) IS on the policy, just not the member this
    # claim was filed for (Ravi Menon, EMP008) → surface a claim/document mismatch and tell the
    # member to fix the member detail, NOT "submit documents for a covered member".
    claim = ClaimInput(
        member_id="EMP008",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=[
            DocumentInput(file_id="a", actual_type="PRESCRIPTION", patient_name_on_doc="Vikram Joshi"),
            DocumentInput(file_id="b", actual_type="HOSPITAL_BILL", patient_name_on_doc="Vikram Joshi"),
        ],
    )
    g = verify_documents(claim, await _classify(claim), policy)
    assert not g.passed
    assert g.problem.problem_type == DocumentProblemType.PATIENT_IDENTITY_MISMATCH
    assert "Ravi Menon" in g.problem.message  # the member entered on the form
    assert "Vikram Joshi" in g.problem.message  # the patient on the documents
    assert "doesn't match your documents" in g.problem.message
    assert "covered member" not in g.problem.message  # no longer blames the document


async def test_optional_unreadable_not_gating(policy) -> None:
    claim = ClaimInput(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=[
            DocumentInput(file_id="a", actual_type="PRESCRIPTION", patient_name_on_doc="Rajesh Kumar"),
            DocumentInput(file_id="b", actual_type="HOSPITAL_BILL", patient_name_on_doc="Rajesh Kumar"),
            DocumentInput(file_id="c", actual_type="LAB_REPORT", quality="UNREADABLE"),
        ],
    )
    g = verify_documents(claim, await _classify(claim), policy)
    assert g.passed


async def test_no_patient_names_skips_identity(policy) -> None:
    claim = ClaimInput(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=[
            DocumentInput(file_id="a", actual_type="PRESCRIPTION"),
            DocumentInput(file_id="b", actual_type="HOSPITAL_BILL"),
        ],
    )
    g = verify_documents(claim, await _classify(claim), policy)
    assert g.passed


# ── Stage 1.5: claim ↔ document consistency ─────────────────────────────────────
def _cc_claim(*, claimed: int = 1500, date: str = "2024-11-01", hospital: str | None = None) -> ClaimInput:
    return ClaimInput(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date=date,
        claimed_amount=claimed,
        hospital_name=hospital,
        documents=[DocumentInput(file_id="bill", file_name="bill.jpg", actual_type="HOSPITAL_BILL")],
    )


def _bill(
    *, total: int | None = None, date: str | None = None, hospital: str | None = None
) -> ExtractedDocument:
    return ExtractedDocument(file_id="bill", doc_type="HOSPITAL_BILL", total=total, date=date, hospital_name=hospital)


def _consistency(claim: ClaimInput, ex_docs: list[ExtractedDocument]):
    return verify_claim_consistency(claim, ex_docs, build_claim_view(ex_docs))


def test_consistency_amount_mismatch() -> None:
    g = _consistency(_cc_claim(claimed=1500), [_bill(total=2000, date="2024-11-01")])
    assert not g.passed
    assert g.problem.problem_type == DocumentProblemType.CLAIM_DOCUMENT_MISMATCH
    assert "₹1,500" in g.problem.message and "₹2,000" in g.problem.message
    assert "bill total" in g.problem.message.lower()
    assert g.trace[0].step == "gate.consistency" and g.trace[0].status == TraceStatus.FAIL


def test_consistency_date_mismatch() -> None:
    g = _consistency(_cc_claim(claimed=1500, date="2024-11-01"), [_bill(total=1500, date="2024-12-25")])
    assert not g.passed
    assert "treatment date" in g.problem.message.lower()
    assert "2024-12-25" in g.problem.message


def test_consistency_hospital_mismatch() -> None:
    g = _consistency(_cc_claim(hospital="Apollo Hospital"), [_bill(total=1500, hospital="Fortis Healthcare")])
    assert not g.passed
    assert "hospital" in g.problem.message.lower()
    assert "Fortis Healthcare" in g.problem.message


def test_consistency_multiple_mismatches_are_joined() -> None:
    g = _consistency(
        _cc_claim(claimed=1500, date="2024-11-01", hospital="Apollo Hospital"),
        [_bill(total=2000, date="2024-12-25", hospital="Fortis Healthcare")],
    )
    assert not g.passed
    assert "; and " in g.problem.message  # three clauses joined into one readable sentence
    assert g.problem.file_ids == ["bill"]


def test_consistency_all_fields_match_passes() -> None:
    g = _consistency(
        _cc_claim(claimed=1500, date="2024-11-01", hospital="Apollo Hospital"),
        [_bill(total=1500, date="2024-11-01", hospital="Apollo Hospital")],
    )
    assert g.passed and g.problem is None
    assert g.trace[0].status == TraceStatus.PASS


def test_consistency_alternate_date_format_still_matches() -> None:
    # the bill prints 01/11/2024 — the same calendar day as the ISO treatment_date, no mismatch
    g = _consistency(_cc_claim(date="2024-11-01"), [_bill(total=1500, date="01/11/2024")])
    assert g.passed


def test_consistency_unparseable_date_is_not_flagged() -> None:
    # an unparseable document date is treated as unknown, never a mismatch (no false positive)
    g = _consistency(_cc_claim(date="2024-11-01"), [_bill(total=1500, date="sometime last week")])
    assert g.passed


def test_consistency_no_comparable_fields_skips() -> None:
    g = _consistency(_cc_claim(), [_bill()])  # no total, date or hospital on the document
    assert g.passed
    assert g.trace[0].status == TraceStatus.SKIP


def test_consistency_without_a_view_still_checks_date() -> None:
    # a missing view means no bill_total to compare, but per-document dates are still cross-checked
    g = verify_claim_consistency(_cc_claim(date="2024-11-01"), [_bill(date="2024-12-25")], None)
    assert not g.passed
    assert "treatment date" in g.problem.message.lower()


def test_consistency_unknown_doc_type_reads_as_document() -> None:
    # an extracted doc whose type couldn't be determined is labelled "document", never "unknown"
    ex = [ExtractedDocument(file_id="bill", doc_type="UNKNOWN", date="2024-12-25")]
    g = verify_claim_consistency(_cc_claim(date="2024-11-01"), ex, build_claim_view(ex))
    assert not g.passed
    assert "your document (" in g.problem.message
    assert "unknown" not in g.problem.message.lower()


async def test_graph_blocks_on_claim_document_mismatch() -> None:
    # end-to-end: the claim passes the gate but the bill total contradicts the claimed amount,
    # so the consistency node routes to the member-action blocker (decision withheld).
    claim = ClaimInput(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        mode="eval",
        documents=[
            DocumentInput(file_id="p", actual_type="PRESCRIPTION", content={"patient_name": "Rajesh Kumar"}),
            DocumentInput(
                file_id="b",
                actual_type="HOSPITAL_BILL",
                content={"patient_name": "Rajesh Kumar", "total": 9999, "date": "2024-11-01"},
            ),
        ],
    )
    result = await run_claim(claim, claim_id="MISMATCH1")
    assert result.decision.decision is None
    assert result.decision.document_problem is not None
    assert result.decision.document_problem.problem_type == DocumentProblemType.CLAIM_DOCUMENT_MISMATCH
    assert "gate.consistency" in [t.step for t in result.trace]


async def test_diagnostic_report_satisfies_required_lab_report(policy) -> None:
    # LAB_REPORT and DIAGNOSTIC_REPORT are interchangeable for the presence check.
    claim = ClaimInput(
        member_id="EMP007",
        policy_id="PLUM_GHI_2024",
        claim_category="DIAGNOSTIC",
        treatment_date="2024-11-02",
        claimed_amount=15000,
        documents=[
            DocumentInput(file_id="a", actual_type="PRESCRIPTION"),
            DocumentInput(file_id="b", actual_type="DIAGNOSTIC_REPORT"),
            DocumentInput(file_id="c", actual_type="HOSPITAL_BILL"),
        ],
    )
    g = verify_documents(claim, await _classify(claim), policy)
    assert g.passed

"""Stage 1 — Document Verification Gate. Runs BEFORE any adjudication.

Three deterministic sub-checks in order (presence → readability → patient-identity).
The first failure stops the claim with ``decision=None`` and a SPECIFIC, actionable
member message. Covers TC001 (wrong/missing doc), TC002 (unreadable), TC003 (different
patients). The LLM is used only to normalize names; pass/fail is deterministic.

``verify_claim_consistency`` is a Stage-1.5 check that runs AFTER extraction (it needs the
extracted amounts/dates): it cross-checks what the member DECLARED on the claim against
what the documents actually say, so a mismatch is surfaced as the same actionable member
message as the other gate stops.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from app.core.clock import now_iso
from app.core.money import fmt_inr
from app.engine.names import cluster_names, name_matches
from app.engine.results import GateResult
from app.engine.view import ClaimView
from app.policy.repository import PolicyRepository
from app.schemas.claim import ClaimInput
from app.schemas.decision import DocumentProblem
from app.schemas.enums import DocumentProblemType, DocumentQuality, DocumentType, TraceStatus
from app.schemas.extraction import ExtractedDocument
from app.schemas.trace import TraceEvent

# Document-type equivalence: a required type may be satisfied by a near-synonym.
# (LAB_REPORT and DIAGNOSTIC_REPORT are interchangeable in practice.)
_TYPE_ALIASES: dict[str, set[str]] = {
    "LAB_REPORT": {"LAB_REPORT", "DIAGNOSTIC_REPORT"},
    "DIAGNOSTIC_REPORT": {"DIAGNOSTIC_REPORT", "LAB_REPORT"},
}


def _present(required: str, uploaded: list[str]) -> bool:
    accepted = _TYPE_ALIASES.get(required, {required})
    return any(t in accepted for t in uploaded)


def _readable(doc_type: str) -> str:
    return doc_type.replace("_", " ").lower()


def _doc_label(doc_type: str) -> str:
    """Member-facing label for a document type — never the literal 'unknown'."""
    return "document" if doc_type == DocumentType.UNKNOWN.value else _readable(doc_type)


def _readable_list(types: list[str]) -> str:
    items = [f"a {_readable(t)}" for t in types]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _ev(step: str, status: TraceStatus, detail: str, policy_ref: str | None = None, **data: object) -> TraceEvent:
    return TraceEvent(
        step=step,
        status=status,
        detail=detail,
        policy_ref=policy_ref,
        data=dict(data),
        ts=now_iso(),
    )


def verify_documents(
    claim: ClaimInput,
    classified: list[ExtractedDocument],
    policy: PolicyRepository,
) -> GateResult:
    category = claim.claim_category.value
    name_of = {d.file_id: (d.file_name or d.file_id) for d in claim.documents}
    trace: list[TraceEvent] = []

    reqs = policy.document_requirements(category)
    required = reqs["required"]
    uploaded = [d.doc_type.value for d in classified]

    # ── 1a. Required-document presence ────────────────────────────────────────
    missing = [t for t in required if not _present(t, uploaded)]
    if missing:
        counts = Counter(uploaded)
        uploaded_summary = ", ".join(f"{n}× {_readable(t)}" for t, n in counts.items()) or "no documents"
        message = (
            f"You uploaded {uploaded_summary}. A {category} claim requires "
            f"{_readable_list(required)}. Please upload: {_readable_list(missing)}."
        )
        trace.append(
            _ev(
                "gate.presence",
                TraceStatus.FAIL,
                f"Missing required document(s): {', '.join(missing)}.",
                policy_ref=f"document_requirements.{category}.required",
                required=required,
                uploaded=uploaded,
                missing=missing,
            )
        )
        return GateResult(
            passed=False,
            problem=DocumentProblem(
                problem_type=DocumentProblemType.DOCUMENT_PRESENCE,
                message=message,
                file_ids=[d.file_id for d in claim.documents],
                required_action=f"Upload {_readable_list(missing)} and resubmit the claim.",
            ),
            trace=trace,
        )
    trace.append(
        _ev(
            "gate.presence",
            TraceStatus.PASS,
            f"All required documents present: {', '.join(required)}.",
            policy_ref=f"document_requirements.{category}.required",
            required=required,
            uploaded=uploaded,
        )
    )

    # ── 1b. Readability (only required docs gate; optional unreadable docs noted) ─
    unreadable_required = [
        d for d in classified if d.quality == DocumentQuality.UNREADABLE and d.doc_type.value in required
    ]
    if unreadable_required:
        d = unreadable_required[0]
        fname = name_of.get(d.file_id, d.file_id)
        message = (
            f"Your {_readable(d.doc_type.value)} ({fname}) could not be read — the image is "
            f"too blurry or unclear to process. Please re-upload a clear photo of that document. "
            f"Your other documents were accepted."
        )
        trace.append(
            _ev(
                "gate.readability",
                TraceStatus.FAIL,
                f"Required document unreadable: {fname} ({d.doc_type.value}).",
                file_id=d.file_id,
                doc_type=d.doc_type.value,
            )
        )
        return GateResult(
            passed=False,
            problem=DocumentProblem(
                problem_type=DocumentProblemType.DOCUMENT_READABILITY,
                message=message,
                file_ids=[d.file_id],
                required_action=f"Re-upload a clear, well-lit photo of your {_readable(d.doc_type.value)} ({fname}).",
            ),
            trace=trace,
        )
    trace.append(_ev("gate.readability", TraceStatus.PASS, "All required documents are readable."))

    # ── 1c. Patient-identity consistency ──────────────────────────────────────
    named = [(d.file_id, d.doc_type.value, d.patient_name) for d in classified if d.patient_name]
    if named:
        names = [n[2] for n in named if n[2]]
        clusters = cluster_names(names)
        if len(clusters) > 1:
            rep_a, rep_b = clusters[0][0], clusters[1][0]
            doc_a = next(n for n in named if n[2] == rep_a)
            doc_b = next(n for n in named if n[2] == rep_b)
            fa, fb = name_of.get(doc_a[0], doc_a[0]), name_of.get(doc_b[0], doc_b[0])
            message = (
                f"The {_readable(doc_a[1])} ({fa}) is for '{doc_a[2]}' but the "
                f"{_readable(doc_b[1])} ({fb}) is for '{doc_b[2]}'. All documents in a single "
                f"claim must belong to the same patient."
            )
            trace.append(
                _ev(
                    "gate.patient_identity",
                    TraceStatus.FAIL,
                    f"Documents name different patients: '{doc_a[2]}' vs '{doc_b[2]}'.",
                    names_found=[{"file": name_of.get(n[0], n[0]), "name": n[2]} for n in named],
                )
            )
            return GateResult(
                passed=False,
                problem=DocumentProblem(
                    problem_type=DocumentProblemType.PATIENT_IDENTITY_MISMATCH,
                    message=message,
                    file_ids=[doc_a[0], doc_b[0]],
                    required_action="Ensure every document is for the same patient, then resubmit.",
                ),
                trace=trace,
            )

        # single patient across docs — verify it is the member or a covered dependent
        covered = policy.covered_names_for(claim.member_id)
        patient = clusters[0][0]
        if covered and not any(name_matches(patient, cn) for cn in covered):
            selected = policy.member(claim.member_id)
            selected_name = selected["name"] if selected else claim.member_id
            # Is the document's patient on the policy at all? If so, this isn't an "uncovered
            # person" — it's that the CLAIM FORM names a different member than the DOCUMENTS,
            # so we tell them to fix the member detail rather than blaming the document.
            on_roster = any(name_matches(patient, rn) for rn in policy.roster_names())
            if on_roster:
                message = (
                    f"This claim was filed for {selected_name} ({claim.member_id}), but the uploaded "
                    f"documents are for '{patient}'. The member you entered doesn't match your documents. "
                    f"Please correct the member on the claim to match your documents, or upload documents "
                    f"for {selected_name}."
                )
                action = (
                    f"Set the member to the person on your documents ('{patient}'), or upload documents "
                    f"for {selected_name}, then resubmit."
                )
                detail = (
                    f"Claim filed for '{selected_name}' ({claim.member_id}) but documents are for "
                    f"'{patient}' (a different member on the policy) — claim/document mismatch."
                )
            else:
                message = (
                    f"This claim was filed for {selected_name} ({claim.member_id}), but the uploaded "
                    f"documents are for '{patient}', who is not {selected_name} or a covered dependent on "
                    f"policy {claim.policy_id}. Please upload documents for {selected_name} or a covered "
                    f"dependent."
                )
                action = f"Upload documents for {selected_name} or a covered dependent, then resubmit."
                detail = f"Patient '{patient}' is not {selected_name} or a covered dependent."
            trace.append(
                _ev(
                    "gate.patient_identity",
                    TraceStatus.FAIL,
                    detail,
                    patient=patient,
                    member=claim.member_id,
                    member_name=selected_name,
                    on_roster=on_roster,
                    covered=covered,
                )
            )
            return GateResult(
                passed=False,
                problem=DocumentProblem(
                    problem_type=DocumentProblemType.PATIENT_IDENTITY_MISMATCH,
                    message=message,
                    file_ids=[n[0] for n in named],
                    required_action=action,
                ),
                trace=trace,
            )
        trace.append(
            _ev(
                "gate.patient_identity",
                TraceStatus.PASS,
                f"All documents belong to the same covered patient: '{patient}'.",
                patient=patient,
            )
        )
    else:
        trace.append(
            _ev(
                "gate.patient_identity",
                TraceStatus.SKIP,
                "No patient names available to cross-check.",
            )
        )

    return GateResult(passed=True, trace=trace)


# ── Stage 1.5 — claim ↔ document consistency (post-extraction) ──────────────────
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y")


def _norm_date(s: str) -> str | None:
    """Normalise a date string to ISO ``YYYY-MM-DD``, or ``None`` if it can't be parsed.
    Unparseable dates are treated as 'unknown' (never a mismatch) to avoid false flags."""
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _dates_differ(declared: str, found: str) -> bool:
    """True only when BOTH dates parse and refer to different calendar days."""
    a, b = _norm_date(declared), _norm_date(found)
    return a is not None and b is not None and a != b


def _join_clauses(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return "; ".join(items[:-1]) + "; and " + items[-1]


def verify_claim_consistency(
    claim: ClaimInput,
    extracted: list[ExtractedDocument],
    view: ClaimView | None,
) -> GateResult:
    """Cross-check the member's DECLARED claim details against what the documents actually
    say. Each field is compared only when BOTH the declared value and the extracted value
    are present (None-safe skip), so it never flags on missing data — only on genuine
    contradictions. A mismatch stops the claim with the SAME actionable member message as
    the other gate checks, so the member can correct the claim or upload matching documents.
    """
    name_of = {d.file_id: (d.file_name or d.file_id) for d in claim.documents}
    mismatches: list[str] = []
    file_ids: list[str] = []

    # ── amount: declared claimed_amount vs the bill total found on the documents ──
    bill_total = view.bill_total if view else None
    if bill_total is not None and bill_total != claim.claimed_amount:
        mismatches.append(
            f"the claim amount you entered ({fmt_inr(claim.claimed_amount)}) doesn't match your "
            f"bill total ({fmt_inr(bill_total)})"
        )
        file_ids.extend(d.file_id for d in extracted if d.total is not None)

    # ── treatment date: declared vs the date printed on a document ──
    for d in extracted:
        if d.date and _dates_differ(claim.treatment_date, d.date):
            fname = name_of.get(d.file_id, d.file_id)
            mismatches.append(
                f"the treatment date you entered ({claim.treatment_date}) doesn't match the date "
                f"on your {_doc_label(d.doc_type.value)} ({fname}: {d.date})"
            )
            file_ids.append(d.file_id)

    # ── hospital / provider: declared vs the name on a document ──
    if claim.hospital_name:
        for d in extracted:
            if d.hospital_name and not name_matches(claim.hospital_name, d.hospital_name):
                fname = name_of.get(d.file_id, d.file_id)
                mismatches.append(
                    f"the hospital you entered ('{claim.hospital_name}') doesn't match the provider "
                    f"on your {_doc_label(d.doc_type.value)} ({fname}: '{d.hospital_name}')"
                )
                file_ids.append(d.file_id)

    if mismatches:
        message = (
            "Some details you entered don't match your documents — "
            + _join_clauses(mismatches)
            + ". Please correct the claim so it matches your documents, or upload the documents "
            "that match what you entered, then resubmit."
        )
        return GateResult(
            passed=False,
            problem=DocumentProblem(
                problem_type=DocumentProblemType.CLAIM_DOCUMENT_MISMATCH,
                message=message,
                file_ids=sorted(set(file_ids)) or [d.file_id for d in claim.documents],
                required_action=(
                    "Correct the highlighted detail(s) to match your documents, or upload the "
                    "documents that match what you entered, then resubmit."
                ),
            ),
            trace=[
                _ev(
                    "gate.consistency",
                    TraceStatus.FAIL,
                    f"Claim details don't match the documents: {'; '.join(mismatches)}.",
                    mismatches=mismatches,
                )
            ],
        )

    # nothing contradicted — but did we actually have anything to compare?
    compared = (
        bill_total is not None
        or any(d.date for d in extracted)
        or bool(claim.hospital_name and any(d.hospital_name for d in extracted))
    )
    if compared:
        return GateResult(
            passed=True,
            trace=[_ev("gate.consistency", TraceStatus.PASS, "The claim details match the uploaded documents.")],
        )
    return GateResult(
        passed=True,
        trace=[_ev("gate.consistency", TraceStatus.SKIP, "No comparable claim/document fields to cross-check.")],
    )

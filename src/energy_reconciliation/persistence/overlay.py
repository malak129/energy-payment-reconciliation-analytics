"""Replay append-only operator effects over one Phase 3 base, never over summed snapshots."""

from collections import Counter, defaultdict
from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictInt

from energy_reconciliation.ingestion.csv_dataset import ensure
from energy_reconciliation.models import records as m
from energy_reconciliation.reconciliation.engine import normalize
from energy_reconciliation.reconciliation.results import (
    AdjustmentEffect,
    ExceptionItem,
    MatchEvidence,
    ReconciliationResult,
)
from energy_reconciliation.utilities.serialization import fingerprint, stable_id


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invoice_id: m.Identifier
    amount_cents: m.Cents


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: m.Identifier
    dataset_id: m.Identifier
    case_id: m.Identifier | None = None
    sequence: StrictInt
    action: Literal["allocate", "reverse", "correction", "refund", "chargeback", "defer"]
    effective_on: date
    created_at: AwareDatetime
    actor: str
    reason: str
    note: str = ""
    payload: dict
    reverses_decision_id: m.Identifier | None = None
    origin_run_id: m.Identifier | None = None


def replay(base: ReconciliationResult, data, operations: list[Operation]) -> ReconciliationResult:
    operations = sorted(
        (
            o
            for o in operations
            if o.action != "defer"
            and o.effective_on <= base.run.as_of
            and o.created_at <= base.run.known_at
        ),
        key=lambda o: o.sequence,
    )
    if not operations:
        return base
    identity = [o.model_dump(mode="json", exclude={"origin_run_id"}) for o in operations]
    run_id = stable_id("run", [base.run.id, "manual-overlay-1", identity])
    payments = {p.payment_id: p for p in base.payments}
    original_accounts = {p.payment_id: p.validated_account_id for p in base.payments}
    invoices = {i.invoice_id: i for i in base.invoices}
    originals = {i.id: i for i in data.rows("invoices")}
    payment_originals = {p.id: p for p in data.rows("payments")}
    allocations, releases, evidence, effects = (
        list(base.allocations),
        list(base.releases),
        list(base.evidence),
        list(base.adjustments),
    )
    alloc_map = {a.id: a for a in allocations}
    released = defaultdict(int)
    for release in releases:
        released[release.allocation_id] += release.amount_cents
    decision_allocations, applied_ops, reversed_ops = {}, {}, set()
    fully_reversed = {op.reverses_decision_id for op in operations if op.action == "reverse"}
    undo_dates = {
        op.reverses_decision_id: op.effective_on for op in operations if op.action == "reverse"
    }
    neutralized = set()
    refund_total, chargeback_total = (
        base.controls["refund_cents"],
        base.controls["chargeback_cents"],
    )

    def release_allocation(allocation, amount, operation, reversal_id=None, affect_balance=True):
        ensure(
            0 < amount <= allocation.amount_cents - released[allocation.id],
            "Excess allocation release",
        )
        key = stable_id("release", [operation.id, allocation.id])
        authority = {"reversal_id": reversal_id} if reversal_id else {"decision_id": operation.id}
        releases.append(
            m.AllocationRelease(
                id=key,
                synthetic=True,
                allocation_id=allocation.id,
                amount_cents=amount,
                effective_on=operation.effective_on,
                created_at=operation.created_at,
                reason=operation.reason,
                **authority,
            )
        )
        released[allocation.id] += amount
        if not affect_balance:
            return
        p, i = payments[allocation.payment_id], invoices[allocation.invoice_id]
        payments[p.payment_id] = p.model_copy(
            update={
                "allocated_cents": p.allocated_cents - amount,
                "unapplied_cents": p.unapplied_cents + amount,
            }
        )
        invoices[i.invoice_id] = i.model_copy(
            update={
                "allocated_cents": i.allocated_cents - amount,
                "outstanding_cents": i.outstanding_cents + amount,
            }
        )

    def correction(invoice_id, amount, op, affect_balance=True):
        ensure(type(amount) is int and amount != 0, "Correction needs nonzero integer cents")
        ensure(invoice_id in invoices, "Invoice not eligible at this cutoff")
        invoice = invoices[invoice_id]
        if affect_balance:
            ensure(
                invoice.adjusted_face_cents + amount >= invoice.allocated_cents,
                "Correction needs explicit releases or would create negative debt",
            )
            invoices[invoice_id] = invoice.model_copy(
                update={
                    "correction_cents": invoice.correction_cents + amount,
                    "adjusted_face_cents": invoice.adjusted_face_cents + amount,
                    "outstanding_cents": invoice.outstanding_cents + amount,
                }
            )
        effects.append(
            AdjustmentEffect(
                id=stable_id("effect", op.id),
                synthetic=True,
                source_record_id=stable_id("correction", op.id),
                kind="correction",
                signed_cash_cents=0,
                signed_receivable_cents=amount,
                released_cents=0,
                reason=op.reason,
            )
        )

    for op in operations:
        ensure(op.dataset_id == base.run.dataset_id, "Cross-dataset decision")
        if op.action == "allocate":
            payment_id = op.payload["payment_id"]
            ensure(payment_id in payments, "Payment not eligible at this cutoff")
            targets = [Target.model_validate(t) for t in op.payload["targets"]]
            ensure(
                targets and len({t.invoice_id for t in targets}) == len(targets),
                "Duplicate/empty manual targets",
            )
            ensure(all(t.invoice_id in invoices for t in targets), "Unknown invoice target")
            accounts = {originals[t.invoice_id].account_id for t in targets}
            ensure(len(accounts) == 1, "Manual targets must belong to one account")
            p = payments[payment_id]
            cancelled = op.id in fully_reversed and (
                p.validated_account_id is not None
                and p.validated_account_id not in accounts
                or sum(t.amount_cents for t in targets) > p.unapplied_cents
                or any(t.amount_cents > invoices[t.invoice_id].outstanding_cents for t in targets)
            )
            if cancelled:
                ensure(
                    undo_dates[op.id] == op.effective_on,
                    "Cannot neutralize a reversed decision across effective dates; "
                    "historical balances would be inconsistent",
                )
                neutralized.add(op.id)
            ensure(
                cancelled or p.validated_account_id is None or p.validated_account_id in accounts,
                "Manual target conflicts with already validated account",
            )
            ensure(
                cancelled or sum(t.amount_cents for t in targets) <= p.unapplied_cents,
                "Insufficient available cash",
            )
            made = []
            for target in targets:
                invoice = invoices[target.invoice_id]
                ensure(
                    cancelled or target.amount_cents <= invoice.outstanding_cents,
                    "Invoice over-allocation",
                )
                allocation = m.Allocation(
                    id=stable_id("allocation", [op.id, target.invoice_id]),
                    synthetic=True,
                    payment_id=payment_id,
                    invoice_id=target.invoice_id,
                    decision_id=op.id,
                    run_id=op.origin_run_id or run_id,
                    amount_cents=target.amount_cents,
                    effective_on=op.effective_on,
                    created_at=op.created_at,
                    reason_code="manual_approved",
                    confidence="manual",
                )
                allocations.append(allocation)
                alloc_map[allocation.id] = allocation
                made.append(allocation)
                p = payments[payment_id]
                if not cancelled:
                    payments[payment_id] = p.model_copy(
                        update={
                            "allocated_cents": p.allocated_cents + target.amount_cents,
                            "unapplied_cents": p.unapplied_cents - target.amount_cents,
                            "validated_account_id": next(iter(accounts)),
                        }
                    )
                if not cancelled:
                    invoices[target.invoice_id] = invoice.model_copy(
                        update={
                            "allocated_cents": invoice.allocated_cents + target.amount_cents,
                            "outstanding_cents": invoice.outstanding_cents - target.amount_cents,
                        }
                    )
                original = originals[target.invoice_id]
                evidence.append(
                    MatchEvidence(
                        id=stable_id("evidence", allocation.id),
                        synthetic=True,
                        allocation_id=allocation.id,
                        rule_id="MANUAL-1",
                        reason_code="manual_approved",
                        payment_reference=payment_originals[payment_id].reference,
                        invoice_reference=original.reference,
                        normalized_invoice_reference=normalize(original.reference),
                        account_evidence="explicit_manual_decision",
                        explanation=f"{op.actor}: {op.reason}; decision {op.id}. {op.note}",
                    )
                )
            decision_allocations[op.id] = made
        elif op.action == "correction":
            invoice = invoices[op.payload["invoice_id"]]
            cancelled = (
                op.id in fully_reversed
                and invoice.adjusted_face_cents + op.payload["amount_cents"]
                < invoice.allocated_cents
            )
            if cancelled:
                ensure(
                    undo_dates[op.id] == op.effective_on,
                    "Cannot neutralize a reversed correction across effective dates; "
                    "historical balances would be inconsistent",
                )
                neutralized.add(op.id)
            correction(op.payload["invoice_id"], op.payload["amount_cents"], op, not cancelled)
        elif op.action == "reverse":
            ensure(
                op.reverses_decision_id in applied_ops
                and op.reverses_decision_id not in reversed_ops,
                "Decision is missing, already reversed or outside this cutoff",
            )
            original = applied_ops[op.reverses_decision_id]
            if original.action == "allocate":
                for allocation in decision_allocations[original.id]:
                    ensure(
                        released[allocation.id] == 0,
                        "Decision has later releases; reverse those dependencies first",
                    )
                    release_allocation(
                        allocation,
                        allocation.amount_cents,
                        op,
                        affect_balance=original.id not in neutralized,
                    )
            elif original.action == "correction":
                correction(
                    original.payload["invoice_id"],
                    -original.payload["amount_cents"],
                    op,
                    original.id not in neutralized,
                )
            else:
                raise ValueError(
                    "Only manual allocations and corrections can be undone; bank cash is immutable"
                )
            reversed_ops.add(original.id)
        elif op.action in ("refund", "chargeback"):
            event = m.Reversal.model_validate(op.payload["event"])
            ensure(
                event.payment_id in payments and event.booked_on == op.effective_on,
                "Invalid local outflow date/parent",
            )
            p = payments[event.payment_id]
            ensure(
                event.amount_cents <= p.received_cents - p.reversed_cents,
                "Outflow exceeds effective cash",
            )
            needed = max(0, event.amount_cents - p.unapplied_cents)
            active = [
                a
                for a in allocations
                if a.payment_id == event.payment_id and a.amount_cents > released[a.id]
            ]
            plan = [dict(item) for item in op.payload.get("releases", [])]
            for item in plan:
                if "signature" in item:
                    matches = [
                        a
                        for a in active
                        if {
                            k: v
                            for k, v in a.model_dump(mode="json").items()
                            if k
                            in (
                                "payment_id",
                                "invoice_id",
                                "decision_id",
                                "amount_cents",
                                "effective_on",
                            )
                        }
                        == item["signature"]
                    ]
                    ensure(
                        len(matches) == 1,
                        "Explicit release basis changed; review before activating new snapshot",
                    )
                    item["allocation_id"] = matches[0].id
            if not plan:
                ensure(
                    not needed
                    or len(active) == 1
                    or needed == sum(a.amount_cents - released[a.id] for a in active),
                    "Ambiguous partial outflow: supply an explicit release plan",
                )
                remaining = needed
                for allocation in active:
                    amount = min(remaining, allocation.amount_cents - released[allocation.id])
                    if amount:
                        plan.append({"allocation_id": allocation.id, "amount_cents": amount})
                        remaining -= amount
            ensure(
                len({item["allocation_id"] for item in plan}) == len(plan)
                and sum(item["amount_cents"] for item in plan) == needed,
                "Release plan must exactly cover outflow beyond unapplied cash",
            )
            for item in plan:
                ensure(
                    item["allocation_id"] in alloc_map and type(item["amount_cents"]) is int,
                    "Invalid release plan",
                )
                allocation = alloc_map[item["allocation_id"]]
                ensure(
                    allocation.payment_id == event.payment_id, "Release belongs to another payment"
                )
                release_allocation(allocation, item["amount_cents"], op, event.id)
            p = payments[event.payment_id]
            payments[event.payment_id] = p.model_copy(
                update={
                    "reversed_cents": p.reversed_cents + event.amount_cents,
                    "unapplied_cents": p.unapplied_cents - event.amount_cents,
                }
            )
            if op.action == "refund":
                refund_total += event.amount_cents
            else:
                chargeback_total += event.amount_cents
            effects.append(
                AdjustmentEffect(
                    id=stable_id("effect", op.id),
                    synthetic=True,
                    source_record_id=event.id,
                    kind=op.action,
                    signed_cash_cents=-event.amount_cents,
                    signed_receivable_cents=0,
                    released_cents=needed,
                    reason=op.reason,
                )
            )
        applied_ops[op.id] = op
        for p in payments.values():
            ensure(
                0 <= p.allocated_cents <= p.received_cents - p.reversed_cents
                and p.unapplied_cents == p.received_cents - p.reversed_cents - p.allocated_cents,
                "Payment conservation failed during manual replay",
            )
        for i in invoices.values():
            ensure(
                0 <= i.allocated_cents <= i.adjusted_face_cents
                and i.outstanding_cents == i.adjusted_face_cents - i.allocated_cents,
                "Invoice conservation failed during manual replay",
            )

    manual_payments = {
        a.payment_id for a in allocations if a.decision_id and released[a.id] < a.amount_cents
    }
    for key, p in payments.items():
        if key not in manual_payments:
            original_account = original_accounts[key]
            p = p.model_copy(update={"validated_account_id": original_account})
        available = p.received_cents - p.reversed_cents
        status = (
            "reversed"
            if available == 0
            else "unapplied"
            if p.allocated_cents == 0
            else "partial"
            if p.unapplied_cents
            else "allocated"
        )
        classification = (
            "reversed"
            if available == 0
            else "manually_matched"
            if key in manual_payments
            else "overpaid"
            if p.unapplied_cents and p.validated_account_id
            else p.classification
        )
        payments[key] = p.model_copy(
            update={"allocation_status": status, "classification": classification}
        )
    for key, i in invoices.items():
        status = (
            "cancelled"
            if i.adjusted_face_cents == 0
            else "settled"
            if i.outstanding_cents == 0
            else "partial"
            if i.allocated_cents
            else "open"
        )
        invoices[key] = i.model_copy(
            update={
                "status": status,
                "adjusted": i.correction_cents != 0,
                "overdue": i.outstanding_cents > 0 and originals[key].due_on < base.run.as_of,
            }
        )
    exceptions = [
        e.model_copy(update={"amount_cents": payments[e.subject_id].unapplied_cents})
        for e in base.exceptions
        if e.subject_type == "payment"
        and e.requires_manual_review
        and payments[e.subject_id].unapplied_cents > 0
    ]
    for i in invoices.values():
        if i.outstanding_cents:
            exceptions.append(
                ExceptionItem(
                    id=stable_id("exception", [run_id, i.invoice_id]),
                    synthetic=True,
                    subject_type="invoice",
                    subject_id=i.invoice_id,
                    reason_code="outstanding_invoice",
                    amount_cents=i.outstanding_cents,
                    requires_manual_review=False,
                    explanation="Open receivable after explicit operator effects.",
                )
            )
    controls = dict(base.controls)
    controls.update(
        signed_correction_cents=sum(i.correction_cents for i in invoices.values()),
        adjusted_receivables_cents=sum(i.adjusted_face_cents for i in invoices.values()),
        refund_cents=refund_total,
        chargeback_cents=chargeback_total,
        net_cash_cents=sum(p.received_cents - p.reversed_cents for p in payments.values()),
        net_allocated_cents=sum(p.allocated_cents for p in payments.values()),
        unapplied_cents=sum(p.unapplied_cents for p in payments.values()),
        outstanding_cents=sum(i.outstanding_cents for i in invoices.values()),
        identified_credit_cents=sum(
            p.unapplied_cents for p in payments.values() if p.validated_account_id
        ),
        suspense_cents=sum(
            p.unapplied_cents for p in payments.values() if not p.validated_account_id
        ),
        matched_event_count=sum(p.allocated_cents > 0 for p in payments.values()),
        unmatched_event_count=sum(
            p.allocated_cents == 0 and p.unapplied_cents > 0 for p in payments.values()
        ),
        reversed_event_count=sum(p.allocation_status == "reversed" for p in payments.values()),
    )
    controls["cash_control_difference_cents"] = (
        controls["net_cash_cents"] - controls["net_allocated_cents"] - controls["unapplied_cents"]
    )
    controls["receivable_control_difference_cents"] = (
        controls["adjusted_receivables_cents"]
        - controls["net_allocated_cents"]
        - controls["outstanding_cents"]
    )
    ensure(
        controls["cash_control_difference_cents"]
        == controls["receivable_control_difference_cents"]
        == 0,
        "Manual controls failed",
    )
    run = base.run.model_copy(
        update={
            "id": run_id,
            "rules_version": base.rules_version + "+manual-1",
            "input_sha256": fingerprint([base.run.input_sha256, identity]),
            "result_sha256": "0" * 64,
        }
    )
    result = base.model_copy(
        update={
            "run": run,
            "rules_version": run.rules_version,
            "allocations": tuple(sorted(allocations, key=lambda a: a.id)),
            "releases": tuple(sorted(releases, key=lambda a: a.id)),
            "evidence": tuple(sorted(evidence, key=lambda a: a.id)),
            "adjustments": tuple(sorted(effects, key=lambda a: a.id)),
            "payments": tuple(payments[k] for k in sorted(payments)),
            "invoices": tuple(invoices[k] for k in sorted(invoices)),
            "exceptions": tuple(sorted(exceptions, key=lambda e: e.id)),
            "review_queue": tuple(
                sorted((e for e in exceptions if e.requires_manual_review), key=lambda e: e.id)
            ),
            "controls": controls,
            "exception_counts_by_reason": dict(
                sorted(Counter(e.reason_code for e in exceptions).items())
            ),
            "source_counts": {**base.source_counts, "manual_financial_operations": len(operations)},
        }
    )
    checksum = fingerprint(result.model_dump(mode="json", exclude={"run"}))
    return result.model_copy(update={"run": run.model_copy(update={"result_sha256": checksum})})

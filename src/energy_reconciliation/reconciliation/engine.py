"""Pure deterministic snapshot reconciliation. No oracle, generator or database imports."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, time

from energy_reconciliation.ingestion.csv_dataset import (
    InputDataset,
    ensure,
    midnight,
    validate_input,
)
from energy_reconciliation.models.records import Allocation, AllocationRelease, ReconciliationRun
from energy_reconciliation.reconciliation.results import (
    RULES_VERSION,
    AdjustmentEffect,
    Candidate,
    ExceptionItem,
    InvoiceOutcome,
    MatchEvidence,
    PaymentOutcome,
    ReconciliationResult,
    RunOptions,
)
from energy_reconciliation.utilities.serialization import fingerprint, stable_id


def normalize(reference: str) -> str:
    return reference.strip().upper()


class _HoldNeeded(Exception):
    def __init__(self, payment_id: str, invoice_ids: tuple[str, ...]):
        self.payment_id, self.invoice_ids = payment_id, invoice_ids


def reconcile(data: InputDataset, options: RunOptions) -> ReconciliationResult:
    options.aware()
    validate_input(data)
    options = options.model_copy(update={"known_at": options.known_at.astimezone(UTC)})
    holds = {}
    while True:
        try:
            return _Snapshot(data, options, holds).run()
        except _HoldNeeded as hold:
            ensure(hold.payment_id not in holds, "Internal reversal hold did not converge")
            holds[hold.payment_id] = hold.invoice_ids


class _Snapshot:
    def __init__(self, data: InputDataset, options: RunOptions, holds: dict):
        self.data, self.options, self.holds = data, options, holds
        self.invoices = {
            i.id: i
            for i in data.rows("invoices")
            if i.issued_on <= options.evaluation_date and midnight(i.issued_on) <= options.known_at
        }
        self.payments = {
            p.id: p
            for p in data.rows("payments")
            if p.booked_on <= options.evaluation_date
            and data.bank_known_at[p.id] <= options.known_at
        }
        self.reversals = tuple(
            r
            for r in data.rows("refunds_chargebacks")
            if r.booked_on <= options.evaluation_date
            and data.bank_known_at[r.id] <= options.known_at
        )
        decisions = {d.id: d for d in data.rows("manual_decisions")}
        cases = {c.id: c for c in data.rows("review_cases")}
        audited = defaultdict(list)
        for audit in data.rows("audit_events"):
            audited[audit.entity_id].append(audit.occurred_at)
        self.corrections = tuple(
            c
            for c in data.rows("corrections")
            if c.invoice_id in self.invoices
            and c.effective_on <= options.evaluation_date
            and max(
                c.created_at,
                decisions[c.decision_id].created_at,
                cases[decisions[c.decision_id].case_id].created_at,
                *audited[c.id],
            )
            <= options.known_at
        )
        known_corrections = {c.id for c in self.corrections}
        ensure(
            all(
                c.reverses_correction_id is None or c.reverses_correction_id in known_corrections
                for c in self.corrections
            ),
            "Known correction undo lacks a known original",
        )
        config = {
            "evaluation_date": options.evaluation_date.isoformat(),
            "known_at": options.known_at.isoformat(),
            "rules_version": RULES_VERSION,
        }
        input_hash = fingerprint(
            {
                "manifest": data.source_manifest_sha256,
                "files": data.source_hashes,
                "dataset": data.dataset.id,
                "records": {
                    name: [r.model_dump(mode="json") for r in sorted(rows, key=lambda r: r.id)]
                    for name, rows in data.tables.items()
                },
                "availability": {
                    key: value.isoformat() for key, value in data.bank_known_at.items()
                },
            }
        )
        self.run_id = stable_id("run", [input_hash, config])
        self.input_hash, self.config_hash = input_hash, fingerprint(config)
        self.references = {normalize(i.reference): i.id for i in self.invoices.values()}
        self.accounts = defaultdict(list)
        for invoice in self.invoices.values():
            self.accounts[invoice.account_id].append(invoice.id)
        self.face = defaultdict(int)
        self.invoice_alloc = defaultdict(int)
        self.payment_alloc = defaultdict(int)
        self.received = defaultdict(int)
        self.returned = defaultdict(int)
        self.correction_totals = defaultdict(int)
        self.allocated_by_payment = defaultdict(list)
        self.released = defaultdict(int)
        self.validated_accounts = {}
        self.partial_payments = set()
        self.flags = defaultdict(set)
        self.allocations, self.releases, self.evidence, self.effects, self.exceptions = (
            [],
            [],
            [],
            [],
            [],
        )

    def fields(self, kind: str, key: object) -> dict:
        return {"id": stable_id(kind, [self.run_id, key]), "synthetic": True}

    def candidate(self, invoice_id: str) -> Candidate:
        invoice = self.invoices[invoice_id]
        return Candidate(
            invoice_id=invoice_id,
            reference=invoice.reference,
            account_id=invoice.account_id,
            outstanding_cents=self.face[invoice_id] - self.invoice_alloc[invoice_id],
        )

    def exception(
        self,
        subject: str,
        code: str,
        amount: int,
        explanation: str,
        candidates: tuple[str, ...] = (),
        manual: bool = True,
        subject_type: str = "payment",
    ) -> None:
        self.exceptions.append(
            ExceptionItem(
                **self.fields("exception", [subject, code]),
                subject_type=subject_type,
                subject_id=subject,
                reason_code=code,
                amount_cents=amount,
                requires_manual_review=manual,
                explanation=explanation,
                candidates=tuple(self.candidate(key) for key in sorted(set(candidates))),
            )
        )

    def allocate(self, payment, invoice_id: str, amount: int, combined: bool) -> None:
        invoice = self.invoices[invoice_id]
        ensure(
            amount > 0 and amount <= self.face[invoice_id] - self.invoice_alloc[invoice_id],
            "Invoice allocation exceeds open balance",
        )
        ensure(
            amount
            <= self.received[payment.id]
            - self.returned[payment.id]
            - self.payment_alloc[payment.id],
            "Payment allocation exceeds available effective cash",
        )
        reason = "explicit_combined" if combined else "exact_reference"
        allocation = Allocation(
            **self.fields("allocation", [payment.id, invoice_id]),
            payment_id=payment.id,
            invoice_id=invoice_id,
            run_id=self.run_id,
            amount_cents=amount,
            effective_on=payment.booked_on,
            created_at=self.options.known_at,
            reason_code=reason,
            confidence="exact",
        )
        self.allocations.append(allocation)
        self.allocated_by_payment[payment.id].append(allocation)
        self.invoice_alloc[invoice_id] += amount
        self.payment_alloc[payment.id] += amount
        self.validated_accounts[payment.id] = invoice.account_id
        if payment.booked_on > invoice.due_on:
            self.flags[payment.id].add("late")
        if (payment.booked_on.year, payment.booked_on.month) != (
            invoice.issued_on.year,
            invoice.issued_on.month,
        ):
            self.flags[payment.id].add("cross_month")
        self.evidence.append(
            MatchEvidence(
                **self.fields("evidence", allocation.id),
                allocation_id=allocation.id,
                rule_id="REF-COMBINED-1" if combined else "REF-SINGLE-1",
                reason_code=reason,
                payment_reference=payment.reference,
                invoice_reference=invoice.reference,
                normalized_invoice_reference=normalize(invoice.reference),
                account_evidence="matching_account_claim"
                if payment.account_id
                else "unique_reference_account",
                explanation="Exact normalized reference, issued invoice, same account and EUR; "
                + (
                    "explicit reference set equals its total open balance."
                    if combined
                    else "allocation is capped at open debt and available receipt."
                ),
            )
        )

    def match(self, payment) -> None:
        self.received[payment.id] = payment.amount_cents
        if payment.id in self.holds:
            self.exception(
                payment.id,
                "reversal_conflict",
                payment.amount_cents,
                "A linked partial outflow has multiple possible invoice releases. All automatic "
                "applications of this payment are withheld in this snapshot; choose no invoice.",
                self.holds[payment.id],
            )
            return
        tokens = [normalize(t) for t in (payment.reference or "").split("|")]
        exact = [self.references[t] for t in tokens if t in self.references]
        if payment.reference is None or not payment.reference.strip():
            reason = "missing_reference"
        elif any(not t for t in tokens) or len(set(tokens)) != len(tokens):
            reason = "ambiguous"
        elif len(exact) != len(tokens):
            reason = "unknown_reference"
        else:
            account_ids = {self.invoices[key].account_id for key in exact}
            if len(account_ids) != 1 or (
                payment.account_id is not None and account_ids != {payment.account_id}
            ):
                self.exception(
                    payment.id,
                    "account_mismatch",
                    payment.amount_cents,
                    "Explicit references conflict with the account claim or span accounts.",
                    tuple(exact),
                )
                return
            if any(self.face[key] == 0 for key in exact):
                self.exception(
                    payment.id,
                    "invoice_not_open",
                    payment.amount_cents,
                    "A referenced invoice is not issued at payment date or was cancelled.",
                    tuple(exact),
                )
                return
            balances = [self.face[key] - self.invoice_alloc[key] for key in exact]
            if len(tokens) > 1:
                if any(b <= 0 for b in balances) or sum(balances) != payment.amount_cents:
                    self.exception(
                        payment.id,
                        "combined_amount_mismatch",
                        payment.amount_cents,
                        "Combined references require positive open balances and an exact total; "
                        "no partial split is inferred.",
                        tuple(exact),
                    )
                    return
                for key, amount in sorted(zip(exact, balances, strict=True)):
                    self.allocate(payment, key, amount, True)
            else:
                self.validated_accounts[payment.id] = next(iter(account_ids))
                amount = min(payment.amount_cents, balances[0])
                if amount:
                    if amount < balances[0]:
                        self.partial_payments.add(payment.id)
                    self.allocate(payment, exact[0], amount, False)
            return
        candidates = tuple(
            key
            for key in self.accounts.get(payment.account_id, ())
            if self.face[key] - self.invoice_alloc[key] > 0
        )
        equal_candidates = tuple(
            key
            for key in candidates
            if self.face[key] - self.invoice_alloc[key] == payment.amount_cents
        )
        if reason == "unknown_reference" and len(equal_candidates) > 1:
            reason = "ambiguous"
        self.exception(
            payment.id,
            reason,
            payment.amount_cents,
            "No unique valid explicit invoice reference. Account/open-balance candidates are "
            "review evidence only; amount or customer identity never authorizes allocation.",
            candidates,
        )

    def reverse(self, reversal) -> None:
        ensure(
            reversal.payment_id in self.payments and self.received[reversal.payment_id] > 0,
            "Known reversal lacks a known/effective parent payment at this cutoff",
        )
        payment_id = reversal.payment_id
        unapplied = (
            self.received[payment_id] - self.returned[payment_id] - self.payment_alloc[payment_id]
        )
        needed = max(0, reversal.amount_cents - unapplied)
        active = [
            (a, a.amount_cents - self.released[a.id])
            for a in self.allocated_by_payment[payment_id]
            if a.amount_cents > self.released[a.id]
        ]
        if needed and len(active) > 1 and needed != sum(amount for _, amount in active):
            raise _HoldNeeded(payment_id, tuple(a.invoice_id for a, _ in active))
        remaining = needed
        for allocation, available in sorted(active, key=lambda pair: pair[0].id):
            if not remaining:
                break
            amount = min(remaining, available)
            release = AllocationRelease(
                **self.fields("release", [reversal.id, allocation.id]),
                allocation_id=allocation.id,
                reversal_id=reversal.id,
                amount_cents=amount,
                effective_on=reversal.booked_on,
                created_at=self.options.known_at,
                reason=f"{reversal.kind}: consume unapplied cash first, release linked allocation",
            )
            self.releases.append(release)
            self.released[allocation.id] += amount
            self.payment_alloc[payment_id] -= amount
            self.invoice_alloc[allocation.invoice_id] -= amount
            remaining -= amount
        ensure(remaining == 0, "Reversal release cannot be funded")
        self.returned[payment_id] += reversal.amount_cents
        ensure(
            self.payment_alloc[payment_id] <= self.received[payment_id] - self.returned[payment_id],
            "Reversal exceeds effective cash",
        )
        self.effects.append(
            AdjustmentEffect(
                **self.fields("effect", reversal.id),
                source_record_id=reversal.id,
                kind=reversal.kind,
                signed_cash_cents=-reversal.amount_cents,
                signed_receivable_cents=0,
                released_cents=needed,
                reason=reversal.reason,
            )
        )

    def run(self) -> ReconciliationResult:
        timeline = []
        for invoice in self.invoices.values():
            timeline.append((invoice.issued_on, 0, 0, invoice.id, invoice))
        for correction in self.corrections:
            timeline.append(
                (
                    correction.effective_on,
                    1,
                    int(correction.reverses_correction_id is not None),
                    correction.id,
                    correction,
                )
            )
        for payment in self.payments.values():
            timeline.append((payment.booked_on, 2, 0, payment.id, payment))
        for reversal in self.reversals:
            timeline.append((reversal.booked_on, 3, 0, reversal.id, reversal))
        for _, kind, _, _, record in sorted(timeline):
            if kind == 0:
                self.face[record.id] = record.amount_cents
            elif kind == 1:
                face = self.face[record.invoice_id] + record.amount_cents
                ensure(
                    face >= self.invoice_alloc[record.invoice_id],
                    "Correction requires explicit allocation releases; resolve before reconciling",
                )
                self.face[record.invoice_id] = face
                self.correction_totals[record.invoice_id] += record.amount_cents
                self.effects.append(
                    AdjustmentEffect(
                        **self.fields("effect", record.id),
                        source_record_id=record.id,
                        kind="correction",
                        signed_cash_cents=0,
                        signed_receivable_cents=record.amount_cents,
                        released_cents=0,
                        reason=record.reason,
                    )
                )
            elif kind == 2:
                self.match(record)
            else:
                self.reverse(record)
        invoice_results = []
        for key, invoice in sorted(self.invoices.items()):
            face, allocated = self.face[key], self.invoice_alloc[key]
            ensure(0 <= allocated <= face, "Invoice conservation failed")
            outstanding = face - allocated
            status = (
                "cancelled"
                if face == 0
                else "settled"
                if outstanding == 0
                else "open"
                if allocated == 0
                else "partial"
            )
            invoice_results.append(
                InvoiceOutcome(
                    **self.fields("invoiceoutcome", key),
                    invoice_id=key,
                    original_cents=invoice.amount_cents,
                    correction_cents=self.correction_totals[key],
                    adjusted_face_cents=face,
                    allocated_cents=allocated,
                    outstanding_cents=outstanding,
                    status=status,
                    adjusted=self.correction_totals[key] != 0,
                    overdue=outstanding > 0 and invoice.due_on < self.options.evaluation_date,
                )
            )
            if outstanding:
                self.exception(
                    key,
                    "outstanding_invoice",
                    outstanding,
                    "Outstanding receivable; no unreferenced cash is assigned to it.",
                    manual=False,
                    subject_type="invoice",
                )
        results = []
        for key, payment in sorted(self.payments.items()):
            allocated, returned = self.payment_alloc[key], self.returned[key]
            available = payment.amount_cents - returned
            ensure(0 <= allocated <= available, "Payment conservation failed")
            unapplied = available - allocated
            status = (
                "reversed"
                if available == 0
                else "unapplied"
                if allocated == 0
                else "allocated"
                if unapplied == 0
                else "partial"
            )
            codes = {e.reason_code for e in self.exceptions if e.subject_id == key}
            classification = (
                "reversed"
                if available == 0
                else "ambiguous"
                if "ambiguous" in codes
                else "manual_review"
                if codes
                else "overpaid"
                if unapplied > 0 and key in self.validated_accounts
                else "unmatched"
                if allocated == 0
                else "adjusted"
                if returned
                else "partial_payment"
                if key in self.partial_payments
                else "matched"
            )
            results.append(
                PaymentOutcome(
                    **self.fields("paymentoutcome", key),
                    payment_id=key,
                    received_cents=payment.amount_cents,
                    reversed_cents=returned,
                    allocated_cents=allocated,
                    unapplied_cents=unapplied,
                    validated_account_id=self.validated_accounts.get(key),
                    allocation_status=status,
                    classification=classification,
                    late="late" in self.flags[key] if self.allocated_by_payment[key] else None,
                    cross_month="cross_month" in self.flags[key]
                    if self.allocated_by_payment[key]
                    else None,
                )
            )
            if unapplied > 0 and key in self.validated_accounts:
                self.exception(
                    key,
                    "overpayment",
                    unapplied,
                    "Verified account credit remains after settling explicit references.",
                    tuple(a.invoice_id for a in self.allocated_by_payment[key]),
                )
            if key in self.partial_payments:
                open_targets = tuple(
                    a.invoice_id
                    for a in self.allocated_by_payment[key]
                    if self.face[a.invoice_id] > self.invoice_alloc[a.invoice_id]
                )
                if open_targets:
                    self.exception(
                        key,
                        "amount_mismatch",
                        0,
                        "Receipt fully applied; its referenced invoice remains partly unpaid.",
                        open_targets,
                        manual=False,
                    )
        # Review amounts describe remaining cash, not the original receipt twice.
        outcomes = {p.payment_id: p for p in results}
        exceptions = tuple(
            sorted(
                (
                    e.model_copy(update={"amount_cents": outcomes[e.subject_id].unapplied_cents})
                    if e.subject_type == "payment" and e.requires_manual_review
                    else e
                    for e in self.exceptions
                ),
                key=lambda e: (e.subject_type, e.subject_id, e.reason_code),
            )
        )
        controls = {
            "original_invoice_cents": sum(i.original_cents for i in invoice_results),
            "signed_correction_cents": sum(i.correction_cents for i in invoice_results),
            "adjusted_receivables_cents": sum(i.adjusted_face_cents for i in invoice_results),
            "gross_incoming_cents": sum(p.received_cents for p in results),
            "refund_cents": sum(r.amount_cents for r in self.reversals if r.kind == "refund"),
            "chargeback_cents": sum(
                r.amount_cents for r in self.reversals if r.kind == "chargeback"
            ),
            "net_cash_cents": sum(p.received_cents - p.reversed_cents for p in results),
            "net_allocated_cents": sum(p.allocated_cents for p in results),
            "unapplied_cents": sum(p.unapplied_cents for p in results),
            "outstanding_cents": sum(i.outstanding_cents for i in invoice_results),
            "identified_credit_cents": sum(
                p.unapplied_cents for p in results if p.validated_account_id
            ),
            "suspense_cents": sum(p.unapplied_cents for p in results if not p.validated_account_id),
            "matched_event_count": sum(p.allocated_cents > 0 for p in results),
            "unmatched_event_count": sum(
                p.allocated_cents == 0 and p.unapplied_cents > 0 for p in results
            ),
            "reversed_event_count": sum(p.allocation_status == "reversed" for p in results),
        }
        controls["cash_control_difference_cents"] = (
            controls["net_cash_cents"]
            - controls["net_allocated_cents"]
            - controls["unapplied_cents"]
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
            "Aggregate financial controls failed",
        )
        ensure(
            sum(i.allocated_cents for i in invoice_results) == controls["net_allocated_cents"],
            "Allocation sides disagree",
        )
        body = dict(
            source_manifest_sha256=self.data.source_manifest_sha256,
            source_hashes=dict(sorted(self.data.source_hashes.items())),
            allocations=tuple(sorted(self.allocations, key=lambda a: a.id)),
            releases=tuple(sorted(self.releases, key=lambda r: r.id)),
            evidence=tuple(sorted(self.evidence, key=lambda e: e.id)),
            adjustments=tuple(sorted(self.effects, key=lambda e: e.id)),
            payments=tuple(results),
            invoices=tuple(invoice_results),
            exceptions=exceptions,
            review_queue=tuple(e for e in exceptions if e.requires_manual_review),
            controls=controls,
            exception_counts_by_reason=dict(
                sorted(Counter(e.reason_code for e in exceptions).items())
            ),
            source_counts={
                "unique_bank_events": len(self.data.rows("payments"))
                + len(self.data.rows("refunds_chargebacks")),
                "duplicate_file_receipts": self.data.duplicate_file_receipts,
                "duplicate_event_representations": self.data.duplicate_event_representations,
                "excluded_payments_at_cutoff": len(self.data.rows("payments")) - len(self.payments),
                "excluded_invoices_at_cutoff": len(self.data.rows("invoices")) - len(self.invoices),
                "excluded_reversals_at_cutoff": len(self.data.rows("refunds_chargebacks"))
                - len(self.reversals),
                "excluded_corrections_at_cutoff": len(self.data.rows("corrections"))
                - len(self.corrections),
                "reversal_hold_payment_count": len(self.holds),
            },
        )
        placeholder = ReconciliationRun(
            id=self.run_id,
            synthetic=True,
            dataset_id=self.data.dataset.id,
            input_sha256=self.input_hash,
            rules_version=RULES_VERSION,
            config_sha256=self.config_hash,
            as_of=self.options.evaluation_date,
            known_at=self.options.known_at,
            started_at=self.options.known_at,
            completed_at=self.options.known_at,
            result_sha256="0" * 64,
            status="completed",
        )
        result = ReconciliationResult(run=placeholder, **body)
        checksum = fingerprint(result.model_dump(mode="json", exclude={"run"}))
        return result.model_copy(
            update={"run": placeholder.model_copy(update={"result_sha256": checksum})}
        )


def default_options(evaluation_date) -> RunOptions:
    return RunOptions(
        evaluation_date=evaluation_date, known_at=datetime.combine(evaluation_date, time.max, UTC)
    )

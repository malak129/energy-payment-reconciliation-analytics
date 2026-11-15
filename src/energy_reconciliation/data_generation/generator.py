"""Author synthetic records and expected relationships from explicit scenario templates."""

import hashlib
import json
import random
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid5

from energy_reconciliation.data_generation.expectations import (
    EXCEPTION_SCENARIOS,
    NORMAL_SCENARIOS,
    ExpectedApplication,
    ExpectedException,
    ExpectedRelease,
    GroundTruth,
    InvoiceBalance,
    PaymentBalance,
    ScenarioCase,
)
from energy_reconciliation.data_generation.settings import (
    GenerationSettings,
    month_end,
    month_start,
)
from energy_reconciliation.models.records import (
    Account,
    AuditEvent,
    Correction,
    Customer,
    Dataset,
    Invoice,
    InvoiceLine,
    ManualDecision,
    Payment,
    ReconciliationRun,
    Reversal,
    ReviewCase,
)
from energy_reconciliation.utilities.money import euros_to_cents, round_euros

NAMESPACE = UUID("5d846a52-b5cf-5791-a2b5-8da3e62ed80c")
SOURCE_SYSTEM = "SYN_BANK_UTILITY"


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def timestamp(day: date) -> datetime:
    return datetime.combine(day, time(12), UTC)


@dataclass(frozen=True)
class SyntheticDataset:
    settings: GenerationSettings
    manifest_record: Dataset
    customers: tuple[Customer, ...]
    accounts: tuple[Account, ...]
    invoices: tuple[Invoice, ...]
    invoice_items: tuple[InvoiceLine, ...]
    payments: tuple[Payment, ...]
    reversals: tuple[Reversal, ...]
    corrections: tuple[Correction, ...]
    review_cases: tuple[ReviewCase, ...]
    manual_decisions: tuple[ManualDecision, ...]
    authoring_runs: tuple[ReconciliationRun, ...]
    audit_events: tuple[AuditEvent, ...]
    ground_truth: GroundTruth

    def business_tables(self) -> dict[str, tuple]:
        return {
            name: getattr(self, name)
            for name in (
                "customers",
                "accounts",
                "invoices",
                "invoice_items",
                "payments",
                "corrections",
                "review_cases",
                "manual_decisions",
                "authoring_runs",
                "audit_events",
            )
        } | {"refunds_chargebacks": self.reversals}


class _Author:
    def __init__(self, settings: GenerationSettings):
        self.settings = settings
        self.rng = random.Random(settings.seed)
        self.dataset_id = "syn_dataset_" + uuid5(NAMESPACE, digest(settings.semantic_config())).hex
        self.customers = []
        self.accounts = []
        self.invoices = []
        self.invoice_items = []
        self.payments = []
        self.reversals = []
        self.corrections = []
        self.review_cases = []
        self.manual_decisions = []
        self.applications = []
        self.intended = []
        self.releases = []
        self.exceptions = []
        self.cases = []
        self.groups = []
        self.run_id = self.identity("run", "correction_authoring")

    def identity(self, kind: str, key: object) -> str:
        return f"syn_{kind}_" + uuid5(NAMESPACE, f"{self.dataset_id}:{kind}:{key}").hex

    def fields(self, kind: str, key: object, imported: bool = False) -> dict:
        result = {"id": self.identity(kind, key), "synthetic": True}
        if imported:
            result |= {"dataset_id": self.dataset_id, "source_record_id": f"SYN-{kind}-{key}"}
        return result

    def billing(self) -> None:
        for number in range(1, self.settings.customer_count + 1):
            business = number % 5 == 0
            label = "Gewerbe SYN Betrieb" if business else "Privat"
            customer = Customer(
                **self.fields("customer", number, True),
                display_name=f"Synthetic Customer {label} {number:06d}",
                customer_type="small_business" if business else "private",
            )
            self.customers.append(customer)
            primary = "gas" if number % 3 == 0 else "electricity"
            energies = [primary]
            if number % 5 == 0:
                energies.append("electricity" if primary == "gas" else "gas")
            for energy in energies:
                energy_label = "Strom" if energy == "electricity" else "Gas"
                index = len(self.accounts) + 1
                account = Account(
                    **self.fields("account", index, True),
                    customer_id=customer.id,
                    energy_type=energy,
                    contract_reference=f"SYN-KONTO-{index:06d}",
                    opened_on=self.settings.start_date,
                    synthetic_iban=f"DE00{index:018d}",
                )
                self.accounts.append(account)
                limits = (
                    ((18000, 65000) if business else (6500, 16000))
                    if energy == "electricity"
                    else ((25000, 90000) if business else (10000, 25000))
                )
                net = self.rng.randint(*limits)
                base = self.rng.randint(1200, 2200)
                bills = []
                for period in range(self.settings.billing_periods):
                    start = max(
                        month_start(self.settings.start_date, period), self.settings.start_date
                    )
                    end = min(month_end(start), self.settings.end_date)
                    key = f"{index}_{period}"
                    invoice_id = self.identity("invoice", key)
                    items = []
                    for line_number, (description, cents) in enumerate(
                        (("Grundpreis", base), ("Verbrauchsabschlag", net - base)), 1
                    ):
                        tax = euros_to_cents(round_euros(Decimal(cents) / 100 * Decimal("0.19")))
                        items.append(
                            InvoiceLine(
                                **self.fields("item", f"{key}_{line_number}", True),
                                invoice_id=invoice_id,
                                line_number=line_number,
                                description=f"Synthetisch {energy_label} {description}",
                                net_cents=cents,
                                tax_cents=tax,
                                gross_cents=cents + tax,
                            )
                        )
                    invoice = Invoice(
                        **self.fields("invoice", key, True),
                        account_id=account.id,
                        reference=f"SYN-RE-{start:%Y%m}-{index:06d}",
                        issued_on=start,
                        due_on=start + timedelta(days=14),
                        service_start=start,
                        service_end=end,
                        amount_cents=sum(item.gross_cents for item in items),
                    )
                    bills.append(invoice)
                    self.invoices.append(invoice)
                    self.invoice_items.extend(items)
                self.groups.extend(tuple(bills[p : p + 2]) for p in range(0, len(bills), 2))

    def payment(
        self, invoices: tuple[Invoice, ...], amount: int, booked: date, reference: str | None
    ) -> Payment:
        number = len(self.payments) + 1
        result = Payment(
            **self.fields("payment", number, True),
            source_system=SOURCE_SYSTEM,
            bank_event_id=f"SYN-EVENT-P-{number:07d}",
            booked_on=booked,
            value_on=booked,
            amount_cents=amount,
            account_id=invoices[0].account_id,
            reference=reference,
        )
        self.payments.append(result)
        return result

    def application(
        self,
        payment: Payment,
        invoice: Invoice,
        amount: int,
        *,
        expected: bool = True,
        combined: bool = False,
    ) -> ExpectedApplication:
        item = ExpectedApplication(
            **self.fields("expectation", len(self.intended) + 1),
            payment_id=payment.id,
            invoice_id=invoice.id,
            amount_cents=amount,
            effective_on=payment.booked_on,
            reason_code=("explicit_combined" if combined else "exact_reference")
            if expected
            else "intent_only",
        )
        self.intended.append(item)
        if expected:
            self.applications.append(item)
        return item

    def exception(
        self,
        subject: str,
        category: str,
        candidates: tuple[str, ...] = (),
        effective: date | None = None,
        resolved: date | None = None,
    ) -> None:
        if effective is None:
            payment = next((p for p in reversed(self.payments) if p.id == subject), None)
            invoice = (
                next((i for i in self.invoices if i.id == subject), None)
                if payment is None
                else None
            )
            effective = payment.booked_on if payment else invoice.due_on + timedelta(days=1)
        self.exceptions.append(
            ExpectedException(
                **self.fields("exception", len(self.exceptions) + 1),
                subject_id=subject,
                category=category,
                candidate_invoice_ids=candidates,
                effective_on=effective,
                resolved_on=resolved,
            )
        )

    def correction(self, invoice: Invoice) -> int:
        key = invoice.id
        created = timestamp(invoice.issued_on + timedelta(days=1))
        case = ReviewCase(
            **self.fields("review", key),
            invoice_id=invoice.id,
            run_id=self.run_id,
            reason_code="invoice_correction",
            reason="Synthetic approved Abschlagskorrektur",
            created_at=created,
        )
        decision = ManualDecision(
            **self.fields("decision", key),
            case_id=case.id,
            action="correct_invoice",
            actor="SYNTHETIC_OPERATOR",
            reason=case.reason,
            created_at=created,
            resolved_account_id=invoice.account_id,
        )
        correction = Correction(
            **self.fields("correction", key),
            invoice_id=invoice.id,
            decision_id=decision.id,
            amount_cents=-(invoice.amount_cents // 10),
            effective_on=created.date(),
            created_at=created,
            reason=case.reason,
        )
        self.review_cases.append(case)
        self.manual_decisions.append(decision)
        self.corrections.append(correction)
        self.exception(invoice.id, "invoice_correction", effective=correction.effective_on)
        return invoice.amount_cents + correction.amount_cents

    def scenarios(self) -> None:
        self.rng.shuffle(self.groups)
        quota = int(Decimal(len(self.groups)) * self.settings.discrepancy_rate)
        for index, invoices in enumerate(self.groups):
            patterns = tuple(
                s
                for s in EXCEPTION_SCENARIOS
                if len(invoices) == 2 or s not in ("combined", "ambiguous")
            )
            scenario = (
                patterns[index % len(patterns)]
                if index < quota
                else NORMAL_SCENARIOS[(index - quota) % len(NORMAL_SCENARIOS)]
            )
            first_payment = len(self.payments)
            if scenario == "combined":
                payment = self.payment(
                    invoices,
                    sum(i.amount_cents for i in invoices),
                    invoices[-1].issued_on + timedelta(days=7),
                    " | ".join(i.reference for i in invoices),
                )
                for invoice in invoices:
                    self.application(payment, invoice, invoice.amount_cents, combined=True)
            elif scenario == "ambiguous":
                payment = self.payment(
                    invoices,
                    invoices[0].amount_cents,
                    invoices[-1].issued_on + timedelta(days=7),
                    "SYN-Abschlag ohne Rechnungsnummer",
                )
                self.application(payment, invoices[0], payment.amount_cents, expected=False)
                self.exception(payment.id, "ambiguous", tuple(i.id for i in invoices))
            else:
                for invoice in invoices:
                    amount = invoice.amount_cents
                    if scenario == "unpaid":
                        self.exception(invoice.id, "unpaid")
                        continue
                    if scenario == "correction":
                        amount = self.correction(invoice)
                    booked = invoice.due_on
                    if scenario == "early":
                        booked = invoice.issued_on + timedelta(days=2)
                    elif scenario == "late":
                        booked += timedelta(days=18)
                    elif scenario == "cross_month":
                        booked = month_start(invoice.issued_on, 1) + timedelta(days=3)
                    reference = invoice.reference
                    if scenario == "missing_reference":
                        reference = None
                    elif scenario == "incorrect_reference":
                        reference = "SYN-RE-UNKNOWN-" + invoice.reference
                    credit = (
                        self.rng.randint(500, 4000) if scenario in ("overpayment", "refund") else 0
                    )
                    amounts = [amount + credit]
                    if scenario == "partial":
                        amounts = [amount * 3 // 5]
                    elif scenario == "multiple_payments":
                        amounts = [amount // 2, amount - amount // 2]
                    for part, paid in enumerate(amounts):
                        payment = self.payment(
                            (invoice,), paid, booked + timedelta(days=part * 2), reference
                        )
                        matched = scenario not in ("missing_reference", "incorrect_reference")
                        application = self.application(
                            payment, invoice, min(paid, amount), expected=matched
                        )
                        if not matched:
                            self.exception(
                                payment.id,
                                "missing_reference" if reference is None else "unknown_reference",
                                (invoice.id,),
                            )
                        elif scenario in ("partial", "overpayment"):
                            self.exception(
                                payment.id,
                                "amount_mismatch" if scenario == "partial" else "overpayment",
                                (invoice.id,),
                            )
                        if scenario in ("refund", "chargeback"):
                            reversal = Reversal(
                                **self.fields("reversal", len(self.reversals) + 1, True),
                                source_system=SOURCE_SYSTEM,
                                bank_event_id=f"SYN-EVENT-R-{len(self.reversals) + 1:07d}",
                                payment_id=payment.id,
                                kind=scenario,
                                amount_cents=credit if scenario == "refund" else paid,
                                booked_on=payment.booked_on + timedelta(days=7),
                                value_on=payment.booked_on + timedelta(days=7),
                                reason="Synthetic Guthabenerstattung"
                                if scenario == "refund"
                                else "Synthetic Ruecklastschrift",
                            )
                            self.reversals.append(reversal)
                            if scenario == "refund":
                                self.exception(
                                    payment.id,
                                    "overpayment",
                                    (invoice.id,),
                                    resolved=reversal.booked_on,
                                )
                            if scenario == "chargeback":
                                self.releases.append(
                                    ExpectedRelease(
                                        **self.fields("release", len(self.releases) + 1),
                                        application_id=application.id,
                                        reversal_id=reversal.id,
                                        amount_cents=paid,
                                        effective_on=reversal.booked_on,
                                    )
                                )
            self.cases.append(
                ScenarioCase(
                    **self.fields("scenario", index),
                    scenario=scenario,
                    invoice_ids=tuple(i.id for i in invoices),
                    payment_ids=tuple(p.id for p in self.payments[first_payment:]),
                )
            )

    def finish(self) -> SyntheticDataset:
        cutoff = self.settings.evaluation_date
        invoice_allocated = dict.fromkeys((i.id for i in self.invoices), 0)
        payment_allocated = dict.fromkeys((p.id for p in self.payments), 0)
        apps = {a.id: a for a in self.applications}
        for application in self.applications:
            if application.effective_on <= cutoff:
                invoice_allocated[application.invoice_id] += application.amount_cents
                payment_allocated[application.payment_id] += application.amount_cents
        for release in self.releases:
            if release.effective_on <= cutoff:
                application = apps[release.application_id]
                invoice_allocated[application.invoice_id] -= release.amount_cents
                payment_allocated[application.payment_id] -= release.amount_cents
        adjustments = dict.fromkeys(invoice_allocated, 0)
        for correction in self.corrections:
            if correction.effective_on <= cutoff:
                adjustments[correction.invoice_id] += correction.amount_cents
        outflows = dict.fromkeys(payment_allocated, 0)
        for reversal in self.reversals:
            if reversal.booked_on <= cutoff:
                outflows[reversal.payment_id] += reversal.amount_cents
        invoice_balances = []
        for invoice in self.invoices:
            face = (
                invoice.amount_cents + adjustments[invoice.id] if invoice.issued_on <= cutoff else 0
            )
            invoice_balances.append(
                InvoiceBalance(
                    **self.fields("invoicebalance", invoice.id),
                    invoice_id=invoice.id,
                    adjusted_face_cents=face,
                    allocated_cents=invoice_allocated[invoice.id],
                    outstanding_cents=face - invoice_allocated[invoice.id],
                )
            )
        balances = []
        for payment in self.payments:
            received = payment.amount_cents if payment.booked_on <= cutoff else 0
            balances.append(
                PaymentBalance(
                    **self.fields("paymentbalance", payment.id),
                    payment_id=payment.id,
                    received_cents=received,
                    reversed_cents=outflows[payment.id],
                    allocated_cents=payment_allocated[payment.id],
                    unapplied_cents=received - outflows[payment.id] - payment_allocated[payment.id],
                )
            )
        truth = GroundTruth(
            dataset_id=self.dataset_id,
            evaluation_date=cutoff,
            cases=tuple(self.cases),
            intended_relationships=tuple(self.intended),
            expected_applications=tuple(self.applications),
            expected_releases=tuple(self.releases),
            expected_exceptions=tuple(
                e
                for e in self.exceptions
                if e.effective_on <= cutoff and (e.resolved_on is None or e.resolved_on > cutoff)
            ),
            invoice_balances=tuple(invoice_balances),
            payment_balances=tuple(balances),
            expected_unmatched_payment_ids=tuple(
                b.payment_id
                for b in balances
                if b.received_cents > 0 and b.allocated_cents == 0 and b.unapplied_cents > 0
            ),
            expected_manual_review_payment_ids=tuple(
                e.subject_id
                for e in self.exceptions
                if e.category in ("ambiguous", "missing_reference", "unknown_reference")
                and next(p for p in self.payments if p.id == e.subject_id).booked_on <= cutoff
            ),
        )
        # Approval fixtures are not a reconciliation execution or result ledger.
        runs = []
        audits = []
        if self.corrections:
            end = max(c.created_at for c in self.corrections)
            start = min(c.created_at for c in self.corrections)
            runs.append(
                ReconciliationRun(
                    **self.fields("run", "correction_authoring"),
                    dataset_id=self.dataset_id,
                    input_sha256=digest([i.model_dump(mode="json") for i in self.invoices]),
                    config_sha256=digest(self.settings.semantic_config()),
                    result_sha256=digest([c.model_dump(mode="json") for c in self.corrections]),
                    rules_version="synthetic-correction-authoring-v1",
                    as_of=end.date(),
                    known_at=start,
                    started_at=start,
                    completed_at=end,
                    status="completed",
                )
            )
            for correction in self.corrections:
                audits.append(
                    AuditEvent(
                        **self.fields("audit", correction.id),
                        entity_type="Correction",
                        entity_id=correction.id,
                        action="synthetic_approval_fixture",
                        actor="SYNTHETIC_OPERATOR",
                        occurred_at=correction.created_at,
                        run_id=self.run_id,
                        payload_sha256=digest(correction.model_dump(mode="json")),
                    )
                )
        tables = {
            name: tuple(getattr(self, name))
            for name in (
                "customers",
                "accounts",
                "invoices",
                "invoice_items",
                "payments",
                "reversals",
                "corrections",
                "review_cases",
                "manual_decisions",
            )
        }
        record = Dataset(
            **self.fields("dataset", "manifest"),
            generator_version="1",
            seed=self.settings.seed,
            config_sha256=digest(self.settings.semantic_config()),
            content_sha256="0" * 64,
            effective_at=timestamp(cutoff),
        )
        # Dataset identity is configuration-derived, not the manifest record's sequence key.
        record = record.model_copy(update={"id": self.dataset_id})
        result = SyntheticDataset(
            self.settings,
            record,
            **tables,
            authoring_runs=tuple(runs),
            audit_events=tuple(audits),
            ground_truth=truth,
        )
        content = {
            name: [r.model_dump(mode="json") for r in rows]
            for name, rows in result.business_tables().items()
        }
        return replace(
            result, manifest_record=record.model_copy(update={"content_sha256": digest(content)})
        )


def generate_dataset(settings: GenerationSettings | None = None) -> SyntheticDataset:
    settings = settings or GenerationSettings()
    with localcontext() as context:
        context.prec = max(32, len(settings.discrepancy_rate.as_tuple().digits) + 10)
        author = _Author(settings)
        author.billing()
        author.scenarios()
        return author.finish()

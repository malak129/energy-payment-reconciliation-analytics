"""Validate generated fixtures and their explicit oracle; this never matches references."""

from collections import Counter, defaultdict
from itertools import chain

from energy_reconciliation.data_generation.generator import SyntheticDataset, digest


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Synthetic dataset validation: {message}")


def validate_dataset(data: SyntheticDataset) -> dict:
    tables = data.business_tables()
    require(
        data.manifest_record.config_sha256 == digest(data.settings.semantic_config()),
        "configuration fingerprint mismatch",
    )
    require(
        data.manifest_record.content_sha256
        == digest(
            {name: [r.model_dump(mode="json") for r in rows] for name, rows in tables.items()}
        ),
        "business content fingerprint mismatch",
    )
    records = list(chain.from_iterable(tables.values())) + [data.manifest_record]
    require(len({r.id for r in records}) == len(records), "duplicate business ID")
    for record in records:
        type(record).model_validate(record.model_dump())
        require(record.synthetic is True, "record is not synthetic")
        if hasattr(record, "dataset_id"):
            require(record.dataset_id == data.manifest_record.id, "foreign dataset")
    for rows in tables.values():
        source_ids = [r.source_record_id for r in rows if hasattr(r, "source_record_id")]
        require(len(set(source_ids)) == len(source_ids), "duplicate source record key")
    customers = {c.id: c for c in data.customers}
    accounts = {a.id: a for a in data.accounts}
    invoices = {i.id: i for i in data.invoices}
    payments = {p.id: p for p in data.payments}
    reversals = {r.id: r for r in data.reversals}
    decisions = {d.id: d for d in data.manual_decisions}
    cases = {c.id: c for c in data.review_cases}
    runs = {r.id: r for r in data.authoring_runs}
    require(
        len({i.reference.upper().strip() for i in data.invoices}) == len(invoices),
        "duplicate normalized invoice reference",
    )
    require(
        len({a.contract_reference for a in data.accounts}) == len(accounts), "duplicate contract"
    )
    require(len({a.synthetic_iban for a in data.accounts}) == len(accounts), "duplicate IBAN token")
    for customer in data.customers:
        require(customer.display_name.startswith("Synthetic Customer"), "fictional name missing")
    for account in data.accounts:
        require(account.customer_id in customers, "orphan account")
    lines = defaultdict(int)
    line_keys = set()
    for item in data.invoice_items:
        require(item.invoice_id in invoices, "orphan invoice item")
        require((item.invoice_id, item.line_number) not in line_keys, "duplicate invoice line")
        line_keys.add((item.invoice_id, item.line_number))
        lines[item.invoice_id] += item.gross_cents
    for invoice in data.invoices:
        require(invoice.account_id in accounts, "orphan invoice")
        require(lines[invoice.id] == invoice.amount_cents, "invoice line total mismatch")
        require(
            accounts[invoice.account_id].opened_on <= invoice.issued_on, "invoice before account"
        )
        require(
            data.settings.start_date
            <= invoice.service_start
            <= invoice.service_end
            <= data.settings.end_date,
            "invoice outside configured service range",
        )
    events = (*data.payments, *data.reversals)
    require(
        len({(e.source_system, e.bank_event_id) for e in events}) == len(events),
        "duplicate original bank event",
    )
    for payment in data.payments:
        require(payment.account_id in accounts, "orphan payment account")
    outflows = defaultdict(int)
    for reversal in data.reversals:
        require(reversal.payment_id in payments, "orphan reversal")
        payment = payments[reversal.payment_id]
        require(reversal.booked_on >= payment.booked_on, "reversal precedes payment")
        outflows[payment.id] += reversal.amount_cents
        require(outflows[payment.id] <= payment.amount_cents, "excess reversal")
    adjustments = defaultdict(int)
    for correction in data.corrections:
        require(
            correction.invoice_id in invoices and correction.decision_id in decisions,
            "orphan correction",
        )
        invoice = invoices[correction.invoice_id]
        decision = decisions[correction.decision_id]
        require(decision.case_id in cases, "orphan decision")
        case = cases[decision.case_id]
        require(case.run_id in runs and case.invoice_id == invoice.id, "correction case mismatch")
        require(
            decision.action == "correct_invoice"
            and decision.resolved_account_id == invoice.account_id,
            "correction authority mismatch",
        )
        require(invoice.issued_on <= correction.effective_on, "correction precedes invoice")
        adjustments[invoice.id] += correction.amount_cents
        require(invoice.amount_cents + adjustments[invoice.id] >= 0, "negative adjusted invoice")
    for audit in data.audit_events:
        require(
            audit.entity_id in {c.id for c in data.corrections} and audit.run_id in runs,
            "orphan authoring audit",
        )

    truth = data.ground_truth
    require(
        truth.dataset_id == data.manifest_record.id
        and truth.evaluation_date == data.settings.evaluation_date,
        "oracle snapshot mismatch",
    )
    expected_rows = (
        *truth.cases,
        *truth.intended_relationships,
        *truth.expected_releases,
        *truth.expected_exceptions,
        *truth.invoice_balances,
        *truth.payment_balances,
    )
    require(len({r.id for r in expected_rows}) == len(expected_rows), "duplicate oracle ID")
    require(all(r.synthetic is True for r in expected_rows), "oracle not synthetic")
    coverage = Counter(chain.from_iterable(c.invoice_ids for c in truth.cases))
    require(
        set(coverage) == set(invoices) and all(n == 1 for n in coverage.values()),
        "scenario invoice coverage",
    )
    payment_coverage = Counter(chain.from_iterable(c.payment_ids for c in truth.cases))
    require(
        set(payment_coverage) == set(payments) and all(n == 1 for n in payment_coverage.values()),
        "scenario payment coverage",
    )
    intended = {a.id: a for a in truth.intended_relationships}
    applications = {a.id: a for a in truth.expected_applications}
    require(len(applications) == len(truth.expected_applications), "duplicate expected application")
    for application in truth.intended_relationships:
        require(
            application.payment_id in payments and application.invoice_id in invoices,
            "orphan intended relationship",
        )
        invoice, payment = invoices[application.invoice_id], payments[application.payment_id]
        require(invoice.account_id == payment.account_id, "cross-account application")
        require(
            application.effective_on >= max(invoice.issued_on, payment.booked_on),
            "application before invoice/payment",
        )
    for application in truth.expected_applications:
        require(intended.get(application.id) == application, "application not authored")
        require(
            application.reason_code != "intent_only", "hidden intent cannot authorize application"
        )
    released = defaultdict(int)
    for release in truth.expected_releases:
        require(
            release.application_id in applications and release.reversal_id in reversals,
            "orphan expected release",
        )
        application, reversal = applications[release.application_id], reversals[release.reversal_id]
        require(
            application.payment_id == reversal.payment_id
            and release.effective_on == reversal.booked_on >= application.effective_on,
            "release reversal mismatch",
        )
        released[application.id] += release.amount_cents
        require(released[application.id] <= application.amount_cents, "excess allocation release")

    # Validate all dated snapshots, including dates after an early evaluation cutoff.
    # Oracle links were authored by templates; no match inference occurs.
    changes = defaultdict(list)
    for invoice in data.invoices:
        changes[invoice.issued_on].append(("face", invoice.id, invoice.amount_cents))
    for correction in data.corrections:
        changes[correction.effective_on].append(
            ("face", correction.invoice_id, correction.amount_cents)
        )
    for payment in data.payments:
        changes[payment.booked_on].append(("cash", payment.id, payment.amount_cents))
    for reversal in data.reversals:
        changes[reversal.booked_on].append(("cash", reversal.payment_id, -reversal.amount_cents))
    for application in truth.expected_applications:
        changes[application.effective_on].extend(
            (
                ("invoice_alloc", application.invoice_id, application.amount_cents),
                ("payment_alloc", application.payment_id, application.amount_cents),
            )
        )
    for release in truth.expected_releases:
        application = applications[release.application_id]
        changes[release.effective_on].extend(
            (
                ("invoice_alloc", application.invoice_id, -release.amount_cents),
                ("payment_alloc", application.payment_id, -release.amount_cents),
            )
        )
    state = {name: defaultdict(int) for name in ("face", "cash", "invoice_alloc", "payment_alloc")}
    at_cutoff = {name: {} for name in state}
    for day, entries in sorted(changes.items()):
        for name, key, amount in entries:
            state[name][key] += amount
        for key, value in state["invoice_alloc"].items():
            require(0 <= value <= state["face"][key], "invoice allocation bound")
        for key, value in state["payment_alloc"].items():
            require(0 <= value <= state["cash"][key], "payment allocation bound")
        require(all(v >= 0 for v in state["cash"].values()), "negative available cash")
        if day <= truth.evaluation_date:
            at_cutoff = {name: dict(values) for name, values in state.items()}
    invoice_balances = {b.invoice_id: b for b in truth.invoice_balances}
    payment_balances = {b.payment_id: b for b in truth.payment_balances}
    require(
        set(invoice_balances) == set(invoices) and set(payment_balances) == set(payments),
        "missing expected balances",
    )
    for key, balance in invoice_balances.items():
        face = at_cutoff["face"].get(key, 0)
        allocated = at_cutoff["invoice_alloc"].get(key, 0)
        require(
            (balance.adjusted_face_cents, balance.allocated_cents, balance.outstanding_cents)
            == (face, allocated, face - allocated),
            "oracle invoice balance mismatch",
        )
    for key, balance in payment_balances.items():
        received = (
            payments[key].amount_cents if payments[key].booked_on <= truth.evaluation_date else 0
        )
        cash, allocated = at_cutoff["cash"].get(key, 0), at_cutoff["payment_alloc"].get(key, 0)
        require(
            (
                balance.received_cents,
                balance.reversed_cents,
                balance.allocated_cents,
                balance.unapplied_cents,
            )
            == (received, received - cash, allocated, cash - allocated),
            "oracle payment balance mismatch",
        )
    for exception in truth.expected_exceptions:
        require(
            exception.subject_id in payments or exception.subject_id in invoices, "orphan exception"
        )
        require(set(exception.candidate_invoice_ids) <= invoices.keys(), "orphan candidate")
        require(
            exception.effective_on <= truth.evaluation_date
            and (exception.resolved_on is None or exception.resolved_on > truth.evaluation_date),
            "exception outside snapshot",
        )
    require(
        set(truth.expected_unmatched_payment_ids)
        == {
            b.payment_id
            for b in truth.payment_balances
            if b.unapplied_cents > 0 and b.allocated_cents == 0
        },
        "unmatched oracle mismatch",
    )
    require(
        set(truth.expected_manual_review_payment_ids)
        == {
            e.subject_id
            for e in truth.expected_exceptions
            if e.category in ("ambiguous", "missing_reference", "unknown_reference")
        },
        "manual review mismatch",
    )

    totals = {
        "invoice_cents_all_dates": sum(i.amount_cents for i in data.invoices),
        "payment_cents_all_dates": sum(p.amount_cents for p in data.payments),
        "refund_cents_all_dates": sum(r.amount_cents for r in data.reversals if r.kind == "refund"),
        "chargeback_cents_all_dates": sum(
            r.amount_cents for r in data.reversals if r.kind == "chargeback"
        ),
        "correction_cents_all_dates": sum(c.amount_cents for c in data.corrections),
        "adjusted_face_cents_as_of": sum(b.adjusted_face_cents for b in truth.invoice_balances),
        "net_cash_cents_as_of": sum(
            b.received_cents - b.reversed_cents for b in truth.payment_balances
        ),
        "allocated_cents_as_of": sum(b.allocated_cents for b in truth.payment_balances),
        "outstanding_cents_as_of": sum(b.outstanding_cents for b in truth.invoice_balances),
        "unapplied_cents_as_of": sum(b.unapplied_cents for b in truth.payment_balances),
    }
    require(
        totals["net_cash_cents_as_of"]
        == totals["allocated_cents_as_of"] + totals["unapplied_cents_as_of"],
        "cash control",
    )
    require(
        totals["adjusted_face_cents_as_of"]
        == totals["allocated_cents_as_of"] + totals["outstanding_cents_as_of"],
        "receivable control",
    )
    return {
        "counts": {name: len(rows) for name, rows in tables.items()},
        "scenario_counts": dict(sorted(Counter(c.scenario for c in truth.cases).items())),
        "scenario_record_counts": {
            scenario: {
                "cases": sum(c.scenario == scenario for c in truth.cases),
                "invoices": sum(len(c.invoice_ids) for c in truth.cases if c.scenario == scenario),
                "payments": sum(len(c.payment_ids) for c in truth.cases if c.scenario == scenario),
            }
            for scenario in sorted({c.scenario for c in truth.cases})
        },
        "totals": totals,
        "unmatched_payments_as_of": len(truth.expected_unmatched_payment_ids),
        "manual_review_payments_as_of": len(truth.expected_manual_review_payment_ids),
    }

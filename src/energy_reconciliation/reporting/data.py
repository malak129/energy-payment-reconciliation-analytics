"""Read one persisted snapshot; aggregate its effects, never all historical runs."""

import calendar
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select

from energy_reconciliation.ingestion.csv_dataset import ensure
from energy_reconciliation.persistence import schema as s
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import Store
from energy_reconciliation.utilities.serialization import stable_id


@dataclass
class Report:
    metadata: dict
    controls: dict[str, int]
    tables: dict[str, list[dict]]
    checks: list[dict]
    aging: dict[str, int]


def read_report(
    path: Path, *, dataset_id=None, run_id=None, as_of: date | None = None, lightweight=False
) -> Report:
    """Select an existing exact-date snapshot. Never reconcile or activate during export."""
    ensure(Path(path).is_file(), "Reporting requires an existing reconciled SQLite database")
    database = Database(path, read_only=True)
    try:
        store = Store(database)
        with database.engine.connect() as c:
            c.exec_driver_sql("PRAGMA query_only=ON")
            c.exec_driver_sql("BEGIN")
            if run_id:
                row = c.execute(select(s.runs).where(s.runs.c.id == run_id)).mappings().first()
                ensure(row is not None, "Unknown persisted reconciliation run")
                ensure(dataset_id is None or row["dataset_id"] == dataset_id, "Wrong dataset")
                dataset_id = row["dataset_id"]
            else:
                dataset_id = store.dataset_id(c, dataset_id)
                if as_of is None:
                    row = dict(store._head(c, dataset_id))
                    run_id = row["run_id"]
                    row = c.execute(select(s.runs).where(s.runs.c.id == run_id)).mappings().one()
                else:
                    row = (
                        c.execute(
                            select(s.runs)
                            .where(
                                s.runs.c.dataset_id == dataset_id,
                                s.runs.c.as_of == as_of.isoformat(),
                            )
                            .order_by(s.runs.c.known_at.desc(), s.runs.c.kind.desc(), s.runs.c.id)
                        )
                        .mappings()
                        .first()
                    )
                    ensure(
                        row is not None,
                        "No persisted run for as-of date; persist a historical run first",
                    )
            result = store._result(c, row["id"])
            ensure(
                as_of is None or result.run.as_of == as_of, "As-of date differs from selected run"
            )
            data = store.load_input(
                c,
                row["source_version_id"],
                include_provenance=not lightweight,
                table_names=(
                    "customers",
                    "accounts",
                    "invoices",
                    "payments",
                    "refunds_chargebacks",
                    "corrections",
                )
                if lightweight
                else None,
            )
            base = store._result(c, row["base_run_id"]) if row["base_run_id"] else result
            # Read all immutable details and live status inside the same read transaction.
            operations = store.operations(c, dataset_id)
            decisions = [
                o
                for o in operations
                if row["kind"] == "LEDGER" or o.action == "defer"
                if o.created_at <= result.run.known_at and o.effective_on <= result.run.as_of
            ]
            adjustments = {
                r["id"]: json.loads(r["payload_json"])
                for r in c.execute(
                    select(s.adjustments)
                    .join(s.decisions, s.decisions.c.id == s.adjustments.c.decision_id)
                    .where(s.decisions.c.dataset_id == dataset_id)
                ).mappings()
            }
            head = (
                c.execute(select(s.ledger_heads).where(s.ledger_heads.c.dataset_id == dataset_id))
                .mappings()
                .first()
            )
            live = (
                {
                    r["id"]: dict(r)
                    for r in c.execute(
                        select(s.review_cases).where(s.review_cases.c.dataset_id == dataset_id)
                    ).mappings()
                }
                if (head and head["run_id"] == row["id"])
                else {}
            )
            if live:
                known_ids = {o.id for o in decisions}
                decisions += [
                    o for o in operations if o.action == "defer" and o.id not in known_ids
                ]
            # Audit is operational traceability through export, not fictional business-date cash.
            audit = [
                dict(r)
                for r in c.execute(
                    select(s.audit_events)
                    .where(s.audit_events.c.dataset_id == dataset_id, not lightweight)
                    .order_by(s.audit_events.c.occurred_at, s.audit_events.c.id)
                ).mappings()
            ]
            return build_report(
                result,
                base,
                data,
                sorted(decisions, key=lambda o: o.sequence),
                adjustments,
                live,
                audit,
                row,
            )
    finally:
        database.close()


def build_report(result, base, data, decisions, local_adjustments, live, audit, header):
    originals = {i.id: i for i in data.rows("invoices")}
    payments = {p.id: p for p in data.rows("payments")}
    accounts = {a.id: a for a in data.rows("accounts")}
    customers = {c.id: c for c in data.rows("customers")}
    reversal_sources = {r.id: r for r in data.rows("refunds_chargebacks")}
    corrections = {r.id: r for r in data.rows("corrections")}
    for key, payload in local_adjustments.items():
        (corrections if "invoice_id" in payload else reversal_sources)[key] = payload
    allocations = {a.id: a for a in result.allocations}
    released = Counter()
    for r in result.releases:
        released[r.allocation_id] += r.amount_cents
    monthly = defaultdict(Counter)
    account_totals = defaultdict(Counter)
    aging = dict.fromkeys(
        ["Not overdue", "1–30 days", "31–60 days", "61–90 days", "Over 90 days"], 0
    )
    invoice_rows, payment_rows, allocation_rows, adjustment_rows = [], [], [], []
    for i in sorted(
        result.invoices, key=lambda i: (originals[i.invoice_id].issued_on, i.invoice_id)
    ):
        source = originals[i.invoice_id]
        days = max(0, (result.run.as_of - source.due_on).days)
        bucket = (
            "Not overdue"
            if days == 0
            else "1–30 days"
            if days <= 30
            else "31–60 days"
            if days <= 60
            else "61–90 days"
            if days <= 90
            else "Over 90 days"
        )
        aging[bucket] += i.outstanding_cents
        account = accounts[source.account_id]
        invoice_rows.append(
            dict(
                invoice_id=i.invoice_id,
                reference=source.reference,
                account_id=source.account_id,
                customer_id=account.customer_id,
                issued_on=source.issued_on,
                due_on=source.due_on,
                original_cents=i.original_cents,
                correction_cents=i.correction_cents,
                adjusted_cents=i.adjusted_face_cents,
                allocated_cents=i.allocated_cents,
                outstanding_cents=i.outstanding_cents,
                status=i.status,
                overdue_days=days,
                aging_bucket=bucket,
            )
        )
        monthly[source.issued_on.replace(day=1)]["issued_cents"] += i.original_cents
        for key, amount in [
            ("original_cents", i.original_cents),
            ("correction_cents", i.correction_cents),
            ("allocated_cents", i.allocated_cents),
            ("outstanding_cents", i.outstanding_cents),
        ]:
            account_totals[source.account_id][key] += amount
    evidence = defaultdict(list)
    for e in result.evidence:
        evidence[allocations[e.allocation_id].payment_id].append(f"{e.rule_id}: {e.explanation}")
    for p in sorted(
        result.payments, key=lambda p: (payments[p.payment_id].booked_on, p.payment_id)
    ):
        source = payments[p.payment_id]
        payment_rows.append(
            dict(
                payment_id=p.payment_id,
                bank_event_id=source.bank_event_id,
                reference=source.reference,
                claimed_account_id=source.account_id,
                validated_account_id=p.validated_account_id,
                booked_on=source.booked_on,
                value_on=source.value_on,
                received_cents=p.received_cents,
                reversed_cents=p.reversed_cents,
                net_cash_cents=p.received_cents - p.reversed_cents,
                allocated_cents=p.allocated_cents,
                unapplied_cents=p.unapplied_cents,
                status=p.allocation_status,
                classification=p.classification,
                evidence="\n".join(evidence[p.payment_id]),
            )
        )
        monthly[source.booked_on.replace(day=1)]["incoming_cents"] += p.received_cents
        if p.validated_account_id:
            account_totals[p.validated_account_id]["identified_credit_cents"] += p.unapplied_cents
    for a in sorted(result.allocations, key=lambda a: (a.effective_on, a.id)):
        ensure(0 <= released[a.id] <= a.amount_cents, "Invalid persisted allocation release total")
        allocation_rows.append(
            dict(
                allocation_id=a.id,
                payment_id=a.payment_id,
                invoice_id=a.invoice_id,
                account_id=originals[a.invoice_id].account_id,
                effective_on=a.effective_on,
                allocated_cents=a.amount_cents,
                released_cents=released[a.id],
                net_allocated_cents=a.amount_cents - released[a.id],
                decision_id=a.decision_id,
                origin_run_id=a.run_id,
                confidence=a.confidence,
                reason=a.reason_code,
            )
        )
        monthly[a.effective_on.replace(day=1)]["allocation_increases_cents"] += a.amount_cents
    for r in result.releases:
        monthly[r.effective_on.replace(day=1)]["releases_cents"] += r.amount_cents
    for effect in sorted(result.adjustments, key=lambda e: e.id):
        source = (corrections if effect.kind == "correction" else reversal_sources)[
            effect.source_record_id
        ]
        payload = source if isinstance(source, dict) else source.model_dump(mode="json")
        when = date.fromisoformat(
            payload["effective_on" if effect.kind == "correction" else "booked_on"]
        )
        invoice_id = payload.get("invoice_id")
        account_id = originals[invoice_id].account_id if invoice_id else None
        if effect.kind == "correction":
            monthly[when.replace(day=1)]["corrections_cents"] += effect.signed_receivable_cents
        else:
            monthly[when.replace(day=1)][effect.kind + "_cents"] -= effect.signed_cash_cents
        adjustment_rows.append(
            dict(
                effect_id=effect.id,
                original_record_id=effect.source_record_id,
                kind=effect.kind,
                effective_on=when,
                invoice_id=invoice_id,
                payment_id=payload.get("payment_id"),
                account_id=account_id,
                signed_cash_cents=effect.signed_cash_cents,
                signed_receivable_cents=effect.signed_receivable_cents,
                released_cents=effect.released_cents,
                decision_id=payload.get("decision_id"),
                reverses_record_id=payload.get("reverses_correction_id"),
                reason=effect.reason,
            )
        )
    # Explicit releases remain individually traceable, with zero additional cash/debt face.
    for r in sorted(result.releases, key=lambda r: (r.effective_on, r.id)):
        a = allocations[r.allocation_id]
        adjustment_rows.append(
            dict(
                effect_id=r.id,
                original_record_id=r.allocation_id,
                kind="allocation_release",
                effective_on=r.effective_on,
                invoice_id=a.invoice_id,
                payment_id=a.payment_id,
                account_id=originals[a.invoice_id].account_id,
                signed_cash_cents=0,
                signed_receivable_cents=0,
                released_cents=r.amount_cents,
                decision_id=r.decision_id,
                reverses_record_id=r.reversal_id,
                reason=r.reason,
            )
        )
    monthly_rows = monthly_rollforward(monthly, result.run.as_of)
    balance_rows = []
    for aid in sorted(account_totals):
        a = accounts[aid]
        totals = account_totals[aid]
        balance_rows.append(
            dict(
                customer_id=a.customer_id,
                customer_name=customers[a.customer_id].display_name,
                account_id=aid,
                contract_reference=a.contract_reference,
                energy_type=a.energy_type,
                original_cents=totals["original_cents"],
                correction_cents=totals["correction_cents"],
                adjusted_cents=totals["original_cents"] + totals["correction_cents"],
                allocated_cents=totals["allocated_cents"],
                outstanding_cents=totals["outstanding_cents"],
                identified_credit_cents=totals["identified_credit_cents"],
            )
        )
    case_rows = exception_rows(result, base, payments, decisions, live)
    decision_rows = [
        dict(
            decision_id=o.id,
            action=o.action,
            case_id=o.case_id,
            effective_on=o.effective_on,
            created_at_utc=o.created_at.isoformat(),
            actor=o.actor,
            reason=o.reason,
            note=o.note,
            reverses_decision_id=o.reverses_decision_id,
            details_json=json.dumps(o.payload, sort_keys=True),
        )
        for o in decisions
    ]
    # Each audit row occurs once; retain structured detail without treating it as cash.
    audit_rows = [
        dict(
            event_id=a["id"],
            occurred_at_utc=a["occurred_at"],
            actor=a["actor"],
            action=a["action"],
            entity_type=a["entity_type"],
            entity_id=a["entity_id"],
            payment_id=a["payment_id"],
            invoice_id=a["invoice_id"],
            account_id=a["account_id"],
            run_id=a["run_id"],
            reason=a["reason"],
            details_json=a["details_json"],
        )
        for a in audit
    ]
    tables = {
        "Invoice Register": invoice_rows,
        "Payment Register": payment_rows,
        "Allocation Details": allocation_rows,
        "Monthly Reconciliation": monthly_rows,
        "Exception Queue": case_rows,
        "Customer Balances": balance_rows,
        "Corrections and Reversals": adjustment_rows,
        "Audit Trail": audit_rows,
        "Manual Decisions": decision_rows,
    }
    checks = validate_totals(result.controls, tables)
    return Report(
        dict(
            dataset_id=result.run.dataset_id,
            snapshot_kind=header["kind"],
            run_id=result.run.id,
            as_of=result.run.as_of,
            known_at_utc=result.run.known_at.isoformat(),
            source_version_id=header["source_version_id"],
            rules_version=result.rules_version,
            result_sha256=result.run.result_sha256,
            input_sha256=result.run.input_sha256,
            case_status_basis="live current head"
            if live
            else "selected snapshot and eligible decisions",
            audit_scope="Operational history through export; may include later runs",
        ),
        dict(result.controls),
        tables,
        checks,
        aging,
    )


def exception_rows(result, base, payments, decisions, live):
    items = {
        stable_id("case", [result.run.dataset_id, e.subject_id, e.reason_code]): e
        for e in (*base.review_queue, *result.review_queue)
    }
    pending = {
        stable_id("case", [result.run.dataset_id, e.subject_id, e.reason_code])
        for e in result.review_queue
    }
    rows = []
    for case_id, item in sorted(items.items()):
        history = [o for o in decisions if o.case_id == case_id]
        status = (
            (
                "REOPENED"
                if history and history[-1].action == "reverse"
                else "IN_REVIEW"
                if history
                else "OPEN"
            )
            if case_id in pending
            else "RESOLVED"
        )
        if case_id in live:
            status = live[case_id]["status"]
        ensure(
            (status != "RESOLVED") == (case_id in pending), "Case status disagrees with snapshot"
        )
        p = payments[item.subject_id]
        rows.append(
            dict(
                case_id=case_id,
                payment_id=p.id,
                bank_event_id=p.bank_event_id,
                payment_reference=p.reference,
                booked_on=p.booked_on,
                category=item.reason_code,
                amount_cents=item.amount_cents if case_id in pending else 0,
                status=status,
                unresolved=case_id in pending,
                reason_code=item.reason_code,
                reason=item.explanation,
                candidate_evidence=json.dumps(
                    [c.model_dump(mode="json") for c in item.candidates], sort_keys=True
                ),
                review_history="\n".join(
                    f"{o.id}: {o.action}; {o.reason}; {o.note}" for o in history
                ),
                resolution_details="\n".join(
                    json.dumps(o.payload, sort_keys=True) for o in history
                ),
            )
        )
    return rows


def monthly_rollforward(flows, as_of):
    if not flows:
        return []
    month = min(flows)
    final = as_of.replace(day=1)
    rows, g, n, a = [], 0, 0, 0
    keys = [
        "issued_cents",
        "corrections_cents",
        "incoming_cents",
        "refund_cents",
        "chargeback_cents",
        "allocation_increases_cents",
        "releases_cents",
    ]
    while month <= final:
        f = flows[month]
        opening_o, opening_u = g - a, n - a
        adjusted = f["issued_cents"] + f["corrections_cents"]
        cash = f["incoming_cents"] - f["refund_cents"] - f["chargeback_cents"]
        allocated = f["allocation_increases_cents"] - f["releases_cents"]
        g, n, a = g + adjusted, n + cash, a + allocated
        rows.append(
            dict(
                month=month,
                period_end=min(
                    as_of,
                    date(month.year, month.month, calendar.monthrange(month.year, month.month)[1]),
                ),
                **{k: f[k] for k in keys},
                adjusted_activity_cents=adjusted,
                net_cash_activity_cents=cash,
                net_allocation_activity_cents=allocated,
                opening_outstanding_cents=opening_o,
                opening_unapplied_cents=opening_u,
                closing_adjusted_cents=g,
                closing_net_cash_cents=n,
                closing_allocated_cents=a,
                closing_unapplied_cents=n - a,
                closing_outstanding_cents=g - a,
            )
        )
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return rows


def validate_totals(c, tables):
    def total(sheet, key):
        return sum(r[key] for r in tables[sheet])

    values = {
        "original_invoice_cents": total("Invoice Register", "original_cents"),
        "signed_correction_cents": total("Invoice Register", "correction_cents"),
        "adjusted_receivables_cents": total("Invoice Register", "adjusted_cents"),
        "gross_incoming_cents": total("Payment Register", "received_cents"),
        "refund_cents": -sum(
            r["signed_cash_cents"]
            for r in tables["Corrections and Reversals"]
            if r["kind"] == "refund"
        ),
        "chargeback_cents": -sum(
            r["signed_cash_cents"]
            for r in tables["Corrections and Reversals"]
            if r["kind"] == "chargeback"
        ),
        "net_cash_cents": total("Payment Register", "net_cash_cents"),
        "net_allocated_cents": total("Allocation Details", "net_allocated_cents"),
        "unapplied_cents": total("Payment Register", "unapplied_cents"),
        "outstanding_cents": total("Invoice Register", "outstanding_cents"),
        "identified_credit_cents": total("Customer Balances", "identified_credit_cents"),
        "suspense_cents": sum(
            r["unapplied_cents"]
            for r in tables["Payment Register"]
            if not r["validated_account_id"]
        ),
    }
    checks = [
        dict(
            check="Database = export: " + key,
            expected_cents=c[key],
            actual_cents=v,
            difference_cents=v - c[key],
            status="PASS" if v == c[key] else "FAIL",
        )
        for key, v in values.items()
    ]
    diagnostics = {
        "Adjusted receivables = original invoices + corrections": values[
            "adjusted_receivables_cents"
        ]
        - values["original_invoice_cents"]
        - values["signed_correction_cents"],
        "Unapplied = identified credit + suspense": values["unapplied_cents"]
        - values["identified_credit_cents"]
        - values["suspense_cents"],
        "Customer outstanding = invoice outstanding": total(
            "Customer Balances", "outstanding_cents"
        )
        - values["outstanding_cents"],
        "Net cash = gross receipts - refunds - chargebacks": values["net_cash_cents"]
        - values["gross_incoming_cents"]
        + values["refund_cents"]
        + values["chargeback_cents"],
        "Net cash = net allocated + unapplied": values["net_cash_cents"]
        - values["net_allocated_cents"]
        - values["unapplied_cents"],
        "Adjusted receivables = net allocated + outstanding": values["adjusted_receivables_cents"]
        - values["net_allocated_cents"]
        - values["outstanding_cents"],
        "Customer allocation = invoice allocation": total("Customer Balances", "allocated_cents")
        - values["net_allocated_cents"],
        "Payment allocation = invoice allocation": total("Payment Register", "allocated_cents")
        - total("Invoice Register", "allocated_cents"),
        "Signed corrections = correction effects": values["signed_correction_cents"]
        - total("Corrections and Reversals", "signed_receivable_cents"),
    }
    if tables["Monthly Reconciliation"]:
        last = tables["Monthly Reconciliation"][-1]
        for a, b in [
            ("closing_adjusted_cents", "adjusted_receivables_cents"),
            ("closing_net_cash_cents", "net_cash_cents"),
            ("closing_allocated_cents", "net_allocated_cents"),
            ("closing_unapplied_cents", "unapplied_cents"),
            ("closing_outstanding_cents", "outstanding_cents"),
        ]:
            diagnostics["Month-end = snapshot: " + a] = last[a] - values[b]
    checks.extend(
        dict(
            check=k,
            expected_cents=0,
            actual_cents=v,
            difference_cents=v,
            status="PASS" if v == 0 else "FAIL",
        )
        for k, v in diagnostics.items()
    )
    return checks

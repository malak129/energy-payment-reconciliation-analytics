"""Read-only independent SQLite arithmetic audit. Run from repository root."""

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/phase7"


def digest(value):
    data = (
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    )
    return hashlib.sha256(data.encode()).hexdigest()


def audit(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as c:
        c.row_factory = sqlite3.Row
        assert c.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert not c.execute("pragma foreign_key_check").fetchall()
        records = list(c.execute("select * from source_records"))
        for row in records:
            assert digest(json.loads(row["payload_json"])) == row["payload_sha256"]
        for row in c.execute("select * from source_files"):
            assert hashlib.sha256(row["content"]).hexdigest() == row["sha256"]
        assert not c.execute(
            "select source_system,bank_event_id,count(*) from bank_events "
            "group by source_system,bank_event_id having count(*)>1"
        ).fetchall()
        run = c.execute(
            "select r.* from reconciliation_runs r join ledger_heads h on r.id=h.run_id"
        ).fetchone()
        result = json.loads(run["result_json"])
        for historical in c.execute("select * from reconciliation_runs"):
            body = json.loads(historical["result_json"])
            body.pop("run")
            assert digest(body) == historical["result_sha256"]
        selected = defaultdict(dict)
        for row in c.execute(
            "select s.* from source_records s join version_records v "
            "on s.id=v.record_id where v.version_id=?",
            (run["source_version_id"],),
        ):
            selected[row["table_name"]][row["id"]] = json.loads(row["payload_json"])
        # Full-knowledge audited snapshots only; reject unsupported cutoffs rather than infer.
        meta = json.loads(
            c.execute(
                "select metadata_json from source_versions where id=?", (run["source_version_id"],)
            ).fetchone()[0]
        )
        from datetime import datetime

        tables = {
            name: sorted(rows.values(), key=lambda v: v["id"]) for name, rows in selected.items()
        }
        input_hash = digest(
            {
                "manifest": meta["source_manifest_sha256"],
                "files": meta["source_hashes"],
                "dataset": run["dataset_id"],
                "records": tables,
                "availability": {
                    k: datetime.fromisoformat(v.replace("Z", "+00:00")).isoformat()
                    for k, v in meta["bank_known_at"].items()
                },
            }
        )
        for engine in c.execute("select * from reconciliation_runs where kind='ENGINE'"):
            assert engine["input_sha256"] == input_hash
            config = {
                "evaluation_date": engine["as_of"],
                "known_at": engine["known_at"],
                "rules_version": "reconciliation-1.0.0",
            }
            body = json.loads(engine["result_json"])
            assert digest(config) == body["run"]["config_sha256"]
            assert (
                engine["id"] == "syn_run_" + uuid5(NAMESPACE_URL, digest([input_hash, config])).hex
            )
        from datetime import datetime

        for ledger in c.execute("select * from reconciliation_runs where kind='LEDGER'"):
            base = c.execute(
                "select * from reconciliation_runs where id=?", (ledger["base_run_id"],)
            ).fetchone()
            identity = []
            for operation in c.execute(
                "select * from manual_decisions where dataset_id=? order by sequence",
                (ledger["dataset_id"],),
            ):
                if (
                    operation["action"] != "defer"
                    and operation["effective_on"] <= ledger["as_of"]
                    and datetime.fromisoformat(operation["created_at"].replace("Z", "+00:00"))
                    <= datetime.fromisoformat(ledger["known_at"])
                ):
                    payload = json.loads(operation["payload_json"])
                    payload.pop("origin_run_id", None)
                    identity.append(payload)
            assert ledger["input_sha256"] == digest([base["input_sha256"], identity])
            assert (
                ledger["id"]
                == "syn_run_"
                + uuid5(NAMESPACE_URL, digest([base["id"], "manual-overlay-1", identity])).hex
            )
        known = datetime.fromisoformat(run["known_at"])
        assert all(
            datetime.fromisoformat(t.replace("Z", "+00:00")) <= known
            for t in meta["bank_known_at"].values()
        )
        invoices = {k: v for k, v in selected["invoices"].items() if v["issued_on"] <= run["as_of"]}
        payments = {k: v for k, v in selected["payments"].items() if v["booked_on"] <= run["as_of"]}
        corrections = [
            v for v in selected["corrections"].values() if v["effective_on"] <= run["as_of"]
        ]
        reversals = [
            v for v in selected["refunds_chargebacks"].values() if v["booked_on"] <= run["as_of"]
        ]
        # Audit supported original/recovery fixtures contain manual allocation/undo only.
        assert not c.execute(
            "select 1 from manual_decisions where action in ('correction','refund','chargeback')"
        ).fetchone()
        apps = {
            r["id"]: json.loads(r["payload_json"])
            for r in c.execute(
                "select a.* from allocations a join run_allocations ra on a.id=ra.allocation_id "
                "where ra.run_id=?",
                (run["id"],),
            )
        }
        releases = [
            json.loads(r[0])
            for r in c.execute(
                "select a.payload_json from allocation_releases a join run_releases ra "
                "on a.id=ra.release_id where ra.run_id=?",
                (run["id"],),
            )
        ]
        pnet = {k: v["amount_cents"] for k, v in payments.items()}
        debt = {k: v["amount_cents"] for k, v in invoices.items()}
        # Independently accumulate dated entity stock deltas, not report monthly functions.
        movements = defaultdict(lambda: {"cash": defaultdict(int), "debt": defaultdict(int)})

        def event(day, kind, key, amount):
            movements[day[:7]][kind][key] += amount

        for k, v in invoices.items():
            event(v["issued_on"], "debt", k, v["amount_cents"])
        for k, v in payments.items():
            event(v["booked_on"], "cash", k, v["amount_cents"])
        for v in corrections:
            debt[v["invoice_id"]] += v["amount_cents"]
            event(v["effective_on"], "debt", v["invoice_id"], v["amount_cents"])
        for v in reversals:
            pnet[v["payment_id"]] -= v["amount_cents"]
            event(v["booked_on"], "cash", v["payment_id"], -v["amount_cents"])
        for v in apps.values():
            pnet[v["payment_id"]] -= v["amount_cents"]
            debt[v["invoice_id"]] -= v["amount_cents"]
            event(v["effective_on"], "cash", v["payment_id"], -v["amount_cents"])
            event(v["effective_on"], "debt", v["invoice_id"], -v["amount_cents"])
        released = defaultdict(int)
        for v in releases:
            a = apps[v["allocation_id"]]
            released[a["id"]] += v["amount_cents"]
            pnet[a["payment_id"]] += v["amount_cents"]
            debt[a["invoice_id"]] += v["amount_cents"]
            event(v["effective_on"], "cash", a["payment_id"], v["amount_cents"])
            event(v["effective_on"], "debt", a["invoice_id"], v["amount_cents"])
        assert all(n <= apps[k]["amount_cents"] for k, n in released.items())
        assert all(n >= 0 for n in [*pnet.values(), *debt.values()])
        assert debt == {v["invoice_id"]: v["outstanding_cents"] for v in result["invoices"]}
        assert pnet == {v["payment_id"]: v["unapplied_cents"] for v in result["payments"]}
        month_ends, stocks = {}, {"cash": defaultdict(int), "debt": defaultdict(int)}
        for month, kinds in sorted(movements.items()):
            for kind, entities in kinds.items():
                for key, n in entities.items():
                    stocks[kind][key] += n
                assert all(n >= 0 for n in stocks[kind].values())
            month_ends[month] = {kind: sum(v.values()) for kind, v in stocks.items()}
        account_debt = defaultdict(int)
        for key, n in debt.items():
            account_debt[invoices[key]["account_id"]] += n
        customer_debt = defaultdict(int)
        for key, n in account_debt.items():
            customer_debt[selected["accounts"][key]["customer_id"]] += n
        # This audited fixture has no active manual allocations. Independently attribute
        # remaining credit using a unique exact single reference plus account/date evidence.
        references = {v["reference"].strip().upper(): v for v in invoices.values()}
        credits = defaultdict(int)
        for key, n in pnet.items():
            if not n:
                continue
            p = payments[key]
            inv = references.get((p.get("reference") or "").strip().upper())
            if (
                inv
                and inv["issued_on"] <= p["booked_on"]
                and p.get("account_id") in (None, inv["account_id"])
            ):
                credits[inv["account_id"]] += n
        from energy_reconciliation.reporting.data import read_report

        report = read_report(path)
        flow_sources = {
            "issued_cents": [(v["issued_on"], v["amount_cents"]) for v in invoices.values()],
            "corrections_cents": [(v["effective_on"], v["amount_cents"]) for v in corrections],
            "incoming_cents": [(v["booked_on"], v["amount_cents"]) for v in payments.values()],
            "refund_cents": [
                (v["booked_on"], v["amount_cents"]) for v in reversals if v["kind"] == "refund"
            ],
            "chargeback_cents": [
                (v["booked_on"], v["amount_cents"]) for v in reversals if v["kind"] == "chargeback"
            ],
            "allocation_increases_cents": [
                (v["effective_on"], v["amount_cents"]) for v in apps.values()
            ],
            "releases_cents": [(v["effective_on"], v["amount_cents"]) for v in releases],
        }
        for row in report.tables["Customer Balances"]:
            assert row["outstanding_cents"] == account_debt[row["account_id"]]
            assert row["identified_credit_cents"] == credits[row["account_id"]]
        for row in report.tables["Monthly Reconciliation"]:
            month = str(row["period_end"])[:7]
            for key, dated in flow_sources.items():
                assert row[key] == sum(n for day, n in dated if day[:7] == month)
            if month in month_ends:
                assert row["closing_unapplied_cents"] == month_ends[month]["cash"]
                assert row["closing_outstanding_cents"] == month_ends[month]["debt"]
        assert all(
            v["display_name"].startswith("Synthetic") for v in selected["customers"].values()
        )
        assert all(v["synthetic_iban"].startswith("DE00") for v in selected["accounts"].values())
        gross = sum(v["amount_cents"] for v in payments.values())
        refunds = sum(v["amount_cents"] for v in reversals if v["kind"] == "refund")
        chargebacks = sum(v["amount_cents"] for v in reversals if v["kind"] == "chargeback")
        face = sum(v["amount_cents"] for v in invoices.values())
        corr = sum(v["amount_cents"] for v in corrections)
        net_a = sum(v["amount_cents"] for v in apps.values()) - sum(released.values())
        assert gross - refunds - chargebacks == net_a + sum(pnet.values())
        assert face + corr == net_a + sum(debt.values())
        controls = result["controls"]
        for key, n in {
            "net_allocated_cents": net_a,
            "unapplied_cents": sum(pnet.values()),
            "outstanding_cents": sum(debt.values()),
        }.items():
            assert controls[key] == n
        manual_a = sum(v["amount_cents"] for v in apps.values() if v.get("decision_id"))
        manual_r = sum(v["amount_cents"] for v in releases if v.get("decision_id"))
        return {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "run_id": run["id"],
            "source_records": len(records),
            "source_identity_sha256": digest(
                sorted((r["id"], r["payload_sha256"]) for r in records)
            ),
            "gross_payments_cents": gross,
            "refunds_cents": refunds,
            "chargebacks_cents": chargebacks,
            "invoice_face_cents": face,
            "signed_corrections_cents": corr,
            "net_allocated_cents": net_a,
            "unapplied_cents": sum(pnet.values()),
            "outstanding_cents": sum(debt.values()),
            "manual_allocated_cents": manual_a,
            "manual_released_cents": manual_r,
            "identified_credit_cents": sum(credits.values()),
            "suspense_cents": sum(pnet.values()) - sum(credits.values()),
            "month_ends": month_ends,
            "account_debt_cents": dict(account_debt),
            "customer_debt_cents": dict(customer_debt),
            "decisions": [
                dict(r)
                for r in c.execute("select id,action,reverses_decision_id from manual_decisions")
            ],
            "audit_ids": [r[0] for r in c.execute("select id from audit_events")],
        }


def main():
    paths = {
        "primary": "data/phase4-demo.sqlite3",
        "clean": "outputs/phase4-demo-backup.sqlite3",
        "incident": "outputs/phase6-recovery/audited-incident.sqlite3",
    }
    results = {key: audit(ROOT / value) for key, value in paths.items()}
    assert results["primary"] == results["clean"]
    p, i = results["primary"], results["incident"]
    assert set(p["audit_ids"]) <= set(i["audit_ids"])
    for key in (
        "net_allocated_cents",
        "unapplied_cents",
        "outstanding_cents",
        "account_debt_cents",
        "customer_debt_cents",
        "source_records",
        "source_identity_sha256",
    ):
        assert p[key] == i[key]
    assert i["manual_allocated_cents"] == i["manual_released_cents"]
    for result in results.values():
        result["audit_count"] = len(result.pop("audit_ids"))
    baseline = json.loads((OUT / "baseline/baseline.json").read_text())
    assert p["sha256"] == baseline["primary_sha256"]
    for relative, expected in baseline["source_hashes"].items():
        assert (
            hashlib.sha256((ROOT / "data/synthetic" / relative).read_bytes()).hexdigest()
            == expected
        )
    assert (
        hashlib.sha256((OUT / "baseline/primary.sqlite3").read_bytes()).hexdigest() == p["sha256"]
    )
    (OUT / "independent-audit.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Independent primary, clean backup and incident audits PASS")


if __name__ == "__main__":
    main()

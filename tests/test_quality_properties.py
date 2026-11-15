"""Independent arithmetic properties; deterministic seed, no oracle reads."""

from dataclasses import replace

from hypothesis import given, seed, settings
from hypothesis import strategies as st
from test_reconciliation import OPTIONS, invoice, payment, reversal, unit_data

from energy_reconciliation.reconciliation.engine import reconcile


@seed(20261115)
@settings(max_examples=100, deadline=None, database=None)
@given(face=st.integers(1, 10**8), amounts=st.lists(st.integers(1, 10**7), min_size=1, max_size=8))
def test_random_cash_conservation_order_and_determinism(face, amounts):
    data = unit_data(
        invoices=[invoice(amount=face)],
        payments=[payment(key=str(n), amount=a) for n, a in enumerate(amounts)],
    )
    result = reconcile(data, OPTIONS)
    allocated = min(face, sum(amounts))
    assert sum(i.allocated_cents for i in result.invoices) == allocated
    assert sum(i.outstanding_cents for i in result.invoices) == face - allocated
    assert sum(p.unapplied_cents for p in result.payments) == sum(amounts) - allocated
    assert all(p.unapplied_cents >= 0 for p in result.payments)
    shuffled = dict(data.tables)
    shuffled["payments"] = tuple(reversed(shuffled["payments"]))
    assert reconcile(replace(data, tables=shuffled), OPTIONS) == result
    assert reconcile(data, OPTIONS) == result


@seed(20261116)
@settings(max_examples=80, deadline=None, database=None)
@given(face=st.integers(1, 10**8), received=st.integers(1, 10**8), outflow=st.integers(1, 10**8))
def test_random_reversal_independent_cash_and_debt(face, received, outflow):
    outflow = min(outflow, received)
    result = reconcile(
        unit_data(
            invoices=[invoice(amount=face)],
            payments=[payment(amount=received)],
            reversals=[reversal(amount=outflow)],
        ),
        OPTIONS,
    )
    net = received - outflow
    assert sum(p.unapplied_cents for p in result.payments) == max(net - face, 0)
    assert sum(i.outstanding_cents for i in result.invoices) == max(face - net, 0)
    assert sum(a.amount_cents for a in result.allocations) - sum(
        r.amount_cents for r in result.releases
    ) == min(face, net)


@seed(20261117)
@settings(max_examples=60, deadline=None, database=None)
@given(amount=st.integers(1, 10**8), suffix=st.text(alphabet="ABCDEFGXYZ0123456789", min_size=1))
def test_plausible_amount_and_reference_never_suffice(amount, suffix):
    result = reconcile(
        unit_data(
            invoices=[invoice(amount=amount)],
            payments=[payment(amount=amount, reference="INV-001-" + suffix)],
        ),
        OPTIONS,
    )
    assert not result.allocations
    assert result.payments[0].unapplied_cents == amount

"""Independent cached-value/range inspection of the clean baseline workbook."""

import json
import re
from decimal import Decimal
from pathlib import Path
from xml.etree.ElementTree import tostring

import openpyxl
from openpyxl.utils.cell import range_boundaries

ROOT = Path(__file__).resolve().parents[1]


def main():
    expected = json.loads((ROOT / "outputs/phase7/independent-audit.json").read_text())["primary"]
    path = ROOT / "outputs/phase7/native-excel.xlsx"
    wb = openpyxl.load_workbook(path)
    cached = openpyxl.load_workbook(path, data_only=True)
    expected_sheets = [
        "Executive Summary",
        "Monthly Reconciliation",
        "Invoice Register",
        "Payment Register",
        "Allocation Details",
        "Exception Queue",
        "Customer Balances",
        "Corrections and Reversals",
        "Audit Trail",
        "Control Checks",
        "Data Dictionary and KPIs",
        "Manual Decisions",
    ]
    assert wb.sheetnames == expected_sheets
    summary = {
        7: expected["invoice_face_cents"] + expected["signed_corrections_cents"],
        8: expected["gross_payments_cents"],
        9: expected["refunds_cents"],
        10: expected["chargebacks_cents"],
        11: expected["gross_payments_cents"]
        - expected["refunds_cents"]
        - expected["chargebacks_cents"],
        12: expected["net_allocated_cents"],
        13: expected["unapplied_cents"],
        14: expected["outstanding_cents"],
    }
    for row, n in summary.items():
        assert Decimal(str(cached["Executive Summary"].cell(row, 2).value)) * 100 == n
    balances = cached["Customer Balances"]
    headers = {cell.value: n for n, cell in enumerate(balances[5])}
    seen = set()
    for row in balances.iter_rows(min_row=6, values_only=True):
        aid = row[headers["Account id"]]
        if not aid:
            continue
        assert aid not in seen
        seen.add(aid)
        assert Decimal(str(row[headers["Outstanding (EUR)"]])) * 100 == (
            expected["account_debt_cents"].get(aid, 0)
        )
    formulas = charts = chart_ranges = 0
    pattern = r"'([^']+)'!([$A-Z]+\$?\d+(?::[$A-Z]+\$?\d+)?)"

    def check_refs(text):
        count = 0
        for sheet, ref in re.findall(pattern, text):
            assert sheet in wb.sheetnames
            left, top, right, bottom = range_boundaries(ref.replace("$", ""))
            assert 1 <= left <= right <= wb[sheet].max_column
            assert 1 <= top <= bottom <= wb[sheet].max_row
            count += 1
        return count

    for ws in wb:
        for table in ws.tables.values():
            left, top, right, bottom = range_boundaries(table.ref)
            assert top == 5 and left == 1 and bottom == ws.max_row and right == ws.max_column
        for row in ws:
            for cell in row:
                if cell.data_type == "f":
                    assert "#REF!" not in cell.value
                    check_refs(cell.value)
                    assert cached[ws.title][cell.coordinate].value is not None
                    formulas += 1
        for chart in ws._charts:
            charts += 1
            chart_ranges += check_refs(tostring(chart.to_tree()).decode())
    assert charts == 3 and chart_ranges > 0 and formulas > 20
    wb.close()
    cached.close()
    result = {
        "sheets": len(expected_sheets),
        "charts": charts,
        "chart_ranges": chart_ranges,
        "formulas": formulas,
        "accounts": len(seen),
        "summary_values_checked": len(summary),
        "status": "PASS",
        "native_recalculation": False,
    }
    (ROOT / "outputs/phase7/workbook-audit.json").write_text(json.dumps(result, indent=2))
    print(result)


if __name__ == "__main__":
    main()

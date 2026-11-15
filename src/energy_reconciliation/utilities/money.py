"""Exact EUR boundaries. Import amounts must already have whole-cent precision."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

MAX_CENTS = 9_000_000_000_000_000  # Below SQLite signed 64-bit limit.


def euros_to_cents(value: str | Decimal) -> int:
    if not isinstance(value, (str, Decimal)):
        raise ValueError("Money must be a decimal string or Decimal")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Money must be decimal text") from exc
    if not amount.is_finite():
        raise ValueError("Money must be finite")
    if amount.copy_abs() > Decimal("90000000000000.00"):
        raise ValueError("Money exceeds supported range")
    with localcontext() as context:
        context.prec = 32
        quantized = amount.quantize(Decimal("0.01"))
        if amount != quantized:
            raise ValueError("Imported money must have whole-cent precision")
        return int(quantized * 100)


def round_euros(value: Decimal) -> Decimal:
    """Explicit commercial rounding for future calculated line amounts only."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Expected a finite Decimal")
    if value.copy_abs() > Decimal("90000000000000.00"):
        raise ValueError("Money exceeds supported range")
    with localcontext() as context:
        context.prec = 32
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

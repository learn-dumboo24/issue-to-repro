"""Parse and format rupee amounts. Internally every amount is an int number of paise."""

import re

_AMOUNT = re.compile(r"^(-)?(\d+)(?:\.(\d{1,2}))?$")


def parse_amount(text: str) -> int:
    """Parse "1,234.50", "₹ 99", "-12.75" into paise.

    Commas, spaces and a leading rupee sign are ignored.
    """
    cleaned = text.strip().replace(",", "").replace(" ", "").removeprefix("₹")
    match = _AMOUNT.match(cleaned)
    if not match:
        raise ValueError(f"not an amount: {text!r}")
    sign, rupees, paise = match.groups()
    value = int(rupees) * 100 + int((paise or "0").ljust(2, "0"))
    return -value if sign else value


def format_inr(paise: int) -> str:
    """Format paise as rupees with Indian digit grouping: 12345650 -> "₹1,23,456.50"."""
    sign = "-" if paise < 0 else ""
    rupees, rest = divmod(abs(paise), 100)
    digits = str(rupees)
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    grouped = ",".join(([head] if head else []) + groups + [tail])
    return f"{sign}₹{grouped}.{rest:02d}"

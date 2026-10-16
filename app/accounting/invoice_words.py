"""Small helpers for printing money on invoices: Indian digit grouping and amount in words."""

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
         "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_thousand(n: int) -> str:
    out = []
    if n >= 100:
        out.append(f"{_ONES[n // 100]} Hundred")
        n %= 100
    if n >= 20:
        out.append(_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else ""))
    elif n > 0:
        out.append(_ONES[n])
    return " ".join(out)


def _words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand")):
        if n >= size:
            parts.append(f"{_below_thousand(n // size)} {name}")
            n %= size
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def amount_in_words(amount: float) -> str:
    """Rupees Nine Thousand Nine Hundred Twenty Only / Rupees One Hundred and Fifty Paise Only."""
    amount = round(abs(float(amount or 0)), 2)
    rupees = int(amount)
    paise = int(round((amount - rupees) * 100))
    text = f"Rupees {_words(rupees)}"
    if paise:
        text += f" and {_words(paise)} Paise"
    return text + " Only"


def indian_number(value: float, decimals: int = 2) -> str:
    """12345678.9 -> 1,23,45,678.90 (lakh / crore grouping)."""
    neg = float(value or 0) < 0
    s = f"{abs(float(value or 0)):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + whole + (f".{frac}" if decimals else "")

"""Work out who pays whom so everyone ends up even."""


def settle_up(balances: dict[str, int]) -> list[tuple[str, str, int]]:
    """Turn net balances (positive = is owed, negative = owes) into payments.

    Returns (payer, payee, paise) tuples. The largest debtor pays the largest creditor first,
    which keeps the number of payments small.
    """
    if sum(balances.values()) != 0:
        raise ValueError("balances must add up to zero")
    creditors = sorted(((v, p) for p, v in balances.items() if v > 0), reverse=True)
    debtors = sorted(((-v, p) for p, v in balances.items() if v < 0), reverse=True)
    payments = []
    while creditors and debtors:
        owed, payee = creditors.pop(0)
        owes, payer = debtors.pop(0)
        amount = min(owed, owes)
        payments.append((payer, payee, amount))
        if owed > amount:
            creditors.insert(0, (owed - amount, payee))
        if owes > amount:
            debtors.insert(0, (owes - amount, payer))
    return payments

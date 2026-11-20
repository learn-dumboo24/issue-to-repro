"""Split a total among people."""


def split_equally(total: int, people: list[str]) -> dict[str, int]:
    """Split `total` paise equally. The shares always add up to `total`."""
    if not people:
        raise ValueError("need at least one person")
    if len(set(people)) != len(people):
        raise ValueError("people must be unique")
    share, leftover = divmod(total, len(people))
    return {person: share + (1 if i < leftover else 0) for i, person in enumerate(people)}


def split_by_shares(total: int, shares: dict[str, int]) -> dict[str, int]:
    """Split `total` paise in proportion to whole-number shares, e.g. {"Asha": 2, "Ravi": 1}.

    Leftover paise from rounding go to the people with the largest shares first, so the result
    always adds up to `total`.
    """
    if not shares or any(s <= 0 for s in shares.values()):
        raise ValueError("shares must be positive")
    weight = sum(shares.values())
    result = {person: total * s // weight for person, s in shares.items()}
    leftover = total - sum(result.values())
    for person in sorted(shares, key=lambda p: (-shares[p], p))[:leftover]:
        result[person] += 1
    return result

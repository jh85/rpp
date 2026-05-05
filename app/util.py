from __future__ import annotations


def last_name_of(full: str | None) -> str:
    """Family name of an author string.

    Handles 'Given Family', 'Family, Given', single-name authors,
    and multi-token surnames like 'van der Berg, Henk'.
    """
    if not full:
        return ""
    s = str(full).strip()
    if not s:
        return ""
    if "," in s:
        return s.split(",", 1)[0].strip()
    return s.split()[-1]


def year_of(date: str | None) -> str:
    """Leading 4-digit year from a date string ('2020-03-15' -> '2020')."""
    if not date:
        return ""
    s = str(date).strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return ""

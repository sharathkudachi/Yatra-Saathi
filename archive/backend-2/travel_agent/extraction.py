# travel_agent/extraction.py
"""Deterministic requirement extraction from a free-text goal.

This is the always-available path (tests, demo without an API key) and the
only source of the spend cap: the LLM is never allowed to set the budget.
"""
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from travel_agent.tools.city_tools import find_city_mentions

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9}
_PEOPLE_RE = r"(people|persons?|adults?|travell?ers?|pax|guests|of us)"
_CURRENCY_MARK = r"(₹|rs\.?|inr|rupees)"


def detect_language(text: str) -> Optional[str]:
    """BCP-47 tag from the script used, or None if Latin/unknown."""
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    if re.search(r"[ಀ-೿]", text):
        return "kn"
    if re.search(r"[஀-௿]", text):
        return "ta"
    return None


def _resolve_year(month: int, day: int, year: Optional[str], today: date) -> Optional[date]:
    try:
        if year:
            return date(int(year), month, day)
        candidate = date(today.year, month, day)
        return candidate if candidate >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def _find_dates(text: str, today: date) -> List[date]:
    found: List[Tuple[int, date]] = []
    for m in re.finditer(r"\b(20\d\d)-(\d{2})-(\d{2})\b", text):
        try:
            found.append((m.start(), date(int(m[1]), int(m[2]), int(m[3]))))
        except ValueError:
            continue
    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH_RE}(?:,?\s+(20\d\d))?", text, re.I):
        d = _resolve_year(_MONTHS[m[2].lower()[:3]], int(m[1]), m[3], today)
        if d:
            found.append((m.start(), d))
    for m in re.finditer(rf"\b{_MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(20\d\d))?", text, re.I):
        d = _resolve_year(_MONTHS[m[1].lower()[:3]], int(m[2]), m[3], today)
        if d and all(abs(pos - m.start()) > 3 for pos, _ in found):
            found.append((m.start(), d))
    return [d for _, d in sorted(found)]


def _find_nights(text: str) -> Optional[int]:
    """'3-day trip' / '3 nights' → 3 (same convention as agent_sessions.constraints_json)."""
    m = re.search(r"\b(\d{1,2})\s*-?\s*(days?|nights?)\b", text, re.I)
    if m:
        return int(m[1])
    return 7 if re.search(r"\ba week\b", text, re.I) else None


def _find_travellers(text: str) -> Optional[int]:
    m = re.search(rf"\b(\d{{1,2}})\s+{_PEOPLE_RE}\b", text, re.I)
    if m:
        return int(m[1])
    m = re.search(rf"\b({'|'.join(_NUMBER_WORDS)})\s+{_PEOPLE_RE}\b", text, re.I)
    if m:
        return _NUMBER_WORDS[m[1].lower()]
    if re.search(r"\b(solo|alone|just me|by myself)\b", text, re.I):
        return 1
    if re.search(r"\b(a couple|couple)\b", text, re.I):
        return 2
    return None


def _amount(number: str, scale: Optional[str]) -> str:
    value = number.replace(",", "")
    multiplier = {"k": 1000, "thousand": 1000, "l": 100000, "lakh": 100000, "lakhs": 100000}.get(
        (scale or "").lower(), 1)
    if multiplier == 1:
        return value
    whole, _, frac = value.partition(".")
    cents = int(whole or "0") * 100 + int((frac + "00")[:2])
    return f"{cents * multiplier // 100}.{cents * multiplier % 100:02d}"


def _find_budget(text: str, known_currencies: set) -> Tuple[Optional[str], Optional[str]]:
    """(amount string, ISO currency) for an explicit spend limit, else (None, None)."""
    number = (r"(\d[\d,]*(?:\.\d{1,2})?)\s*(k|thousand|lakhs?|l)?\b"
              r"(?!\s*-?\s*(?:days?|nights?|star|hours?|km|people|persons?|adults?|pax|guests|travell?ers?))")
    keyword = r"(?:under|below|within|budget(?:\s+of)?|max(?:imum)?(?:\s+of)?|up\s*to|less than|not more than|cap(?:\s+of)?)"
    patterns = [
        rf"{keyword}\s*:?\s*{_CURRENCY_MARK}?\s*{number}\s*([a-z]{{3}})?",
        rf"(){_CURRENCY_MARK}\s*{number}()",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        groups = m.groups()
        mark, num, scale, code = (groups[0], groups[1], groups[2], groups[3]) if len(groups) == 4 \
            else (groups[1], groups[2], groups[3], None)
        currency = "INR" if mark else None
        if code and code.upper() in known_currencies:
            currency = code.upper()
        elif code and code.lower() in ("inr", "rupees"):
            currency = "INR"
        return _amount(num, scale), currency
    return None, None


def parse_goal(text: str, today: date, known_currencies: Optional[set] = None) -> Dict[str, Any]:
    """Extract whatever the text states; absent fields are simply not returned."""
    fields: Dict[str, Any] = {}
    mentions = find_city_mentions(text)
    lowered = text.lower()
    for pos, name in mentions:
        before = lowered[max(0, pos - 6):pos]
        if "from" in before and "origin_name" not in fields:
            fields["origin_name"] = name
        elif re.search(r"\b(to|in|visit)\s*$", before) and "destination_name" not in fields:
            fields["destination_name"] = name
    remaining = [n for _, n in mentions if n not in fields.values()]
    if "origin_name" not in fields and "destination_name" not in fields and len(remaining) >= 2:
        fields["origin_name"], fields["destination_name"] = remaining[0], remaining[1]
    elif "destination_name" not in fields and remaining:
        fields["destination_name"] = remaining[0]
    elif "origin_name" not in fields and remaining:
        fields["origin_name"] = remaining[0]

    dates = _find_dates(text, today)
    nights = _find_nights(text)
    if dates:
        fields["start_date"] = dates[0].isoformat()
        if len(dates) > 1:
            fields["end_date"] = dates[1].isoformat()
        elif nights:
            fields["end_date"] = (dates[0] + timedelta(days=nights)).isoformat()
    if nights:
        fields["nights"] = nights

    travellers = _find_travellers(text)
    if travellers:
        fields["travellers"] = travellers

    amount, currency = _find_budget(text, known_currencies or {"INR"})
    if amount:
        fields["budget_amount"] = amount
        fields["budget_currency"] = currency or "INR"
    return fields

# travel_agent/extraction.py
"""Deterministic requirement extraction from a free-text goal.

This is the always-available path (tests, demo without an API key) and the
only source of the spend cap: the LLM is never allowed to set the budget.
"""
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_backend_dir = str(Path(__file__).resolve().parent.parent.parent / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from src.schemas.preferences import PreferenceItem, PreferenceProposal
from travel_agent.tools.city_tools import find_city_mentions

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_INDIC_TRANS = str.maketrans("०१२३४५६७८९௦௧௨௩௪௫௬௭௮௯", "01234567890123456789")


def _normalize_indic_digits(text: str) -> str:
    return text.translate(_INDIC_TRANS) if text else text


_INDIC_MONTHS = {
    "जनवरी": 1, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6,
    "जुलाई": 7, "अगस्त": 8, "सितंबर": 9, "अक्टूबर": 10, "अक्तूबर": 10, "नवंबर": 11, "दिसंबर": 12,
    "ஜனவரி": 1, "பிப்ரவரி": 2, "மார்ச்": 3, "ஏப்ரல்": 4, "மே": 5, "ஜூன்": 6,
    "ஜூலை": 7, "ஆகஸ்ட்": 8, "செப்டம்பர்": 9, "அக்டோபர்": 10, "நவம்பர்": 11, "டிசம்பர்": 12,
}

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9}
_PEOPLE_RE = r"(people|persons?|adults?|trav[a-z]*ers?|pax|guests|of us|लोग|व्यक्ति|यात्री|நபர்கள்|பயணிகள்|பேர்)"
_CURRENCY_MARK = r"(?:₹|rs\.?|inr|rupees|\$|€|£|रुपये|रुपए|रु|ரூபாய்)"
_MARK_CURRENCY = {"₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "rupees": "INR",
                  "रुपये": "INR", "रुपए": "INR", "रु": "INR", "ரூபாய்": "INR",
                  "$": "USD", "€": "EUR", "£": "GBP"}
# Words that mark a city as the origin / destination (tolerates common misspellings
# such as "depurture"). Checked against the text just before the city name.
_ORIGIN_CUE = r"\b(from|dep[a-z]*r[a-z]*|leaving|starting|start(?:ing)? (?:point|city)|origin|source|flying out of|से|இருந்து)\b"
_DEST_CUE = r"\b(dest[a-z]*|going to|travell?ing to|trip to|headed to|heading to|के लिए|को|க்கு|நோக்கி)\b"


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
    def add(position: int, value: Optional[date]) -> None:
        if value and all(abs(existing_position - position) > 3 for existing_position, _ in found):
            found.append((position, value))

    for m in re.finditer(r"\b(20\d\d)-(\d{2})-(\d{2})\b", text):
        try:
            add(m.start(), date(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            continue
    for m in re.finditer(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)\b", text):  # day-first (en-IN)
        try:
            add(m.start(), date(int(m[3]), int(m[2]), int(m[1])))
        except ValueError:
            continue
    for m in re.finditer(
        rf"\b(?:from\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+to\s+"
        rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH_RE}(?:,?\s+(20\d\d))?\b",
        text, re.I,
    ):
        month = _MONTHS[m[3].lower()[:3]]
        end = _resolve_year(month, int(m[2]), m[4], today)
        start = None
        if end:
            try:
                start = date(end.year, month, int(m[1]))
                if start > end and not m[4]:
                    start = date(end.year - 1, month, int(m[1]))
            except ValueError:
                start = None
        add(m.start(), start)
        add(m.start(2), end)
    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH_RE}(?:,?\s+(20\d\d))?", text, re.I):
        add(m.start(), _resolve_year(_MONTHS[m[2].lower()[:3]], int(m[1]), m[3], today))
    for m in re.finditer(rf"\b{_MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(20\d\d))?", text, re.I):
        d = _resolve_year(_MONTHS[m[1].lower()[:3]], int(m[2]), m[3], today)
        add(m.start(), d)
    for m in re.finditer(rf"(\d{{1,2}})\s*({'|'.join(_INDIC_MONTHS)})(?:\s+(20\d\d))?", text):
        month = _INDIC_MONTHS[m.group(2)]
        add(m.start(), _resolve_year(month, int(m.group(1)), m.group(3), today))
    for m in re.finditer(rf"({'|'.join(_INDIC_MONTHS)})\s*(\d{{1,2}})(?:\s+(20\d\d))?", text):
        month = _INDIC_MONTHS[m.group(1)]
        add(m.start(), _resolve_year(month, int(m.group(2)), m.group(3), today))
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
    multiplier = {
        "k": 1000, "thousand": 1000, "l": 100000, "lakh": 100000, "lakhs": 100000,
        "हजार": 1000, "हज़ार": 1000, "ஆயிரம்": 1000, "लाख": 100000, "லட்சம்": 100000,
    }.get((scale or "").lower(), 1)
    if multiplier == 1:
        return value
    whole, _, frac = value.partition(".")
    cents = int(whole or "0") * 100 + int((frac + "00")[:2])
    return f"{cents * multiplier // 100}.{cents * multiplier % 100:02d}"


def _find_budget(text: str, known_currencies: set) -> Tuple[Optional[str], Optional[str]]:
    """(amount string, ISO currency) for an explicit spend limit, else (None, None)."""
    scale_pat = r"k|thousand|lakhs?|l|हजार|हज़ार|ஆயிரம்|लाख|லட்சம்"
    number = (rf"(\d[\d,]*(?:\.\d{{1,2}})?)\s*({scale_pat})?(?:\b|(?=\s|$))"
              r"(?!\s*-?\s*(?:days?|nights?|stars?|hours?|km|people|persons?|adults?|pax|guests|trav[a-z]*ers?)\b)")
    keyword = (r"(?:under|below|within|budget(?:\s+(?:of|is|=))?|max(?:imum)?(?:\s+budget)?(?:\s+(?:of|is|=))?"
               r"|up\s*to|less than|not more than|cap(?:\s+(?:of|is|=))?"
               r"|बजट(?:\s*(?:का|है|=|:))?|तक|से कम|अधिकतम"
               r"|பட்ஜெட்(?:\s*(?:ஆக|=|:))?|வரை|குறைவாக)")
    patterns = [
        rf"{keyword}\s*:?\s*({_CURRENCY_MARK})?\s*{number}\s*([a-z]{{3}}|{_CURRENCY_MARK})?",
        rf"({_CURRENCY_MARK})?\s*{number}\s*({_CURRENCY_MARK})?\s*(?:का\s+)?{keyword}",
        rf"()({_CURRENCY_MARK})\s*{number}()",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        groups = m.groups()
        mark, num, scale, code = (groups[0], groups[1], groups[2], groups[3]) if len(groups) == 4 \
            else (groups[1], groups[2], groups[3], None)
        currency = _MARK_CURRENCY.get(mark.lower()) if mark else None
        if not currency and code:
            currency = _MARK_CURRENCY.get(code.lower())
            if not currency and code.upper() in known_currencies:
                currency = code.upper()
            elif not currency and code.lower() in ("inr", "rupees"):
                currency = "INR"
        if not currency and any(w in text for w in ["रुपये", "रुपए", "रु", "ரூபாய்"]):
            currency = "INR"
        return _amount(num, scale), currency
    return None, None


def _last_match(pattern: str, text: str) -> int:
    """Start of the last match of `pattern` in `text`, or -1."""
    starts = [m.start() for m in re.finditer(pattern, text)]
    return starts[-1] if starts else -1


def parse_goal(text: str, today: date, known_currencies: Optional[set] = None,
               cities: Optional[dict] = None) -> Dict[str, Any]:
    """Extract whatever the text states; absent fields are simply not returned.
    `cities` overrides the local-database city lookup (used when running
    through the backend's catalog instead of a local database)."""
    text = _normalize_indic_digits(text)
    fields: Dict[str, Any] = {}
    mentions = find_city_mentions(text, cities)
    lowered = text.lower()
    previous_end = 0
    for pos, name in mentions:
        # The words between the previous city mention (or 40 chars) and this one.
        before = lowered[max(previous_end, pos - 40):pos]
        previous_end = pos + len(name)
        # The cue closest to the city wins: "from Atlantis to Lucknow" makes Lucknow the destination.
        origin_at = _last_match(_ORIGIN_CUE, before)
        dest_at = max(_last_match(_DEST_CUE, before), _last_match(r"\b(to|in|visit)\s*$", before))
        if origin_at > dest_at and "origin_name" not in fields:
            fields["origin_name"] = name
        elif dest_at > origin_at and "destination_name" not in fields:
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
    if len(dates) == 1 and re.search(r"\b(return\w*|back|until|till|coming home|end date)\b", lowered):
        fields["end_date"] = dates[0].isoformat()  # "return on 19/11/2026" answers the return leg
    elif dates:
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
        # None when no currency is stated: the budget is then in the trip's own currency.
        fields["budget_currency"] = currency
    return fields


# --- choosing between offered packages, and what the user cares about -------------------

_PREFERENCES = (
    ("value", r"\b(cheap(er|est)?|budget|lower (price|cost)|less expensive|save money|economical|affordable)\b"),
    ("comfort", r"\b(comfort(able)?|luxur(y|ious)|better hotel|nicer hotel|upgrade|5[- ]?star|premium|best hotel)\b"),
    ("timing", r"\b(convenient|shortest|non-?stop|direct flights?|faster|quick(er|est)?|flight times?|timing)\b"),
)
_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "one": 1, "two": 2, "three": 3}
_LABEL_KEYS = {"value": r"best value|cheapest", "comfort": r"comfort(able)?", "timing": r"(best )?timing"}


def find_preference(text: str) -> Optional[str]:
    """Which kind of option the user wants to lead with ('value' | 'comfort' | 'timing'), or
    'cheapest' when they ask for something cheaper than what they were shown."""
    if re.search(r"\b(cheaper|less expensive|lower (price|cost)|reduce|cut (the )?cost)\b", text, re.I):
        return "cheapest"
    for key, pattern in _PREFERENCES:
        if re.search(pattern, text, re.I):
            return key
    return None


def wants_other_hotels(text: str) -> bool:
    return bool(re.search(r"\b(other|different|another|more|new)\s+(hotels?|stays?|rooms?|places to stay)\b", text, re.I))


def pick_option(text: str, packages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The package the user chose from `packages` (offered last turn), if the text is a choice."""
    if not packages:
        return None
    lowered = text.strip().lower()
    index = None
    m = re.fullmatch(r"#?\s*([1-9])\s*[.!]?", lowered)
    if m:
        index = int(m[1])
    for m in re.finditer(r"\b(?:option|package|plan|choice|number|no\.?|#)\s*#?\s*([1-9]|one|two|three)\b", lowered):
        index = int(m[1]) if m[1].isdigit() else _ORDINALS[m[1]]
    m = re.search(r"\b(first|1st|second|2nd|third|3rd)\b(\s+(one|option|package|plan))?", lowered)
    if index is None and m and (m[2] or re.search(r"\b(choose|pick|take|go with|book|select|want|prefer|like)\b", lowered)):
        index = _ORDINALS[m[1]]
    if index is None and re.search(r"\b(choose|pick|take|go with|book|select|want|prefer)\b", lowered):
        for pkg in packages:
            if re.search(rf"\b({_LABEL_KEYS.get(pkg['key'], pkg['key'])})\b", lowered):
                return pkg
    if index is not None and 1 <= index <= len(packages):
        return packages[index - 1]
    return None


def find_flight_time(text: str) -> Optional[str]:
    """'morning' | 'afternoon' | 'evening' when the user states a preferred flight time."""
    m = re.search(r"\b(morning|afternoon|evening|night|late)\s*(flights?|departures?)?\b", text, re.I)
    if not m or not (m[2] or re.search(r"\b(flights?|fly|leave|depart)", text, re.I)):
        return None
    word = m[1].lower()
    return "evening" if word in ("evening", "night", "late") else word


# --- Phase 3 Comparison & Optimization Intent Extraction -------------------


def find_comparison_intent(text: str) -> Optional[Dict[str, Any]]:
    """Detect if the user is asking a travel option comparison or trade-off question."""
    lowered = text.strip().lower()
    cat = None
    if re.search(r"\b(which (?:is|option is|one is|hotel is)?\s*(?:the\s+)?cheapest|what(?:'s|\s+is)\s+(?:the\s+)?cheapest|show (?:me\s+)?(?:the\s+)?cheapest)\b", lowered):
        cat = "cheapest"
    elif re.search(r"\b(which (?:is|option is|hotel gives)?\s*(?:the\s+)?best value|what(?:'s|\s+is)\s+(?:the\s+)?best value)\b", lowered):
        cat = "best_value"
    elif re.search(r"\b(which (?:is|option is)?\s*(?:the\s+)?fastest|what(?:'s|\s+is)\s+(?:the\s+)?fastest|quickest|give me the fastest)\b", lowered):
        cat = "fastest"
    elif re.search(r"\b(which (?:is|option is)?\s*(?:the\s+)?(most comfortable|comfort|best hotel|nicest)|make (?:the trip|it) more comfortable)\b", lowered):
        cat = "comfort"
    elif re.search(r"\b(best balance between price and (?:travel\s+)?time|balanced|show (?:me\s+)?(?:three|3|all)\s+options|which option is better)\b", lowered):
        cat = "balanced"
    elif re.search(r"\b(compare|comparison|trade-?offs?)\b", lowered):
        cat = "balanced"

    if cat is not None:
        return {"intent": "compare", "category": cat, "mode": cat}
    return None


def find_optimization_intent(text: str) -> Optional[Dict[str, Any]]:
    """Detect if the user is asking to optimize the budget, make it cheaper, or upgrade comfort."""
    lowered = text.strip().lower()

    # Allowed changes detection
    allowed = {"flight": True, "hotel": True, "activities": False, "dates": False}
    if re.search(r"\bkeep (the )?hotel\b", lowered):
        allowed["hotel"] = False
    if re.search(r"\bkeep (the )?(flights?|plane)\b", lowered):
        allowed["flight"] = False

    # Target budget extraction (e.g. "below ₹45,000")
    target_budget = None
    m_budget = re.search(r"\b(below|under|less than)\s*(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{3})*|\d+)\b", lowered)
    if m_budget:
        val = m_budget[2].replace(",", "")
        target_budget = f"{val}.00"

    if re.search(r"\b(make (it|the trip|this trip) cheaper|cheaper please|reduce (the )?(total )?cost|cut (the )?cost|optimize (the )?budget)\b", lowered):
        return {"objective": "cheaper", "allowed_changes": allowed, "target_budget": target_budget}
    if re.search(r"\b(make (it|the trip) more comfortable|upgrade (the )?hotel|more comfortable without exceeding)\b", lowered):
        return {"objective": "comfort", "allowed_changes": allowed, "target_budget": target_budget}
    if "cheaper flights" in lowered:
        return {"objective": "cheaper", "allowed_changes": {"flight": True, "hotel": False, "activities": False, "dates": False}, "target_budget": target_budget}
    if "better hotel" in lowered or "cheaper hotel" in lowered:
        return {"objective": "cheaper" if "cheaper" in lowered else "comfort", "allowed_changes": {"flight": False, "hotel": True, "activities": False, "dates": False}, "target_budget": target_budget}

    return None


# --- Phase 4 Preference Extraction & Proposal Generation -------------------


def extract_preference_proposal(text: str) -> PreferenceProposal:
    """Deterministically extract structured travel preferences into a PreferenceProposal.

    Flow: User text -> AI interpretation -> Structured Proposal -> Backend validation.
    AI proposes; backend validates and persists.
    """
    lowered = text.strip().lower()

    # Injection defense: detect instructions to override, leak, or execute
    injection_patterns = (
        r"ignore (all )?(your )?(system )?instructions",
        r"reveal (your )?(system )?prompt",
        r"another user('s)? (hotel )?preferences",
        r"access someone else",
        r"hidden hotels",
        r"override the backend",
        r"fake coordinates",
        r"\bselect\b.*\bfrom\b",
        r"\bunion\b.*\bselect\b",
        r"\bdrop\b\s+\btable\b",
    )
    if any(re.search(pat, lowered) for pat in injection_patterns):
        return PreferenceProposal(
            proposal_id="prop_sanitized",
            preferences=[],
            explanation="Security check: Untrusted prompt injection or system override detected and safely ignored.",
            requires_confirmation=False,
            is_ambiguous=False,
            clarification_question=None,
        )

    # Ambiguity check: user expresses vague unactionable preference
    ambiguous_patterns = (
        r"\b(maybe|perhaps|not sure|whatever|anything|something different)\b",
        r"\bi guess (whatever|anything)\b",
        r"\bjust pick whatever\b",
        r"\bmaybe a hotel\?*$",
    )
    if any(re.search(pat, lowered) for pat in ambiguous_patterns):
        return PreferenceProposal(
            proposal_id="prop_ambiguous",
            preferences=[],
            explanation="Statement is ambiguous and requires user clarification.",
            requires_confirmation=False,
            is_ambiguous=True,
            clarification_question="Could you clarify your preferred travel style, hotel rating, or pace?",
        )

    preferences: list[dict] = []
    explanations: list[str] = []

    # 1. Direct flight preference
    if re.search(r"\b(only direct|must be direct|direct flights? only|non-?stop only)\b", lowered):
        preferences.append({
            "preference_key": "direct_flights_only",
            "value": True,
            "is_hard": True,
            "priority": "hard",
            "confidence": 1.0,
            "source": "explicit_user",
        })
        explanations.append("Require non-stop direct flights only")
    elif re.search(r"\b(prefer|like|want|love|usually (take|fly))\s+(direct|non-?stop)\s+flights?\b|\bi (like|prefer)\s+direct flights?\b|सीधी उड़ान|डायरेक्ट फ्लाइट|நேரடி விமானம்", lowered):
        preferences.append({
            "preference_key": "direct_flights_only",
            "value": True,
            "is_hard": False,
            "priority": "high",
            "confidence": 0.9,
            "source": "explicit_user",
        })
        explanations.append("Prefer direct flights")

    # 2. Hotel quality / star rating
    m_hard_star = re.search(r"\b(need|require|must have|only)\s+(a\s+)?([345])[- ]?star\b", lowered)
    m_soft_star = re.search(r"\b(prefer|like|want|usually (prefer|stay in|book))\s+(a\s+)?([345])[- ]?star(\+)?\b|\b([345])[- ]?star\+?\s+hotels?\b", lowered)
    m_good_hotel = re.search(r"\b(usually prefer good hotels|prefer good hotels|like good hotels|nice hotels?)\b", lowered)

    if m_hard_star:
        stars = float(m_hard_star.group(3))
        preferences.append({
            "preference_key": "min_hotel_star_rating",
            "value": stars,
            "is_hard": True,
            "priority": "hard",
            "confidence": 1.0,
            "source": "explicit_user",
        })
        explanations.append(f"Require at least {int(stars)}-star hotel accommodation")
    elif m_soft_star:
        stars = float(m_soft_star.group(4) or m_soft_star.group(6) or 4.0)
        preferences.append({
            "preference_key": "min_hotel_star_rating",
            "value": stars,
            "is_hard": False,
            "priority": "high",
            "confidence": 0.9,
            "source": "explicit_user",
        })
        explanations.append(f"Prefer {int(stars)}-star or higher hotels")
    elif m_good_hotel:
        preferences.append({
            "preference_key": "min_hotel_star_rating",
            "value": 4.0,
            "is_hard": False,
            "priority": "high",
            "confidence": 0.85,
            "source": "explicit_user",
        })
        explanations.append("Prefer higher-quality 4-star+ hotels")

    # 3. Pacing
    if re.search(r"\b(relaxed|unhurried|not too much rushing|don't like packed|not packed|not rushed|take it easy|slow pace)\b|आराम से|आरामदायक|निதானமான", lowered):
        preferences.append({
            "preference_key": "preferred_daily_pace",
            "value": "relaxed",
            "is_hard": False,
            "priority": "high",
            "confidence": 0.95,
            "source": "explicit_user",
        })
        explanations.append("Relaxed itinerary pace with unhurried daily activities")
    elif re.search(r"\b(packed|fast pace|cover everything|see as much as possible)\b|जल्दी|तेज़|வேகமான", lowered):
        preferences.append({
            "preference_key": "preferred_daily_pace",
            "value": "fast",
            "is_hard": False,
            "priority": "medium",
            "confidence": 0.9,
            "source": "explicit_user",
        })
        explanations.append("Fast-paced itinerary covering maximum sights")

    # 4. Activity categories
    cats = []
    if re.search(r"\b(sightseeing|more sightseeing|top attractions?|landmarks?)\b", lowered):
        cats.append("sightseeing")
    if re.search(r"\b(cultur(e|al)|historic(al)?|heritage|monuments?|museums?)\b", lowered):
        cats.append("culture")
    if re.search(r"\b(nature|parks?|wildlife|outdoors?|gardens?)\b", lowered):
        cats.append("nature")
    if re.search(r"\b(food|culinary|dining|street food|tasting)\b", lowered):
        cats.append("food")
    if re.search(r"\b(adventure|zipline|hiking|rafting)\b", lowered):
        cats.append("adventure")
    if re.search(r"\b(relaxation|spa|wellness|beach)\b", lowered):
        cats.append("relaxation")

    if cats:
        preferences.append({
            "preference_key": "preferred_activity_categories",
            "value": cats,
            "is_hard": False,
            "priority": "high",
            "confidence": 0.9,
            "source": "explicit_user",
        })
        explanations.append(f"Focus on {', '.join(cats)} activities")

    # 5. Priorities (comfort vs price)
    if re.search(r"\b(keep (the trip|it) comfortable|comfort is (the )?priority|prioritize comfort)\b", lowered):
        preferences.append({
            "preference_key": "comfort_priority",
            "value": "high",
            "is_hard": False,
            "priority": "high",
            "confidence": 0.9,
            "source": "explicit_user",
        })
        explanations.append("Prioritize travel comfort and accommodation quality")
    if re.search(r"\b(price is more important than comfort|don't spend too much on hotels|budget is priority|budget-?conscious)\b", lowered):
        preferences.append({
            "preference_key": "price_priority",
            "value": "high",
            "is_hard": False,
            "priority": "high",
            "confidence": 0.9,
            "source": "explicit_user",
        })
        preferences.append({
            "preference_key": "budget_sensitivity",
            "value": "high",
            "is_hard": False,
            "priority": "high",
            "confidence": 0.9,
            "source": "explicit_user",
        })
        explanations.append("Prioritize competitive price and budget sensitivity")

    # 6. Hotel change preference
    if re.search(r"\b(don't make me change hotels|don't change hotels?|dont change hotels?|single hotel|same hotel throughout)\b", lowered):
        preferences.append({
            "preference_key": "dont_change_hotels",
            "value": True,
            "is_hard": False,
            "priority": "high",
            "confidence": 0.95,
            "source": "explicit_user",
        })
        explanations.append("Avoid changing hotels during the stay")

    if not preferences:
        return PreferenceProposal(
            proposal_id="prop_none",
            preferences=[],
            explanation="No specific travel preferences detected in text.",
            requires_confirmation=False,
            is_ambiguous=False,
            clarification_question=None,
        )

    summary = "; ".join(explanations)
    return PreferenceProposal(
        proposal_id="prop_" + str(abs(hash(summary)))[:8],
        preferences=[PreferenceItem(**p) for p in preferences],
        explanation=summary,
        requires_confirmation=False,
        is_ambiguous=False,
        clarification_question=None,
    )



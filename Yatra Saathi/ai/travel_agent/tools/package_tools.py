# travel_agent/tools/package_tools.py
"""Three trip packages for the user to choose from, built from the search results.

  value    -- cheapest flights + cheapest room that fits
  comfort  -- best-rated hotel, daytime flights
  timing   -- nonstop/shortest daytime flights, hotel closest to the centre

Every package must fit the hard cap (tax included); a package that duplicates an earlier one
is swapped for the next-best distinct combination, so the user sees real alternatives. Prices
here are the agent's own estimate for ranking and display -- the backend re-prices whatever
is chosen before anything reaches the cart.
"""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

TAX_BP_DEFAULT = 1200
LABELS = {"value": "Best value", "comfort": "Most comfortable", "timing": "Best timing"}


def _hour(fare: Dict[str, Any]) -> int:
    try:
        return int(str(fare["departs_at"])[11:13])
    except (KeyError, ValueError):
        return 12


def _daytime(fare: Dict[str, Any]) -> bool:
    return 7 <= _hour(fare) <= 20


def price(outbound, ret, hotel, travellers: int, tax_bp: int = TAX_BP_DEFAULT) -> Dict[str, Decimal]:
    subtotal = (Decimal(outbound["unit_price"]) + Decimal(ret["unit_price"])) * travellers \
        + sum((Decimal(n["price"]) * hotel["rooms"] for n in hotel["nightly"]), Decimal("0.00"))
    tax = (subtotal * tax_bp / Decimal(10000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"subtotal": subtotal, "tax": tax, "total": subtotal + tax}


WINDOWS = {"morning": (5, 12), "afternoon": (12, 17), "evening": (17, 24)}


def _flight_rank(style: str, flight_time: Optional[str] = None):
    lo, hi = WINDOWS.get(flight_time or "", (0, 24))
    outside = lambda f: not (lo <= _hour(f) < hi)  # the user's preferred time of day comes first
    if style == "comfort":
        return lambda f: (outside(f), not _daytime(f), f.get("cabin_class") != "economy", Decimal(f["unit_price"]))
    if style == "timing":
        return lambda f: (outside(f), f.get("stops", 0), not _daytime(f), f.get("duration_minutes") or 9999,
                          Decimal(f["unit_price"]))
    return lambda f: (outside(f), f.get("cabin_class") != "economy", Decimal(f["unit_price"]), _hour(f))


def _hotel_rank(style: str):
    if style == "comfort":
        return lambda h: (-(h.get("guest_score") or 0), -(h.get("star_rating") or 0), Decimal(h["total_price"]))
    if style == "timing":
        return lambda h: (h.get("distance_to_centre_km") if h.get("distance_to_centre_km") is not None else 99,
                          -(h.get("guest_score") or 0))
    return lambda h: (Decimal(h["total_price"]), -(h.get("guest_score") or 0))


def build_packages(outbound: Sequence[dict], returns: Sequence[dict], hotels: Sequence[dict], *,
                   travellers: int, cap: Optional[Decimal], tax_bp: int = TAX_BP_DEFAULT,
                   styles: Iterable[str] = ("value", "comfort", "timing"),
                   exclude_hotels: Iterable[str] = (), flight_time: Optional[str] = None) -> List[Dict[str, Any]]:
    excluded = set(exclude_hotels)
    hotels = [h for h in hotels if h.get("hotel_id") not in excluded] or list(hotels)
    if not outbound or not returns or not hotels:
        return []
    packages: List[Dict[str, Any]] = []
    seen: set = set()
    used_hotels: set = set()

    def connects(out: dict, ret: dict) -> bool:
        # The return flight must leave after the outbound one lands (instants, not dates).
        try:
            return datetime.fromisoformat(str(ret["departs_at"])) > datetime.fromisoformat(str(out["arrives_at"]))
        except (KeyError, TypeError, ValueError):
            return True

    def first_fit(style: str, new_hotel_only: bool):
        # Walk the style's preferred combinations until one fits the cap and is new.
        for out in sorted(outbound, key=_flight_rank(style, flight_time))[:6]:
            for ret in sorted(returns, key=_flight_rank(style, flight_time))[:6]:
                for hotel in sorted(hotels, key=_hotel_rank(style))[:20]:
                    key = (out["fare_id"], ret["fare_id"], hotel["room_type_id"])
                    if key in seen or not connects(out, ret) or (new_hotel_only and hotel.get("hotel_id") in used_hotels):
                        continue
                    cost = price(out, ret, hotel, travellers, tax_bp)
                    if cap is None or cost["total"] <= cap:
                        return key, out, ret, hotel, cost
        return None

    for style in styles:
        # Prefer a different hotel for each option; fall back to another room in the same one.
        best = first_fit(style, True) or first_fit(style, False)
        if best:
            key, out, ret, hotel, cost = best
            seen.add(key)
            used_hotels.add(hotel.get("hotel_id"))
            repeat = sum(1 for p in packages if p["key"].split("-")[0] == style)
            label = LABELS.get(style, style.title()) if not repeat else \
                ("Next best value", "Also good value")[min(repeat, 2) - 1] if style == "value" else f"{LABELS.get(style, style)} #{repeat + 1}"
            packages.append({"key": style if not repeat else f"{style}-{repeat + 1}", "label": label,
                             "outbound": out, "return": ret, "hotel": hotel, **cost})
    return packages


def _clock(ts: str) -> str:
    return str(ts)[11:16]


def _day(ts: str) -> str:
    from datetime import date
    try:
        d = date.fromisoformat(str(ts)[:10])
        return f"{d.day} {d.strftime('%b')}"
    except ValueError:
        return str(ts)[:10]


def describe(pkg: Dict[str, Any], index: int, currency: str, travellers: int, fmt) -> str:
    """One option, spelled out for the chat."""
    out, ret, h = pkg["outbound"], pkg["return"], pkg["hotel"]

    def leg(f):
        stops = "nonstop" if not f.get("stops") else f"{f['stops']} stop(s)"
        mins = f.get("duration_minutes") or 0
        return (f"{f['airline']} {f['flight_number']}, {_day(f['departs_at'])} {_clock(f['departs_at'])}→"
                f"{_clock(f['arrives_at'])} ({stops}, {mins // 60}h{mins % 60:02d}m, {f.get('cabin_class', 'economy')})")
    stars = f"{h.get('star_rating')}★, " if h.get("star_rating") else ""
    score = f"guest score {h['guest_score']}, " if h.get("guest_score") is not None else ""
    near = f"{h['distance_to_centre_km']} km from centre, " if h.get("distance_to_centre_km") is not None else ""
    return (f"{index}. {pkg['label']} — {fmt(pkg['total'], currency)} for {travellers} (incl. tax)\n"
            f"   ✈ Out: {leg(out)}\n   ✈ Back: {leg(ret)}\n"
            f"   🏨 {h['hotel_name']} · {h['room_name']} ({stars}{score}{near}{h['nights']} nights, {h['rooms']} room(s))")


def _no_floats(x):
    """The backend's hash-chained audit trail refuses floats: send decimals as text."""
    if isinstance(x, float):
        return f"{x:g}"
    if isinstance(x, dict):
        return {k: _no_floats(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_no_floats(v) for v in x]
    return x


def card(pkg: Dict[str, Any], index: int, currency: str) -> Dict[str, Any]:
    """Structured form for the UI (JSON-safe, no floats)."""
    return _no_floats(_card(pkg, index, currency))


def _card(pkg: Dict[str, Any], index: int, currency: str) -> Dict[str, Any]:
    def f(fare):
        return {"airline": fare["airline"], "flight_number": fare["flight_number"], "departs_at": str(fare["departs_at"]),
                "arrives_at": str(fare["arrives_at"]), "stops": fare.get("stops", 0),
                "duration_minutes": fare.get("duration_minutes"), "cabin_class": fare.get("cabin_class"),
                "from": fare.get("origin_iata"), "to": fare.get("destination_iata"),
                "refundable": bool(fare.get("refundable"))}
    h = pkg["hotel"]
    return {"index": index, "key": pkg["key"], "label": pkg["label"], "currency": currency,
            "total": f"{pkg['total']:.2f}", "subtotal": f"{pkg['subtotal']:.2f}", "tax": f"{pkg['tax']:.2f}",
            "outbound": f(pkg["outbound"]), "return": f(pkg["return"]),
            "hotel": {"name": h["hotel_name"], "room": h["room_name"], "stars": h.get("star_rating"),
                      "guest_score": h.get("guest_score"), "distance_km": h.get("distance_to_centre_km"),
                      "nights": h["nights"], "rooms": h["rooms"], "total": f"{Decimal(h['total_price']):.2f}"}}


def to_json(pkg: Dict[str, Any]) -> Dict[str, Any]:
    """Package with Decimals as strings, for the agent's saved state between turns."""
    def clean(x):
        if isinstance(x, Decimal):
            return f"{x:.2f}"
        if isinstance(x, float):  # the backend's saved state (checksummed) refuses floats
            return f"{x:g}"
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items() if k != "offer_ref"}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x
    return clean(pkg)

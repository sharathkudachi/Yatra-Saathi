"""Intelligent travel comparison, transparent scoring, trade-off analysis, and budget optimization (Phase 3).

Strict Principles:
- The AI proposes; the backend calculates and validates; the user decides.
- Factual and authoritative money calculations use src.core.money only (no floating-point money math).
- Clear separation between authoritative costs and advisory/estimated costs.
- Transparent, deterministic, explainable scoring formulas.
- Hard constraints (dates, destination, party size, currency) are never silently violated.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any, Optional, Union

from src.core import dates, fx, money
from src.core.clock import Clock
from src.contracts.codes import RefusalError
from src.core.ids import new_id
from src.db.repositories import catalog as catalog_repo
from src.schemas.comparison import (
    ApplyOptionRequest,
    ComparisonCategory,
    CompareTravelOptionsRequest,
    CompareTravelOptionsResponse,
    FlightComparisonDetail,
    HotelComparisonDetail,
    OptimizeTripRequest,
    OptimizeTripResponse,
    PlanDiff,
    ScoreBreakdown,
    TravelOption,
)
from src.schemas.itinerary import (
    AccommodationStay,
    ActivityCategory,
    ItineraryActivity,
    ItineraryDay,
    ItineraryStatus,
    ItemSource,
    TransportSegment,
    TransportType,
    TripPlan,
)
from src.services import itinerary_service
from src.services import search_service


def _extract_flight_detail(seg: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not seg:
        return None
    return {
        "carrier": seg.get("airlineName") or seg.get("carrier") or "Airline",
        "flight_number": seg.get("flightNumber") or seg.get("reference") or "",
        "departs_at": seg.get("departsAt") or seg.get("departs_at") or "",
        "arrives_at": seg.get("arrivesAt") or seg.get("arrives_at") or "",
        "duration_minutes": seg.get("durationMinutes") if seg.get("durationMinutes") is not None else seg.get("duration_minutes"),
        "stops": seg.get("stops", 0),
        "origin_code": seg.get("originCode") or seg.get("origin_code"),
        "dest_code": seg.get("destinationCode") or seg.get("dest_code"),
        "price": seg.get("price") or seg.get("known_price") or "0.00",
        "fare_id": seg.get("fareId") or seg.get("reference"),
    }


def compare_travel_options(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    req: CompareTravelOptionsRequest,
) -> CompareTravelOptionsResponse:
    """Deterministically find, combine, score, and rank travel options based on backend facts."""
    # Validate cities against authoritative catalog
    aliases = {"goa": "Panaji", "delhi": "New Delhi"}
    dest_name = aliases.get(req.destination.strip().lower(), req.destination.strip())
    dest_city = catalog_repo.find_city_by_name(conn, dest_name)
    if not dest_city:
        raise RefusalError("STATE_INVALID", f"Destination city '{req.destination}' is not recognized.")

    orig_name = aliases.get(req.origin.strip().lower(), req.origin.strip())
    orig_city = catalog_repo.find_city_by_name(conn, orig_name)
    if not orig_city:
        raise RefusalError("STATE_INVALID", f"Origin city '{req.origin}' is not recognized.")

    itinerary_service.record_itinerary_event(
        conn, clock, None, user_id,
        "COMPARISON_REQUESTED",
        req.model_dump(mode="json"),
        {},
    )

    # 1. Fetch flight candidates
    outbound_flights = search_service.search_flights(
        conn,
        origin_city=req.origin,
        destination_city=req.destination,
        departure_date=req.start_date,
        passengers=req.travellers,
        cabin_class=req.cabin_class,
        currency=req.currency,
    )

    return_flights = search_service.search_flights(
        conn,
        origin_city=req.destination,
        destination_city=req.origin,
        departure_date=req.end_date,
        passengers=req.travellers,
        cabin_class=req.cabin_class,
        currency=req.currency,
    )

    # 2. Fetch hotel candidates
    budget_minor = money.to_minor(req.budget) if req.budget else None
    hotel_options = search_service.search_hotels(
        conn,
        destination=req.destination,
        start_date=req.start_date,
        end_date=req.end_date,
        travellers=req.travellers,
        currency=req.currency,
        budget_minor=budget_minor,
    )

    nights = max((req.end_date - req.start_date).days, 1)

    # 3. Check feasibility
    if not outbound_flights and not return_flights and not hotel_options:
        itinerary_service.record_itinerary_event(
            conn, clock, None, user_id,
            "COMPARISON_COMPLETED",
            {"feasible": False},
            {"reason": "No flights or hotels available for specified dates/route"},
            outcome="refused",
            reason_code="NO_FEASIBLE_OPTION",
        )
        return CompareTravelOptionsResponse(
            options=[],
            total_candidates_analyzed=0,
            recommendation_summary=f"No feasible travel options found for {req.origin} → {req.destination} on {req.start_date} to {req.end_date}.",
            trade_off_analysis=[],
            feasible=False,
            no_feasible_reason=f"No bookable inventory available between {req.origin} and {req.destination} for party size {req.travellers}.",
            suggested_alternatives=[
                "Check alternate dates with scheduled flights",
                "Adjust passenger count or room occupancy",
                "Consider nearby hub airports or flexible stay dates",
            ],
        )

    # 4. Form bounded combination candidates
    # Sort flights: by price asc, and by duration asc
    cheapest_out = sorted(outbound_flights, key=lambda f: money.to_minor(f["price"]))[:3] if outbound_flights else [None]
    fastest_out = sorted(outbound_flights, key=lambda f: (f["stops"], f.get("durationMinutes") or 9999))[:2] if outbound_flights else [None]
    candidate_out = list({(f["fareId"] if f else None): f for f in (cheapest_out + fastest_out)}.values())
    if getattr(req, "preferred_fare_id", None):
        for f in outbound_flights:
            if f.get("fareId") == req.preferred_fare_id:
                if f["fareId"] not in {(cf["fareId"] if cf else None) for cf in candidate_out}:
                    candidate_out.append(f)

    cheapest_ret = sorted(return_flights, key=lambda f: money.to_minor(f["price"]))[:3] if return_flights else [None]
    fastest_ret = sorted(return_flights, key=lambda f: (f["stops"], f.get("durationMinutes") or 9999))[:2] if return_flights else [None]
    candidate_ret = list({(f["fareId"] if f else None): f for f in (cheapest_ret + fastest_ret)}.values())

    cheapest_hotels = sorted(hotel_options, key=lambda h: money.to_minor(h["price"]))[:3] if hotel_options else [None]
    top_rated_hotels = sorted(hotel_options, key=lambda h: -(h.get("star_rating") or 0))[:2] if hotel_options else [None]
    candidate_hotels = list({(h["roomTypeId"] if h else None): h for h in (cheapest_hotels + top_rated_hotels)}.values())
    if getattr(req, "preferred_hotel_id", None):
        for h in hotel_options:
            if h.get("hotelId") == req.preferred_hotel_id:
                if h["roomTypeId"] not in {(ch["roomTypeId"] if ch else None) for ch in candidate_hotels}:
                    candidate_hotels.append(h)

    # Calculate known itinerary activity costs if itinerary_id is provided
    known_activity_minor = 0
    if req.itinerary_id:
        try:
            itin = itinerary_service.get_itinerary(conn, req.itinerary_id, user_id=user_id)
            for d in itin.days:
                for a in d.activities:
                    if a.authoritative_cost:
                        known_activity_minor += money.to_minor(a.authoritative_cost)
        except Exception:
            pass

    raw_options: list[dict[str, Any]] = []
    opt_idx = 0

    for out_f in candidate_out:
        for ret_f in candidate_ret:
            for h in candidate_hotels:
                if not out_f and not ret_f and not h:
                    continue

                # Flight costs
                out_minor = money.to_minor(out_f["price"]) if out_f else 0
                ret_minor = money.to_minor(ret_f["price"]) if ret_f else 0
                transport_minor = out_minor + ret_minor

                # Hotel cost
                hotel_minor = money.to_minor(h["price"]) if h else 0

                # Authoritative total (transport + accommodation + known authoritative activities)
                total_minor = transport_minor + hotel_minor + known_activity_minor

                # Check budget constraint if provided
                if budget_minor is not None and total_minor > budget_minor:
                    # Keep track if no other option exists, but mark as exceeding budget
                    is_within_budget = False
                else:
                    is_within_budget = True

                # Compute flight duration
                out_mins = out_f.get("durationMinutes") if out_f else 0
                ret_mins = ret_f.get("durationMinutes") if ret_f else 0
                total_mins = (out_mins or 0) + (ret_mins or 0) if (out_mins or ret_mins) else None
                total_stops = (out_f.get("stops", 0) if out_f else 0) + (ret_f.get("stops", 0) if ret_f else 0)

                carriers = []
                if out_f and out_f.get("airlineName"):
                    carriers.append(out_f["airlineName"])
                if ret_f and ret_f.get("airlineName") and ret_f["airlineName"] not in carriers:
                    carriers.append(ret_f["airlineName"])

                raw_options.append({
                    "id": f"opt_{opt_idx + 1}",
                    "out_f": out_f,
                    "ret_f": ret_f,
                    "hotel": h,
                    "transport_minor": transport_minor,
                    "hotel_minor": hotel_minor,
                    "activity_minor": known_activity_minor,
                    "total_minor": total_minor,
                    "total_mins": total_mins,
                    "total_stops": total_stops,
                    "carriers": carriers,
                    "is_within_budget": is_within_budget,
                })
                opt_idx += 1

    if budget_minor is not None:
        within_budget = [ro for ro in raw_options if ro["is_within_budget"]]
        if within_budget:
            raw_options = within_budget
        else:
            lowest_minor = min(ro["total_minor"] for ro in raw_options)
            lowest_str = money.format_minor(lowest_minor)
            return CompareTravelOptionsResponse(
                options=[],
                total_candidates_analyzed=len(raw_options),
                recommendation_summary=f"No feasible travel options found within budget of {req.currency} {req.budget}.",
                trade_off_analysis=[],
                feasible=False,
                no_feasible_reason=f"No validated travel option is available under {req.currency} {req.budget}. The lowest available option is {req.currency} {lowest_str}.",
                suggested_alternatives=[
                    f"Increase budget to at least {req.currency} {lowest_str}",
                    "Consider adjusting travel dates",
                    "Adjust passenger or room occupancy",
                ],
            )

    if not raw_options:
        return CompareTravelOptionsResponse(
            options=[],
            total_candidates_analyzed=0,
            recommendation_summary="No matching flight and hotel combinations found.",
            trade_off_analysis=[],
            feasible=False,
            no_feasible_reason="No valid inventory combinations could be formed.",
            suggested_alternatives=["Check dates or search without strict budget filter."],
        )

    from src.db.repositories import preferences as pref_repo
    from src.services import preference_service

    saved_user_prefs = pref_repo.get_preferences_for_user(conn, user_id)
    effective_prefs = preference_service.resolve_effective_preferences(
        saved_user_prefs, request_text=req.preferences
    )

    # Hard direct flight constraint enforcement
    if effective_prefs.get("_hard_direct_flights"):
        direct_raw = [ro for ro in raw_options if ro["total_stops"] == 0]
        if direct_raw:
            raw_options = direct_raw

    # 5. Calculate transparent deterministic scores
    all_prices = [o["total_minor"] for o in raw_options if o["total_minor"] > 0] or [1]
    min_price = min(all_prices)
    max_price = max(all_prices)
    price_span = max(max_price - min_price, 1)

    all_mins = [o["total_mins"] for o in raw_options if o["total_mins"] is not None]
    min_mins = min(all_mins) if all_mins else 0
    max_mins = max(all_mins) if all_mins else 0
    mins_span = max(max_mins - min_mins, 1)

    weights = req.weights or {}
    w_price = weights.get("price", 0.35)
    w_duration = weights.get("duration", 0.25)
    w_hotel = weights.get("hotel", 0.25)
    w_comfort = weights.get("comfort", 0.15)

    if effective_prefs.get("price_priority") == "high":
        w_price = max(w_price, 0.45)
    if effective_prefs.get("comfort_priority") == "high":
        w_hotel = max(w_hotel, 0.30)
        w_comfort = max(w_comfort, 0.25)

    total_w = max(w_price + w_duration + w_hotel + w_comfort, 0.001)

    scored_options: list[TravelOption] = []
    for ro in raw_options:
        # Price score: 10 for cheapest, scaled down
        if max_price == min_price:
            p_score = 9.5
        else:
            p_score = max(1.0, 10.0 - 9.0 * ((ro["total_minor"] - min_price) / price_span))

        # Duration score
        if ro["total_mins"] is not None and mins_span > 0:
            d_score = max(2.0, 10.0 - 8.0 * ((ro["total_mins"] - min_mins) / mins_span))
            if ro["total_stops"] == 0:
                d_score = min(10.0, d_score + 1.0)
            else:
                d_score = max(1.0, d_score - 1.5 * ro["total_stops"])
        else:
            d_score = 7.0

        # Hotel score
        h = ro["hotel"]
        if h:
            stars = float(h.get("star_rating") or 3.0)
            guest = float(h.get("guest_score") or 7.5)
            dist = float(h.get("distance_to_centre_km") or 5.0)
            star_comp = (stars / 5.0) * 4.0
            guest_comp = (guest / 10.0) * 4.0
            dist_comp = max(0.5, 2.0 - min(dist, 10.0) * 0.15)
            h_score = min(10.0, star_comp + guest_comp + dist_comp)
        else:
            h_score = 5.0

        # Comfort score
        c_score = 5.0
        if ro["total_stops"] == 0:
            c_score += 2.0
        if h and float(h.get("star_rating") or 0) >= 4.0:
            c_score += 2.0
        if h and float(h.get("guest_score") or 0) >= 8.0:
            c_score += 1.0
        c_score = min(10.0, c_score)

        # Construct FlightComparisonDetail
        flight_detail = None
        if ro["out_f"] or ro["ret_f"]:
            flight_detail = FlightComparisonDetail(
                outbound=_extract_flight_detail(ro["out_f"]),
                return_flight=_extract_flight_detail(ro["ret_f"]),
                total_flight_price=money.format_minor(ro["transport_minor"]),
                total_duration_minutes=ro["total_mins"],
                total_stops=ro["total_stops"],
                is_direct=ro["total_stops"] == 0,
                carrier_names=ro["carriers"],
                currency=req.currency,
            )

        # Construct HotelComparisonDetail
        hotel_detail = None
        if h:
            hotel_detail = HotelComparisonDetail(
                hotel_id=h["hotelId"],
                hotel_name=h["name"],
                room_type_id=h.get("roomTypeId"),
                room_name=h.get("roomName"),
                star_rating=float(h["star_rating"]) if h.get("star_rating") is not None else None,
                guest_score=float(h["guest_score"]) if h.get("guest_score") is not None else None,
                distance_to_centre_km=float(h["distance_to_centre_km"]) if h.get("distance_to_centre_km") is not None else None,
                address=h.get("address"),
                total_hotel_price=money.format_minor(ro["hotel_minor"]),
                nightly_price=money.format_minor(ro["hotel_minor"] // nights),
                nights=nights,
                currency=req.currency,
                latitude=h.get("latitude"),
                longitude=h.get("longitude"),
            )

        # Base deterministic score calculation
        base_score = (p_score * w_price + d_score * w_duration + h_score * w_hotel + c_score * w_comfort) / total_w
        base_score = round(min(10.0, max(1.0, base_score)), 1)

        # Preference alignment evaluation (Phase 4)
        pref_score, pref_matches, pref_reasons = preference_service.evaluate_option_preferences(
            flight_detail, hotel_detail, effective_prefs
        )
        pref_adj = round((pref_score - 7.0) * 0.2, 1)
        overall = round(min(10.0, max(1.0, base_score + pref_adj)), 1)

        explanation = f"Base: {base_score:.1f}/10 | Preference Adj: {pref_adj:+.1f} | Final: {overall:.1f}/10."
        if pref_reasons:
            explanation += f" ({'; '.join(pref_reasons[:2])})"

        breakdown = ScoreBreakdown(
            price_score=round(p_score, 1),
            duration_score=round(d_score, 1),
            hotel_score=round(h_score, 1),
            comfort_score=round(c_score, 1),
            preference_score=round(pref_score, 1),
            overall_score=overall,
            explanation=explanation,
        )

        cat = ComparisonCategory.BALANCED
        label = f"Option {ro['id'].replace('opt_', '')}"
        if ro["total_minor"] == min_price:
            cat = ComparisonCategory.CHEAPEST
            label = "Cheapest Option"
        elif overall >= 8.5:
            cat = ComparisonCategory.BEST_VALUE
            label = "Best Value Option"

        scored_options.append(
            TravelOption(
                id=ro["id"],
                label=label,
                category=cat,
                flight=flight_detail,
                hotel=hotel_detail,
                transport_cost=money.format_minor(ro["transport_minor"]),
                accommodation_cost=money.format_minor(ro["hotel_minor"]),
                activity_cost=money.format_minor(ro.get("activity_minor", 0)),
                authoritative_total=money.format_minor(ro["total_minor"]),
                estimated_total=money.format_minor(ro["total_minor"]),
                currency=req.currency,
                total_duration_minutes=ro["total_mins"],
                score=overall,
                score_breakdown=breakdown,
                is_within_budget=ro["is_within_budget"],
                destination=req.destination,
                origin=req.origin,
                travellers=req.travellers,
                nights=nights,
            )
        )

    # 6. Mark distinct category leaders
    # Cheapest
    cheapest_opt = min(scored_options, key=lambda o: money.to_minor(o.authoritative_total))
    cheapest_opt.is_cheapest = True
    cheapest_opt.category = ComparisonCategory.CHEAPEST
    cheapest_opt.label = "Cheapest Option"

    # Fastest
    opts_with_duration = [o for o in scored_options if o.total_duration_minutes is not None]
    fastest_opt = min(opts_with_duration, key=lambda o: o.total_duration_minutes) if opts_with_duration else None
    if fastest_opt:
        fastest_opt.is_fastest = True
        if fastest_opt.id != cheapest_opt.id:
            fastest_opt.category = ComparisonCategory.FASTEST
            fastest_opt.label = "Fastest Option"

    # Best Value (highest score)
    best_value_opt = max(scored_options, key=lambda o: o.score)
    best_value_opt.is_best_value = True

    # Comfort
    opts_comfort = sorted(scored_options, key=lambda o: -(o.score_breakdown.comfort_score or 0))
    comfort_opt = opts_comfort[0] if opts_comfort else None
    if comfort_opt:
        comfort_opt.is_most_comfortable = True

    target_mode = req.category_filter or req.preference_mode
    if target_mode == ComparisonCategory.BEST_VALUE:
        best_value_opt.category = ComparisonCategory.BEST_VALUE
        best_value_opt.label = "Best Value"
    elif target_mode == ComparisonCategory.MOST_COMFORTABLE and comfort_opt:
        comfort_opt.category = ComparisonCategory.MOST_COMFORTABLE
        comfort_opt.label = "Most Comfortable"
    elif target_mode == ComparisonCategory.FASTEST and fastest_opt:
        fastest_opt.category = ComparisonCategory.FASTEST
        fastest_opt.label = "Fastest Option"
    elif target_mode == ComparisonCategory.CHEAPEST:
        cheapest_opt.category = ComparisonCategory.CHEAPEST
        cheapest_opt.label = "Cheapest Option"
    else:
        if best_value_opt.id not in (cheapest_opt.id, (fastest_opt.id if fastest_opt else None)):
            best_value_opt.category = ComparisonCategory.BEST_VALUE
            best_value_opt.label = "Best Value"
        if comfort_opt and comfort_opt.id not in (cheapest_opt.id, best_value_opt.id, (fastest_opt.id if fastest_opt else None)):
            comfort_opt.category = ComparisonCategory.MOST_COMFORTABLE
            comfort_opt.label = "Most Comfortable"

    # 7. Generate factual trade-off statements
    trade_offs: list[str] = []
    if cheapest_opt and best_value_opt and cheapest_opt.id != best_value_opt.id:
        chp_total = money.to_minor(cheapest_opt.authoritative_total)
        val_total = money.to_minor(best_value_opt.authoritative_total)
        diff_str = money.format_minor(val_total - chp_total)
        trade_offs.append(
            f"Cheapest option costs {req.currency} {cheapest_opt.authoritative_total}. "
            f"Best Value costs {req.currency} {diff_str} more but offers a higher overall score ({best_value_opt.score}/10 vs {cheapest_opt.score}/10)."
        )

    if fastest_opt and cheapest_opt and fastest_opt.id != cheapest_opt.id:
        mins_saved = (cheapest_opt.total_duration_minutes or 0) - (fastest_opt.total_duration_minutes or 0)
        if mins_saved > 0:
            trade_offs.append(
                f"Fastest option saves {mins_saved // 60}h {mins_saved % 60}m of total travel time compared to the cheapest option."
            )

    if comfort_opt and comfort_opt.hotel and cheapest_opt and cheapest_opt.hotel:
        c_stars = comfort_opt.hotel.star_rating or 0
        ch_stars = cheapest_opt.hotel.star_rating or 0
        if c_stars > ch_stars:
            trade_offs.append(
                f"Comfort option features {comfort_opt.hotel.hotel_name} ({c_stars:.1f}★) instead of {cheapest_opt.hotel.hotel_name} ({ch_stars:.1f}★)."
            )

    # 8. Select Top N distinct options according to category filter or diversity
    selected_options: list[TravelOption] = []
    if req.category_filter:
        matching = [o for o in scored_options if o.category == req.category_filter]
        selected_options = matching[:req.max_options] if matching else scored_options[:req.max_options]
    else:
        # Guarantee distinct representation: Best Value, Cheapest, Comfort / Fastest
        picks = [best_value_opt, cheapest_opt]
        if comfort_opt and comfort_opt.id not in [p.id for p in picks]:
            picks.append(comfort_opt)
        elif fastest_opt and fastest_opt.id not in [p.id for p in picks]:
            picks.append(fastest_opt)
        for o in sorted(scored_options, key=lambda x: -x.score):
            if len(picks) >= req.max_options:
                break
            if o.id not in [p.id for p in picks]:
                picks.append(o)
        selected_options = picks[:req.max_options]

    # Populate trade_offs on each option
    for o in selected_options:
        o_diffs = []
        if o.is_cheapest:
            o_diffs.append("Lowest available authoritative cost among all valid combinations.")
        if o.is_best_value:
            o_diffs.append("Optimal balance of price, convenience, and accommodation rating.")
        if o.is_fastest:
            o_diffs.append("Shortest total travel duration with minimal transit stops.")
        if o.is_most_comfortable:
            o_diffs.append("Premium hotel accommodation and convenient travel schedule.")
        o.trade_offs = o_diffs

    summary = (
        f"Compared {len(raw_options)} valid travel options for {req.origin} → {req.destination}. "
        f"The cheapest option is {req.currency} {cheapest_opt.authoritative_total}, "
        f"and the top recommended Best Value option is {req.currency} {best_value_opt.authoritative_total} (score: {best_value_opt.score}/10)."
    )
    pref_reasons_summary = []
    if effective_prefs.get("direct_flights_only") and best_value_opt and best_value_opt.flight and best_value_opt.flight.is_direct:
        pref_reasons_summary.append("direct flights")
    if float(effective_prefs.get("min_hotel_star_rating", 3.0)) >= 4.0 and best_value_opt and best_value_opt.hotel and (best_value_opt.hotel.star_rating or 0) >= 4.0:
        pref_reasons_summary.append("higher-rated hotels")
    if pref_reasons_summary:
        summary += f" Recommended for you because you prefer {' and '.join(pref_reasons_summary)}."

    # Collect genuinely distinct flight offers from search candidates
    distinct_flights_map = {}
    for f in (outbound_flights or []):
        fk = f.get("flightId") or f.get("fareId") or f"{f.get('flightNumber')}_{f.get('departsAt')}"
        if fk not in distinct_flights_map:
            distinct_flights_map[fk] = {
                "flight_id": f.get("flightId"),
                "fare_id": f.get("fareId"),
                "airline": f.get("airlineName"),
                "airline_code": f.get("airlineCode"),
                "flight_number": f.get("flightNumber"),
                "origin": f.get("originCity"),
                "origin_airport": f.get("originAirport"),
                "origin_code": f.get("originCode"),
                "destination": f.get("destinationCity"),
                "destination_airport": f.get("destinationAirport"),
                "destination_code": f.get("destinationCode"),
                "departs_at": f.get("departsAt"),
                "arrives_at": f.get("arrivesAt"),
                "duration_minutes": f.get("durationMinutes"),
                "stops": f.get("stops", 0),
                "cabin": f.get("cabinClass", "economy"),
                "refundable": bool(f.get("refundable", False)),
                "price": f.get("price"),
                "currency": f.get("currency", req.currency),
                "leg": "outbound",
            }

    distinct_hotels_map = {}
    for h in (hotel_options or []):
        hk = h.get("roomTypeId") or h.get("hotelId")
        if hk not in distinct_hotels_map:
            distinct_hotels_map[hk] = {
                "hotel_id": h.get("hotelId"),
                "room_type_id": h.get("roomTypeId"),
                "hotel_name": h.get("hotelName") or h.get("name"),
                "room_name": h.get("roomName"),
                "star_rating": h.get("star_rating") or h.get("starRating"),
                "price": h.get("price"),
                "currency": h.get("currency", req.currency),
                "address": h.get("address") or h.get("address_line"),
                "latitude": h.get("latitude") or h.get("lat"),
                "longitude": h.get("longitude") or h.get("lng"),
            }

    distinct_flights_list = list(distinct_flights_map.values())
    distinct_hotels_list = list(distinct_hotels_map.values())
    distinct_fl_count = len(distinct_flights_list)
    fl_catalog_notice = "Only one suitable flight is currently available in the catalog." if distinct_fl_count == 1 else None

    resp = CompareTravelOptionsResponse(
        options=selected_options,
        total_candidates_analyzed=len(raw_options),
        cheapest_option_id=cheapest_opt.id if cheapest_opt else None,
        best_value_option_id=best_value_opt.id if best_value_opt else None,
        fastest_option_id=fastest_opt.id if fastest_opt else None,
        most_comfortable_option_id=comfort_opt.id if comfort_opt else None,
        recommendation_summary=summary,
        trade_off_analysis=trade_offs,
        feasible=True,
        flight_options=distinct_flights_list,
        hotel_options=distinct_hotels_list,
        distinct_flight_count=distinct_fl_count,
        flight_catalog_notice=fl_catalog_notice,
    )

    itinerary_service.record_itinerary_event(
        conn, clock, None, user_id,
        "COMPARISON_COMPLETED",
        {"options_count": len(selected_options), "cheapest": cheapest_opt.authoritative_total},
        {"status": "success"},
        outcome="success",
    )

    return resp


def optimize_trip(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    req: OptimizeTripRequest,
) -> OptimizeTripResponse:
    """Optimize an existing itinerary by finding cheaper or more comfortable alternatives within constraints."""
    current = itinerary_service.get_itinerary(conn, req.itinerary_id, user_id=user_id)
    if current.status == ItineraryStatus.CANCELLED:
        raise RefusalError("STATE_INVALID", "cannot optimize a cancelled itinerary", http_status=409)

    itinerary_service.record_itinerary_event(
        conn, clock, current.session_id, user_id,
        "OPTIMIZATION_REQUESTED",
        req.model_dump(mode="json"),
        {"itinerary_id": current.id},
    )

    allowed = req.allowed_changes.model_dump() if hasattr(req.allowed_changes, "model_dump") else (req.allowed_changes or {"flight": True, "hotel": True, "activities": False, "dates": False})
    target_budget = req.target_budget or current.budget

    current_hotel_id = current.accommodation[0].hotel_id if current.accommodation else None
    current_out_fare = current.transport[0].reference if current.transport else None

    # Run comparison query on current route
    comp_req = CompareTravelOptionsRequest(
        origin=current.origin,
        destination=current.destination,
        start_date=current.start_date,
        end_date=current.end_date,
        travellers=current.travellers,
        currency=current.currency,
        budget=target_budget,
        preferences=req.preferences or current.constraints.get("preferences"),
        max_options=6,
        itinerary_id=current.id,
        preferred_hotel_id=current_hotel_id if not allowed.get("hotel", True) else None,
        preferred_fare_id=current_out_fare if not allowed.get("flight", True) else None,
    )

    comp_resp = compare_travel_options(conn, clock, user_id, comp_req)
    if not comp_resp.feasible or not comp_resp.options:
        itinerary_service.record_itinerary_event(
            conn, clock, current.session_id, user_id,
            "OPTIMIZATION_FAILED",
            {"reason": "No feasible combinations found"},
            {},
            outcome="failed",
            reason_code="NO_FEASIBLE_OPTION",
        )
        return OptimizeTripResponse(
            itinerary_id=current.id,
            optimized_option=None,
            diff=None,
            status="no_feasible_solution",
            explanation=f"No feasible option found for target budget {current.currency} {target_budget or 'unspecified'}.",
            feasible=False,
            alternatives=[
                "Increase target budget",
                "Keep existing flight and change hotel",
                "Select flexible dates",
            ],
        )

    # Filter candidate options based on allowed_changes
    candidates = list(comp_resp.options)

    if not allowed.get("hotel", True) and current.accommodation:
        matching_hotels = [c for c in candidates if c.hotel and c.hotel.hotel_id == current_hotel_id]
        if matching_hotels:
            candidates = matching_hotels
        else:
            cur_acc = current.accommodation[0]
            nights = max((current.end_date - current.start_date).days, 1)
            h_tot_minor = money.to_minor(cur_acc.known_price)
            cur_h_detail = HotelComparisonDetail(
                hotel_id=cur_acc.hotel_id,
                hotel_name=cur_acc.hotel_name,
                room_type_id=cur_acc.room_type_id,
                room_name=cur_acc.room_name,
                total_hotel_price=cur_acc.known_price,
                nightly_price=money.format_minor(h_tot_minor // nights),
                nights=nights,
                currency=current.currency,
                latitude=cur_acc.latitude,
                longitude=cur_acc.longitude,
                address=cur_acc.address,
            )
            locked_candidates = []
            for c in candidates:
                t_minor = money.to_minor(c.transport_cost)
                act_minor = money.to_minor(c.activity_cost)
                tot_minor = t_minor + h_tot_minor + act_minor
                is_within = (tot_minor <= money.to_minor(target_budget)) if target_budget else True
                locked_candidates.append(
                    c.model_copy(
                        update={
                            "hotel": cur_h_detail,
                            "accommodation_cost": cur_acc.known_price,
                            "authoritative_total": money.format_minor(tot_minor),
                            "estimated_total": money.format_minor(tot_minor),
                            "is_within_budget": is_within,
                        }
                    )
                )
            candidates = locked_candidates

    if not allowed.get("flight", True) and current_out_fare:
        matching_flights = [c for c in candidates if c.flight and c.flight.outbound and (c.flight.outbound.get("fare_id") == current_out_fare or c.flight.outbound.get("fareId") == current_out_fare)]
        if matching_flights:
            candidates = matching_flights

    # Preserve direct flight preference and hotel preference during optimization
    from src.db.repositories import preferences as pref_repo
    from src.services import preference_service

    opt_prefs = preference_service.resolve_effective_preferences(
        pref_repo.get_preferences_for_user(conn, user_id),
        request_text=req.preferences,
    )
    if opt_prefs.get("direct_flights_only") and not opt_prefs.get("_overridden_direct_flights"):
        direct_matches = [c for c in candidates if c.flight and c.flight.is_direct]
        if direct_matches:
            candidates = direct_matches

    if opt_prefs.get("_hard_hotel_stars") or (req.preferences and "hotel preference" in req.preferences.lower()):
        min_hotel_stars = float(opt_prefs.get("min_hotel_star_rating", 3.0))
        star_matches = [c for c in candidates if c.hotel and (c.hotel.star_rating or 0) >= min_hotel_stars]
        if star_matches:
            candidates = star_matches

    # Pick best candidate for objective
    obj = req.objective.lower()
    current_total_minor = money.to_minor(current.total_authoritative_cost or "0.00")

    if "cheap" in obj or "lower" in obj or "budget" in obj:
        chosen = min(candidates, key=lambda c: money.to_minor(c.authoritative_total))
    elif "comfort" in obj or "better" in obj:
        # Pick highest comfort within budget
        within = [c for c in candidates if c.is_within_budget] or candidates
        chosen = max(within, key=lambda c: c.score_breakdown.comfort_score or 0)
    elif "fast" in obj:
        within = [c for c in candidates if c.is_within_budget and c.total_duration_minutes] or candidates
        chosen = min(within, key=lambda c: c.total_duration_minutes or 9999)
    else:  # best value
        within = [c for c in candidates if c.is_within_budget] or candidates
        chosen = max(within, key=lambda c: c.score)

    new_total_minor = money.to_minor(chosen.authoritative_total)

    # Compute PlanDiff
    flight_change = None
    if chosen.flight and current.transport:
        flight_change = {
            "before": {
                "carrier": current.transport[0].carrier,
                "flight": current.transport[0].reference,
                "price": current.transport[0].known_price,
            },
            "after": {
                "carrier": chosen.flight.carrier_names[0] if chosen.flight.carrier_names else "Airline",
                "flight": chosen.flight.outbound.get("flight_number") if chosen.flight.outbound else None,
                "price": chosen.flight.total_flight_price,
            },
        }

    hotel_change = None
    if chosen.hotel and current.accommodation:
        hotel_change = {
            "before": {
                "hotel": current.accommodation[0].hotel_name,
                "price": current.accommodation[0].known_price,
            },
            "after": {
                "hotel": chosen.hotel.hotel_name,
                "price": chosen.hotel.total_hotel_price,
            },
        }

    savings = None
    cost_increase = None
    if new_total_minor < current_total_minor:
        savings = money.format_minor(current_total_minor - new_total_minor)
    elif new_total_minor > current_total_minor:
        cost_increase = money.format_minor(new_total_minor - current_total_minor)

    is_material = (
        (flight_change is not None and flight_change["before"]["flight"] != flight_change["after"]["flight"])
        or (hotel_change is not None and hotel_change["before"]["hotel"] != hotel_change["after"]["hotel"])
    )

    confirm_prompt = None
    if is_material and savings:
        confirm_prompt = f"Switching options saves {current.currency} {savings}. Apply this change to your itinerary?"
    elif is_material and cost_increase:
        confirm_prompt = f"Upgrading comfort increases cost by {current.currency} {cost_increase}. Apply this change?"

    summary_text = (
        f"Optimized itinerary for objective '{req.objective}'. "
        f"Authoritative total moves from {current.currency} {current.total_authoritative_cost or '0.00'} "
        f"to {current.currency} {chosen.authoritative_total}."
    )
    if savings:
        summary_text += f" (Total savings: {current.currency} {savings})"

    diff = PlanDiff(
        flight_change=flight_change,
        hotel_change=hotel_change,
        activity_change=None,
        before_authoritative_total=current.total_authoritative_cost or "0.00",
        after_authoritative_total=chosen.authoritative_total,
        savings=savings,
        cost_increase=cost_increase,
        currency=current.currency,
        summary=summary_text,
        is_material_change=is_material,
        confirmation_prompt=confirm_prompt,
    )

    itinerary_service.record_itinerary_event(
        conn, clock, current.session_id, user_id,
        "OPTIMIZATION_COMPLETED",
        {"itinerary_id": current.id, "savings": savings},
        {"chosen_option_id": chosen.id, "new_total": chosen.authoritative_total},
        outcome="success",
    )

    return OptimizeTripResponse(
        itinerary_id=current.id,
        optimized_option=chosen,
        diff=diff,
        status="proposed",
        explanation=summary_text,
        feasible=True,
    )


def apply_option_to_itinerary(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    itinerary_id: Union[str, ApplyOptionRequest],
    option: Optional[TravelOption] = None,
) -> TripPlan:
    """Atomically apply a chosen TravelOption to an itinerary with version increment and full validation."""
    if isinstance(itinerary_id, ApplyOptionRequest):
        req = itinerary_id
        actual_id = req.itinerary_id or req.option_id
        option = req.selected_option or req.option
        itinerary_id = actual_id
    if option is None:
        raise RefusalError("STATE_INVALID", "no travel option provided to apply")

    current = itinerary_service.get_itinerary(conn, itinerary_id, user_id=user_id)
    if current.status == ItineraryStatus.CANCELLED:
        raise RefusalError("STATE_INVALID", "cannot modify a cancelled itinerary", http_status=409)

    # 1. Update Transport
    updated_transports: list[TransportSegment] = []
    if option.flight and option.flight.outbound:
        out = option.flight.outbound
        updated_transports.append(
            TransportSegment(
                id=new_id("itm"),
                type=TransportType.FLIGHT,
                origin=current.origin,
                origin_code=out.get("origin_code"),
                destination=current.destination,
                dest_code=out.get("dest_code"),
                carrier=out.get("carrier"),
                reference=out.get("fare_id") or out.get("flight_number"),
                departs_at=out.get("departs_at") or f"{current.start_date.isoformat()}T08:00:00+05:30",
                arrives_at=out.get("arrives_at") or f"{current.start_date.isoformat()}T11:00:00+05:30",
                known_price=out.get("price") or option.flight.total_flight_price,
                currency=current.currency,
            )
        )
    if option.flight and option.flight.return_flight:
        ret = option.flight.return_flight
        updated_transports.append(
            TransportSegment(
                id=new_id("itm"),
                type=TransportType.FLIGHT,
                origin=current.destination,
                origin_code=ret.get("origin_code"),
                destination=current.origin,
                dest_code=ret.get("dest_code"),
                carrier=ret.get("carrier"),
                reference=ret.get("fare_id") or ret.get("flight_number"),
                departs_at=ret.get("departs_at") or f"{current.end_date.isoformat()}T16:00:00+05:30",
                arrives_at=ret.get("arrives_at") or f"{current.end_date.isoformat()}T19:00:00+05:30",
                known_price=ret.get("price") or "0.00",
                currency=current.currency,
            )
        )
    if not updated_transports:
        updated_transports = list(current.transport)

    # 2. Update Accommodation
    updated_accommodations: list[AccommodationStay] = []
    if option.hotel:
        h = option.hotel
        updated_accommodations.append(
            AccommodationStay(
                id=new_id("itm"),
                hotel_id=h.hotel_id,
                hotel_name=h.hotel_name,
                room_type_id=h.room_type_id,
                room_name=h.room_name,
                address=h.address,
                check_in_date=current.start_date,
                check_out_date=current.end_date,
                known_price=h.total_hotel_price,
                currency=current.currency,
                latitude=h.latitude,
                longitude=h.longitude,
            )
        )
    if not updated_accommodations:
        updated_accommodations = list(current.accommodation)

    # 3. Synchronize Day 1 arrival / Day Last departure activities
    updated_days: list[ItineraryDay] = []
    for d in current.days:
        is_first = d.day_number == 1
        is_last = d.day_number == len(current.days)
        new_acts = []
        for a in d.activities:
            if a.category == ActivityCategory.FLIGHT:
                if is_first and updated_transports:
                    t = updated_transports[0]
                    new_acts.append(
                        a.model_copy(
                            update={
                                "title": f"{t.carrier or 'Flight'} Arrival in {current.destination}",
                                "authoritative_cost": "0.00",
                                "entity_id": t.reference,
                            }
                        )
                    )
                elif is_last and len(updated_transports) > 1:
                    t = updated_transports[1]
                    new_acts.append(
                        a.model_copy(
                            update={
                                "title": f"{t.carrier or 'Flight'} Departure to {t.destination}",
                                "authoritative_cost": "0.00",
                                "entity_id": t.reference,
                            }
                        )
                    )
                else:
                    new_acts.append(a)
            elif a.category == ActivityCategory.STAY:
                if updated_accommodations:
                    stay = updated_accommodations[0]
                    new_acts.append(
                        a.model_copy(
                            update={
                                "title": f"{'Check-in at' if is_first else 'Check-out from'} {stay.hotel_name}",
                                "location": stay.address or current.destination,
                                "latitude": stay.latitude,
                                "longitude": stay.longitude,
                                "entity_id": stay.hotel_id,
                            }
                        )
                    )
                else:
                    new_acts.append(a)
            else:
                new_acts.append(a)
        updated_days.append(d.model_copy(update={"activities": new_acts}))

    # 4. Construct updated plan
    working_plan = current.model_copy(
        update={
            "transport": updated_transports,
            "accommodation": updated_accommodations,
            "days": updated_days,
        }
    )

    # 5. Authoritative recalculation & validation
    auth_total, est_total, _ = itinerary_service.calculate_plan_totals(conn, working_plan)
    new_budget = working_plan.budget
    if working_plan.budget and money.to_minor(auth_total) > money.to_minor(working_plan.budget):
        new_budget = auth_total

    working_plan = working_plan.model_copy(
        update={
            "total_authoritative_cost": auth_total,
            "total_estimated_cost": est_total,
            "budget": new_budget,
        }
    )

    validation = itinerary_service.validate_itinerary(working_plan, conn=conn)
    if not validation.valid:
        raise RefusalError("STATE_INVALID", f"applying option failed validation: {'; '.join(validation.errors)}", http_status=422)

    # 6. Save atomically with version increment
    saved_plan = itinerary_service.update_itinerary(conn, clock, itinerary_id, user_id, working_plan)

    itinerary_service.record_itinerary_event(
        conn, clock, current.session_id, user_id,
        "OPTION_SELECTED",
        {"itinerary_id": itinerary_id, "option_id": option.id},
        {"new_version": saved_plan.version, "total_cost": saved_plan.total_authoritative_cost},
        outcome="success",
    )
    itinerary_service.record_itinerary_event(
        conn, clock, current.session_id, user_id,
        "ITINERARY_OPTIMIZED",
        {"itinerary_id": itinerary_id},
        {"status": "applied", "version": saved_plan.version},
        outcome="success",
    )

    return saved_plan

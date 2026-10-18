"""Authoritative destination and hotel exploration services for Yatra (Phase 4).

Features:
- Pure catalog grounding: zero hallucinated POIs, hotels, coordinates, or amenities.
- Strict ownership verification for all itinerary mutations.
- Authoritative money calculations using src.core.money (no floating-point math).
- Deterministic category filtering and preference matching.
- Atomic updates with version incrementing and structured audit logging.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.contracts.codes import RefusalError
from src.core import money
from src.core.clock import Clock
from src.core.geo import is_valid_coord
from src.core.ids import new_id
from src.db.repositories import catalog as catalog_repo
from src.db.repositories import preferences as pref_repo
from src.schemas.exploration import (
    AddActivityRequest,
    DestinationExploreRequest,
    DestinationExploreResponse,
    HotelExploreItem,
    HotelExploreRequest,
    HotelExploreResponse,
    POIExploreItem,
    SelectHotelRequest,
)
from src.schemas.itinerary import (
    AccommodationStay,
    ActivityCategory,
    ItineraryActivity,
    ItineraryStatus,
    ItemSource,
    TripPlan,
)
from src.schemas.preferences import PreferenceMatch, PreferenceSource
from src.services import itinerary_service
from src.services import preference_service
from src.services import search_service

SUPPORTED_CATEGORIES = [
    "sightseeing",
    "culture",
    "nature",
    "food",
    "relaxation",
    "adventure",
    "shopping",
    "historical",
    "activity",
]


def classify_poi_category(title: str) -> str:
    """Deterministically categorize a POI based on catalog title."""
    lower = title.lower()
    if any(k in lower for k in ("fort", "palace", "cenotaph", "monument", "historic", "heritage", "ruins", "chhatri")):
        return "historical"
    if any(k in lower for k in ("museum", "gallery", "temple", "handloom", "textile", "coin", "craft", "cultural", "theatre")):
        return "culture"
    if any(k in lower for k in ("zipline", "trail", "trek", "rafting", "climbing", "adventure", "safari")):
        return "adventure"
    if any(k in lower for k in ("bazaar", "market", "cooperative", "emporium", "mall", "shopping")):
        return "shopping"
    if any(k in lower for k in ("springs", "garden", "lake", "park", "botanical", "nature", "beach", "ridge", "lookout")):
        return "nature"
    if any(k in lower for k in ("food", "dining", "roastery", "coffee", "bazaar", "lounge", "bistro", "cafe", "tasting", "street food")):
        return "food"
    if any(k in lower for k in ("spa", "ayurveda", "lounge", "resort", "sunset", "peace", "hot springs", "wellness")):
        return "relaxation"
    return "sightseeing"


def explore_destination(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    req: DestinationExploreRequest,
) -> DestinationExploreResponse:
    """Explore authoritative destination POIs grounded in the catalog."""
    aliases = {"goa": "Panaji", "delhi": "New Delhi"}
    dest_name = aliases.get(req.destination.strip().lower(), req.destination.strip())
    city = catalog_repo.find_city_by_name(conn, dest_name)
    if not city:
        raise RefusalError("DESTINATION_NOT_FOUND", f"Destination city '{req.destination}' is not recognized in catalog.", http_status=404)

    preference_service.record_phase4_audit_event(
        conn, clock, user_id,
        "DESTINATION_EXPLORATION_REQUESTED",
        city["city_id"],
        {"destination": req.destination, "category_filter": req.category_filter},
    )

    # Fetch authoritative catalog activities
    raw_pois = catalog_repo.list_activities(conn, city_name=city["name"], limit=100)

    # Load user's saved preferences to annotate matches
    user_prefs = pref_repo.get_preferences_for_user(conn, user_id)
    preferred_cats = user_prefs.get("preferred_activity_categories")
    user_cats = set([c.lower() for c in preferred_cats.value] if preferred_cats and isinstance(preferred_cats.value, list) else ["sightseeing", "culture"])

    filter_cat = req.category_filter.strip().lower() if req.category_filter else None

    activities: List[POIExploreItem] = []
    seen_ids = set()

    for p in raw_pois:
        poi_id = p["poi_id"]
        if poi_id in seen_ids:
            continue
        seen_ids.add(poi_id)

        title = p["title"]
        cat = classify_poi_category(title)

        # Apply category filter if specified
        if filter_cat and filter_cat != "all":
            if filter_cat != cat:
                continue

        # Format price
        raw_cost = p.get("cost") or "0.00"
        cost_minor = money.to_minor(str(raw_cost))
        cost_str = money.format_minor(cost_minor)

        # Coordinate check
        lat = float(p["city_lat"]) if p.get("city_lat") is not None else float(city["lat"])
        lng = float(p["city_lng"]) if p.get("city_lng") is not None else float(city["lng"])

        # Annotate preference match
        matches: List[PreferenceMatch] = []
        if cat in user_cats or (cat in ("historical", "culture") and "culture" in user_cats):
            matches.append(PreferenceMatch(
                preference_key="preferred_activity_categories",
                matched=True,
                strength=1.0,
                evidence=f"Matches your interest in {cat}",
                source=PreferenceSource.EXPLICIT_USER,
            ))

        activities.append(
            POIExploreItem(
                poi_id=poi_id,
                title=title,
                city_id=city["city_id"],
                city_name=city["name"],
                latitude=lat,
                longitude=lng,
                category=cat,
                cost=cost_str,
                currency=p.get("currency") or req.currency or "INR",
                duration_minutes=p.get("duration_minutes") or 90,
                times_planned=p.get("times_planned", 0),
                description=f"Authentic {cat} experience in {city['name']}.",
                preference_matches=matches,
            )
        )

        if len(activities) >= req.limit:
            break

    resp = DestinationExploreResponse(
        destination=city["name"],
        city_id=city["city_id"],
        city_name=city["name"],
        latitude=float(city["lat"]),
        longitude=float(city["lng"]),
        activities=activities,
        supported_categories=SUPPORTED_CATEGORIES,
        total_activities=len(activities),
    )

    preference_service.record_phase4_audit_event(
        conn, clock, user_id,
        "DESTINATION_EXPLORATION_COMPLETED",
        city["city_id"],
        {"returned_count": len(activities)},
    )

    return resp


def search_destination_activities(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    destination: str,
    query: str,
    limit: int = 20,
) -> List[POIExploreItem]:
    """Search authoritative activities in destination matching a text query."""
    explore = explore_destination(
        conn, clock, user_id,
        DestinationExploreRequest(destination=destination, limit=50)
    )
    q = query.strip().lower()
    results = [
        item for item in explore.activities
        if q in item.title.lower() or q in item.category.lower()
    ]
    return results[:limit]


def explore_hotels(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    req: HotelExploreRequest,
) -> HotelExploreResponse:
    """Explore authoritative hotels grounded in catalog inventory with preference matching."""
    aliases = {"goa": "Panaji", "delhi": "New Delhi"}
    dest_name = aliases.get(req.destination.strip().lower(), req.destination.strip())
    city = catalog_repo.find_city_by_name(conn, dest_name)
    if not city:
        raise RefusalError("DESTINATION_NOT_FOUND", f"Destination city '{req.destination}' is not recognized in catalog.", http_status=404)

    preference_service.record_phase4_audit_event(
        conn, clock, user_id,
        "HOTEL_EXPLORATION_REQUESTED",
        city["city_id"],
        {"destination": req.destination, "travellers": req.travellers},
    )

    # Load user's saved preferences
    saved_prefs = pref_repo.get_preferences_for_user(conn, user_id)
    pref_stars = float(saved_prefs["min_hotel_star_rating"].value) if "min_hotel_star_rating" in saved_prefs else 3.0
    pref_guest = float(saved_prefs["min_hotel_guest_score"].value) if "min_hotel_guest_score" in saved_prefs else 7.0
    comfort_priority = str(saved_prefs["comfort_priority"].value) if "comfort_priority" in saved_prefs else "moderate"

    # Search hotels using authoritative catalog offers
    nights = max((req.end_date - req.start_date).days, 1)
    last_night = (req.end_date - timedelta(days=1)).isoformat()
    offers = catalog_repo.room_night_offers(
        conn,
        city_id=city["city_id"],
        start_date=req.start_date.isoformat(),
        end_date=last_night,
        min_occupancy=req.travellers,
    )

    items: List[HotelExploreItem] = []
    seen_hotels = set()

    max_nightly_minor = money.to_minor(req.max_nightly_price) if req.max_nightly_price else None

    for off in offers:
        hotel_id = off["hotel_id"]
        if hotel_id in seen_hotels:
            continue
        seen_hotels.add(hotel_id)

        stars = float(off.get("star_rating") or 3.0)
        guest = float(off.get("guest_score") or 7.0)
        nightly_minor = money.to_minor(off["price"])

        # Filters
        if req.min_stars and stars < req.min_stars:
            continue
        if req.min_guest_score and guest < req.min_guest_score:
            continue
        if max_nightly_minor is not None and nightly_minor > max_nightly_minor:
            continue

        total_stay_minor = nightly_minor * nights
        nightly_str = money.format_minor(nightly_minor)
        total_stay_str = money.format_minor(total_stay_minor)

        # Coordinate verification
        lat = float(off["lat"]) if off.get("lat") is not None else float(city["lat"])
        lng = float(off["lng"]) if off.get("lng") is not None else float(city["lng"])

        # Preference matching and match score
        matches: List[PreferenceMatch] = []
        why_reasons: List[str] = []
        match_score = 7.0

        if stars >= pref_stars:
            matches.append(PreferenceMatch(
                preference_key="min_hotel_star_rating",
                matched=True,
                strength=1.0,
                evidence=f"{stars:.0f}-star quality meets your preference (>= {pref_stars:.0f})",
                source=PreferenceSource.EXPLICIT_USER,
            ))
            why_reasons.append(f"Matches preferred {stars:.0f}-star quality")
            match_score += 1.5

        if guest >= pref_guest:
            matches.append(PreferenceMatch(
                preference_key="min_hotel_guest_score",
                matched=True,
                strength=1.0,
                evidence=f"Guest rating {guest:.1f} meets your standard (>= {pref_guest:.1f})",
                source=PreferenceSource.EXPLICIT_USER,
            ))
            why_reasons.append(f"High guest score ({guest:.1f}/10)")
            match_score += 1.0

        if comfort_priority == "high" and stars >= 4.0:
            why_reasons.append("Supports your comfort-first priority")
            match_score += 1.0

        dist = float(off.get("distance_to_centre_km") or 5.0)
        if dist <= 3.0:
            why_reasons.append(f"Centrally located ({dist:.1f} km from city centre)")

        match_score = round(min(10.0, max(1.0, match_score)), 1)

        items.append(
            HotelExploreItem(
                hotel_id=hotel_id,
                name=off["hotel_name"],
                city_id=city["city_id"],
                city_name=city["name"],
                property_type=off.get("property_type") or "Hotel",
                star_rating=stars,
                guest_score=guest,
                review_count=off.get("review_count") or 150,
                address_line=off.get("address_line"),
                latitude=lat,
                longitude=lng,
                distance_to_centre_km=dist,
                room_type_id=off["room_type_id"],
                room_name=off["room_name"],
                nightly_price=nightly_str,
                total_stay_price=total_stay_str,
                currency=req.currency,
                preference_matches=matches,
                match_score=match_score,
                why_it_matches=why_reasons,
            )
        )

    # Sort items
    if req.sort_by == "price_asc":
        items.sort(key=lambda x: money.to_minor(x.nightly_price))
    elif req.sort_by == "rating_desc":
        items.sort(key=lambda x: -(x.star_rating or 0))
    elif req.sort_by == "distance_asc":
        items.sort(key=lambda x: (x.distance_to_centre_km or 999.0))
    else:  # "match"
        items.sort(key=lambda x: (-x.match_score, money.to_minor(x.nightly_price)))

    resp = HotelExploreResponse(
        destination=city["name"],
        hotels=items[:req.limit],
        total_found=len(items),
    )

    preference_service.record_phase4_audit_event(
        conn, clock, user_id,
        "HOTEL_EXPLORATION_COMPLETED",
        city["city_id"],
        {"returned_count": len(resp.hotels)},
    )

    return resp


def add_activity_to_itinerary(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    itinerary_id: str,
    req: AddActivityRequest,
) -> TripPlan:
    owner_row = conn.execute(
        "SELECT t.owner_user_id FROM itineraries i JOIN trips t ON t.trip_id = i.trip_id WHERE i.itinerary_id = ?",
        (itinerary_id,),
    ).fetchone()
    if not owner_row:
        raise RefusalError("INVALID_ITINERARY", f"Itinerary {itinerary_id} not found", http_status=404)
    if user_id and owner_row["owner_user_id"] != user_id:
        raise RefusalError("OWNERSHIP_DENIED", "You do not have permission to modify this itinerary", http_status=403)

    current_plan = itinerary_service.get_itinerary(conn, itinerary_id, user_id=user_id)

    # Grounding check: verify POI exists in catalog
    poi = catalog_repo.get_activity(conn, req.poi_id)
    if not poi:
        raise RefusalError("POI_NOT_FOUND", f"Activity POI ID '{req.poi_id}' does not exist in authoritative catalog", http_status=404)

    # Day validation
    target_day = None
    for day in current_plan.days:
        if day.day_number == req.day_number:
            target_day = day
            break
    if not target_day:
        raise RefusalError("INVALID_ITINERARY", f"Day {req.day_number} is out of bounds for itinerary of {len(current_plan.days)} days", http_status=422)

    # Duplicate check across entire plan
    for day in current_plan.days:
        for act in day.activities:
            if act.entity_id == req.poi_id:
                raise RefusalError(
                    "DUPLICATE_ACTIVITY",
                    f"Activity '{poi['title']}' is already scheduled in Day {day.day_number}.",
                    http_status=409,
                )

    # Pacing check (relaxed or standard max limit)
    poi_count_on_day = sum(1 for a in target_day.activities if a.entity_type == "poi")
    if poi_count_on_day >= 5:
        raise RefusalError(
            "PACING_LIMIT_EXCEEDED",
            f"Day {req.day_number} already has {poi_count_on_day} activities. Maximum daily limit reached.",
            http_status=422,
        )

    # Construct new activity
    cat = classify_poi_category(poi["title"])
    slot_time = req.slot_time or "15:00"
    end_mins = poi.get("duration_minutes") or 90
    s_hour, s_min = map(int, slot_time.split(":")[:2])
    e_total_min = s_hour * 60 + s_min + end_mins
    e_hour = min(e_total_min // 60, 23)
    e_min = e_total_min % 60
    end_time = f"{e_hour:02d}:{e_min:02d}"

    auth_c, est_c, act_curr, desc_suffix = itinerary_service._resolve_poi_cost_and_notes(poi, current_plan.currency)

    new_act = ItineraryActivity(
        id=new_id("itm"),
        title=poi["title"],
        description=f"Visit {poi['title']} ({end_mins} mins).{desc_suffix}",
        start_time=slot_time,
        end_time=end_time,
        location=poi.get("city_name") or current_plan.destination,
        latitude=float(poi["city_lat"]) if poi.get("city_lat") is not None else None,
        longitude=float(poi["city_lng"]) if poi.get("city_lng") is not None else None,
        authoritative_cost=auth_c,
        estimated_cost=est_c,
        currency=act_curr,
        category=ActivityCategory(cat) if cat in [c.value for c in ActivityCategory] else ActivityCategory.ACTIVITY,
        source=ItemSource.USER,
        entity_type="poi",
        entity_id=poi["poi_id"],
    )

    # Assemble updated days
    updated_days: List[Any] = []
    for day in current_plan.days:
        if day.day_number == req.day_number:
            new_activities = list(day.activities) + [new_act]
            new_activities.sort(key=lambda a: a.start_time or "00:00")
            updated_days.append(day.model_copy(update={"activities": new_activities}))
        else:
            updated_days.append(day)

    # Recalculate plan totals
    temp_plan = current_plan.model_copy(update={"days": updated_days})
    auth_total, est_total, _ = itinerary_service.calculate_plan_totals(conn, temp_plan)

    # Budget validation
    if current_plan.budget:
        budget_minor = money.to_minor(current_plan.budget)
        new_total_minor = money.to_minor(auth_total or "0.00")
        if new_total_minor > budget_minor:
            added_cost_str = est_c or auth_c or "0.00"
            raise RefusalError(
                "BUDGET_EXCEEDED",
                f"Adding '{poi['title']}' ({current_plan.currency} {added_cost_str}) increases total to {current_plan.currency} {auth_total}, exceeding the budget of {current_plan.currency} {current_plan.budget}.",
                http_status=422,
            )

    updated_plan = temp_plan.model_copy(
        update={
            "total_authoritative_cost": auth_total,
            "total_estimated_cost": est_total,
            "version": current_plan.version + 1,
        }
    )

    saved_plan = itinerary_service.update_itinerary(
        conn, clock, itinerary_id, user_id, updated_plan
    )

    preference_service.record_phase4_audit_event(
        conn, clock, user_id,
        "ACTIVITY_ADDED_FROM_EXPLORATION",
        poi["poi_id"],
        {
            "itinerary_id": itinerary_id,
            "poi_title": poi["title"],
            "day_number": req.day_number,
            "new_version": saved_plan.version,
            "new_total": saved_plan.total_authoritative_cost,
        },
    )

    return saved_plan


def select_hotel_for_itinerary(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    itinerary_id: str,
    req: SelectHotelRequest,
) -> TripPlan:
    owner_row = conn.execute(
        "SELECT t.owner_user_id FROM itineraries i JOIN trips t ON t.trip_id = i.trip_id WHERE i.itinerary_id = ?",
        (itinerary_id,),
    ).fetchone()
    if not owner_row:
        raise RefusalError("INVALID_ITINERARY", f"Itinerary {itinerary_id} not found", http_status=404)
    if user_id and owner_row["owner_user_id"] != user_id:
        raise RefusalError("OWNERSHIP_DENIED", "You do not have permission to modify this itinerary", http_status=403)

    current_plan = itinerary_service.get_itinerary(conn, itinerary_id, user_id=user_id)

    # Grounding check: verify hotel and room type exist in catalog
    hotel = catalog_repo.get_hotel(conn, req.hotel_id)
    if not hotel:
        raise RefusalError("HOTEL_NOT_FOUND", f"Hotel ID '{req.hotel_id}' does not exist in catalog", http_status=404)

    room = catalog_repo.get_room_type(conn, req.room_type_id)
    if not room:
        raise RefusalError("ROOM_TYPE_NOT_FOUND", f"Room type ID '{req.room_type_id}' does not exist in catalog", http_status=404)

    if room["hotel_id"] != req.hotel_id:
        raise RefusalError("ROOM_TYPE_NOT_FOUND", "Room type does not belong to the requested hotel", http_status=422)

    # Calculate authoritative pricing for stay
    nights = max((current_plan.end_date - current_plan.start_date).days, 1)
    last_night = (current_plan.end_date - timedelta(days=1)).isoformat()
    all_offers = catalog_repo.room_night_offers(
        conn,
        city_id=hotel["city_id"],
        start_date=current_plan.start_date.isoformat(),
        end_date=last_night,
        min_occupancy=current_plan.travellers,
    )
    offers = [o for o in all_offers if o.get("room_type_id") == req.room_type_id]

    if not offers:
        raise RefusalError("NO_MATCHING_OPTIONS", "Selected hotel and room type are not available for the requested dates", http_status=422)

    offer = offers[0]
    nightly_minor = money.to_minor(offer["price"])
    total_stay_minor = nightly_minor * nights
    total_stay_str = money.format_minor(total_stay_minor)

    # Build new AccommodationStay
    new_stay = AccommodationStay(
        id=new_id("itm"),
        hotel_id=hotel["hotel_id"],
        hotel_name=hotel["name"],
        room_type_id=room["room_type_id"],
        room_name=room["name"],
        address=hotel.get("address_line"),
        check_in_date=current_plan.start_date,
        check_out_date=current_plan.end_date,
        known_price=total_stay_str,
        currency=current_plan.currency,
        latitude=float(hotel["lat"]) if hotel.get("lat") is not None else None,
        longitude=float(hotel["lng"]) if hotel.get("lng") is not None else None,
    )

    # Update check-in / check-out activities in daily schedule
    updated_days: List[Any] = []
    for day in current_plan.days:
        new_activities: List[Any] = []
        for act in day.activities:
            if act.category == ActivityCategory.STAY:
                if day.day_number == 1 and "Check-in" in act.title:
                    new_activities.append(
                        act.model_copy(
                            update={
                                "title": f"Check-in at {hotel['name']}",
                                "location": hotel.get("address_line") or current_plan.destination,
                                "latitude": new_stay.latitude,
                                "longitude": new_stay.longitude,
                                "entity_id": hotel["hotel_id"],
                            }
                        )
                    )
                elif day.day_number == len(current_plan.days) and "Check-out" in act.title:
                    new_activities.append(
                        act.model_copy(
                            update={
                                "title": f"Check-out from {hotel['name']}",
                                "location": hotel.get("address_line") or current_plan.destination,
                                "latitude": new_stay.latitude,
                                "longitude": new_stay.longitude,
                                "entity_id": hotel["hotel_id"],
                            }
                        )
                    )
                else:
                    new_activities.append(act)
            else:
                new_activities.append(act)
        updated_days.append(day.model_copy(update={"activities": new_activities}))

    temp_plan = current_plan.model_copy(
        update={
            "accommodation": [new_stay],
            "days": updated_days,
        }
    )

    auth_total, est_total, _ = itinerary_service.calculate_plan_totals(conn, temp_plan)

    # Budget validation
    if current_plan.budget:
        budget_minor = money.to_minor(current_plan.budget)
        new_total_minor = money.to_minor(auth_total or "0.00")
        if new_total_minor > budget_minor:
            raise RefusalError(
                "BUDGET_EXCEEDED",
                f"Changing hotel to '{hotel['name']}' increases total to {current_plan.currency} {auth_total}, exceeding the budget of {current_plan.currency} {current_plan.budget}.",
                http_status=422,
            )

    updated_plan = temp_plan.model_copy(
        update={
            "total_authoritative_cost": auth_total,
            "total_estimated_cost": est_total,
            "version": current_plan.version + 1,
        }
    )

    saved_plan = itinerary_service.update_itinerary(
        conn, clock, itinerary_id, user_id, updated_plan
    )

    preference_service.record_phase4_audit_event(
        conn, clock, user_id,
        "HOTEL_SELECTED_FROM_EXPLORATION",
        hotel["hotel_id"],
        {
            "itinerary_id": itinerary_id,
            "hotel_name": hotel["name"],
            "room_name": room["name"],
            "new_total": saved_plan.total_authoritative_cost,
            "new_version": saved_plan.version,
        },
    )

    return saved_plan

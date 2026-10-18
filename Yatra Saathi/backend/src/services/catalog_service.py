"""Thin read-only pass-through over the catalog repository for the agent's
`GET /catalog/...` endpoints (section 12). No ranking, no filtering beyond
what is asked for."""
from __future__ import annotations

from src.db.repositories import catalog as catalog_repo

CATALOG_RESOURCES = ("cities", "airports", "flights", "fares", "hotels", "room-types", "inventory", "activities")


def cities(conn, **kwargs) -> list[dict]:
    return catalog_repo.list_cities(conn, **kwargs)


def airports(conn, **kwargs) -> list[dict]:
    return catalog_repo.list_airports(conn, **kwargs)


def flights(conn, **kwargs) -> list[dict]:
    return catalog_repo.search_flights(conn, **kwargs)


def fares(conn, flight_id: str, **kwargs) -> list[dict]:
    return catalog_repo.list_fares_for_flight(conn, flight_id, **kwargs)


def hotels(conn, **kwargs) -> list[dict]:
    return catalog_repo.search_hotels(conn, **kwargs)


def room_types(conn, hotel_id: str, **kwargs) -> list[dict]:
    return catalog_repo.list_room_types_for_hotel(conn, hotel_id, **kwargs)


def inventory(conn, entity_type: str, entity_id: str, **kwargs) -> list[dict]:
    return catalog_repo.list_inventory_for_entity(conn, entity_type, entity_id, **kwargs)


def activities(conn, **kwargs) -> list[dict]:
    return catalog_repo.list_activities(conn, **kwargs)


def activity(conn, poi_id: str) -> Optional[dict]:
    return catalog_repo.get_activity(conn, poi_id)


# Aliases
list_activities = activities
get_activity = activity


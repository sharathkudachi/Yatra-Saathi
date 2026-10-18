"""GET /internal/agent/v1/sessions/{sid}/catalog/{resource} (plain reads, no ranking)."""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from src.api.deps import CurrentAgent, get_conn, get_current_agent, require_agent_session_match
from src.contracts.envelope import ok
from src.core import fx
from src.services import catalog_service

router = APIRouter()


@router.get("/sessions/{session_id}/catalog/cities")
def cities(session_id: str, name_like: Optional[str] = None,
           agent: CurrentAgent = Depends(get_current_agent), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    return ok({"rows": catalog_service.cities(conn, name_like=name_like)})


@router.get("/sessions/{session_id}/catalog/currencies")
def currencies(session_id: str, agent: CurrentAgent = Depends(get_current_agent)):
    # The demo exchange rates the backend prices with, so the agent converts identically.
    require_agent_session_match(session_id, agent)
    return ok({"rows": fx.rate_rows()})


@router.get("/sessions/{session_id}/catalog/airports")
def airports(session_id: str, city_id: Optional[str] = None,
             agent: CurrentAgent = Depends(get_current_agent), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    return ok({"rows": catalog_service.airports(conn, city_id=city_id)})


@router.get("/sessions/{session_id}/catalog/flights")
def flights(session_id: str, origin_airport_id: Optional[str] = None,
            dest_airport_id: Optional[str] = None, depart_date: Optional[str] = None,
            agent: CurrentAgent = Depends(get_current_agent), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    return ok({"rows": catalog_service.flights(conn, origin_airport_id=origin_airport_id,
                                               dest_airport_id=dest_airport_id, depart_date=depart_date)})


@router.get("/sessions/{session_id}/catalog/fares")
def fares(session_id: str, flight_id: str, agent: CurrentAgent = Depends(get_current_agent),
          conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    return ok({"rows": catalog_service.fares(conn, flight_id)})


@router.get("/sessions/{session_id}/catalog/hotels")
def hotels(session_id: str, city_id: Optional[str] = None,
           agent: CurrentAgent = Depends(get_current_agent), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    return ok({"rows": catalog_service.hotels(conn, city_id=city_id)})


@router.get("/sessions/{session_id}/catalog/room-types")
def room_types(session_id: str, hotel_id: str, agent: CurrentAgent = Depends(get_current_agent),
               conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    return ok({"rows": catalog_service.room_types(conn, hotel_id)})


@router.get("/sessions/{session_id}/catalog/inventory")
def inventory(session_id: str, entity_type: str, entity_id: str, start_date: Optional[str] = None,
              end_date: Optional[str] = None, agent: CurrentAgent = Depends(get_current_agent),
              conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    return ok({"rows": catalog_service.inventory(conn, entity_type, entity_id, start_date=start_date,
                                                 end_date=end_date)})


@router.get("/sessions/{session_id}/catalog/activities")
def activities(session_id: str, city_id: Optional[str] = None, city_name: Optional[str] = None,
               currency: Optional[str] = None, agent: CurrentAgent = Depends(get_current_agent),
               conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    return ok({"rows": catalog_service.activities(conn, city_id=city_id, city_name=city_name, currency=currency)})


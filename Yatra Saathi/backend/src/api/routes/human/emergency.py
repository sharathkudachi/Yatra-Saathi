"""Human emergency assistance & SOS routes (/api/v1/emergency)."""
from __future__ import annotations

import sqlite3
from fastapi import APIRouter, Depends, Query

from src.api.deps import CurrentUser, get_conn, get_current_user
from src.contracts.envelope import ok
from src.schemas.emergency import (
    ActivateSosRequest,
    CreateTrustedContactRequest,
    ShareTripRequest,
    UpdateTrustedContactRequest,
)
from src.services.emergency_service import EmergencyService
from src.services.geocoding_service import GeocodingService

router = APIRouter()


@router.get("/emergency/geocode")
def geocode_location_endpoint(
    query: str = Query(..., min_length=2, description="Place or landmark name to search"),
    limit: int = Query(5, ge=1, le=10),
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Geocode a place or landmark for emergency location attachment (Nominatim with local fallback)."""
    service = GeocodingService(conn)
    res = service.search_places(query=query, limit=limit)
    return ok(res.model_dump())


@router.get("/emergency/info")
def get_emergency_info_endpoint(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Retrieve authoritative emergency services, trusted contacts, and current trip context."""
    service = EmergencyService(conn)
    info = service.get_emergency_info(user.user_id)
    return ok(info.model_dump())


@router.post("/emergency/activate")
def activate_sos_endpoint(
    body: ActivateSosRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Explicitly activate SOS assistance in demo simulation mode."""
    service = EmergencyService(conn)
    res = service.activate_sos(user.user_id, body)
    return ok(res.model_dump())


@router.post("/emergency/share-trip")
def share_trip_endpoint(
    body: ShareTripRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Share verified trip details to trusted contacts with explicit user confirmation."""
    service = EmergencyService(conn)
    res = service.share_trip_details(user.user_id, body)
    return ok(res.model_dump())


@router.get("/emergency/contacts")
def list_contacts_endpoint(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """List trusted emergency contacts for authenticated user."""
    service = EmergencyService(conn)
    contacts = service.list_trusted_contacts(user.user_id)
    return ok([c.model_dump() for c in contacts])


@router.post("/emergency/contacts")
def add_contact_endpoint(
    body: CreateTrustedContactRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Add a trusted emergency contact."""
    service = EmergencyService(conn)
    contact = service.add_trusted_contact(user.user_id, body)
    return ok(contact.model_dump())


@router.put("/emergency/contacts/{contact_id}")
def update_contact_endpoint(
    contact_id: str,
    body: UpdateTrustedContactRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Update an existing trusted emergency contact."""
    service = EmergencyService(conn)
    contact = service.update_trusted_contact(user.user_id, contact_id, body)
    return ok(contact.model_dump())


@router.delete("/emergency/contacts/{contact_id}")
def delete_contact_endpoint(
    contact_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Delete a trusted emergency contact."""
    service = EmergencyService(conn)
    service.delete_trusted_contact(user.user_id, contact_id)
    return ok({"deleted": True, "contact_id": contact_id})

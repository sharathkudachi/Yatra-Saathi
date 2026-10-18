"""Human language and multilingual routes (/api/v1/language)."""
from __future__ import annotations

import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_conn, get_current_user
from src.contracts.envelope import ok
from src.schemas.multilingual import (
    MultilingualTextRequest,
    UpdateLanguagePreferenceRequest,
)
from src.services.language_service import LanguageService

router = APIRouter()


@router.get("/language")
def get_language_preference(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Retrieve the current user's preferred language and supported languages."""
    service = LanguageService(conn)
    current_lang = service.get_preferred_language(user.user_id)
    prefs = service.repo.get_notification_preferences(user.user_id)
    data = {
        "user_id": user.user_id,
        "preferred_language": current_lang,
        "supported_languages": [
            {"code": "en-IN", "name": "English (India)", "native_name": "English"},
            {"code": "hi-IN", "name": "Hindi", "native_name": "हिन्दी"},
            {"code": "ta-IN", "name": "Tamil", "native_name": "தமிழ்"},
        ],
        "updated_at": prefs["updated_at"],
    }
    return ok(data)


@router.put("/language")
def update_language_preference(
    body: UpdateLanguagePreferenceRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Update the authenticated user's preferred language."""
    service = LanguageService(conn)
    res = service.set_preferred_language(user.user_id, body.preferred_language)
    return ok(res.dict())


@router.get("/language/preference")
def get_language_preference_alias(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Alias for /language."""
    return get_language_preference(user, conn)


@router.put("/language/preference")
def update_language_preference_alias(
    body: dict,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Alias for /language accepting language_code."""
    lang = body.get("language_code") or body.get("preferred_language") or "en-IN"
    service = LanguageService(conn)
    res = service.set_preferred_language(user.user_id, lang)
    return ok(res.dict())


@router.post("/language/detect")
def detect_language_endpoint(
    body: MultilingualTextRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Detect language of supplied text."""
    service = LanguageService(conn)
    res = service.detect_language(body.text, user.user_id)
    return ok(res.dict())

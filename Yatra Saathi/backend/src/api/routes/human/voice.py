"""Human voice assistant routes (/api/v1/voice)."""
from __future__ import annotations

import sqlite3
from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_conn, get_current_user
from src.contracts.envelope import ok
from src.schemas.voice import (
    VoiceTranscriptionRequest,
)
from src.services.voice_service import VoiceService

router = APIRouter()


@router.post("/voice/transcribe")
def transcribe_voice_endpoint(
    body: VoiceTranscriptionRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Processes speech transcript safely through NLU and enforces confirmation boundaries."""
    service = VoiceService(conn)
    result = service.process_voice_transcript(body, user_id=user.user_id)
    return ok(result.dict())

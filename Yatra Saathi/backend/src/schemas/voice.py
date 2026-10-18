"""Pydantic schemas for Phase 6 Voice Assistant."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .multilingual import SupportedLanguageCode, CanonicalIntent


class VoiceTranscriptionRequest(BaseModel):
    transcript: Optional[str] = Field(None, max_length=2000)
    text_hint: Optional[str] = None
    audio_base64: Optional[str] = None  # Ephemeral, never stored in DB
    language_hint: Optional[SupportedLanguageCode] = None
    session_id: Optional[str] = None


class VoiceActionConfirmation(BaseModel):
    action_type: str  # "CONFIRM_BOOKING", "CANCEL_BOOKING", "DELETE_TRIP"
    target_reference: Optional[str] = None
    title: str
    message: str
    requires_visual_click: bool = True
    confirm_button_label: str
    cancel_button_label: str = "Cancel"


class VoiceTranscriptionResponse(BaseModel):
    transcript: str
    detected_language: SupportedLanguageCode
    confidence: float
    canonical_intent: Optional[CanonicalIntent] = None
    pending_confirmation: Optional[VoiceActionConfirmation] = None
    requires_explicit_confirmation: bool = False
    confirmation_prompt: Optional[str] = None
    system_response_text: str
    tts_audio_url: Optional[str] = None  # Optional synthetic speech url/directive
    raw_audio_persisted: bool = False  # Strictly False (privacy guarantee)

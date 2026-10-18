"""Pydantic schemas for Phase 6 Multilingual Intelligence."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

SupportedLanguageCode = Literal["en-IN", "hi-IN", "ta-IN"]

SUPPORTED_LANGUAGES = [
    {"code": "en-IN", "name": "English (India)", "native_name": "English"},
    {"code": "hi-IN", "name": "Hindi", "native_name": "हिन्दी"},
    {"code": "ta-IN", "name": "Tamil", "native_name": "தமிழ்"},
]


class LanguageDetectionResult(BaseModel):
    language_code: SupportedLanguageCode
    confidence: float = Field(ge=0.0, le=1.0)
    detection_source: str
    is_low_confidence: bool = False
    suggested_fallback: Optional[SupportedLanguageCode] = None


class UserLanguagePreferenceResponse(BaseModel):
    user_id: str
    preferred_language: SupportedLanguageCode
    supported_languages: List[Dict[str, str]]
    updated_at: str


class UpdateLanguagePreferenceRequest(BaseModel):
    preferred_language: SupportedLanguageCode


class MultilingualTextRequest(BaseModel):
    text: str
    source_language: Optional[SupportedLanguageCode] = None
    target_language: Optional[SupportedLanguageCode] = None


class LocalizedResponse(BaseModel):
    original_text: str
    localized_text: str
    language: SupportedLanguageCode
    preserved_identifiers: List[str] = Field(default_factory=list)


class CanonicalIntent(BaseModel):
    language: SupportedLanguageCode
    confidence: float
    intent_type: str = "travel_query"
    destination: Optional[str] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    nights: Optional[int] = None
    travellers: Optional[int] = None
    budget_amount: Optional[str] = None
    budget_currency: Optional[str] = "INR"
    preferences: Dict[str, Any] = Field(default_factory=dict)
    action_requested: Optional[str] = None
    requires_explicit_confirmation: bool = False
    confirmation_prompt: Optional[str] = None

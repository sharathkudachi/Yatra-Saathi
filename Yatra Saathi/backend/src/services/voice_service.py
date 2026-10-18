"""Phase 6 Voice Assistant Service.

Responsibilities:
- Provider abstraction for Speech-To-Text (STT) and Text-To-Speech (TTS).
- Treats voice transcripts as untrusted input.
- Strict voice confirmation safety: material actions (booking, cancellation) require visual confirmation.
- Absolute privacy: zero raw audio is ever stored in SQLite or filesystem.
- Text fallback support.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, Optional

from src.contracts.codes import RefusalError
from src.services.language_service import LanguageService
from src.schemas.voice import (
    VoiceActionConfirmation,
    VoiceTranscriptionRequest,
    VoiceTranscriptionResponse,
)


class BaseSpeechToTextProvider:
    def transcribe(self, transcript: str, audio_bytes: Optional[bytes] = None) -> str:
        raise NotImplementedError


class MockSpeechToTextProvider(BaseSpeechToTextProvider):
    def transcribe(self, transcript: str, audio_bytes: Optional[bytes] = None) -> str:
        return transcript.strip()


class VoiceService:
    def __init__(self, conn: sqlite3.Connection, stt_provider: Optional[BaseSpeechToTextProvider] = None):
        self.conn = conn
        self.stt_provider = stt_provider or MockSpeechToTextProvider()
        self.lang_service = LanguageService(conn)

    def process_voice_transcript(
        self,
        request: VoiceTranscriptionRequest,
        user_id: Optional[str] = None,
    ) -> VoiceTranscriptionResponse:
        """Processes voice transcripts safely through NLU, enforcing strict confirmation boundaries."""
        raw_text = (request.transcript or request.text_hint or "").strip()
        if not raw_text:
            raise RefusalError("VOICE_TRANSCRIPTION_FAILED", "Empty or corrupted voice transcription received.")

        # Transcribe through provider abstraction
        clean_text = self.stt_provider.transcribe(raw_text)

        # Detect language
        detection = self.lang_service.detect_language(clean_text, user_id)
        lang = request.language_hint or detection.language_code

        # Canonical NLU extraction
        intent = self.lang_service.extract_canonical_intent(clean_text, user_id)

        # Voice Safety Check: Material Actions require explicit visual confirmation
        pending_conf: Optional[VoiceActionConfirmation] = None
        system_response = ""

        # 1. Cancellation check
        if intent.action_requested == "CANCEL_BOOKING" or re.search(r"\b(cancel|रद्द|ரத்து)\b", clean_text, re.I):
            # Extract possible booking reference
            m_ref = re.search(r"(YTR-DEMO-[A-Z0-9]{8})", clean_text)
            target_ref = m_ref.group(1) if m_ref else "your active booking"
            pending_conf = VoiceActionConfirmation(
                action_type="CANCEL_BOOKING",
                target_reference=target_ref,
                title="Cancel Booking Confirmation",
                message=f"Do you want to cancel booking {target_ref}? This action cannot be undone.",
                requires_visual_click=True,
                confirm_button_label="Yes, Cancel Booking",
                cancel_button_label="Keep Trip",
            )
            system_response = f"I heard your request to cancel booking {target_ref}. Please confirm visually to proceed."

        # 2. Booking confirmation check
        elif intent.action_requested == "CONFIRM_BOOKING" or re.search(r"\b(confirm\s+(?:my\s+)?booking|book\s+(?:this\s+)?trip|book\s+it|कन्फर्म करो)\b", clean_text, re.I):
            pending_conf = VoiceActionConfirmation(
                action_type="CONFIRM_BOOKING",
                target_reference=None,
                title="Confirm Trip Booking",
                message="Review details and click Confirm Booking to complete your reservation.",
                requires_visual_click=True,
                confirm_button_label="Proceed to Booking Review",
                cancel_button_label="Cancel",
            )
            system_response = "I heard your request to book this trip. Please review the booking summary and confirm visually."

        # 3. Emergency / SOS check
        elif intent.action_requested == "EMERGENCY_ASSISTANCE" or re.search(r"\b(emergency|sos|danger|help me|मदद|आपातकाल)\b", clean_text, re.I):
            system_response = (
                "If you are in immediate danger, please dial 112 for emergency services immediately. "
                "I can open the Emergency Assistance panel for your configured contacts and trip details."
            )

        # 4. Standard informational or planning request
        else:
            if lang == "hi-IN":
                system_response = f"मैंने सुना: '{clean_text}'। आपकी यात्रा योजना तैयार की जा रही है।"
            elif lang == "ta-IN":
                system_response = f"நான் கேட்டது: '{clean_text}'. உங்கள் பயண திட்டம் தயாரிக்கப்படுகிறது."
            else:
                system_response = f"Understood: '{clean_text}'. Processing your travel request."

        requires_conf = pending_conf is not None
        conf_prompt = pending_conf.message if pending_conf else None

        return VoiceTranscriptionResponse(
            transcript=clean_text,
            detected_language=lang,
            confidence=detection.confidence,
            canonical_intent=intent,
            pending_confirmation=pending_conf,
            requires_explicit_confirmation=requires_conf,
            confirmation_prompt=conf_prompt,
            system_response_text=system_response,
            tts_audio_url=None,
            raw_audio_persisted=False,  # Privacy guarantee
        )

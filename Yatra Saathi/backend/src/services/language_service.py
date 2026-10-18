"""Phase 6 Language & Multilingual Service.

Responsibilities:
- Deterministic and bounded language detection (en-IN, hi-IN, ta-IN).
- Low-confidence handling with safe fallback to user profile / conversation language.
- Persistence of user language preferences.
- Preservation of numbers, currencies, dates, booking references, and identifiers.
- Canonical structured intent generation across supported languages.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from src.contracts.codes import RefusalError
from src.db.repositories.phase6_repo import Phase6Repository
from src.schemas.multilingual import (
    SUPPORTED_LANGUAGES,
    CanonicalIntent,
    LanguageDetectionResult,
    LocalizedResponse,
    SupportedLanguageCode,
    UserLanguagePreferenceResponse,
)

# Immutable patterns that MUST NOT be altered or translated
PRESERVED_PATTERNS = [
    r"YTR-DEMO-[A-Z0-9]{8}",            # Demo booking references
    r"(?:[A-Z0-9]{2}|[A-Z]{3})-\d{3,4}", # Flight numbers (e.g., AI-101, 6E-204)
    r"(?:bkg|trp|itn|htl|flt|usr|cit)_[0-9a-f]{8,16}",  # Entity IDs
    r"₹\s*[\d,]+(?:\.\d{2})?",           # INR currency amounts
    r"\$\s*[\d,]+(?:\.\d{2})?",          # USD currency amounts
    r"\b\d{4}-\d{2}-\d{2}\b",            # ISO dates (2026-10-12)
    r"\b\d{1,2}:\d{2}(?:\s*[AP]M)?\b",   # Times
    r"\b(?:112|100|102|101|108|1091|1363)\b", # Emergency numbers
]

# Canonical city transliterations
CITY_TRANSLITERATIONS: Dict[str, str] = {
    # Hindi
    "जयपुर": "Jaipur",
    "दिल्ली": "Delhi",
    "नई दिल्ली": "Delhi",
    "मुंबई": "Mumbai",
    "बम्बई": "Mumbai",
    "बेंगलुरु": "Bengaluru",
    "बैंगलोर": "Bengaluru",
    "कोलकाता": "Kolkata",
    "चेन्नई": "Chennai",
    "मद्रास": "Chennai",
    "गोवा": "Goa",
    "आगरा": "Agra",
    "वाराणसी": "Varanasi",
    "उदयपुर": "Udaipur",
    "केरल": "Kochi",
    "कोच्चि": "Kochi",
    # Tamil
    "ஜெய்ப்பூர்": "Jaipur",
    "ஜெய்ப்பூருக்கு": "Jaipur",
    "தில்லி": "Delhi",
    "புது தில்லி": "Delhi",
    "மும்பை": "Mumbai",
    "பெங்களூரு": "Bengaluru",
    "கொல்கத்தா": "Kolkata",
    "சென்னை": "Chennai",
    "கோவா": "Goa",
    "ஆக்ரா": "Agra",
    "வாரணாசி": "Varanasi",
    "உதய்பூர்": "Udaipur",
    "கொச்சி": "Kochi",
}

# Standard localized templates
LOCALIZED_STRINGS: Dict[str, Dict[str, str]] = {
    "booking_confirmed_title": {
        "en-IN": "Booking Confirmed",
        "hi-IN": "बुकिंग कन्फर्म हो गई",
        "ta-IN": "முன்பதிவு உறுதி செய்யப்பட்டது",
    },
    "booking_confirmed_body": {
        "en-IN": "Your demo booking {reference} is confirmed.",
        "hi-IN": "आपकी डेमो बुकिंग {reference} कन्फर्म हो गई है।",
        "ta-IN": "உங்கள் டெமோ முன்பதிவு {reference} உறுதி செய்யப்பட்டது.",
    },
    "booking_cancelled_title": {
        "en-IN": "Booking Cancelled",
        "hi-IN": "बुकिंग रद्द कर दी गई",
        "ta-IN": "முன்பதிவு ரத்து செய்யப்பட்டது",
    },
    "booking_cancelled_body": {
        "en-IN": "Your booking {reference} has been cancelled.",
        "hi-IN": "आपकी बुकिंग {reference} रद्द कर दी गई है।",
        "ta-IN": "உங்கள் முன்பதிவு {reference} ரத்து செய்யப்பட்டது.",
    },
    "trip_upcoming_title": {
        "en-IN": "Upcoming Trip",
        "hi-IN": "आगामी यात्रा",
        "ta-IN": "வரவிருக்கும் பயணம்",
    },
    "trip_upcoming_body": {
        "en-IN": "Your trip to {destination} begins on {date}.",
        "hi-IN": "{destination} की आपकी यात्रा {date} को शुरू होगी।",
        "ta-IN": "{destination} பயணமானது {date} அன்று தொடங்குகிறது.",
    },
    "trip_pack_ready_title": {
        "en-IN": "Trip Pack Ready",
        "hi-IN": "ट्रिप पैक तैयार है",
        "ta-IN": "பயண ஆவணத் தொகுப்பு தயார்",
    },
    "trip_pack_ready_body": {
        "en-IN": "Your travel documents for {destination} are ready to download.",
        "hi-IN": "{destination} के लिए आपके यात्रा दस्तावेज़ डाउनलोड के लिए तैयार हैं।",
        "ta-IN": "{destination} க்கான உங்கள் பயண ஆவணங்கள் பதிவிறக்க தயாராக உள்ளன.",
    },
}


class LanguageService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = Phase6Repository(conn)

    def detect_language(self, text: str, user_id: Optional[str] = None) -> LanguageDetectionResult:
        """Deterministic, script-based language detection."""
        if not text or not text.strip():
            fallback = self.get_preferred_language(user_id) if user_id else "en-IN"
            return LanguageDetectionResult(
                language_code=fallback,
                confidence=0.5,
                detection_source="fallback_empty",
                is_low_confidence=True,
                suggested_fallback=fallback,
            )

        clean = text.strip()

        # 1. Script checks
        has_devanagari = bool(re.search(r"[\u0900-\u097F]", clean))
        has_tamil = bool(re.search(r"[\u0B80-\u0BFF]", clean))

        if has_devanagari and not has_tamil:
            return LanguageDetectionResult(
                language_code="hi-IN",
                confidence=0.98,
                detection_source="script_analysis_devanagari",
                is_low_confidence=False,
            )
        if has_tamil and not has_devanagari:
            return LanguageDetectionResult(
                language_code="ta-IN",
                confidence=0.98,
                detection_source="script_analysis_tamil",
                is_low_confidence=False,
            )

        # 2. Ambiguous multi-script
        if has_devanagari and has_tamil:
            fallback = self.get_preferred_language(user_id) if user_id else "en-IN"
            return LanguageDetectionResult(
                language_code=fallback,
                confidence=0.4,
                detection_source="ambiguous_mixed_scripts",
                is_low_confidence=True,
                suggested_fallback=fallback,
            )

        # 3. Latin script
        # Check if text looks like pure numbers or symbols
        has_letters = bool(re.search(r"[a-zA-Z]", clean))
        if not has_letters:
            fallback = self.get_preferred_language(user_id) if user_id else "en-IN"
            return LanguageDetectionResult(
                language_code=fallback,
                confidence=0.5,
                detection_source="latin_no_letters",
                is_low_confidence=True,
                suggested_fallback=fallback,
            )

        # Latin English default
        return LanguageDetectionResult(
            language_code="en-IN",
            confidence=0.95,
            detection_source="script_analysis_latin",
            is_low_confidence=False,
        )

    def get_preferred_language(self, user_id: str) -> SupportedLanguageCode:
        return self.repo.get_user_language_preference(user_id)

    def set_preferred_language(self, user_id: str, language_code: str) -> UserLanguagePreferenceResponse:
        norm = self._normalize_code(language_code)
        if norm not in ("en-IN", "hi-IN", "ta-IN"):
            raise RefusalError("UNSUPPORTED_LANGUAGE", f"Language {language_code} is not supported in Phase 6.")
        saved = self.repo.set_user_language_preference(user_id, norm)
        return UserLanguagePreferenceResponse(
            user_id=user_id,
            preferred_language=saved,
            supported_languages=SUPPORTED_LANGUAGES,
            updated_at=self.repo.get_notification_preferences(user_id)["updated_at"],
        )

    def extract_canonical_intent(self, text: str, user_id: Optional[str] = None) -> CanonicalIntent:
        """Extracts structured intent deterministically, preserving semantics across en-IN, hi-IN, and ta-IN."""
        detection = self.detect_language(text, user_id)
        lang = detection.language_code
        lowered = text.lower()

        # Destination resolution
        destination = None
        for trans_term, canonical_name in CITY_TRANSLITERATIONS.items():
            if trans_term in text:
                destination = canonical_name
                break
        if not destination:
            # Check English city mentions
            for city in ["jaipur", "delhi", "mumbai", "bengaluru", "kolkata", "chennai", "goa", "agra", "kochi"]:
                if re.search(rf"\b{city}\b", lowered):
                    destination = city.title()
                    break

        # Travellers resolution
        travellers = None
        if re.search(r"(solo|alone|just me|अकेले|தனியாக)", lowered):
            travellers = 1
        elif re.search(r"(couple|two|हम दो|இருவர்|2\s*(?:लोग|people|நபர்கள்)?)", lowered):
            travellers = 2
        else:
            m = re.search(r"(\d+)\s*(?:people|persons?|adults?|लोग|व्यक्ति|நபர்கள்|பயணிகள்)", text)
            if m:
                travellers = int(m.group(1))

        # Budget extraction
        budget_amount = None
        currency = "INR"
        # Check standard digits or Hindi/Tamil numeric words
        m_num = re.search(r"(?:₹|rs\.?|inr|रुपये|रुपए|ரூபாய்)?\s*([0-9,]+)(?:\s*(?:k|thousand|हजार|हज़ार|ஆயிரம்|लाख|लख|லட்சம்))?", lowered)
        if m_num and len(m_num.group(1).replace(",", "")) >= 3:
            raw_val = m_num.group(1).replace(",", "")
            # check multipliers
            scale = 1
            if any(k in lowered for k in ["k", "thousand", "हजार", "हज़ार", "ஆயிரம்"]):
                scale = 1000
            elif any(k in lowered for k in ["lakh", "लाख", "லட்சம்"]):
                scale = 100000
            total_val = int(raw_val) * scale if raw_val.isdigit() else 50000
            budget_amount = f"{total_val:.2f}"

        # Preferences extraction
        preferences: Dict[str, Any] = {}
        # 1. Direct flights
        if any(term in text for term in ["direct flight", "non-stop", "सीधी उड़ान", "डायरेक्ट फ्लाइट", "நேரடி விமானம்"]):
            preferences["direct_flights_only"] = True

        # 2. Pace
        if any(term in text for term in ["relaxed", "slow pace", "आराम से", "आरामदायक", "நிதானமான"]):
            preferences["preferred_daily_pace"] = "relaxed"
        elif any(term in text for term in ["packed", "fast pace", "जल्दी", "வேகமான"]):
            preferences["preferred_daily_pace"] = "fast"

        # Action requests
        action_requested = None
        requires_explicit_conf = False
        conf_prompt = None

        if any(term in text for term in ["cancel booking", "cancel my trip", "बुकिंग रद्द", "रद्द करो", "ரத்து செய்"]):
            action_requested = "CANCEL_BOOKING"
            requires_explicit_conf = True
            conf_prompt = "Do you want to cancel your booking?"
        elif any(term in text for term in ["confirm booking", "book this trip", "बुकिंग कन्फर्म", "முன்பதிவு செய்"]):
            action_requested = "CONFIRM_BOOKING"
            requires_explicit_conf = True
            conf_prompt = "Do you want to proceed to confirm this booking?"
        elif any(term in text for term in ["sos", "emergency", "मदद", "आपातकाल", "அவசரம்"]):
            action_requested = "EMERGENCY_ASSISTANCE"
            requires_explicit_conf = False
            conf_prompt = "Would you like to open the Emergency Assistance panel?"

        return CanonicalIntent(
            language=lang,
            confidence=detection.confidence,
            intent_type="travel_query" if not action_requested else "action_request",
            destination=destination,
            travellers=travellers,
            budget_amount=budget_amount,
            budget_currency=currency,
            preferences=preferences,
            action_requested=action_requested,
            requires_explicit_confirmation=requires_explicit_conf,
            confirmation_prompt=conf_prompt,
        )

    def localize_template(
        self,
        key: str,
        target_language: SupportedLanguageCode,
        **kwargs: Any,
    ) -> str:
        """Returns a localized template string with strict preservation of kwargs invariants."""
        tpl = LOCALIZED_STRINGS.get(key, {}).get(target_language) or LOCALIZED_STRINGS.get(key, {}).get("en-IN")
        if not tpl:
            return ""
        # Format kwargs without altering their exact values
        return tpl.format(**kwargs)

    def extract_preserved_identifiers(self, text: str) -> List[str]:
        """Finds all booking references, currencies, dates, flight numbers, and IDs that must remain unaltered."""
        found: List[str] = []
        for pattern in PRESERVED_PATTERNS:
            for m in re.finditer(pattern, text):
                found.append(m.group(0))
        return list(dict.fromkeys(found))

    def _normalize_code(self, code: str) -> str:
        c = code.strip().lower()
        if c in ("en", "en-in", "english"):
            return "en-IN"
        if c in ("hi", "hi-in", "hindi"):
            return "hi-IN"
        if c in ("ta", "ta-in", "tamil"):
            return "ta-IN"
        return code

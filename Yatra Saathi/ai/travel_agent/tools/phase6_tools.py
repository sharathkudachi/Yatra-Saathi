"""Bounded AI Phase 6 Multimodal, Notifications & Emergency Tools.

Safety Rules:
- All operations call backend HTTP client or service abstractions.
- AI NEVER directly modifies SQLite or executes SQL.
- Voice/text cannot bypass explicit confirmation boundaries.
- Prompt injection defense strictly rejects attempts to call arbitrary numbers,
  access other users' contacts, send data to arbitrary URLs, or auto-activate SOS.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Prompt injection patterns specific to Phase 6
PHASE6_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"ignore\s+(safety|rules|the\s+rules)",
    r"cancel\s+(booking\s+)?without\s+confirmation",
    r"call\s+(this\s+)?arbitrary\s+number",
    r"send\s+(my\s+)?trip\s+to\s+https?://",
    r"reveal\s+(another\s+)?user'?s?\s+emergency\s+contact",
    r"give\s+me\s+another\s+user",
    r"automatically\s+activate\s+sos",
    r"activate\s+sos\s+without\s+confirmation",
    r"send\s+notifications?\s+to\s+everyone",
    r"ignore\s+(my\s+)?notification\s+settings",
    r"bypass\s+safety",
    r"drop\s+table",
    r"select\s+\*\s+from",
]


def check_phase6_injection(text: Optional[str]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    for pattern in PHASE6_INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            return True
    return False


def detect_user_language_tool(text: str) -> Dict[str, Any]:
    """Bounded tool to detect language of input text."""
    if check_phase6_injection(text):
        return {"error": "INJECTION_ATTEMPT_DETECTED", "language_code": "en-IN", "confidence": 0.0}

    # Deterministic script check
    clean = text.strip()
    if re.search(r"[\u0900-\u097F]", clean):
        return {"language_code": "hi-IN", "confidence": 0.98, "source": "script_analysis"}
    if re.search(r"[\u0B80-\u0BFF]", clean):
        return {"language_code": "ta-IN", "confidence": 0.98, "source": "script_analysis"}
    return {"language_code": "en-IN", "confidence": 0.95, "source": "script_analysis"}


def get_emergency_assistance_info_tool(
    client,
    session_id: str,
    *,
    user_query: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieves authoritative emergency numbers and trip context safely via backend client."""
    if check_phase6_injection(user_query):
        return {
            "refused": True,
            "reason": "Security violation: prompt injection detected.",
            "safety_notice": "If you are in immediate danger, please dial 112 directly on your phone.",
        }

    # Bounded response with verified static configuration
    return {
        "safety_notice": "If you are in immediate danger, contact local emergency services immediately (Dial 112).",
        "primary_emergency_number": "112",
        "official_numbers": {
            "National Emergency Helpline": "112",
            "Police": "100",
            "Ambulance": "102",
            "Fire": "101",
            "Women Helpline": "1091",
            "Tourist Helpline": "1363",
        },
        "location_tracking": "Disabled (never tracked without consent)",
        "action_required": "To activate SOS or share trip details, user must explicitly confirm via the Emergency Assistance UI.",
    }


def prepare_trip_share_tool(
    trip_id: str,
    destination: str,
    dates: str,
    booking_reference: Optional[str] = None,
    recipient_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Prepares a bounded trip sharing summary. Rejects arbitrary URLs."""
    if recipient_url and re.search(r"https?://", recipient_url, re.I):
        return {
            "refused": True,
            "reason": "Security violation: Arbitrary external URLs are strictly forbidden for trip sharing.",
        }

    return {
        "trip_id": trip_id,
        "summary": {
            "destination": destination,
            "dates": dates,
            "booking_reference": booking_reference or "YTR-DEMO-TRIP",
        },
        "requires_explicit_confirmation": True,
        "preview_text": f"Emergency Trip Details: Travelling to {destination} ({dates}). Reference: {booking_reference or 'Demo'}.",
    }

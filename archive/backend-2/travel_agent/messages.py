# travel_agent/messages.py
"""User-facing message templates, keyed by BCP-47 language. Falls back to en-IN."""
from typing import Dict

_MESSAGES: Dict[str, Dict[str, str]] = {
    "en-IN": {
        "clarify_intro": "I can plan that. Before I search, I need:",
        "field.origin": "your departure city",
        "field.destination": "your destination city",
        "field.start_date": "your travel start date",
        "field.end_date": "your return date or the number of nights",
        "field.travellers": "the number of travellers",
        "field.budget_cap": "your maximum budget (hard spend cap)",
        "plan_created": "Here is my plan. I will follow these steps and show every search and budget check.",
        "cart_ready": ("Cart prepared.\nTotal: {total}\nBudget: {cap}\nRemaining: {remaining}\n"
                       "Confirmation required before booking."),
        "failed": "I could not prepare a trip: {reason}",
    },
    "hi": {
        "clarify_intro": "मैं यह योजना बना सकता हूँ। खोज से पहले मुझे यह जानकारी चाहिए:",
        "field.origin": "आप किस शहर से यात्रा शुरू करेंगे",
        "field.destination": "आप किस शहर जाना चाहते हैं",
        "field.start_date": "यात्रा की शुरुआत की तारीख",
        "field.end_date": "वापसी की तारीख या कितनी रातें",
        "field.travellers": "कितने यात्री",
        "field.budget_cap": "आपका अधिकतम बजट",
        "plan_created": "यह मेरी योजना है। हर खोज और बजट जाँच आपको दिखाई देगी।",
        "cart_ready": ("कार्ट तैयार है।\nकुल: {total}\nबजट: {cap}\nशेष: {remaining}\n"
                       "बुकिंग से पहले आपकी पुष्टि आवश्यक है।"),
        "failed": "मैं यात्रा तैयार नहीं कर सका: {reason}",
    },
}


def message(language: str, key: str, **values: str) -> str:
    table = _MESSAGES.get(language) or _MESSAGES.get(language.split("-")[0]) or _MESSAGES["en-IN"]
    template = table.get(key) or _MESSAGES["en-IN"][key]
    return template.format(**values)

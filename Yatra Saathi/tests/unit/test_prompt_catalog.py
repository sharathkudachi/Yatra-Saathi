"""Automated tests for the beginner-friendly prompt catalog and 10 UI suggestions."""
import json
import os
import re
import unittest
from datetime import date
from pathlib import Path

from travel_agent.extraction import parse_goal

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
USER_GUIDE_PATH = DOCS_DIR / "USER_INPUT_GUIDE.md"
CATALOG_PATH = DOCS_DIR / "supported_input_examples.json"
APP_TSX_PATH = REPO_ROOT / "frontend" / "src" / "app" / "App.tsx"

TODAY = date(2026, 10, 6)


class PromptCatalogTests(unittest.TestCase):
    def test_user_guide_contains_ten_mandatory_sections(self):
        self.assertTrue(USER_GUIDE_PATH.exists(), f"Missing {USER_GUIDE_PATH}")
        content = USER_GUIDE_PATH.read_text(encoding="utf-8")
        
        required_sections = [
            "1. What can I ask Yatra?",
            "2. How to plan a trip",
            "3. How to search flights",
            "4. How to search hotels",
            "5. How to specify a budget",
            "6. How to specify travellers",
            "7. How to specify dates",
            "8. How to combine requirements",
            "9. What happens when inventory is unavailable",
            "10. What Yatra cannot guarantee",
        ]
        for section in required_sections:
            with self.subTest(section=section):
                self.assertIn(section, content, f"Guide missing required section: {section}")

    def test_supported_input_examples_json_schema(self):
        self.assertTrue(CATALOG_PATH.exists(), f"Missing {CATALOG_PATH}")
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        
        self.assertIn("categories", data)
        categories = {c["id"]: c for c in data["categories"]}
        self.assertIn("trip_planning", categories)
        self.assertIn("flight_search", categories)
        self.assertIn("hotel_search", categories)

        trip_examples = categories["trip_planning"]["examples"]
        self.assertEqual(len(trip_examples), 10, "Must have exactly 10 chat trip planning suggestions")

        for cat_id, cat in categories.items():
            for idx, ex in enumerate(cat["examples"]):
                with self.subTest(category=cat_id, index=idx):
                    self.assertIn("prompt", ex)
                    self.assertIn("category", ex)
                    self.assertIn("supported", ex)
                    self.assertIn("database_validated", ex)
                    self.assertIn("expected_behavior", ex)
                    self.assertIn("notes", ex)
                    self.assertTrue(ex["supported"])
                    self.assertTrue(ex["database_validated"])
                    self.assertIn(ex["validation"], ("PASS", "EXPECTED_CLARIFICATION"))

    def test_frontend_app_tsx_contains_exactly_ten_matching_suggestions(self):
        self.assertTrue(APP_TSX_PATH.exists(), f"Missing {APP_TSX_PATH}")
        app_code = APP_TSX_PATH.read_text(encoding="utf-8")
        
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        catalog_prompts = [ex["prompt"] for ex in data["categories"][0]["examples"]]
        self.assertEqual(len(catalog_prompts), 10)

        for prompt in catalog_prompts:
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, app_code, f"Frontend App.tsx missing suggestion: {prompt}")

    def test_all_ten_suggestions_parse_deterministically(self):
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        chat_examples = data["categories"][0]["examples"]

        for ex in chat_examples:
            prompt = ex["prompt"]
            with self.subTest(prompt=prompt):
                parsed = parse_goal(prompt, TODAY, {"INR"})
                self.assertIsNotNone(parsed.get("destination_name"), f"Missing destination in {prompt}")
                self.assertIsNotNone(parsed.get("start_date"), f"Missing start_date in {prompt}")
                self.assertIsNotNone(parsed.get("end_date"), f"Missing end_date in {prompt}")
                self.assertIsNotNone(parsed.get("travellers"), f"Missing travellers in {prompt}")
                self.assertIsNotNone(parsed.get("budget_amount"), f"Missing budget_amount in {prompt}")

    def test_regression_prompt_preserves_exact_entities(self):
        prompt = "Plan a trip from Mumbai to Kolkata for 5 adults from 12 to 16 October 2026, budget \u20b950000"
        parsed = parse_goal(prompt, TODAY, {"INR"})
        self.assertEqual(parsed.get("origin_name"), "Mumbai")
        self.assertEqual(parsed.get("destination_name"), "Kolkata")
        self.assertEqual(parsed.get("start_date"), "2026-10-12")
        self.assertEqual(parsed.get("end_date"), "2026-10-16")
        self.assertEqual(parsed.get("travellers"), 5)
        self.assertEqual(parsed.get("budget_amount"), "50000")
        self.assertEqual(parsed.get("budget_currency"), "INR")


if __name__ == "__main__":
    unittest.main()

"""Unit and API tests for authoritative geographic coordinates on backend routes."""
import math
import sqlite3
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from starlette.testclient import TestClient

from src.core.clock import FixedClock
from src.core.config import Settings
from src.main import create_app
from tests import support


def is_valid_coord(lat, lng):
    if lat is None or lng is None:
        return False
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return False
    if math.isnan(lat) or math.isnan(lng) or math.isinf(lat) or math.isinf(lng):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0


class TestGeoBackend(unittest.TestCase):
    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        self.conn = self.wc.raw()
        self.conn.row_factory = sqlite3.Row
        self.settings = Settings.from_env({
            "APS_DB_PATH": self.wc.path,
            "APS_DB_ORIGINAL_PATH": support.original_path(),
            "APS_DB_ORIGINAL_SHA256": support.RECORDED_ORIGINAL_SHA256,
        })
        self.client = TestClient(create_app(self.settings, clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))))

    def tearDown(self):
        self.conn.close()
        self.wc.cleanup()
        support.assert_original_untouched()

    def test_search_cities_returns_all_active_cities_with_valid_coordinates(self):
        resp = self.client.get("/api/v1/search/cities")
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]["cities"]
        self.assertEqual(len(data), 60)

        for city in data:
            self.assertIn("cityId", city)
            self.assertIn("name", city)
            self.assertIn("latitude", city)
            self.assertIn("longitude", city)
            lat = city["latitude"]
            lng = city["longitude"]
            self.assertTrue(is_valid_coord(lat, lng), f"Invalid coordinate for city {city['name']}: {lat}, {lng}")

        # Check Mumbai & Kolkata specifically
        mumbai = next(c for c in data if c["name"] == "Mumbai")
        self.assertAlmostEqual(mumbai["latitude"], 19.075984, places=4)
        self.assertAlmostEqual(mumbai["longitude"], 72.877656, places=4)

        kolkata = next(c for c in data if c["name"] == "Kolkata")
        self.assertAlmostEqual(kolkata["latitude"], 22.572646, places=4)
        self.assertAlmostEqual(kolkata["longitude"], 88.363895, places=4)

    def test_hotel_search_returns_authoritative_coordinates(self):
        offer = support.find_hotel_offer(self.conn, nights=2)
        city = self.conn.execute(
            "SELECT c.name FROM hotels h JOIN cities c ON c.city_id = h.city_id WHERE h.hotel_id = ?",
            (offer["hotel_id"],)
        ).fetchone()["name"]
        start = offer["nights"][0]["for_date"]
        end = (date.fromisoformat(offer["nights"][-1]["for_date"]) + timedelta(days=1)).isoformat()

        body = {
            "destination": city,
            "startDate": start,
            "endDate": end,
            "travellers": 1,
            "currency": "INR",
        }
        resp = self.client.post("/api/v1/search/hotels", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        hotels = resp.json()["data"]["hotels"]
        self.assertGreater(len(hotels), 0)

        for hotel in hotels:
            self.assertIn("latitude", hotel)
            self.assertIn("longitude", hotel)
            self.assertIn("address", hotel)
            self.assertTrue(is_valid_coord(hotel["latitude"], hotel["longitude"]))
            self.assertTrue(len(hotel["address"]) > 0)

    def test_flight_search_returns_airport_and_city_coordinates(self):
        offer = support.find_flight_offer(self.conn)
        row = self.conn.execute(
            """SELECT co.name AS origin, cd.name AS dest, substr(f.departs_at, 1, 10) AS day
               FROM flight_fares ff JOIN flights f ON f.flight_id = ff.flight_id
               JOIN airports ao ON ao.airport_id = f.origin_airport_id JOIN cities co ON co.city_id = ao.city_id
               JOIN airports ad ON ad.airport_id = f.dest_airport_id JOIN cities cd ON cd.city_id = ad.city_id
               WHERE ff.fare_id = ?""", (offer["fare_id"],)
        ).fetchone()

        body = {
            "originCity": row["origin"],
            "destinationCity": row["dest"],
            "departureDate": row["day"],
            "passengers": 1,
            "currency": "INR",
        }
        resp = self.client.post("/api/v1/search/flights", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        flights = resp.json()["data"]["flights"]
        self.assertGreater(len(flights), 0)

        for flight in flights:
            self.assertIn("originLatitude", flight)
            self.assertIn("originLongitude", flight)
            self.assertIn("destLatitude", flight)
            self.assertIn("destLongitude", flight)
            self.assertTrue(is_valid_coord(flight["originLatitude"], flight["originLongitude"]))
            self.assertTrue(is_valid_coord(flight["destLatitude"], flight["destLongitude"]))

    def test_invalid_and_out_of_bounds_coordinate_validation(self):
        self.assertFalse(is_valid_coord(91.0, 72.0))
        self.assertFalse(is_valid_coord(-91.0, 72.0))
        self.assertFalse(is_valid_coord(19.0, 181.0))
        self.assertFalse(is_valid_coord(19.0, -181.0))
        self.assertFalse(is_valid_coord(None, 72.0))
        self.assertFalse(is_valid_coord(19.0, None))
        self.assertFalse(is_valid_coord(float("nan"), 72.0))
        self.assertFalse(is_valid_coord(float("inf"), 72.0))
        self.assertTrue(is_valid_coord(0.0, 0.0))
        self.assertTrue(is_valid_coord(-90.0, -180.0))
        self.assertTrue(is_valid_coord(90.0, 180.0))

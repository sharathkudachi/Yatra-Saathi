"""Human flight/hotel search (`POST /api/v1/search/...`): read-only, priced like the cart,
and never showing an offer the cart would refuse. Offers are picked from the working copy
rather than hard-coded, so the tests follow the data."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from src.core.clock import FixedClock
from src.core.config import Settings
from src.db.repositories import catalog as catalog_repo
from src.main import create_app
from tests import support


class SearchTestCase(unittest.TestCase):
    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        self.conn = self.wc.raw()
        self.conn.row_factory = sqlite3.Row
        settings = Settings.from_env({
            "APS_DB_PATH": self.wc.path, "APS_DB_ORIGINAL_PATH": support.original_path(),
            "APS_DB_ORIGINAL_SHA256": support.RECORDED_ORIGINAL_SHA256,
        })
        self.settings = settings
        self.client = TestClient(create_app(settings, clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))))

    def tearDown(self):
        self.conn.close()
        self.wc.cleanup()
        support.assert_original_untouched()

    def _flight_query(self, fare_id: str) -> dict:
        row = self.conn.execute(
            """SELECT co.name AS origin, cd.name AS dest, substr(f.departs_at, 1, 10) AS day, ff.cabin_class
               FROM flight_fares ff JOIN flights f ON f.flight_id = ff.flight_id
               JOIN airports ao ON ao.airport_id = f.origin_airport_id JOIN cities co ON co.city_id = ao.city_id
               JOIN airports ad ON ad.airport_id = f.dest_airport_id JOIN cities cd ON cd.city_id = ad.city_id
               WHERE ff.fare_id = ?""", (fare_id,)).fetchone()
        return {"originCity": row["origin"], "destinationCity": row["dest"], "departureDate": row["day"],
                "passengers": 1, "cabinClass": row["cabin_class"], "currency": "INR"}

    def test_flight_search_returns_the_fare_priced_per_passenger(self):
        offer = support.find_flight_offer(self.conn)
        query = self._flight_query(offer["fare_id"])
        r = self.client.post("/api/v1/search/flights", json=query)
        self.assertEqual(r.status_code, 200, r.text)
        match = [f for f in r.json()["data"]["flights"] if f["fareId"] == offer["fare_id"]]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["inventoryId"], offer["inventory_id"])
        self.assertEqual(Decimal(match[0]["price"]), Decimal(offer["price"]))
        if match[0]["seatsAvailable"] >= 2:
            r2 = self.client.post("/api/v1/search/flights", json={**query, "passengers": 2})
            two = [f for f in r2.json()["data"]["flights"] if f["fareId"] == offer["fare_id"]][0]
            self.assertEqual(Decimal(two["price"]), Decimal(offer["price"]) * 2)

    def test_empty_flight_date_suggests_dates_that_have_flights(self):
        query = self._flight_query(support.find_flight_offer(self.conn)["fare_id"])
        r = self.client.post("/api/v1/search/flights", json={**query, "departureDate": "2030-01-01"})
        data = r.json()["data"]
        self.assertEqual(data["flights"], [])
        self.assertTrue(data["otherDates"])
        again = self.client.post("/api/v1/search/flights", json={**query, "departureDate": data["otherDates"][0]})
        self.assertTrue(again.json()["data"]["flights"])

    def test_early_morning_departure_is_found_on_its_local_date(self):
        row = self.conn.execute(
            "SELECT flight_id, origin_airport_id, substr(departs_at, 1, 10) AS day FROM flights "
            "WHERE status = 'active' AND date(departs_at) <> substr(departs_at, 1, 10) LIMIT 1").fetchone()
        if row is None:
            self.skipTest("no pre-05:30 departures in this dataset")
        found = catalog_repo.search_flights(self.conn, origin_airport_id=row["origin_airport_id"],
                                            depart_date=row["day"], limit=1000)
        self.assertIn(row["flight_id"], {f["flight_id"] for f in found})

    def test_hotel_search_returns_the_stay_with_summed_nightly_price(self):
        offer = support.find_hotel_offer(self.conn, nights=2)
        city = self.conn.execute(
            "SELECT c.name FROM hotels h JOIN cities c ON c.city_id = h.city_id WHERE h.hotel_id = ?",
            (offer["hotel_id"],)).fetchone()["name"]
        start = offer["nights"][0]["for_date"]
        end = (date.fromisoformat(offer["nights"][-1]["for_date"]) + timedelta(days=1)).isoformat()
        query = {"destination": city, "startDate": start, "endDate": end, "travellers": 1, "currency": "INR"}
        r = self.client.post("/api/v1/search/hotels", json=query)
        self.assertEqual(r.status_code, 200, r.text)
        match = [h for h in r.json()["data"]["hotels"] if h["roomTypeId"] == offer["room_type_id"]]
        expected = sum(Decimal(n["price"]) for n in offer["nights"])
        if match:  # may fall outside the top results in a busy city
            self.assertEqual(Decimal(match[0]["price"]), expected)
            self.assertEqual(match[0]["inventoryIds"], [n["inventory_id"] for n in offer["nights"]])
        cheapest = min(Decimal(h["price"]) for h in r.json()["data"]["hotels"])
        below = str((cheapest - Decimal("0.01")).quantize(Decimal("0.01")))
        r2 = self.client.post("/api/v1/search/hotels", json={**query, "budget": below})
        self.assertEqual(r2.json()["data"]["hotels"], [])

    def test_hotel_search_with_blank_dates_is_empty_not_an_error(self):
        r = self.client.post("/api/v1/search/hotels", json={
            "destination": "Lucknow", "startDate": "", "endDate": "", "travellers": 2, "budget": "", "currency": "INR"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["hotels"], [])

    def test_checkout_on_or_before_checkin_is_a_validation_error(self):
        for end in ("2026-11-15", "2026-11-16"):
            r = self.client.post("/api/v1/search/hotels", json={
                "destination": "Lucknow", "startDate": "2026-11-16", "endDate": end, "travellers": 2})
            self.assertEqual(r.status_code, 422, r.text)
            self.assertIn("must be after check-in date 2026-11-16", r.text)
        r = self.client.post("/api/v1/search/hotels/htl_nope/rooms",
                             json={"startDate": "2026-11-18", "endDate": "2026-11-16", "travellers": 2})
        self.assertEqual(r.status_code, 422, r.text)

    def test_past_dates_are_refused_but_today_is_allowed(self):
        # The fixed clock is 2026-01-01T00:00Z, i.e. 05:30 on 1 Jan in IST.
        r = self.client.post("/api/v1/search/hotels", json={
            "destination": "Lucknow", "startDate": "2025-12-31", "endDate": "2026-01-02", "travellers": 2})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["refusal"]["code"], "DATE_IN_PAST")
        r = self.client.post("/api/v1/search/flights", json={
            "originCity": "Mumbai", "destinationCity": "Lucknow", "departureDate": "2025-12-31", "passengers": 2})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["refusal"]["code"], "DATE_IN_PAST")
        r = self.client.post("/api/v1/search/hotels", json={
            "destination": "Lucknow", "startDate": "2026-01-01", "endDate": "2026-01-02", "travellers": 2})
        self.assertEqual(r.status_code, 200, r.text)

    def test_valid_multi_night_stay_is_accepted_without_shifting_dates(self):
        # 04/11/2026 -> 07/11/2026: three nights, and the same calendar days come back.
        r = self.client.post("/api/v1/search/hotels", json={
            "destination": "Lucknow", "startDate": "2026-11-04", "endDate": "2026-11-07", "travellers": 2})
        self.assertEqual(r.status_code, 200, r.text)
        hotel_id = self.conn.execute(
            "SELECT h.hotel_id FROM hotels h JOIN cities c ON c.city_id = h.city_id WHERE c.name = 'Lucknow' LIMIT 1"
        ).fetchone()[0]
        r = self.client.post(f"/api/v1/search/hotels/{hotel_id}/rooms",
                             json={"startDate": "2026-11-04", "endDate": "2026-11-07", "travellers": 2})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()["data"]
        self.assertEqual((data["startDate"], data["endDate"], data["nights"]), ("2026-11-04", "2026-11-07", 3))
        for room in data["rooms"]:
            self.assertTrue(all("2026-11-04" <= n["date"] <= "2026-11-06" for n in room["nightly"]))

    def test_dates_must_be_date_only(self):
        # A timestamp would be read in some timezone and could land on another calendar day.
        for bad in ("2026-11-04T00:00:00+05:30", "2026-11-04T20:00:00Z", "04/11/2026"):
            r = self.client.post("/api/v1/search/hotels", json={
                "destination": "Lucknow", "startDate": bad, "endDate": "2026-11-07", "travellers": 2})
            self.assertEqual(r.status_code, 422, bad)

    def _overnight_flight(self):
        return self.conn.execute(
            """SELECT f.flight_id, f.departs_at, f.arrives_at, co.name AS origin, cd.name AS dest,
                      ao.timezone AS origin_tz, ad.timezone AS dest_tz
               FROM flights f
               JOIN airports ao ON ao.airport_id = f.origin_airport_id JOIN cities co ON co.city_id = ao.city_id
               JOIN airports ad ON ad.airport_id = f.dest_airport_id JOIN cities cd ON cd.city_id = ad.city_id
               JOIN flight_fares ff ON ff.flight_id = f.flight_id AND ff.status = 'active' AND ff.cabin_class = 'economy'
               JOIN inventory_calendar ic ON ic.entity_type = 'flight_fare' AND ic.entity_id = ff.fare_id
                                          AND ic.for_date = substr(f.departs_at, 1, 10)
               WHERE f.status = 'active' AND ad.timezone = 'Asia/Kolkata' AND ao.timezone = 'Asia/Kolkata'
                 AND substr(f.arrives_at, 1, 10) > substr(f.departs_at, 1, 10)
                 AND (ic.total_units - ic.booked_units - ic.held_units) >= 1
               ORDER BY f.departs_at LIMIT 1""").fetchone()

    def test_flight_landing_after_local_midnight_is_listed(self):
        f = self._overnight_flight()
        r = self.client.post("/api/v1/search/flights", json={
            "originCity": f["origin"], "destinationCity": f["dest"],
            "departureDate": f["departs_at"][:10], "passengers": 1})
        self.assertEqual(r.status_code, 200, r.text)
        match = [x for x in r.json()["data"]["flights"] if x["flightId"] == f["flight_id"]]
        self.assertTrue(match, "an overnight flight must not be rejected for landing on the next day")
        self.assertEqual(match[0]["arrivalDayOffset"], 1)
        self.assertEqual(match[0]["arrivesAtLocal"][:16], f["arrives_at"][:16])

    def test_flight_that_already_left_today_is_hidden(self):
        f = self._overnight_flight()
        departs = datetime.fromisoformat(f["departs_at"])
        query = {"originCity": f["origin"], "destinationCity": f["dest"],
                 "departureDate": f["departs_at"][:10], "passengers": 1}
        for offset, listed in ((timedelta(minutes=-1), True), (timedelta(minutes=1), False)):
            client = TestClient(create_app(self.settings, clock=FixedClock(departs + offset)))
            ids = [x["flightId"] for x in client.post("/api/v1/search/flights", json=query).json()["data"]["flights"]]
            self.assertEqual(f["flight_id"] in ids, listed, offset)

    def test_departed_flight_offer_is_refused(self):
        from src.services import offer_service
        f = self._overnight_flight()
        fare = self.conn.execute(
            """SELECT ff.fare_id, ic.inventory_id FROM flight_fares ff
               JOIN inventory_calendar ic ON ic.entity_type = 'flight_fare' AND ic.entity_id = ff.fare_id
               WHERE ff.flight_id = ? LIMIT 1""", (f["flight_id"],)).fetchone()
        offer = {"kind": "flight", "entity_type": "flight_fare", "entity_id": fare["fare_id"],
                 "items": [{"inventory_id": fare["inventory_id"], "units": 1}]}
        departs = datetime.fromisoformat(f["departs_at"])
        day = departs.date()
        before = offer_service.validate_offer(self.conn, offer, trip=None, session_currency="INR",
                                              today=day, now=departs - timedelta(minutes=5))
        self.assertTrue(before.accepted, before.message)
        after = offer_service.validate_offer(self.conn, offer, trip=None, session_currency="INR",
                                             today=day, now=departs + timedelta(minutes=5))
        self.assertEqual(after.code, "DATE_IN_PAST")

    def test_malformed_input_is_a_validation_error(self):
        r = self.client.post("/api/v1/search/flights", json={
            "originCity": "Mumbai", "destinationCity": "Lucknow", "departureDate": "16/11/2026", "passengers": 2})
        self.assertEqual(r.status_code, 422)

    def test_hotel_rooms_lists_every_room_with_bookability(self):
        offer = support.find_hotel_offer(self.conn, nights=2)
        start = offer["nights"][0]["for_date"]
        end = (date.fromisoformat(offer["nights"][-1]["for_date"]) + timedelta(days=1)).isoformat()
        r = self.client.post(f"/api/v1/search/hotels/{offer['hotel_id']}/rooms",
                             json={"startDate": start, "endDate": end, "travellers": 1})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()["data"]
        total_rooms = self.conn.execute("SELECT COUNT(*) FROM hotel_room_types WHERE hotel_id = ? AND status = 'active'",
                                        (offer["hotel_id"],)).fetchone()[0]
        self.assertEqual(len(data["rooms"]), total_rooms)
        room = next(x for x in data["rooms"] if x["roomTypeId"] == offer["room_type_id"])
        self.assertTrue(room["bookable"])
        self.assertIsNone(room["unavailableReason"])
        self.assertEqual(Decimal(room["price"]), sum(Decimal(n["price"]) for n in offer["nights"]))
        self.assertEqual([n["date"] for n in room["nightly"]], [n["for_date"] for n in offer["nights"]])
        for other in data["rooms"]:
            self.assertEqual(other["bookable"], other["unavailableReason"] is None)

    def test_hotel_rooms_marks_rooms_too_small_for_the_party(self):
        offer = support.find_hotel_offer(self.conn, nights=2)
        start = offer["nights"][0]["for_date"]
        end = (date.fromisoformat(offer["nights"][-1]["for_date"]) + timedelta(days=1)).isoformat()
        rooms = self.client.post(f"/api/v1/search/hotels/{offer['hotel_id']}/rooms",
                                 json={"startDate": start, "endDate": end, "travellers": 20}).json()["data"]["rooms"]
        self.assertTrue(all(not r["fitsParty"] for r in rooms))

    def test_hotel_rooms_unknown_hotel_is_404(self):
        r = self.client.post("/api/v1/search/hotels/htl_nope/rooms",
                             json={"startDate": "2026-11-16", "endDate": "2026-11-18", "travellers": 2})
        self.assertEqual(r.status_code, 404)

    def test_search_prices_convert_into_the_requested_currency(self):
        offer = support.find_hotel_offer(self.conn, currency="AED", nights=2)
        city = self.conn.execute(
            "SELECT c.name FROM hotels h JOIN cities c ON c.city_id = h.city_id WHERE h.hotel_id = ?",
            (offer["hotel_id"],)).fetchone()["name"]
        start = offer["nights"][0]["for_date"]
        end = (date.fromisoformat(offer["nights"][-1]["for_date"]) + timedelta(days=1)).isoformat()
        hotels = self.client.post("/api/v1/search/hotels", json={
            "destination": city, "startDate": start, "endDate": end, "travellers": 1, "currency": "INR"}).json()["data"]["hotels"]
        match = [h for h in hotels if h["roomTypeId"] == offer["room_type_id"]]
        self.assertTrue(hotels)
        self.assertTrue(all(h["currency"] == "INR" for h in hotels))
        if match:
            from src.core import fx
            self.assertEqual(match[0]["localCurrency"], "AED")
            self.assertEqual(Decimal(match[0]["price"]),
                             sum(Decimal(fx.convert(n["price"], "AED", "INR")) for n in offer["nights"]))

    def test_currency_list_has_rates(self):
        data = self.client.get("/api/v1/currencies").json()["data"]
        codes = {c["code"] for c in data["currencies"]}
        self.assertTrue({"INR", "USD", "EUR", "AED", "THB"} <= codes)

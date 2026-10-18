"""Background loop (every minute) for things that happen with nobody on the page:

  * releasing expired approvals -- otherwise their held rooms/seats stay off the market until
    someone happens to open that session;
  * "your flight departs in 3 hours" and "you've landed" notifications for booked flights.

Each notification is sent once (dedupe key per cart item). Started from the app lifespan only
when NOTIFY_SCHEDULER is on, so tests and embedded apps never run it.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from src.core.clock import Clock, SystemClock
from src.core.config import Settings
from src.db.repositories import confirmations as confirmations_repo
from src.services import confirmation_service, notify_service

logger = logging.getLogger("tech4ce.scheduler")
INTERVAL_SECONDS = 60
DEPARTURE_REMINDER = timedelta(hours=3)
LANDED_WINDOW = timedelta(hours=12)  # don't announce landings from long ago


def run_once(conn, clock: Clock, settings: Settings) -> dict:
    expired = 0
    for (confirmation_id,) in conn.execute(
            "SELECT confirmation_id FROM agent_confirmations WHERE status = 'pending' AND expires_at <= ?",
            (clock.utc(),)).fetchall():
        confirmation = confirmations_repo.get(conn, confirmation_id)
        if confirmation and confirmation_service.expire_if_due(conn, clock, confirmation).status == "expired":
            expired += 1

    now = clock.now()
    sent = 0
    flights = conn.execute(
        """SELECT ci.cart_item_id, ci.cart_id, s.session_id, s.user_id, f.departs_at, f.arrives_at,
                  a.name AS airline, f.flight_number, co.name AS origin, cd.name AS destination
           FROM agent_carts c JOIN agent_sessions s ON s.session_id = c.session_id
           JOIN agent_cart_items ci ON ci.cart_id = c.cart_id AND ci.kind = 'flight' AND ci.status = 'active'
           JOIN flight_fares ff ON ff.fare_id = ci.entity_id JOIN flights f ON f.flight_id = ff.flight_id
           JOIN airlines a ON a.airline_id = f.airline_id
           JOIN airports ao ON ao.airport_id = f.origin_airport_id JOIN cities co ON co.city_id = ao.city_id
           JOIN airports ad ON ad.airport_id = f.dest_airport_id JOIN cities cd ON cd.city_id = ad.city_id
           WHERE c.status = 'booked'""").fetchall()
    for fl in flights:
        departs, arrives = datetime.fromisoformat(fl["departs_at"]), datetime.fromisoformat(fl["arrives_at"])
        if departs - DEPARTURE_REMINDER <= now < departs:
            sent += notify_service.notify(
                conn, clock, settings, user_id=fl["user_id"], kind="flight_departing", session_id=fl["session_id"],
                dedupe_key=f"departing:{fl['cart_item_id']}", url="/#my-trips",
                title=f"{fl['airline']} {fl['flight_number']} departs at {fl['departs_at'][11:16]}",
                body=f"{fl['origin']} → {fl['destination']}. Time to head to the airport — have a good trip!")
        if arrives <= now < arrives + LANDED_WINDOW:
            title, body = notify_service.landing_message(conn, fl["cart_id"], fl["cart_item_id"])
            sent += notify_service.notify(conn, clock, settings, user_id=fl["user_id"], kind="flight_landed",
                                          session_id=fl["session_id"], dedupe_key=f"landed:{fl['cart_item_id']}",
                                          title=title, body=body, url="/#my-trips")
    return {"expired_approvals": expired, "notifications": sent}


def start(settings: Settings) -> threading.Event:
    """Run `run_once` every minute on a daemon thread; set the returned event to stop."""
    from src.db.connection import connect

    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                conn = connect(settings, check_same_thread=False)
                try:
                    result = run_once(conn, SystemClock(), settings)
                    if any(result.values()):
                        logger.info("scheduler: %s", result)
                finally:
                    conn.close()
            except Exception:
                logger.exception("scheduler run failed")
            stop.wait(INTERVAL_SECONDS)

    threading.Thread(target=loop, name="notify-scheduler", daemon=True).start()
    return stop

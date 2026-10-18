-- Migration 0003: allow a cart to hold inventory priced in another currency (working copy only).
-- Checksum is enforced by src/db/migrations/runner.py; do not edit once approved.
--
-- Trips are priced, capped and booked in the session currency; local AED/THB/JPY... prices are
-- converted per unit at the demo rates in src/core/fx.py, and each cart item stores its
-- converted unit price. trg_items_currency_match required every item's *inventory* currency to
-- equal the cart currency, which rules conversion out. The guard moves to the application:
-- offer_service refuses any currency without a rate, and pricing_service reprices with the
-- same conversion. trg_carts_currency_session (cart currency == session currency) stays.

DROP TRIGGER IF EXISTS trg_items_currency_match;

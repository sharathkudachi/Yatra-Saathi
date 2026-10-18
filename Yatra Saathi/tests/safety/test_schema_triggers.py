"""Database-level enforcement of the approved invariants (constraints + 32 triggers).

Every test runs inside a transaction on a temporary migrated working copy and is rolled
back afterwards. These tests prove the database itself refuses unsafe states even if a
service-layer bug tried to write them.
"""
import sqlite3
import unittest

from src.core.hashing import sha256_hex
from src.core.ids import new_id
from tests.support import WorkingCopy, assert_original_untouched

TS = "2026-09-24T10:00:00.000Z"
TS_LATER = "2026-09-24T10:05:00.000Z"
TS_EXPIRES = "2026-09-24T10:15:00.000Z"
EXISTING_TS = "2026-09-24T15:30:00+05:30"


def setUpModule():
    assert_original_untouched()
    global WC
    WC = WorkingCopy(migrate=True)


def tearDownModule():
    WC.cleanup()
    assert_original_untouched()


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = WC.raw()
        self.conn.execute("BEGIN")
        users = [r[0] for r in self.conn.execute(
            "SELECT user_id FROM users WHERE status='active' ORDER BY user_id LIMIT 2")]
        self.owner, self.other_user = users
        self.sid = self.new_session(self.owner)
        self.other_sid = self.new_session(self.other_user)
        rows = self.conn.execute(
            "SELECT inventory_id, entity_type, entity_id, for_date FROM inventory_calendar "
            "WHERE currency='INR' AND entity_type='room_type' ORDER BY inventory_id LIMIT 2").fetchall()
        self.inv, self.inv2 = rows
        self.inv_foreign = self.conn.execute(
            "SELECT inventory_id, entity_type, entity_id, for_date FROM inventory_calendar "
            "WHERE currency<>'INR' AND entity_type='room_type' ORDER BY inventory_id LIMIT 1").fetchone()

    def tearDown(self):
        if self.conn.in_transaction:
            self.conn.execute("ROLLBACK")
        self.conn.close()

    # ---- helpers -------------------------------------------------------------
    def insert(self, table, **cols):
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        self.conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(cols.values()))

    def blocked(self, pattern):
        return self.assertRaisesRegex(sqlite3.IntegrityError, pattern)

    def new_session(self, user_id, currency="INR"):
        sid = new_id("agt")
        self.conn.execute(
            "INSERT INTO agent_sessions VALUES (?,?,NULL,'test goal','en-IN','{}','[]',1,'20000.00','0.00',"
            "?,1,NULL,0,NULL,'planning',?,?)", (sid, user_id, currency, EXISTING_TS, EXISTING_TS))
        return sid

    def last_event(self, sid):
        return self.conn.execute("SELECT seq, hash FROM agent_audit_events WHERE session_id=? "
                                 "ORDER BY seq DESC LIMIT 1", (sid,)).fetchone()

    def add_event(self, sid, event_type="SESSION_CREATED", **overrides):
        last = self.last_event(sid)
        eid = new_id("aud")
        cols = dict(event_id=eid, session_id=sid, seq=1 if last is None else last[0] + 1,
                    event_type=event_type, occurred_at=TS, actor="system", outcome="info",
                    prev_hash=None if last is None else last[1], hash=sha256_hex(eid))
        cols.update(overrides)
        self.insert("agent_audit_events", **cols)
        return cols["event_id"]

    def new_cart(self, sid, currency="INR"):
        cid = new_id("crt")
        self.insert("agent_carts", cart_id=cid, session_id=sid, currency=currency, created_at=TS, updated_at=TS)
        return cid

    def add_item(self, cart_id, sid, inv, source, **overrides):
        inventory_id, entity_type, entity_id, for_date = inv
        cols = dict(cart_item_id=new_id("cit"), cart_id=cart_id, session_id=sid, item_group_id=new_id("grp"),
                    kind="hotel_stay", entity_type=entity_type, entity_id=entity_id, inventory_id=inventory_id,
                    for_date=for_date, units=1, unit_price_minor=186192, line_total_minor=186192,
                    source_event_id=source, source_offer_index=0, added_in_version=1, added_at=TS)
        cols.update(overrides)
        self.insert("agent_cart_items", **cols)
        return cols["cart_item_id"]

    def lock(self, cart_id, h, version=2, subtotal=186192, tax=22343):
        self.conn.execute("UPDATE agent_carts SET status='locked', snapshot_hash=?, version=?, subtotal_minor=?, "
                          "tax_minor=?, total_minor=?, updated_at=? WHERE cart_id=?",
                          (h, version, subtotal, tax, subtotal + tax, TS_LATER, cart_id))

    def new_confirmation(self, sid, cart_id, h, version=2, subtotal=186192, tax=22343, cap=2000000, **overrides):
        cols = dict(confirmation_id=new_id("cnf"), session_id=sid, cart_id=cart_id, cart_version=version,
                    snapshot_hash=h, snapshot_json="{}", currency="INR", subtotal_minor=subtotal, tax_minor=tax,
                    total_minor=subtotal + tax, effective_cap_minor=cap, requested_at=TS, expires_at=TS_EXPIRES)
        cols.update(overrides)
        self.insert("agent_confirmations", **cols)
        return cols["confirmation_id"]

    def new_booking(self, user_id):
        bid = new_id("bkg")
        self.conn.execute(
            "INSERT INTO bookings (booking_id, user_id, booking_reference, channel, total_amount, currency, "
            "tax_amount, idempotency_key, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (bid, user_id, bid[-6:].upper(), "agent", "2085.35", "INR", "223.43", "idem_" + bid[-8:] * 2,
             "confirmed", EXISTING_TS, EXISTING_TS))
        return bid

    def ready_confirmation(self):
        """Session with a TOOL_RESULT, a locked cart with one item, and a pending confirmation."""
        self.add_event(self.sid)
        src = self.add_event(self.sid, "TOOL_RESULT", actor="agent", agent_run_id=new_id("run"))
        cart = self.new_cart(self.sid)
        self.add_item(cart, self.sid, self.inv, src)
        h = sha256_hex("cart-snapshot")
        self.lock(cart, h)
        return src, cart, h, self.new_confirmation(self.sid, cart, h)


class AuditTrailTests(Base):
    def test_valid_chain_is_accepted(self):
        for _ in range(3):
            self.add_event(self.sid)
        self.assertEqual(self.last_event(self.sid)[0], 3)

    def test_update_and_delete_are_blocked(self):
        self.add_event(self.sid)
        with self.blocked("append-only"):
            self.conn.execute("UPDATE agent_audit_events SET request_id='x'")
        with self.blocked("cannot be deleted"):
            self.conn.execute("DELETE FROM agent_audit_events")

    def test_seq_gap_and_duplicate_are_blocked(self):
        self.add_event(self.sid)
        seq, h = self.last_event(self.sid)
        with self.blocked("gapless|chain broken"):
            self.add_event(self.sid, seq=seq + 2, prev_hash=h)
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_event(self.sid, seq=seq, prev_hash=None)
        with self.blocked("gapless|chain broken"):
            self.add_event(self.other_sid, seq=2, prev_hash="a" * 64)

    def test_broken_hash_chain_is_blocked(self):
        self.add_event(self.sid)
        with self.blocked("audit hash chain broken"):
            self.add_event(self.sid, prev_hash="b" * 64)

    def test_envelope_checks(self):
        cases = {
            "ck_audit_time": dict(occurred_at="2026-09-24T15:30:00+05:30"),
            "ck_audit_type": dict(event_type="SPEND_APPROVED"),
            "ck_audit_actor_user": dict(actor="user"),
            "ck_audit_run": dict(actor="agent"),
            "ck_audit_reason": dict(outcome="refused"),
            "ck_audit_reason_text": dict(outcome="refused", reason_code="SPEND_CAP_EXCEEDED"),
            "ck_audit_input": dict(input_json="[1]"),
            "ck_audit_prev": dict(prev_hash="c" * 64),
            "ck_audit_id": dict(event_id="aud_XYZ"),
        }
        for constraint, overrides in cases.items():
            with self.subTest(constraint=constraint), self.blocked(constraint):
                self.add_event(self.sid, **overrides)

    def test_refusal_event_with_reason_is_accepted(self):
        self.add_event(self.sid, event_type="ACTION_REFUSED", outcome="refused",
                       reason_code="SPEND_CAP_EXCEEDED", reason="over cap")

    def test_duplicate_hash_is_blocked(self):
        first = self.add_event(self.sid)
        with self.blocked("UNIQUE"):
            self.add_event(self.sid, hash=sha256_hex(first))

    def test_cross_session_cause_is_blocked(self):
        cause = self.add_event(self.sid)
        with self.blocked("cause must be in same session"):
            self.add_event(self.other_sid, caused_by_event_id=cause)

    def test_unknown_session_is_blocked(self):
        with self.blocked("FOREIGN KEY"):
            self.add_event("agt_nosuch01")


class CartTests(Base):
    def test_cart_currency_must_equal_session_currency(self):
        with self.blocked("cart currency must equal session currency"):
            self.new_cart(self.sid, currency="THB")

    def test_only_one_active_cart_per_session(self):
        self.new_cart(self.sid)
        with self.blocked("UNIQUE"):
            self.new_cart(self.sid)

    def test_status_rules(self):
        cart = self.new_cart(self.sid)
        with self.blocked("illegal cart status change"):
            self.conn.execute("UPDATE agent_carts SET status='booked', snapshot_hash=? WHERE cart_id=?",
                              ("a" * 64, cart))
        with self.blocked("ck_carts_hash_required"):
            self.conn.execute("UPDATE agent_carts SET status='locked' WHERE cart_id=?", (cart,))
        self.lock(cart, "a" * 64)
        self.conn.execute("UPDATE agent_carts SET status='open' WHERE cart_id=?", (cart,))  # unlock allowed
        self.conn.execute("UPDATE agent_carts SET status='locked' WHERE cart_id=?", (cart,))
        self.conn.execute("UPDATE agent_carts SET status='booked' WHERE cart_id=?", (cart,))
        with self.blocked("cart is final"):
            self.conn.execute("UPDATE agent_carts SET updated_at=? WHERE cart_id=?", (TS_EXPIRES, cart))
        self.new_cart(self.sid)  # a booked cart no longer counts as active

    def test_version_cannot_decrease_and_keys_are_immutable(self):
        cart = self.new_cart(self.sid)
        self.conn.execute("UPDATE agent_carts SET version=3 WHERE cart_id=?", (cart,))
        with self.blocked("cart version cannot decrease"):
            self.conn.execute("UPDATE agent_carts SET version=2 WHERE cart_id=?", (cart,))
        with self.blocked("cart keys are immutable"):
            self.conn.execute("UPDATE agent_carts SET session_id=? WHERE cart_id=?", (self.other_sid, cart))

    def test_totals_must_add_up_and_carts_cannot_be_deleted(self):
        cart = self.new_cart(self.sid)
        with self.blocked("ck_carts_total"):
            self.conn.execute("UPDATE agent_carts SET subtotal_minor=100, tax_minor=12, total_minor=100 "
                              "WHERE cart_id=?", (cart,))
        with self.blocked("carts cannot be deleted"):
            self.conn.execute("DELETE FROM agent_carts WHERE cart_id=?", (cart,))


class CartItemTests(Base):
    def setUp(self):
        super().setUp()
        self.add_event(self.sid)
        self.src = self.add_event(self.sid, "TOOL_RESULT", actor="agent", agent_run_id=new_id("run"))
        self.cart = self.new_cart(self.sid)

    def test_valid_item_is_accepted(self):
        self.add_item(self.cart, self.sid, self.inv, self.src)

    def test_duplicate_inventory_row_is_blocked_but_readd_after_removal_allowed(self):
        item = self.add_item(self.cart, self.sid, self.inv, self.src)
        with self.blocked("UNIQUE"):
            self.add_item(self.cart, self.sid, self.inv, self.src)
        self.conn.execute("UPDATE agent_cart_items SET status='removed', removed_in_version=2, removed_at=? "
                          "WHERE cart_item_id=?", (TS_LATER, item))
        self.add_item(self.cart, self.sid, self.inv, self.src, added_in_version=3)

    def test_foreign_currency_item_is_allowed(self):
        # Migration 0003 dropped trg_items_currency_match: the item's unit price is stored already
        # converted into the cart currency (src/core/fx.py), and offer_service refuses any currency
        # without a rate. Cart currency == session currency is still enforced (test above).
        self.add_item(self.cart, self.sid, self.inv_foreign, self.src)

    def test_item_must_match_inventory_row(self):
        with self.blocked("item does not match inventory row"):
            self.add_item(self.cart, self.sid, self.inv, self.src, for_date="2030-01-01")

    def test_item_must_come_from_this_sessions_search_result(self):
        not_a_result = self.add_event(self.sid)
        with self.blocked("search result"):
            self.add_item(self.cart, self.sid, self.inv, not_a_result)
        self.add_event(self.other_sid)
        foreign = self.add_event(self.other_sid, "TOOL_RESULT", actor="agent", agent_run_id=new_id("run"))
        with self.blocked("search result"):
            self.add_item(self.cart, self.sid, self.inv, foreign)

    def test_item_session_must_match_cart(self):
        with self.blocked("item session must match cart|search result"):
            self.add_item(self.cart, self.other_sid, self.inv, self.src)

    def test_activities_and_bad_pairs_are_blocked(self):
        with self.blocked("ck_items_kind"):
            self.add_item(self.cart, self.sid, self.inv, self.src, kind="activity")
        with self.blocked("ck_items_pair"):
            self.add_item(self.cart, self.sid, self.inv, self.src, kind="flight")

    def test_invalid_quantities_and_totals_are_blocked(self):
        for units in (0, -1):
            with self.subTest(units=units), self.blocked("ck_items_units"):
                self.add_item(self.cart, self.sid, self.inv, self.src, units=units, line_total_minor=0)
        with self.blocked("ck_items_line"):
            self.add_item(self.cart, self.sid, self.inv, self.src, units=2, line_total_minor=186192)

    def test_locked_cart_is_frozen(self):
        item = self.add_item(self.cart, self.sid, self.inv, self.src)
        self.lock(self.cart, "d" * 64)
        with self.blocked("cart is not open"):
            self.add_item(self.cart, self.sid, self.inv2, self.src)
        with self.blocked("cart is not open"):
            self.conn.execute("UPDATE agent_cart_items SET hold_id=NULL WHERE cart_item_id=?", (item,))

    def test_item_fields_are_immutable_and_removed_items_final(self):
        item = self.add_item(self.cart, self.sid, self.inv, self.src)
        with self.blocked("cart item fields are immutable"):
            self.conn.execute("UPDATE agent_cart_items SET unit_price_minor=1, line_total_minor=1 "
                              "WHERE cart_item_id=?", (item,))
        self.conn.execute("UPDATE agent_cart_items SET status='removed', removed_in_version=2, removed_at=? "
                          "WHERE cart_item_id=?", (TS_LATER, item))
        with self.blocked("removed items are final"):
            self.conn.execute("UPDATE agent_cart_items SET status='active', removed_in_version=NULL, "
                              "removed_at=NULL WHERE cart_item_id=?", (item,))
        with self.blocked("cart items cannot be deleted"):
            self.conn.execute("DELETE FROM agent_cart_items WHERE cart_item_id=?", (item,))


class ConfirmationTests(Base):
    def approve(self, cnf, user):
        self.conn.execute("UPDATE agent_confirmations SET status='approved', decided_at=?, decided_by_user_id=? "
                          "WHERE confirmation_id=?", (TS_LATER, user, cnf))

    def consume(self, cnf, booking):
        self.conn.execute("UPDATE agent_confirmations SET status='consumed', consumed_at=?, "
                          "consumed_by_booking_id=? WHERE confirmation_id=?", (TS_EXPIRES, booking, cnf))

    def test_cannot_be_created_already_approved(self):
        self.add_event(self.sid)
        src = self.add_event(self.sid, "TOOL_RESULT", actor="agent", agent_run_id=new_id("run"))
        cart = self.new_cart(self.sid)
        self.add_item(cart, self.sid, self.inv, src)
        self.lock(cart, "e" * 64)
        with self.blocked("confirmation must be created pending"):
            self.new_confirmation(self.sid, cart, "e" * 64, status="approved", decided_at=TS_LATER,
                                  decided_by_user_id=self.owner)

    def test_must_match_the_locked_cart(self):
        self.add_event(self.sid)
        src = self.add_event(self.sid, "TOOL_RESULT", actor="agent", agent_run_id=new_id("run"))
        cart = self.new_cart(self.sid)
        self.add_item(cart, self.sid, self.inv, src)
        with self.blocked("must match locked cart"):  # cart still open
            self.new_confirmation(self.sid, cart, "e" * 64)
        self.lock(cart, "e" * 64)
        for overrides in (dict(h="f" * 64), dict(version=3), dict(tax=1)):
            with self.subTest(**overrides), self.blocked("must match locked cart"):
                h = overrides.pop("h", "e" * 64)
                self.new_confirmation(self.sid, cart, h, **overrides)
        with self.blocked("must match locked cart"):  # another session's cart
            self.new_confirmation(self.other_sid, cart, "e" * 64)

    def test_total_cannot_exceed_cap(self):
        self.add_event(self.sid)
        src = self.add_event(self.sid, "TOOL_RESULT", actor="agent", agent_run_id=new_id("run"))
        cart = self.new_cart(self.sid)
        self.add_item(cart, self.sid, self.inv, src)
        self.lock(cart, "e" * 64)
        with self.blocked("ck_cnf_cap"):
            self.new_confirmation(self.sid, cart, "e" * 64, cap=100)

    def test_only_one_pending_per_session(self):
        _src, cart, h, _cnf = self.ready_confirmation()
        with self.blocked("UNIQUE"):
            self.new_confirmation(self.sid, cart, h)

    def test_only_the_session_owner_can_decide(self):
        _src, _cart, _h, cnf = self.ready_confirmation()
        with self.blocked("only the session owner can decide"):
            self.approve(cnf, self.other_user)
        with self.blocked("only the session owner can decide"):
            self.conn.execute("UPDATE agent_confirmations SET status='declined', decided_at=?, "
                              "decided_by_user_id=? WHERE confirmation_id=?", (TS_LATER, self.other_user, cnf))
        self.approve(cnf, self.owner)

    def test_status_cannot_go_backwards_and_snapshot_is_immutable(self):
        _src, _cart, _h, cnf = self.ready_confirmation()
        self.approve(cnf, self.owner)
        with self.blocked("illegal confirmation status change"):
            self.conn.execute("UPDATE agent_confirmations SET status='pending', decided_at=NULL, "
                              "decided_by_user_id=NULL WHERE confirmation_id=?", (cnf,))
        with self.blocked("confirmation snapshot is immutable"):
            self.conn.execute("UPDATE agent_confirmations SET total_minor=1, subtotal_minor=1, tax_minor=0 "
                              "WHERE confirmation_id=?", (cnf,))
        with self.blocked("confirmation snapshot is immutable"):
            self.conn.execute("UPDATE agent_confirmations SET snapshot_hash=? WHERE confirmation_id=?",
                              ("0" * 64, cnf))

    def test_closed_states_need_a_reason_and_are_final(self):
        _src, _cart, _h, cnf = self.ready_confirmation()
        with self.blocked("ck_cnf_closed"):
            self.conn.execute("UPDATE agent_confirmations SET status='expired' WHERE confirmation_id=?", (cnf,))
        self.conn.execute("UPDATE agent_confirmations SET status='expired', closed_reason='timeout' "
                          "WHERE confirmation_id=?", (cnf,))
        with self.blocked("confirmation is final"):
            self.approve(cnf, self.owner)

    def test_consume_requires_owner_booking_and_is_final(self):
        _src, _cart, _h, cnf = self.ready_confirmation()
        with self.blocked("illegal confirmation status change"):  # pending cannot be consumed
            self.consume(cnf, self.new_booking(self.owner))
        self.approve(cnf, self.owner)
        with self.blocked("booking owner must match session owner"):
            self.consume(cnf, self.new_booking(self.other_user))
        self.consume(cnf, self.new_booking(self.owner))
        with self.blocked("confirmation is final"):
            self.conn.execute("UPDATE agent_confirmations SET decision_note='x' WHERE confirmation_id=?", (cnf,))
        with self.blocked("confirmations cannot be deleted"):
            self.conn.execute("DELETE FROM agent_confirmations WHERE confirmation_id=?", (cnf,))

    def test_one_booking_per_session(self):
        src, cart, _h, cnf = self.ready_confirmation()
        self.approve(cnf, self.owner)
        self.consume(cnf, self.new_booking(self.owner))
        self.conn.execute("UPDATE agent_carts SET status='booked' WHERE cart_id=?", (cart,))
        cart2 = self.new_cart(self.sid)
        self.add_item(cart2, self.sid, self.inv2, src)
        h2 = sha256_hex("second-cart")
        self.lock(cart2, h2)
        cnf2 = self.new_confirmation(self.sid, cart2, h2)
        self.approve(cnf2, self.owner)
        with self.blocked("UNIQUE"):
            self.consume(cnf2, self.new_booking(self.owner))

    def test_one_booking_cannot_consume_two_confirmations(self):
        _src, _cart, _h, cnf = self.ready_confirmation()
        self.approve(cnf, self.owner)
        booking = self.new_booking(self.owner)
        self.consume(cnf, booking)
        # a confirmation in another session trying to reuse the same booking
        self.add_event(self.other_sid)
        src2 = self.add_event(self.other_sid, "TOOL_RESULT", actor="agent", agent_run_id=new_id("run"))
        cart2 = self.new_cart(self.other_sid)
        self.add_item(cart2, self.other_sid, self.inv, src2)
        self.lock(cart2, "9" * 64)
        cnf2 = self.new_confirmation(self.other_sid, cart2, "9" * 64)
        self.approve(cnf2, self.other_user)
        with self.assertRaises(sqlite3.IntegrityError):
            self.consume(cnf2, booking)


class AgentStateTests(Base):
    def put(self, sid, version, body="{}", sha="a" * 64):
        self.insert("agent_session_state", session_id=sid, state_version=version, state_json=body,
                    state_sha256=sha, updated_at=TS)

    def test_versioning(self):
        with self.blocked("first state version must be 1"):
            self.put(self.sid, 2)
        self.put(self.sid, 1)
        with self.blocked("state version must increase by 1"):
            self.conn.execute("UPDATE agent_session_state SET state_version=3 WHERE session_id=?", (self.sid,))
        self.conn.execute("UPDATE agent_session_state SET state_version=2 WHERE session_id=?", (self.sid,))
        with self.blocked("state session is immutable"):
            self.conn.execute("UPDATE agent_session_state SET session_id=?, state_version=3 WHERE session_id=?",
                              (self.other_sid, self.sid))
        with self.blocked("state cannot be deleted"):
            self.conn.execute("DELETE FROM agent_session_state")

    def test_json_object_only(self):
        for body in ("[1,2]", "not json", '"text"', "42"):
            with self.subTest(body=body), self.blocked("ck_state_json"):
                self.put(self.sid, 1, body)

    def test_size_limit_is_measured_in_bytes(self):
        self.put(self.sid, 1, '{"a":"' + "x" * 1000000 + '"}')  # ~1.0 MB ASCII: allowed
        # 600,000 two-byte characters = 1.2 MB of bytes but only 600,000 characters: refused
        with self.blocked("ck_state_size"):
            self.put(self.other_sid, 1, '{"a":"' + "é" * 600000 + '"}')

    def test_checksum_format(self):
        with self.blocked("ck_state_hash"):
            self.put(self.sid, 1, sha="XYZ")


if __name__ == "__main__":
    unittest.main()

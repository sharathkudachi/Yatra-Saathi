-- Tech4ce schema additions on top of the canonical APS-01 data model (22 tables, used unmodified).
-- 7 new tables, 2 indexes on existing tables, and 1 trigger removed by a later migration.
-- This file is the concatenation, in order, of the four approved, checksum-locked migrations in
-- backend/src/db/migrations/ (runner.py refuses any file whose SHA-256 differs). Do not edit here;
-- edit there. Why each change exists: data-model/DATA_MODEL.md.
--
-- Source of truth:
--   0001_agent_tables.sql        5 agent tables + their triggers
--   0002_existing_indexes.sql    2 indexes on existing tables (flights, flight_fares)
--   0003_multi_currency_cart.sql drops trg_items_currency_match (foreign-currency stays)
--   0004_notifications.sql       push_subscriptions, notifications_sent


-- ======================== 0001_agent_tables.sql ========================
-- Migration 0001: the five approved agent tables (working copy only).
-- Approved schema; do not edit. Checksum is enforced by app/db/migrations/runner.py.

CREATE TABLE agent_audit_events (
  event_id            TEXT    NOT NULL,
  session_id          TEXT    NOT NULL,
  seq                 INTEGER NOT NULL,
  event_type          TEXT    NOT NULL,
  occurred_at         TEXT    NOT NULL,
  actor               TEXT    NOT NULL,
  actor_user_id       TEXT,
  agent_run_id        TEXT,
  outcome             TEXT    NOT NULL,
  reason_code         TEXT,
  reason              TEXT,
  input_json          TEXT    NOT NULL DEFAULT '{}',
  result_json         TEXT    NOT NULL DEFAULT '{}',
  request_id          TEXT,
  caused_by_event_id  TEXT,
  plan_version        INTEGER,
  step_id             TEXT,
  cart_id             TEXT,     -- no FK on purpose: refused actions may reference things never created
  cart_version        INTEGER,
  confirmation_id     TEXT,     -- no FK on purpose (same reason)
  booking_id          TEXT,     -- no FK on purpose (same reason)
  prev_hash           TEXT,
  hash                TEXT    NOT NULL,
  schema_version      INTEGER NOT NULL DEFAULT 1,
  CONSTRAINT pk_audit PRIMARY KEY (event_id),
  CONSTRAINT fk_audit_session FOREIGN KEY (session_id) REFERENCES agent_sessions (session_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_audit_user FOREIGN KEY (actor_user_id) REFERENCES users (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_audit_cause FOREIGN KEY (caused_by_event_id) REFERENCES agent_audit_events (event_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT uq_audit_session_seq UNIQUE (session_id, seq),
  CONSTRAINT uq_audit_hash UNIQUE (hash),
  CONSTRAINT ck_audit_id CHECK (event_id GLOB 'aud_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  CONSTRAINT ck_audit_seq CHECK (seq >= 1),
  CONSTRAINT ck_audit_type CHECK (event_type IN ('SESSION_CREATED','SESSION_RESUMED','CLARIFICATION_REQUESTED','PLAN_CREATED','PLAN_STEP_STARTED','PLAN_STEP_COMPLETED','TOOL_CALL','TOOL_RESULT','BUDGET_CHECK','ACTION_REFUSED','REPLAN','CART_CREATED','CART_UPDATED','CONFIRMATION_REQUIRED','CONFIRMATION_RECEIVED','CONFIRMATION_DECLINED','CONFIRMATION_EXPIRED','CONFIRMATION_INVALIDATED','BOOKING_ATTEMPT','BOOKING_SUCCESS','BOOKING_REFUSED','BOOKING_FAILED','ERROR')),
  CONSTRAINT ck_audit_time CHECK (strftime('%Y-%m-%dT%H:%M:%fZ', occurred_at) = occurred_at),
  CONSTRAINT ck_audit_actor CHECK (actor IN ('user','agent','system')),
  CONSTRAINT ck_audit_actor_user CHECK ((actor = 'user') = (actor_user_id IS NOT NULL)),
  CONSTRAINT ck_audit_run CHECK ((actor = 'agent') = (agent_run_id IS NOT NULL)),
  CONSTRAINT ck_audit_run_fmt CHECK (agent_run_id IS NULL OR agent_run_id GLOB 'run_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  CONSTRAINT ck_audit_outcome CHECK (outcome IN ('success','refused','failed','info')),
  CONSTRAINT ck_audit_reason CHECK ((outcome IN ('refused','failed')) = (reason_code IS NOT NULL)),
  CONSTRAINT ck_audit_reason_text CHECK ((reason_code IS NULL) = (reason IS NULL)),
  CONSTRAINT ck_audit_input CHECK (json_valid(input_json) AND json_type(input_json) = 'object'),
  CONSTRAINT ck_audit_result CHECK (json_valid(result_json) AND json_type(result_json) = 'object'),
  CONSTRAINT ck_audit_plan_version CHECK (plan_version IS NULL OR plan_version >= 1),
  CONSTRAINT ck_audit_cart_version CHECK (cart_version IS NULL OR cart_version >= 1),
  CONSTRAINT ck_audit_prev CHECK ((seq = 1 AND prev_hash IS NULL) OR (seq > 1 AND prev_hash IS NOT NULL AND (length(prev_hash) = 64 AND prev_hash NOT GLOB '*[^0-9a-f]*'))),
  CONSTRAINT ck_audit_hash CHECK ((length(hash) = 64 AND hash NOT GLOB '*[^0-9a-f]*')),
  CONSTRAINT ck_audit_schema CHECK (schema_version = 1)
);
CREATE INDEX ix_audit_session_type ON agent_audit_events (session_id, event_type, seq);
CREATE INDEX ix_audit_type_time    ON agent_audit_events (event_type, occurred_at);
CREATE INDEX ix_audit_caused_by    ON agent_audit_events (caused_by_event_id);

CREATE TRIGGER trg_audit_no_update
BEFORE UPDATE ON agent_audit_events FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;

CREATE TRIGGER trg_audit_no_delete
BEFORE DELETE ON agent_audit_events FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'audit events cannot be deleted'); END;

CREATE TRIGGER trg_audit_seq_gapless
BEFORE INSERT ON agent_audit_events FOR EACH ROW
WHEN NEW.seq <> COALESCE((SELECT MAX(seq) FROM agent_audit_events WHERE session_id = NEW.session_id), 0) + 1
BEGIN SELECT RAISE(ABORT, 'audit seq must be gapless'); END;

CREATE TRIGGER trg_audit_chain_link
BEFORE INSERT ON agent_audit_events FOR EACH ROW
WHEN NEW.seq > 1 AND NEW.prev_hash IS NOT (SELECT hash FROM agent_audit_events WHERE session_id = NEW.session_id AND seq = NEW.seq - 1)
BEGIN SELECT RAISE(ABORT, 'audit hash chain broken'); END;

CREATE TRIGGER trg_audit_cause_same_session
BEFORE INSERT ON agent_audit_events FOR EACH ROW
WHEN NEW.caused_by_event_id IS NOT NULL AND (SELECT session_id FROM agent_audit_events WHERE event_id = NEW.caused_by_event_id) IS NOT NEW.session_id
BEGIN SELECT RAISE(ABORT, 'cause must be in same session'); END;

CREATE TABLE agent_carts (
  cart_id         TEXT    NOT NULL,
  session_id      TEXT    NOT NULL,
  status          TEXT    NOT NULL DEFAULT 'open',
  version         INTEGER NOT NULL DEFAULT 1,
  currency        TEXT    NOT NULL,
  subtotal_minor  INTEGER NOT NULL DEFAULT 0,
  tax_minor       INTEGER NOT NULL DEFAULT 0,
  total_minor     INTEGER NOT NULL DEFAULT 0,
  snapshot_hash   TEXT,
  created_at      TEXT    NOT NULL,
  updated_at      TEXT    NOT NULL,
  CONSTRAINT pk_carts PRIMARY KEY (cart_id),
  CONSTRAINT fk_carts_session FOREIGN KEY (session_id) REFERENCES agent_sessions (session_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_carts_currency FOREIGN KEY (currency) REFERENCES currencies (iso4217) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_carts_id CHECK (cart_id GLOB 'crt_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  CONSTRAINT ck_carts_status CHECK (status IN ('open','locked','booked','abandoned')),
  CONSTRAINT ck_carts_version CHECK (version >= 1),
  CONSTRAINT ck_carts_amounts CHECK (subtotal_minor >= 0 AND tax_minor >= 0),
  CONSTRAINT ck_carts_total CHECK (total_minor = subtotal_minor + tax_minor),
  CONSTRAINT ck_carts_hash CHECK (snapshot_hash IS NULL OR (length(snapshot_hash) = 64 AND snapshot_hash NOT GLOB '*[^0-9a-f]*')),
  CONSTRAINT ck_carts_hash_required CHECK (status NOT IN ('locked','booked') OR snapshot_hash IS NOT NULL),
  CONSTRAINT ck_carts_time CHECK (strftime('%Y-%m-%dT%H:%M:%fZ', created_at) = created_at AND strftime('%Y-%m-%dT%H:%M:%fZ', updated_at) = updated_at AND updated_at >= created_at)
);
CREATE UNIQUE INDEX ux_carts_one_active ON agent_carts (session_id) WHERE status IN ('open','locked');
CREATE INDEX ix_carts_session ON agent_carts (session_id);

CREATE TRIGGER trg_carts_currency_session
BEFORE INSERT ON agent_carts FOR EACH ROW
WHEN NEW.currency IS NOT (SELECT currency FROM agent_sessions WHERE session_id = NEW.session_id)
BEGIN SELECT RAISE(ABORT, 'cart currency must equal session currency'); END;

CREATE TRIGGER trg_carts_immutable_keys
BEFORE UPDATE ON agent_carts FOR EACH ROW
WHEN NEW.cart_id IS NOT OLD.cart_id OR NEW.session_id IS NOT OLD.session_id OR NEW.currency IS NOT OLD.currency OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'cart keys are immutable'); END;

CREATE TRIGGER trg_carts_status_forward
BEFORE UPDATE OF status ON agent_carts FOR EACH ROW
WHEN NEW.status <> OLD.status AND NOT ((OLD.status = 'open' AND NEW.status IN ('locked','abandoned')) OR (OLD.status = 'locked' AND NEW.status IN ('open','booked','abandoned')))
BEGIN SELECT RAISE(ABORT, 'illegal cart status change'); END;

CREATE TRIGGER trg_carts_terminal_frozen
BEFORE UPDATE ON agent_carts FOR EACH ROW
WHEN OLD.status IN ('booked','abandoned')
BEGIN SELECT RAISE(ABORT, 'cart is final'); END;

CREATE TRIGGER trg_carts_version_monotonic
BEFORE UPDATE ON agent_carts FOR EACH ROW
WHEN NEW.version < OLD.version
BEGIN SELECT RAISE(ABORT, 'cart version cannot decrease'); END;

CREATE TRIGGER trg_carts_no_delete
BEFORE DELETE ON agent_carts FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'carts cannot be deleted'); END;

CREATE TABLE agent_cart_items (
  cart_item_id        TEXT    NOT NULL,
  cart_id             TEXT    NOT NULL,
  session_id          TEXT    NOT NULL,
  item_group_id       TEXT    NOT NULL,
  kind                TEXT    NOT NULL,
  entity_type         TEXT    NOT NULL,
  entity_id           TEXT    NOT NULL,   -- polymorphic; checked against inventory by trigger
  inventory_id        TEXT    NOT NULL,
  for_date            TEXT    NOT NULL,
  units               INTEGER NOT NULL,
  unit_price_minor    INTEGER NOT NULL,
  line_total_minor    INTEGER NOT NULL,
  source_event_id     TEXT    NOT NULL,
  source_offer_index  INTEGER NOT NULL,
  hold_id             TEXT,
  status              TEXT    NOT NULL DEFAULT 'active',
  added_in_version    INTEGER NOT NULL,
  removed_in_version  INTEGER,
  added_at            TEXT    NOT NULL,
  removed_at          TEXT,
  CONSTRAINT pk_items PRIMARY KEY (cart_item_id),
  CONSTRAINT fk_items_cart FOREIGN KEY (cart_id) REFERENCES agent_carts (cart_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_items_session FOREIGN KEY (session_id) REFERENCES agent_sessions (session_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_items_inventory FOREIGN KEY (inventory_id) REFERENCES inventory_calendar (inventory_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_items_source FOREIGN KEY (source_event_id) REFERENCES agent_audit_events (event_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_items_hold FOREIGN KEY (hold_id) REFERENCES holds (hold_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_items_id CHECK (cart_item_id GLOB 'cit_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]' AND item_group_id GLOB 'grp_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  CONSTRAINT ck_items_kind CHECK (kind IN ('flight','hotel_stay')),
  CONSTRAINT ck_items_pair CHECK ((kind = 'flight' AND entity_type = 'flight_fare') OR (kind = 'hotel_stay' AND entity_type = 'room_type')),
  CONSTRAINT ck_items_date CHECK (date(for_date) IS for_date),
  CONSTRAINT ck_items_units CHECK (units >= 1),
  CONSTRAINT ck_items_price CHECK (unit_price_minor >= 0),
  CONSTRAINT ck_items_line CHECK (line_total_minor = units * unit_price_minor),
  CONSTRAINT ck_items_offer_idx CHECK (source_offer_index >= 0),
  CONSTRAINT ck_items_status CHECK (status IN ('active','removed')),
  CONSTRAINT ck_items_versions CHECK (added_in_version >= 1 AND (removed_in_version IS NULL OR removed_in_version > added_in_version)),
  CONSTRAINT ck_items_removed CHECK ((status = 'removed') = (removed_in_version IS NOT NULL) AND (status = 'removed') = (removed_at IS NOT NULL)),
  CONSTRAINT ck_items_time CHECK (strftime('%Y-%m-%dT%H:%M:%fZ', added_at) = added_at AND (removed_at IS NULL OR (strftime('%Y-%m-%dT%H:%M:%fZ', removed_at) = removed_at AND removed_at >= added_at)))
);
CREATE UNIQUE INDEX ux_items_active_inventory ON agent_cart_items (cart_id, inventory_id) WHERE status = 'active';
CREATE INDEX ix_items_cart  ON agent_cart_items (cart_id, status);
CREATE INDEX ix_items_group ON agent_cart_items (item_group_id);
CREATE INDEX ix_items_hold  ON agent_cart_items (hold_id);

CREATE TRIGGER trg_items_session_match
BEFORE INSERT ON agent_cart_items FOR EACH ROW
WHEN NEW.session_id IS NOT (SELECT session_id FROM agent_carts WHERE cart_id = NEW.cart_id)
BEGIN SELECT RAISE(ABORT, 'item session must match cart'); END;

CREATE TRIGGER trg_items_currency_match
BEFORE INSERT ON agent_cart_items FOR EACH ROW
WHEN (SELECT currency FROM inventory_calendar WHERE inventory_id = NEW.inventory_id) IS NOT (SELECT currency FROM agent_carts WHERE cart_id = NEW.cart_id)
BEGIN SELECT RAISE(ABORT, 'mixed currency not allowed'); END;

CREATE TRIGGER trg_items_inventory_match
BEFORE INSERT ON agent_cart_items FOR EACH ROW
WHEN NOT EXISTS (SELECT 1 FROM inventory_calendar i WHERE i.inventory_id = NEW.inventory_id AND i.entity_type = NEW.entity_type AND i.entity_id = NEW.entity_id AND i.for_date = NEW.for_date)
BEGIN SELECT RAISE(ABORT, 'item does not match inventory row'); END;

CREATE TRIGGER trg_items_source_valid
BEFORE INSERT ON agent_cart_items FOR EACH ROW
WHEN NOT EXISTS (SELECT 1 FROM agent_audit_events e WHERE e.event_id = NEW.source_event_id AND e.session_id = NEW.session_id AND e.event_type = 'TOOL_RESULT')
BEGIN SELECT RAISE(ABORT, 'item must come from this session''s search result'); END;

CREATE TRIGGER trg_items_cart_open_ins
BEFORE INSERT ON agent_cart_items FOR EACH ROW
WHEN (SELECT status FROM agent_carts WHERE cart_id = NEW.cart_id) IS NOT 'open'
BEGIN SELECT RAISE(ABORT, 'cart is not open'); END;

CREATE TRIGGER trg_items_cart_open_upd
BEFORE UPDATE ON agent_cart_items FOR EACH ROW
WHEN (SELECT status FROM agent_carts WHERE cart_id = OLD.cart_id) IS NOT 'open'
BEGIN SELECT RAISE(ABORT, 'cart is not open'); END;

CREATE TRIGGER trg_items_immutable
BEFORE UPDATE ON agent_cart_items FOR EACH ROW
WHEN NEW.cart_item_id IS NOT OLD.cart_item_id OR NEW.cart_id IS NOT OLD.cart_id OR NEW.session_id IS NOT OLD.session_id OR NEW.item_group_id IS NOT OLD.item_group_id OR NEW.kind IS NOT OLD.kind OR NEW.entity_type IS NOT OLD.entity_type OR NEW.entity_id IS NOT OLD.entity_id OR NEW.inventory_id IS NOT OLD.inventory_id OR NEW.for_date IS NOT OLD.for_date OR NEW.units IS NOT OLD.units OR NEW.unit_price_minor IS NOT OLD.unit_price_minor OR NEW.line_total_minor IS NOT OLD.line_total_minor OR NEW.source_event_id IS NOT OLD.source_event_id OR NEW.source_offer_index IS NOT OLD.source_offer_index OR NEW.added_in_version IS NOT OLD.added_in_version OR NEW.added_at IS NOT OLD.added_at
BEGIN SELECT RAISE(ABORT, 'cart item fields are immutable'); END;

CREATE TRIGGER trg_items_removed_frozen
BEFORE UPDATE ON agent_cart_items FOR EACH ROW
WHEN OLD.status = 'removed'
BEGIN SELECT RAISE(ABORT, 'removed items are final'); END;

CREATE TRIGGER trg_items_no_delete
BEFORE DELETE ON agent_cart_items FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'cart items cannot be deleted'); END;

CREATE TABLE agent_confirmations (
  confirmation_id         TEXT    NOT NULL,
  session_id              TEXT    NOT NULL,
  cart_id                 TEXT    NOT NULL,
  cart_version            INTEGER NOT NULL,
  snapshot_hash           TEXT    NOT NULL,
  snapshot_json           TEXT    NOT NULL,
  currency                TEXT    NOT NULL,
  subtotal_minor          INTEGER NOT NULL,
  tax_minor               INTEGER NOT NULL,
  total_minor             INTEGER NOT NULL,
  effective_cap_minor     INTEGER NOT NULL,
  status                  TEXT    NOT NULL DEFAULT 'pending',
  requested_at            TEXT    NOT NULL,
  expires_at              TEXT    NOT NULL,
  decided_at              TEXT,
  decided_by_user_id      TEXT,
  decision_note           TEXT,
  closed_reason           TEXT,
  consumed_at             TEXT,
  consumed_by_booking_id  TEXT,
  CONSTRAINT pk_cnf PRIMARY KEY (confirmation_id),
  CONSTRAINT fk_cnf_session FOREIGN KEY (session_id) REFERENCES agent_sessions (session_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_cnf_cart FOREIGN KEY (cart_id) REFERENCES agent_carts (cart_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_cnf_currency FOREIGN KEY (currency) REFERENCES currencies (iso4217) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_cnf_user FOREIGN KEY (decided_by_user_id) REFERENCES users (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_cnf_booking FOREIGN KEY (consumed_by_booking_id) REFERENCES bookings (booking_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_cnf_id CHECK (confirmation_id GLOB 'cnf_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  CONSTRAINT ck_cnf_version CHECK (cart_version >= 1),
  CONSTRAINT ck_cnf_hash CHECK ((length(snapshot_hash) = 64 AND snapshot_hash NOT GLOB '*[^0-9a-f]*')),
  CONSTRAINT ck_cnf_snapshot CHECK (json_valid(snapshot_json) AND json_type(snapshot_json) = 'object'),
  CONSTRAINT ck_cnf_amounts CHECK (subtotal_minor >= 0 AND tax_minor >= 0 AND total_minor = subtotal_minor + tax_minor),
  CONSTRAINT ck_cnf_cap CHECK (effective_cap_minor > 0 AND total_minor <= effective_cap_minor),
  CONSTRAINT ck_cnf_status CHECK (status IN ('pending','approved','declined','expired','invalidated','consumed')),
  CONSTRAINT ck_cnf_times CHECK (strftime('%Y-%m-%dT%H:%M:%fZ', requested_at) = requested_at AND strftime('%Y-%m-%dT%H:%M:%fZ', expires_at) = expires_at AND expires_at > requested_at),
  CONSTRAINT ck_cnf_decided_time CHECK (decided_at IS NULL OR (strftime('%Y-%m-%dT%H:%M:%fZ', decided_at) = decided_at AND decided_at >= requested_at)),
  CONSTRAINT ck_cnf_decision_pair CHECK ((decided_at IS NULL) = (decided_by_user_id IS NULL)),
  CONSTRAINT ck_cnf_decision_required CHECK (status NOT IN ('approved','declined','consumed') OR decided_at IS NOT NULL),
  CONSTRAINT ck_cnf_pending_clean CHECK (status <> 'pending' OR (decided_at IS NULL AND decision_note IS NULL AND closed_reason IS NULL AND consumed_at IS NULL AND consumed_by_booking_id IS NULL)),
  CONSTRAINT ck_cnf_note CHECK (decision_note IS NULL OR length(decision_note) <= 500),
  CONSTRAINT ck_cnf_closed CHECK ((status IN ('expired','invalidated')) = (closed_reason IS NOT NULL)),
  CONSTRAINT ck_cnf_closed_values CHECK (closed_reason IS NULL OR closed_reason IN ('timeout','cart_changed','price_changed','sold_out','hold_expired')),
  CONSTRAINT ck_cnf_consumed CHECK ((status = 'consumed') = (consumed_at IS NOT NULL) AND (status = 'consumed') = (consumed_by_booking_id IS NOT NULL)),
  CONSTRAINT ck_cnf_consumed_time CHECK (consumed_at IS NULL OR (strftime('%Y-%m-%dT%H:%M:%fZ', consumed_at) = consumed_at AND consumed_at >= decided_at))
);
CREATE UNIQUE INDEX ux_cnf_one_pending ON agent_confirmations (session_id) WHERE status = 'pending';
CREATE UNIQUE INDEX ux_cnf_cart_version ON agent_confirmations (cart_id, cart_version) WHERE status IN ('pending','approved','consumed');
CREATE UNIQUE INDEX ux_cnf_one_booking_per_session ON agent_confirmations (session_id) WHERE status = 'consumed';
CREATE UNIQUE INDEX ux_cnf_booking ON agent_confirmations (consumed_by_booking_id) WHERE consumed_by_booking_id IS NOT NULL;
CREATE INDEX ix_cnf_session_time ON agent_confirmations (session_id, requested_at);

CREATE TRIGGER trg_cnf_insert_pending
BEFORE INSERT ON agent_confirmations FOR EACH ROW
WHEN NEW.status <> 'pending' OR NEW.decided_at IS NOT NULL OR NEW.decided_by_user_id IS NOT NULL OR NEW.consumed_at IS NOT NULL OR NEW.consumed_by_booking_id IS NOT NULL OR NEW.closed_reason IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'confirmation must be created pending'); END;

CREATE TRIGGER trg_cnf_cart_locked_match
BEFORE INSERT ON agent_confirmations FOR EACH ROW
WHEN NOT EXISTS (SELECT 1 FROM agent_carts c WHERE c.cart_id = NEW.cart_id AND c.session_id = NEW.session_id AND c.status = 'locked' AND c.version = NEW.cart_version AND c.snapshot_hash = NEW.snapshot_hash AND c.total_minor = NEW.total_minor AND c.currency = NEW.currency)
BEGIN SELECT RAISE(ABORT, 'confirmation must match locked cart'); END;

CREATE TRIGGER trg_cnf_transitions
BEFORE UPDATE OF status ON agent_confirmations FOR EACH ROW
WHEN NEW.status <> OLD.status AND NOT ((OLD.status = 'pending' AND NEW.status IN ('approved','declined','expired','invalidated')) OR (OLD.status = 'approved' AND NEW.status IN ('consumed','expired','invalidated')))
BEGIN SELECT RAISE(ABORT, 'illegal confirmation status change'); END;

CREATE TRIGGER trg_cnf_terminal_frozen
BEFORE UPDATE ON agent_confirmations FOR EACH ROW
WHEN OLD.status IN ('declined','expired','invalidated','consumed')
BEGIN SELECT RAISE(ABORT, 'confirmation is final'); END;

CREATE TRIGGER trg_cnf_owner_only
BEFORE UPDATE OF status ON agent_confirmations FOR EACH ROW
WHEN NEW.status IN ('approved','declined') AND NEW.decided_by_user_id IS NOT (SELECT user_id FROM agent_sessions WHERE session_id = NEW.session_id)
BEGIN SELECT RAISE(ABORT, 'only the session owner can decide'); END;

CREATE TRIGGER trg_cnf_snapshot_immutable
BEFORE UPDATE ON agent_confirmations FOR EACH ROW
WHEN NEW.confirmation_id IS NOT OLD.confirmation_id OR NEW.session_id IS NOT OLD.session_id OR NEW.cart_id IS NOT OLD.cart_id OR NEW.cart_version IS NOT OLD.cart_version OR NEW.snapshot_hash IS NOT OLD.snapshot_hash OR NEW.snapshot_json IS NOT OLD.snapshot_json OR NEW.currency IS NOT OLD.currency OR NEW.subtotal_minor IS NOT OLD.subtotal_minor OR NEW.tax_minor IS NOT OLD.tax_minor OR NEW.total_minor IS NOT OLD.total_minor OR NEW.effective_cap_minor IS NOT OLD.effective_cap_minor OR NEW.requested_at IS NOT OLD.requested_at OR NEW.expires_at IS NOT OLD.expires_at
BEGIN SELECT RAISE(ABORT, 'confirmation snapshot is immutable'); END;

CREATE TRIGGER trg_cnf_consume_owner
BEFORE UPDATE OF status ON agent_confirmations FOR EACH ROW
WHEN NEW.status = 'consumed' AND (SELECT user_id FROM bookings WHERE booking_id = NEW.consumed_by_booking_id) IS NOT (SELECT user_id FROM agent_sessions WHERE session_id = NEW.session_id)
BEGIN SELECT RAISE(ABORT, 'booking owner must match session owner'); END;

CREATE TRIGGER trg_cnf_no_delete
BEFORE DELETE ON agent_confirmations FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'confirmations cannot be deleted'); END;

CREATE TABLE agent_session_state (
  session_id     TEXT    NOT NULL,
  state_version  INTEGER NOT NULL,
  state_json     TEXT    NOT NULL,
  state_sha256   TEXT    NOT NULL,
  updated_at     TEXT    NOT NULL,
  CONSTRAINT pk_state PRIMARY KEY (session_id),
  CONSTRAINT fk_state_session FOREIGN KEY (session_id) REFERENCES agent_sessions (session_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_state_version CHECK (state_version >= 1),
  CONSTRAINT ck_state_json CHECK (json_valid(state_json) AND json_type(state_json) = 'object'),
  CONSTRAINT ck_state_size CHECK (length(CAST(state_json AS BLOB)) <= 1048576),
  CONSTRAINT ck_state_hash CHECK ((length(state_sha256) = 64 AND state_sha256 NOT GLOB '*[^0-9a-f]*')),
  CONSTRAINT ck_state_time CHECK (strftime('%Y-%m-%dT%H:%M:%fZ', updated_at) = updated_at)
);

CREATE TRIGGER trg_state_insert_v1
BEFORE INSERT ON agent_session_state FOR EACH ROW
WHEN NEW.state_version <> 1
BEGIN SELECT RAISE(ABORT, 'first state version must be 1'); END;

CREATE TRIGGER trg_state_version_step
BEFORE UPDATE ON agent_session_state FOR EACH ROW
WHEN NEW.state_version <> OLD.state_version + 1
BEGIN SELECT RAISE(ABORT, 'state version must increase by 1'); END;

CREATE TRIGGER trg_state_session_immutable
BEFORE UPDATE ON agent_session_state FOR EACH ROW
WHEN NEW.session_id IS NOT OLD.session_id
BEGIN SELECT RAISE(ABORT, 'state session is immutable'); END;

CREATE TRIGGER trg_state_no_delete
BEFORE DELETE ON agent_session_state FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'state cannot be deleted'); END;

-- ======================== 0002_existing_indexes.sql ========================
-- Migration 0002: the two approved indexes on existing tables (working copy only).
-- Approved schema; do not edit. Checksum is enforced by app/db/migrations/runner.py.

CREATE INDEX IF NOT EXISTS ix_flights_route_departs ON flights (origin_airport_id, dest_airport_id, departs_at);
CREATE INDEX IF NOT EXISTS ix_flight_fares_flight   ON flight_fares (flight_id);

-- ======================== 0003_multi_currency_cart.sql ========================
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

-- ======================== 0004_notifications.sql ========================
-- Migration 0004: push notifications (working copy only). Two new tables; existing tables untouched.
-- Checksum is enforced by src/db/migrations/runner.py; do not edit once approved.
--
-- push_subscriptions  one row per browser/device that allowed notifications (Web Push), with the
--                     user's notification preferences for that device.
-- notifications_sent  every notification raised for a user: the dedupe key guarantees each event
--                     (plan ready, booking confirmed, flight departing/landed) is sent once, and the
--                     rows double as the in-app notification history.

CREATE TABLE push_subscriptions (
  subscription_id TEXT    PRIMARY KEY,
  user_id         TEXT    NOT NULL,
  endpoint        TEXT    NOT NULL UNIQUE,
  p256dh          TEXT    NOT NULL,
  auth            TEXT    NOT NULL,
  prefs_json      TEXT    NOT NULL DEFAULT '{}',
  created_at      TEXT    NOT NULL,
  updated_at      TEXT    NOT NULL,
  CONSTRAINT fk_push_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT ck_push_prefs_json CHECK (json_valid(prefs_json))
);

CREATE TABLE notifications_sent (
  notification_id TEXT    PRIMARY KEY,
  user_id         TEXT    NOT NULL,
  session_id      TEXT,
  kind            TEXT    NOT NULL,
  dedupe_key      TEXT    NOT NULL UNIQUE,
  title           TEXT    NOT NULL,
  body            TEXT    NOT NULL,
  url             TEXT,
  delivered_count INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT    NOT NULL,
  CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_notif_session FOREIGN KEY (session_id) REFERENCES agent_sessions (session_id) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT ck_notif_kind CHECK (kind IN ('plan_ready','approval_ready','booking_confirmed','flight_departing','flight_landed','test'))
);

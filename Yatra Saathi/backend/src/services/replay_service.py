"""Verifies the audit hash chain and replays it to rebuild cart/confirmation/
booking state, comparing the replay against the stored rows (section 10,
`GET /sessions/{sid}/audit/verify`)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from src.db.repositories import audit as audit_repo
from src.db.repositories import carts as carts_repo
from src.db.repositories import confirmations as confirmations_repo
from src.services.audit_service import compute_hash


@dataclass
class VerifyResult:
    ok: bool
    chain_ok: bool
    seq_gapless: bool
    replay_matches: bool
    issues: list[str] = field(default_factory=list)


def verify_chain(events: list[audit_repo.AuditEvent]) -> tuple[bool, bool, list[str]]:
    issues: list[str] = []
    chain_ok = True
    seq_gapless = True
    prev_hash: Optional[str] = None
    for i, ev in enumerate(events, start=1):
        if ev.seq != i:
            seq_gapless = False
            issues.append(f"seq {ev.seq} out of order at position {i}")
        if ev.prev_hash != prev_hash:
            chain_ok = False
            issues.append(f"event {ev.event_id} prev_hash does not match previous event's hash")
        fields = {k: getattr(ev, k) for k in (
            "event_id", "session_id", "seq", "event_type", "occurred_at", "actor",
            "actor_user_id", "agent_run_id", "outcome", "reason_code", "reason",
            "input_json", "result_json", "request_id", "caused_by_event_id",
            "plan_version", "step_id", "cart_id", "cart_version", "confirmation_id",
            "booking_id",
        )}
        expected_hash = compute_hash(ev.prev_hash, fields)
        if expected_hash != ev.hash:
            chain_ok = False
            issues.append(f"event {ev.event_id} hash does not match its recomputed content")
        prev_hash = ev.hash
    return chain_ok, seq_gapless, issues


def _replay_cart_state(events: list[audit_repo.AuditEvent]) -> dict:
    """Rebuild the last known cart totals/version/status purely from CART_* and
    CONFIRMATION_* audit events, to compare with the stored `agent_carts` row."""
    cart_id = None
    version = None
    status = None
    for ev in events:
        if ev.event_type in ("CART_CREATED", "CART_UPDATED"):
            result = json.loads(ev.result_json)
            cart_id = ev.cart_id or result.get("cart_id", cart_id)
            version = ev.cart_version or result.get("version", version)
            status = result.get("status", status or "open")
        elif ev.event_type == "CONFIRMATION_REQUIRED":
            status = "locked"
        elif ev.event_type == "CONFIRMATION_DECLINED":
            status = "open"
        elif ev.event_type in ("BOOKING_SUCCESS",):
            status = "booked"
    return {"cart_id": cart_id, "version": version, "status": status}


def replay_and_verify(conn, session_id: str) -> VerifyResult:
    events = audit_repo.list_for_session(conn, session_id)
    chain_ok, seq_gapless, issues = verify_chain(events)

    replay_matches = True
    replayed = _replay_cart_state(events)
    if replayed["cart_id"]:
        stored_cart = carts_repo.get_cart(conn, replayed["cart_id"])
        if stored_cart is None:
            replay_matches = False
            issues.append(f"replay expects cart {replayed['cart_id']} but it does not exist")
        else:
            if replayed["version"] is not None and stored_cart.version < replayed["version"]:
                replay_matches = False
                issues.append("stored cart version is behind the replayed version")

    pending_or_last_confirmation_ids = {ev.confirmation_id for ev in events if ev.confirmation_id}
    for cid in pending_or_last_confirmation_ids:
        stored = confirmations_repo.get(conn, cid)
        if stored is None:
            replay_matches = False
            issues.append(f"replay references confirmation {cid} but it does not exist")

    ok = chain_ok and seq_gapless and replay_matches
    return VerifyResult(ok=ok, chain_ok=chain_ok, seq_gapless=seq_gapless,
                        replay_matches=replay_matches, issues=issues)

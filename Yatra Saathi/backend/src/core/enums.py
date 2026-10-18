"""Fixed vocabularies. EVENT_TYPES must match ck_audit_type in migration 0001 (tested)."""

EVENT_TYPES = (
    "SESSION_CREATED", "SESSION_RESUMED", "CLARIFICATION_REQUESTED",
    "PLAN_CREATED", "PLAN_STEP_STARTED", "PLAN_STEP_COMPLETED",
    "TOOL_CALL", "TOOL_RESULT", "BUDGET_CHECK", "ACTION_REFUSED", "REPLAN",
    "CART_CREATED", "CART_UPDATED",
    "CONFIRMATION_REQUIRED", "CONFIRMATION_RECEIVED", "CONFIRMATION_DECLINED",
    "CONFIRMATION_EXPIRED", "CONFIRMATION_INVALIDATED",
    "BOOKING_ATTEMPT", "BOOKING_SUCCESS", "BOOKING_REFUSED", "BOOKING_FAILED",
    "ERROR",
)
ACTORS = ("user", "agent", "system")
OUTCOMES = ("success", "refused", "failed", "info")
CART_STATUSES = ("open", "locked", "booked", "abandoned")
CART_ITEM_STATUSES = ("active", "removed")
CONFIRMATION_STATUSES = ("pending", "approved", "declined", "expired", "invalidated", "consumed")
CLOSED_REASONS = ("timeout", "cart_changed", "price_changed", "sold_out", "hold_expired")
# Existing agent_sessions.status vocabulary (no new values added).
SESSION_STATUSES = ("planning", "awaiting_input", "executing", "paused",
                    "awaiting_confirmation", "completed", "failed")
# Existing last_error_code values plus the three approved additions.
LAST_ERROR_CODES = ("over_budget", "sold_out", "hold_expired",
                    "confirmation_declined", "booking_failed", "replan_limit")

"""ID generation.

New tables: prefix + '_' + 16 lowercase hex (approved schema CHECKs).
Existing tables: follow the existing convention, prefix + '_' + 8 lowercase hex.
"""
from __future__ import annotations

import secrets

NEW_TABLE_PREFIXES = frozenset({"aud", "crt", "cit", "grp", "cnf", "run", "psb", "ntf", "prf"})
EXISTING_TABLE_PREFIXES = frozenset({"agt", "bkg", "bit", "pay", "hld", "trp", "bud", "usr", "itn", "itm"})
IDEMPOTENCY_PREFIXES = frozenset({"idem", "pidem", "hidem"})
# Phase 5 new table prefixes (8 hex chars for new tables)
PHASE5_TABLE_PREFIXES = frozenset({"btv", "p5e", "tpk"})
# Phase 6 new table prefixes (8 hex chars for new tables)
PHASE6_TABLE_PREFIXES = frozenset({"not", "sos", "emc", "vox"})


def new_id(prefix: str) -> str:
    if prefix in NEW_TABLE_PREFIXES:
        return f"{prefix}_{secrets.token_hex(8)}"
    if prefix in EXISTING_TABLE_PREFIXES:
        return f"{prefix}_{secrets.token_hex(4)}"
    if prefix in PHASE5_TABLE_PREFIXES or prefix in PHASE6_TABLE_PREFIXES:
        return f"{prefix}_{secrets.token_hex(8)}"
    raise ValueError(f"unknown id prefix: {prefix!r}")


def new_idempotency_key(prefix: str) -> str:
    if prefix not in IDEMPOTENCY_PREFIXES:
        raise ValueError(f"unknown idempotency prefix: {prefix!r}")
    return f"{prefix}_{secrets.token_hex(8)}"


def new_booking_reference() -> str:
    """YTR-DEMO-XXXXXXXX (8 uppercase hex), matching Phase 5 demo booking format.
    Backend-generated only; never from the LLM."""
    return f"YTR-DEMO-{secrets.token_hex(4).upper()}"

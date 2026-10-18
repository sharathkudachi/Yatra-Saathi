"""GET /api/v1/health"""
from __future__ import annotations

from fastapi import APIRouter

from src.contracts.envelope import ok

router = APIRouter()


@router.get("/health")
def health():
    return ok({"status": "ok"})

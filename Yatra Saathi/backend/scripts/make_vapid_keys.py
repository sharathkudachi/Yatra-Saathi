"""Print a fresh VAPID key pair for Web Push, ready to paste into backend/.env.backend.

    python -m scripts.make_vapid_keys

Both keys are base64url without padding: the public key is the uncompressed P-256 point the browser
needs (applicationServerKey); the private key is the raw 32-byte scalar pywebpush accepts.
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    vapid = Vapid01()
    vapid.generate_keys()
    public = vapid.public_key.public_bytes(serialization.Encoding.X962,
                                           serialization.PublicFormat.UncompressedPoint)
    private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    print(f"VAPID_PUBLIC_KEY={_b64(public)}")
    print(f"VAPID_PRIVATE_KEY={_b64(private)}")


if __name__ == "__main__":
    main()

"""TASK 5 — per-outlet gateway webhook secrets, encrypted at rest.

ADDITIVE. Depends on migration 040 (outlet_gateway_credentials) and
app.core.secrets_box (Task 2). Nothing here is reachable from any existing
route; the only callers are the new vendor-gateway webhook route and its
admin-only credential-management route, both introduced in this same task.

NEVER returns, logs, or otherwise surfaces a decrypted secret except as the
return value of get_active_secret, consumed directly by signature
verification and nowhere else.
"""
from __future__ import annotations

import base64
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets_box as sb


async def get_active_secret(db: AsyncSession, outlet_id, provider: str) -> Optional[str]:
    """Decrypt and return the ACTIVE secret for (outlet_id, provider), or
    None if no such row exists. Raises SecretsBoxError if the stored
    ciphertext fails authentication (tampered, or encrypted under a key no
    longer in the keyring) -- that must propagate as a verification failure,
    never as a silent "no secret"."""
    row = (await db.execute(text("""
        SELECT webhook_secret_ciphertext FROM outlet_gateway_credentials
         WHERE outlet_id = :outlet_id AND provider = :provider AND active
    """), {"outlet_id": str(outlet_id), "provider": provider})).first()
    if row is None:
        return None
    blob = base64.b64decode(row[0])
    box = sb.from_settings()
    return box.decrypt(blob).decode("utf-8")


async def set_secret(db: AsyncSession, outlet_id, provider: str, secret: str) -> dict:
    """Encrypt and store/rotate the secret for (outlet_id, provider).

    One row per (outlet_id, provider) -- a rotation UPDATEs that row in
    place (new ciphertext, new key_id, rotated_at stamped) rather than
    inserting a second one, so the prior plaintext is unrecoverable the
    moment this commits. Returns ONLY non-secret metadata; the plaintext
    secret passed in is never echoed back and never logged by this function.
    """
    box = sb.from_settings()
    blob = box.encrypt(secret.encode("utf-8"))
    ciphertext_b64 = base64.b64encode(blob).decode("ascii")

    row = (await db.execute(text("""
        INSERT INTO outlet_gateway_credentials
            (outlet_id, provider, webhook_secret_ciphertext, key_id, active)
        VALUES (:outlet_id, :provider, :ciphertext, :key_id, true)
        ON CONFLICT (outlet_id, provider) DO UPDATE
            SET webhook_secret_ciphertext = EXCLUDED.webhook_secret_ciphertext,
                key_id = EXCLUDED.key_id,
                rotated_at = now(),
                active = true
        RETURNING id, key_id, created_at, rotated_at
    """), {"outlet_id": str(outlet_id), "provider": provider,
           "ciphertext": ciphertext_b64, "key_id": box.active_key_id})).first()
    await db.commit()
    return {
        "outlet_id": str(outlet_id),
        "provider": provider,
        "credential_id": str(row[0]),
        "key_id": row[1],
        "created_at": row[2],
        "rotated_at": row[3],
    }

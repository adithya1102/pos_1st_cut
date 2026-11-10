"""TASK 5 — vendor-direct gateway webhook route + admin credential route.

ADDITIVE. Mounted at /api/v1 by app/main.py, exactly like every other router
in that file. No owner_app or customer_app change accompanies this; no code
here calls any provider's API (only verifies inbound webhooks).

ENUMERATION SAFETY: POST /webhooks/{provider}/{outlet_public_id} answers the
SAME status code and the SAME response body for three different causes --
the feature flag being off, an outlet id that does not exist, and a real
outlet with a signature that does not verify. An attacker who can distinguish
"outlet does not exist" from "outlet exists but you got the signature wrong"
can enumerate outlet ids by probing; collapsing all three into one 404 with
one fixed body removes that signal.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core import secrets_box as sb
from app.modules.carevo_admin.deps import get_current_super_admin
from app.modules.carevo_payments import adapters as ad
from app.modules.carevo_payments import reconciliation as rec
from app.modules.carevo_payments import vendor_credentials as vc
from app.modules.users.model import User

logger = logging.getLogger("app.vendor_webhook")

router = APIRouter()

_NOT_FOUND_DETAIL = "Not Found"

# A fixed, non-secret placeholder used ONLY to give the unknown-outlet path
# the same decrypt + HMAC cost as the known-outlet-wrong-signature path
# (see _decoy_verify). Never derived from any real credential.
_DECOY_SECRET_PLAINTEXT = b"timing-equalization-placeholder-secret-not-real"


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)


def _warn(reason: str, provider: str) -> None:
    """ONE WARNING line per rejected delivery. `reason` is always a fixed
    code from the literals below; `provider` is the path parameter the
    caller sent. Never the body, signature, secret, ciphertext, or key id --
    there is no f-string or %s anywhere in this module that touches any of
    those."""
    logger.warning("vendor_webhook_rejected reason=%s provider=%s", reason, provider)


async def _decoy_verify(provider: str, body: bytes, headers) -> None:
    """Does the SAME shape of work as a known outlet's credential fetch +
    signature check -- one secrets_box decrypt, one adapter HMAC -- against
    a throwaway secret, so a probe against an outlet id that does not exist
    costs the same as a probe against one that does. The result is always
    discarded; every caller ends at _not_found() regardless."""
    try:
        box = sb.from_settings()
        ciphertext = box.encrypt(_DECOY_SECRET_PLAINTEXT)
        decoy_secret = box.decrypt(ciphertext).decode("utf-8")
    except sb.SecretsBoxConfigError:
        decoy_secret = _DECOY_SECRET_PLAINTEXT.decode("utf-8")
    try:
        adapter = _build_adapter(provider, decoy_secret)
        adapter.verify(body, headers)
    except ad.AdapterError:
        pass


async def _resolve_outlet_id(db: AsyncSession, outlet_public_id: str):
    """Outlet ids ARE outlets.id (the same uuid every customer-facing route
    already uses, e.g. GET /menus/zone/{outlet_id}/{zone}) -- no new public
    identifier is introduced. A malformed value must 404 the same as a
    well-formed-but-unknown one, so any DB-level cast error is caught rather
    than allowed to surface as a 500 (which WOULD distinguish the two
    cases)."""
    try:
        row = (await db.execute(
            text("SELECT id FROM outlets WHERE id = :id"),
            {"id": outlet_public_id},
        )).first()
    except Exception:
        await db.rollback()
        return None
    return row[0] if row else None


def _build_adapter(provider: str, secret: str) -> ad.ProviderAdapter:
    key = (provider or "").strip().lower()
    if key == "cashfree":
        from app.modules.carevo_payments.gateway import CashfreeGateway
        gw = CashfreeGateway()
        # THIS outlet's own secret, not the platform CASHFREE_SECRET_KEY --
        # the vendor-direct model never depends on CareVo's own Cashfree
        # credentials or approval.
        gw.secret_key = secret
        return ad.CashfreeAdapter(gateway=gw)
    if key == "razorpay":
        if not settings.RAZORPAY_ADAPTER_ENABLED:
            raise ad.AdapterConfigError("razorpay adapter disabled")
        return ad.RazorpayWebhookAdapter(secret=secret)
    raise ad.AdapterConfigError(f"unknown provider {provider!r}")


@router.post("/webhooks/{provider}/{outlet_public_id}")
async def vendor_gateway_webhook(
    provider: str,
    outlet_public_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not settings.VENDOR_GATEWAY_ENABLED:
        _warn("flag_off", provider)
        raise _not_found()

    body = await request.body()
    headers = dict(request.headers)

    outlet_id = await _resolve_outlet_id(db, outlet_public_id)
    if outlet_id is None:
        # Same shape of work (decrypt + HMAC) as a known outlet with a
        # wrong signature, below -- see _decoy_verify's docstring.
        await _decoy_verify(provider, body, headers)
        _warn("unknown_outlet", provider)
        raise _not_found()

    try:
        secret = await vc.get_active_secret(db, outlet_id, provider)
    except sb.SecretsBoxError:
        # Ciphertext present but fails to decrypt (wrong/rotated key) -- not
        # distinguishable from "no credential configured" to the caller.
        _warn("credential_error", provider)
        raise _not_found()
    except sb.SecretsBoxConfigError:
        # SECRETS_ENC_KEY itself is missing/malformed. assert_startup_ready
        # should already have refused to boot in this state while the flag
        # is on; this is defence in depth, not the expected path.
        _warn("credential_error", provider)
        raise _not_found()
    if secret is None:
        _warn("credential_error", provider)
        raise _not_found()

    try:
        adapter = _build_adapter(provider, secret)
    except ad.AdapterConfigError:
        _warn("adapter_unavailable", provider)
        raise _not_found()

    try:
        event = adapter.verify(body, headers)
    except ad.AdapterError:
        _warn("signature_invalid", provider)
        raise _not_found()

    result = await rec.apply_vendor_payment_event(
        db, provider=adapter.name, event=event, outlet_id=outlet_id,
        body_sha256=rec.sha256_hex(body),
    )
    return {"ok": True, **result}


class SetGatewayCredentialIn(BaseModel):
    secret: str = Field(min_length=1)


class SetGatewayCredentialOut(BaseModel):
    outlet_id: str
    provider: str
    credential_id: str
    key_id: str
    rotated_at: Optional[datetime] = None


@router.put(
    "/admin/vendor-gateway/outlets/{outlet_id}/credentials/{provider}",
    response_model=SetGatewayCredentialOut,
)
async def set_outlet_gateway_credential(
    outlet_id: str,
    provider: str,
    payload: SetGatewayCredentialIn,
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set or rotate ONE outlet's webhook secret for ONE provider.

    SUPER_ADMIN only. The secret is write-only: this response (and every
    log line on this path) carries only non-secret metadata -- never the
    secret itself, in either direction.
    """
    outlet_row = (await db.execute(
        text("SELECT id FROM outlets WHERE id = :id"), {"id": outlet_id}
    )).first()
    if outlet_row is None:
        raise HTTPException(status_code=404, detail="Outlet not found")

    result = await vc.set_secret(db, outlet_id, provider, payload.secret)
    return result

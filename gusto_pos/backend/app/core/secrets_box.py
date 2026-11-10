"""AES-256-GCM secrets-at-rest helper.

ADDITIVE. Nothing in this repository calls this module yet — it exists for
the outlet gateway-credential store (reconciliation layer, Task 5) and has no
effect on any existing behaviour until a caller uses it.

Wire format (all fields are PUBLIC metadata, never secret):

    MAGIC(2="SB") | VERSION(1) | key_id_len(1) | key_id (utf-8, <=255 bytes)
    | nonce(12 bytes) | ciphertext (AES-GCM output, tag appended)

The key id travels WITH the ciphertext so a box can be given more than one
key — the active one for new encryptions, any number of retired ones so rows
written under them still decrypt. That is the entire rotation story: rotating
means constructing the next SecretsBox with a new active key id and the old
key(s) still present, not rewriting existing rows.

FAILS CLOSED, deliberately, in two places:
  * from_settings() raises SecretsBoxConfigError the first time anything
    calls it against a missing/malformed SECRETS_ENC_KEY or
    SECRETS_ENC_KEY_ID — not at import time, since importing this module
    must never require the key to exist.
  * assert_startup_ready(required=...) is the hook a feature flag's startup
    check calls with its own flag's current value; when that value is
    truthy it calls from_settings() and lets any resulting error propagate
    out of the FastAPI startup event, the same fail-closed shape
    app/core/config.py already uses for CASHFREE_ONLY.

NEVER logs plaintext, ciphertext, or key material. Every message below names
only non-secret metadata: which env var is missing, a key id, a byte length.
"""
from __future__ import annotations

import base64
import os
import secrets as _secrets
from dataclasses import dataclass
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"SB"
VERSION = 1
KEY_LEN = 32          # AES-256
NONCE_LEN = 12         # 96-bit GCM nonce, the documented optimum for AESGCM
_HEADER_FIXED_LEN = len(MAGIC) + 1   # MAGIC + VERSION


class SecretsBoxError(RuntimeError):
    """Decryption refused: wrong key, tampered ciphertext, or malformed blob.

    Raised instead of returning anything — AES-GCM's own authentication
    check means there is no such thing as "partial" plaintext to hand back;
    the tag either verifies over the whole ciphertext or it does not.
    """


class SecretsBoxConfigError(RuntimeError):
    """SECRETS_ENC_KEY / SECRETS_ENC_KEY_ID are missing or malformed.

    Never carries the key value — only which variable is wrong and why.
    """


def _b64_key(raw: str, *, var_name: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(raw.encode("ascii"))
    except Exception as exc:  # malformed base64, non-ascii, etc.
        raise SecretsBoxConfigError(
            f"{var_name} is not valid urlsafe-base64"
        ) from exc
    if len(key) != KEY_LEN:
        raise SecretsBoxConfigError(
            f"{var_name} must decode to {KEY_LEN} bytes, got {len(key)}"
        )
    return key


@dataclass(frozen=True)
class SecretsBox:
    """A keyring plus one designated active key for new encryptions.

    `keys` maps key_id -> 32-byte AES key. Every key in the ring can
    decrypt; only `active_key_id` is used by encrypt().
    """

    keys: dict
    active_key_id: str

    def __post_init__(self):
        if self.active_key_id not in self.keys:
            raise SecretsBoxConfigError(
                "active_key_id is not present in the supplied keyring"
            )
        for key_id, key in self.keys.items():
            if not isinstance(key, bytes) or len(key) != KEY_LEN:
                raise SecretsBoxConfigError(
                    f"key id {key_id!r} is not a {KEY_LEN}-byte key"
                )
            if len(key_id.encode("utf-8")) > 255:
                raise SecretsBoxConfigError(
                    f"key id {key_id!r} exceeds 255 bytes encoded"
                )

    def encrypt(self, plaintext: bytes, *, aad: Optional[bytes] = None) -> bytes:
        """Encrypt under the ACTIVE key. Fresh random nonce every call —
        two encryptions of identical plaintext never produce identical
        ciphertext (barring the ~2^-96 chance of a nonce collision)."""
        if not isinstance(plaintext, bytes):
            raise TypeError("plaintext must be bytes")
        key = self.keys[self.active_key_id]
        nonce = _secrets.token_bytes(NONCE_LEN)
        ct = AESGCM(key).encrypt(nonce, plaintext, aad)
        key_id_bytes = self.active_key_id.encode("utf-8")
        return (
            MAGIC + bytes([VERSION]) + bytes([len(key_id_bytes)])
            + key_id_bytes + nonce + ct
        )

    def decrypt(self, blob: bytes, *, aad: Optional[bytes] = None) -> bytes:
        """Decrypt. Raises SecretsBoxError on ANY failure — malformed blob,
        unknown key id, wrong key, or a tampered byte anywhere in the
        ciphertext or its tag. Never returns a fragment of the plaintext."""
        if not isinstance(blob, bytes) or len(blob) < _HEADER_FIXED_LEN + 1:
            raise SecretsBoxError("ciphertext blob is too short to be valid")
        if blob[:len(MAGIC)] != MAGIC:
            raise SecretsBoxError("ciphertext blob has an unrecognised header")
        version = blob[len(MAGIC)]
        if version != VERSION:
            raise SecretsBoxError(f"unsupported ciphertext version {version}")
        offset = _HEADER_FIXED_LEN
        key_id_len = blob[offset]
        offset += 1
        if len(blob) < offset + key_id_len + NONCE_LEN:
            raise SecretsBoxError("ciphertext blob is truncated")
        key_id = blob[offset:offset + key_id_len].decode("utf-8", "strict")
        offset += key_id_len
        nonce = blob[offset:offset + NONCE_LEN]
        offset += NONCE_LEN
        ct = blob[offset:]
        key = self.keys.get(key_id)
        if key is None:
            raise SecretsBoxError(f"ciphertext key id {key_id!r} is not in this keyring")
        try:
            return AESGCM(key).decrypt(nonce, ct, aad)
        except InvalidTag as exc:
            raise SecretsBoxError(
                "ciphertext failed authentication (wrong key or tampered data)"
            ) from exc


def from_settings(cfg=None) -> SecretsBox:
    """The single-current-key production default, built lazily from
    app.core.config.settings. Raises SecretsBoxConfigError — never silently
    falls back to any default key — when SECRETS_ENC_KEY or
    SECRETS_ENC_KEY_ID is missing or malformed. Not called at import time by
    anything in this repository."""
    if cfg is None:
        from app.core.config import settings as cfg
    key_id = (cfg.SECRETS_ENC_KEY_ID or "").strip()
    if not key_id:
        raise SecretsBoxConfigError("SECRETS_ENC_KEY_ID is not set")
    raw = cfg.SECRETS_ENC_KEY
    if not raw:
        raise SecretsBoxConfigError("SECRETS_ENC_KEY is not set")
    key = _b64_key(raw, var_name="SECRETS_ENC_KEY")
    return SecretsBox(keys={key_id: key}, active_key_id=key_id)


def assert_startup_ready(required: bool) -> None:
    """Fail-closed startup hook. A caller with its OWN feature flag passes
    that flag's live value here; when it is true this raises
    SecretsBoxConfigError if the secrets box cannot be constructed, which is
    meant to propagate out of the FastAPI startup event uncaught — the same
    shape as validate_cashfree_only_config in app/core/config.py. A false
    flag makes this a no-op, so importing or starting the app with no
    secrets-dependent feature enabled never requires a key to exist."""
    if not required:
        return
    from_settings()

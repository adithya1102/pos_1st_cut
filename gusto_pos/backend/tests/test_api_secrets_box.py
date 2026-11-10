"""TASK 2 — app.core.secrets_box (AES-256-GCM secrets at rest).

Pure unit tests against the module directly — no HTTP, no DB, no network.
Keys here are generated in memory by the test itself, never read from any
real .env or committed file.
"""
from __future__ import annotations

import base64
import os
import secrets as pysecrets

import pytest

from app.core import secrets_box as sb
from app.core.config import settings


def _fresh_key() -> bytes:
    return pysecrets.token_bytes(sb.KEY_LEN)


def _b64(key: bytes) -> str:
    return base64.urlsafe_b64encode(key).decode("ascii")


class TestRoundtrip:
    def test_encrypt_then_decrypt_returns_original_plaintext(self):
        box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        plaintext = b"a vendor webhook secret, as bytes"
        blob = box.encrypt(plaintext)
        assert box.decrypt(blob) == plaintext

    def test_roundtrip_with_associated_data(self):
        box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        aad = b"outlet_id=abc123"
        blob = box.encrypt(b"secret", aad=aad)
        assert box.decrypt(blob, aad=aad) == b"secret"

    def test_wrong_aad_fails(self):
        box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        blob = box.encrypt(b"secret", aad=b"outlet_id=abc123")
        with pytest.raises(sb.SecretsBoxError):
            box.decrypt(blob, aad=b"outlet_id=WRONG")


class TestNonceFreshness:
    def test_two_encryptions_of_same_plaintext_differ(self):
        box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        a = box.encrypt(b"same plaintext every time")
        b = box.encrypt(b"same plaintext every time")
        assert a != b
        # Both still decrypt to the same thing — the difference is only the
        # random nonce + resulting ciphertext, not the recovered plaintext.
        assert box.decrypt(a) == box.decrypt(b) == b"same plaintext every time"


class TestTamperAndWrongKey:
    def test_tampering_one_ciphertext_byte_fails(self):
        box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        blob = bytearray(box.encrypt(b"do not touch me"))
        blob[-1] ^= 0x01  # flip one bit in the GCM tag/ciphertext tail
        with pytest.raises(sb.SecretsBoxError):
            box.decrypt(bytes(blob))

    def test_tampering_a_middle_byte_fails(self):
        box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        blob = bytearray(box.encrypt(b"a somewhat longer plaintext value"))
        mid = len(blob) // 2
        blob[mid] ^= 0x01
        with pytest.raises(sb.SecretsBoxError):
            box.decrypt(bytes(blob))

    def test_decrypting_with_a_box_that_lacks_the_key_fails(self):
        box_a = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        box_b = sb.SecretsBox(keys={"k2": _fresh_key()}, active_key_id="k2")
        blob = box_a.encrypt(b"secret")
        with pytest.raises(sb.SecretsBoxError):
            box_b.decrypt(blob)

    def test_decrypting_with_the_wrong_key_under_the_same_key_id_fails(self):
        blob = sb.SecretsBox(
            keys={"k1": _fresh_key()}, active_key_id="k1"
        ).encrypt(b"secret")
        wrong_box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        with pytest.raises(sb.SecretsBoxError):
            wrong_box.decrypt(blob)

    def test_truncated_blob_fails_closed_not_with_a_crash(self):
        box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        blob = box.encrypt(b"secret")
        with pytest.raises(sb.SecretsBoxError):
            box.decrypt(blob[:5])

    def test_corrupted_magic_header_fails(self):
        box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        blob = bytearray(box.encrypt(b"secret"))
        blob[0] ^= 0xFF
        with pytest.raises(sb.SecretsBoxError):
            box.decrypt(bytes(blob))


class TestRotation:
    def test_old_key_id_still_decrypts_when_provided_in_the_keyring(self):
        old_key = _fresh_key()
        new_key = _fresh_key()
        old_box = sb.SecretsBox(keys={"k1": old_key}, active_key_id="k1")
        blob_under_old_key = old_box.encrypt(b"written before rotation")

        # Rotate: the new box's active key is k2, but k1 is still present so
        # rows written before rotation keep decrypting.
        rotated_box = sb.SecretsBox(
            keys={"k1": old_key, "k2": new_key}, active_key_id="k2"
        )
        assert rotated_box.decrypt(blob_under_old_key) == b"written before rotation"

        # New encryptions use the new active key id. Header layout:
        # MAGIC(2) + VERSION(1) + key_id_len(1) + key_id.
        new_blob = rotated_box.encrypt(b"written after rotation")
        assert new_blob[4:4 + 2].decode("utf-8") == "k2"

    def test_old_key_absent_from_the_keyring_no_longer_decrypts(self):
        old_key = _fresh_key()
        new_key = _fresh_key()
        old_box = sb.SecretsBox(keys={"k1": old_key}, active_key_id="k1")
        blob = old_box.encrypt(b"secret")

        # A rotation that DROPPED k1 entirely.
        post_rotation_box = sb.SecretsBox(keys={"k2": new_key}, active_key_id="k2")
        with pytest.raises(sb.SecretsBoxError):
            post_rotation_box.decrypt(blob)


class TestConstructionValidation:
    def test_active_key_id_must_be_in_the_keyring(self):
        with pytest.raises(sb.SecretsBoxConfigError):
            sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k-does-not-exist")

    def test_a_short_key_is_rejected(self):
        with pytest.raises(sb.SecretsBoxConfigError):
            sb.SecretsBox(keys={"k1": b"too-short"}, active_key_id="k1")


class TestFromSettingsFailsClosed:
    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY", None)
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY_ID", "k1")
        with pytest.raises(sb.SecretsBoxConfigError):
            sb.from_settings()

    def test_missing_key_id_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY", _b64(_fresh_key()))
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY_ID", None)
        with pytest.raises(sb.SecretsBoxConfigError):
            sb.from_settings()

    def test_malformed_base64_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY", "not-valid-base64!!!")
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY_ID", "k1")
        with pytest.raises(sb.SecretsBoxConfigError):
            sb.from_settings()

    def test_wrong_length_key_raises(self, monkeypatch):
        short = base64.urlsafe_b64encode(b"only16bytes12345").decode("ascii")
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY", short)
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY_ID", "k1")
        with pytest.raises(sb.SecretsBoxConfigError):
            sb.from_settings()

    def test_well_formed_settings_produce_a_working_box(self, monkeypatch):
        key = _fresh_key()
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY", _b64(key))
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY_ID", "k1")
        box = sb.from_settings()
        blob = box.encrypt(b"secret")
        assert box.decrypt(blob) == b"secret"


class TestStartupFailsClosed:
    def test_not_required_is_a_noop_even_when_key_is_missing(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY", None)
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY_ID", None)
        sb.assert_startup_ready(False)  # must not raise

    def test_required_and_missing_key_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY", None)
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY_ID", None)
        with pytest.raises(sb.SecretsBoxConfigError):
            sb.assert_startup_ready(True)

    def test_required_and_well_formed_key_does_not_raise(self, monkeypatch):
        key = _fresh_key()
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY", _b64(key))
        monkeypatch.setattr(settings, "SECRETS_ENC_KEY_ID", "k1")
        sb.assert_startup_ready(True)  # must not raise


class TestNeverLogsSecrets:
    def test_decrypt_error_message_contains_no_key_material_or_plaintext(self):
        box = sb.SecretsBox(keys={"k1": _fresh_key()}, active_key_id="k1")
        plaintext = b"THIS-MUST-NEVER-APPEAR-IN-AN-ERROR-MESSAGE"
        blob = bytearray(box.encrypt(plaintext))
        blob[-1] ^= 0x01
        with pytest.raises(sb.SecretsBoxError) as exc:
            box.decrypt(bytes(blob))
        message = str(exc.value)
        assert b"THIS-MUST-NEVER-APPEAR-IN-AN-ERROR-MESSAGE" not in message.encode()
        # The raw key bytes never appear in the message either.
        for key in box.keys.values():
            assert key.hex() not in message

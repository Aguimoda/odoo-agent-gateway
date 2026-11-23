"""Provider keys at rest (ADR 0015): AES-256-GCM, bound to the provider URL, rotatable."""

import pytest

from odoo_agent_gateway.secretbox import SecretBox, SecretError, new_master_key

URL = "https://api.groq.com/openai/v1"
FAKE_PROVIDER_KEY = "fake-provider-key-for-tests-only"


def test_round_trip_and_ciphertext_hides_the_key():
    box = SecretBox.from_env(new_master_key())
    blob = box.encrypt(FAKE_PROVIDER_KEY, URL)
    assert FAKE_PROVIDER_KEY.encode() not in blob
    assert box.decrypt(blob, URL) == FAKE_PROVIDER_KEY


def test_each_encryption_uses_a_fresh_nonce():
    box = SecretBox.from_env(new_master_key())
    assert box.encrypt(FAKE_PROVIDER_KEY, URL) != box.encrypt(FAKE_PROVIDER_KEY, URL)


def test_a_key_does_not_decrypt_for_another_url():
    box = SecretBox.from_env(new_master_key())
    blob = box.encrypt(FAKE_PROVIDER_KEY, URL)
    with pytest.raises(SecretError):
        box.decrypt(blob, "https://attacker.example/v1")


def test_tampered_ciphertext_is_refused():
    box = SecretBox.from_env(new_master_key())
    blob = bytearray(box.encrypt(FAKE_PROVIDER_KEY, URL))
    blob[-1] ^= 1
    with pytest.raises(SecretError):
        box.decrypt(bytes(blob), URL)


def test_rotation_old_master_key_still_decrypts_new_one_encrypts():
    old, new = new_master_key(), new_master_key()
    blob = SecretBox.from_env(old).encrypt(FAKE_PROVIDER_KEY, URL)
    rotated = SecretBox.from_env(f"{new},{old}")
    assert rotated.decrypt(blob, URL) == FAKE_PROVIDER_KEY
    fresh = rotated.encrypt(FAKE_PROVIDER_KEY, URL)
    assert SecretBox.from_env(new).decrypt(fresh, URL) == FAKE_PROVIDER_KEY
    with pytest.raises(SecretError):
        SecretBox.from_env(old).decrypt(fresh, URL)


def test_unknown_master_key_is_refused():
    blob = SecretBox.from_env(new_master_key()).encrypt(FAKE_PROVIDER_KEY, URL)
    with pytest.raises(SecretError):
        SecretBox.from_env(new_master_key()).decrypt(blob, URL)


@pytest.mark.parametrize("value", ["", " , ", "not-base64!", "c2hvcnQ="])
def test_bad_master_keys_fail_at_start(value):
    with pytest.raises(ValueError):
        SecretBox.from_env(value)


def test_repr_never_shows_master_keys():
    key = new_master_key()
    assert key not in repr(SecretBox.from_env(key))

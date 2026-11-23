"""Encryption of provider API keys at rest (ADR 0015).

AES-256-GCM with master keys from the environment only (`GATEWAY_SECRET_KEYS`, comma
separated, the first one encrypts). The provider's base URL is the associated data, so a
stored key decrypts only for the URL it was entered for.

Blob layout: version (1 byte) | master key id (4 bytes) | nonce (12 bytes) | ciphertext.

Generate a master key with: python -m odoo_agent_gateway.secretbox
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = b"\x01"
_ID_LEN = 4
_NONCE_LEN = 12


class SecretError(Exception):
    """A stored key could not be decrypted. Never carries key material."""


def new_master_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _key_id(key: bytes) -> bytes:
    return hashlib.sha256(key).digest()[:_ID_LEN]


class SecretBox:
    def __init__(self, master_keys: list[bytes]) -> None:
        if not master_keys:
            raise ValueError("At least one master key is required.")
        if any(len(key) != 32 for key in master_keys):
            raise ValueError("Master keys must be 32 bytes, base64 encoded.")
        self._current = master_keys[0]
        self._by_id = {_key_id(key): AESGCM(key) for key in master_keys}

    def __repr__(self) -> str:
        return f"SecretBox(keys={len(self._by_id)})"

    @classmethod
    def from_env(cls, value: str) -> SecretBox:
        keys = []
        for item in (part.strip() for part in (value or "").split(",")):
            if not item:
                continue
            try:
                keys.append(base64.urlsafe_b64decode(item.encode("ascii")))
            except (binascii.Error, ValueError, UnicodeEncodeError):
                raise ValueError("GATEWAY_SECRET_KEYS holds a value that is not base64.") from None
        return cls(keys)

    def encrypt(self, plaintext: str, context: str) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        sealed = AESGCM(self._current).encrypt(nonce, plaintext.encode("utf-8"), _aad(context))
        return _VERSION + _key_id(self._current) + nonce + sealed

    def decrypt(self, blob: bytes, context: str) -> str:
        blob = bytes(blob)
        if len(blob) < 1 + _ID_LEN + _NONCE_LEN + 16 or blob[:1] != _VERSION:
            raise SecretError("Stored key has an unknown format.")
        cipher = self._by_id.get(blob[1 : 1 + _ID_LEN])
        if cipher is None:
            raise SecretError("Stored key was encrypted with a master key this server lacks.")
        nonce = blob[1 + _ID_LEN : 1 + _ID_LEN + _NONCE_LEN]
        try:
            return cipher.decrypt(nonce, blob[1 + _ID_LEN + _NONCE_LEN :], _aad(context)).decode()
        except InvalidTag:
            raise SecretError("Stored key does not match this provider URL.") from None


def _aad(context: str) -> bytes:
    return ("provider-url:" + context).encode("utf-8")


if __name__ == "__main__":
    print(new_master_key())

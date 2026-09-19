"""Passwords, session tokens, and a clinic's API key at rest.

Three different problems, deliberately solved three different ways:

* A **password** must be slow to guess and must never be recoverable, so it
  is hashed with scrypt and salted per user. `hashlib.scrypt` is standard
  library, so this costs no dependency.
* A **session token** must be cheap to check on every poll and must not be
  recoverable from a stolen database, so the token itself is 32 random bytes
  that only ever exist in the cookie, and the database holds its SHA-256.
  There is nothing to brute-force: the input has 256 bits of entropy, so a
  fast digest is the right one here and a slow one would only tax us.
* A **clinic's Prosper API key** must be recoverable — a call needs it to
  reach the clinic — so it is encrypted, not hashed, with AES-256-GCM under a
  key derived from `OPS_SECRET_KEY`. That secret lives where the other ones
  live (a Fly secret), never on the volume, so the database file alone is not
  enough to read a clinic's credential.

The one rule the rest of the code enforces around this module: a decrypted
key goes to the Prosper client and nowhere else. It is never logged, never
returned by an HTTP route, and never put in a trace. What a person is shown
is `fingerprint()` — eight hex characters of a digest, enough to answer
"is the right key loaded" and useless for anything else.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets as stdlib_secrets

# scrypt cost. 2**14 is ~40 ms on this machine, which is the right order for
# a console login: unnoticeable to a person, expensive in bulk.
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

_SECRET_PREFIX = "v1"
_INFO = b"prosper-org-credentials-v1"


class SecretsUnavailable(RuntimeError):
    """No `OPS_SECRET_KEY`, so a credential can be neither stored nor read."""


# ---- passwords ------------------------------------------------------------
def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt$hash`, all base64. Self-describing on purpose.

    The parameters travel with the hash so raising the cost later does not
    invalidate the hashes written before it.
    """
    if not password:
        raise ValueError("empty password")
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check. False for anything malformed, never an exception."""
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        derived = hashlib.scrypt(
            (password or "").encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(derived, expected)


# ---- session tokens -------------------------------------------------------
def new_session_token() -> str:
    """32 random bytes, url-safe. The only copy that exists is the cookie."""
    return stdlib_secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """What the database stores. A digest of 256 bits of entropy needs no salt."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


# ---- a clinic's credential ------------------------------------------------
def _aes_key(key_material: str) -> bytes:
    """Derive a 32-byte AES key from the configured secret."""
    if not key_material:
        raise SecretsUnavailable(
            "OPS_SECRET_KEY is not set: per-organisation credentials cannot be stored"
        )
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        key_material.encode("utf-8")
    )


def encrypt_secret(plaintext: str, key_material: str, aad: str = "") -> str:
    """`v1:<base64(nonce||ciphertext||tag)>`.

    `aad` is the organisation id, bound in as additional authenticated data.
    A ciphertext copied from one row into another then fails to open, rather
    than silently handing clinic A's key to a call placed for clinic B.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    sealed = AESGCM(_aes_key(key_material)).encrypt(
        nonce, plaintext.encode("utf-8"), aad.encode("utf-8")
    )
    return f"{_SECRET_PREFIX}:{base64.b64encode(nonce + sealed).decode('ascii')}"


def decrypt_secret(blob: str, key_material: str, aad: str = "") -> str:
    """The plaintext, or SecretsUnavailable. Never a partial or a guess."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        prefix, payload = (blob or "").split(":", 1)
    except ValueError as exc:
        raise SecretsUnavailable("stored credential is not in a known format") from exc
    if prefix != _SECRET_PREFIX:
        raise SecretsUnavailable(f"unknown credential format {prefix!r}")
    try:
        raw = base64.b64decode(payload)
        opened = AESGCM(_aes_key(key_material)).decrypt(raw[:12], raw[12:], aad.encode("utf-8"))
    except (InvalidTag, ValueError) as exc:
        # Wrong OPS_SECRET_KEY, a row from another organisation, or a tampered
        # one. All three mean "do not use it".
        raise SecretsUnavailable("stored credential could not be decrypted") from exc
    return opened.decode("utf-8")


def fingerprint(plaintext: str) -> str:
    """What a person may see: eight hex characters of a digest.

    Enough to tell two keys apart and to confirm the right one is loaded.
    Not enough to be one.
    """
    if not plaintext:
        return ""
    return "sha256:" + hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:8]

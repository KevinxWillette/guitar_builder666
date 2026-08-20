"""Encryption for the password-locked galleries.

Standard-library only, so the vault works on a fresh machine with nothing
but Python installed:

* key derivation  — scrypt (memory-hard, so a stolen gallery is expensive
  to brute-force even with a short passphrase)
* confidentiality — SHA-256 counter-mode keystream, XORed with the plaintext
* integrity       — HMAC-SHA-256 over the ciphertext (encrypt-then-MAC), so
  a tampered or truncated gallery file fails loudly instead of decrypting
  to garbage

A gallery file that leaves the vault is unreadable without the passphrase.
The passphrase is never written to disk — only the scrypt salt and a
verifier blob are.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

MAGIC = b"KVLT1"
SALT_BYTES = 16
NONCE_BYTES = 16
KEY_BYTES = 32
TAG_BYTES = 32

# scrypt cost. 2**15 * 8 * 128 = 32 MB of memory per attempt.
KDF_N = 1 << 15
KDF_R = 8
KDF_P = 1
KDF_MAXMEM = 96 * 1024 * 1024

VERIFIER_PLAINTEXT = b"killette-vault-verifier"


class BadPassphrase(Exception):
    """Wrong passphrase, or the file was tampered with."""


def new_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def derive_key(passphrase: str, salt: bytes, *, n: int = KDF_N,
               r: int = KDF_R, p: int = KDF_P) -> bytes:
    """Stretch *passphrase* into a 32-byte key."""
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=KEY_BYTES,
        maxmem=KDF_MAXMEM,
    )


def _subkeys(key: bytes) -> tuple[bytes, bytes]:
    enc = hmac.new(key, b"killette-enc", hashlib.sha256).digest()
    mac = hmac.new(key, b"killette-mac", hashlib.sha256).digest()
    return enc, mac


def _keystream(enc_key: bytes, nonce: bytes, nbytes: int) -> bytes:
    blocks = []
    produced = 0
    counter = 0
    while produced < nbytes:
        blocks.append(
            hashlib.sha256(
                enc_key + nonce + counter.to_bytes(8, "big")
            ).digest()
        )
        produced += 32
        counter += 1
    return b"".join(blocks)[:nbytes]


def _xor(data: bytes, stream: bytes) -> bytes:
    if not data:
        return b""
    # Big-int XOR keeps this in C instead of a per-byte Python loop.
    width = len(data)
    mixed = int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")
    return mixed.to_bytes(width, "big")


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Return ``MAGIC | nonce | ciphertext | tag``."""
    nonce = secrets.token_bytes(NONCE_BYTES)
    enc_key, mac_key = _subkeys(key)
    ciphertext = _xor(plaintext, _keystream(enc_key, nonce, len(plaintext)))
    body = MAGIC + nonce + ciphertext
    tag = hmac.new(mac_key, body, hashlib.sha256).digest()
    return body + tag


def decrypt(blob: bytes, key: bytes) -> bytes:
    """Inverse of :func:`encrypt`; raises :class:`BadPassphrase`."""
    header = len(MAGIC) + NONCE_BYTES
    if len(blob) < header + TAG_BYTES or not blob.startswith(MAGIC):
        raise BadPassphrase("not a vault file (bad header)")
    body, tag = blob[:-TAG_BYTES], blob[-TAG_BYTES:]
    enc_key, mac_key = _subkeys(key)
    expected = hmac.new(mac_key, body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise BadPassphrase("wrong passphrase, or the file has been altered")
    nonce = body[len(MAGIC):header]
    ciphertext = body[header:]
    return _xor(ciphertext, _keystream(enc_key, nonce, len(ciphertext)))


def make_verifier(key: bytes) -> str:
    """A blob that proves a passphrase without unlocking any picture."""
    return encrypt(VERIFIER_PLAINTEXT, key).hex()


def check_verifier(verifier_hex: str, key: bytes) -> bool:
    try:
        return decrypt(bytes.fromhex(verifier_hex), key) == VERIFIER_PLAINTEXT
    except (BadPassphrase, ValueError):
        return False


def shred(path, passes: int = 1) -> None:
    """Overwrite a file's bytes before unlinking it.

    Best effort: on copy-on-write and flash filesystems the old blocks can
    survive. It is a speed bump, not an erasure guarantee.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return
    try:
        with open(path, "r+b", buffering=0) as fh:
            for _ in range(max(1, passes)):
                fh.seek(0)
                fh.write(os.urandom(size))
                fh.flush()
                os.fsync(fh.fileno())
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass

"""OIDC 协议纯函数：PKCE、scope、回调校验与 RS256 JWT。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import urllib.parse

SUPPORTED_SCOPES = ("openid", "profile", "email")


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def make_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    return verifier, pkce_challenge(verifier)


def pkce_challenge(verifier: str) -> str:
    return b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def verify_pkce(verifier: str, challenge: str) -> bool:
    if not verifier or not challenge:
        return False
    return hmac.compare_digest(pkce_challenge(verifier), challenge)


def valid_redirect_uri(client: dict, candidate: str) -> bool:
    return bool(candidate) and candidate in (client.get("redirect_uris") or [])


def validate_registered_redirect(uri: str) -> bool:
    if not isinstance(uri, str) or not uri or len(uri) > 2048:
        return False
    parsed = urllib.parse.urlsplit(uri)
    if parsed.fragment or parsed.username or parsed.password:
        return False
    if not parsed.hostname or not parsed.netloc:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme == "http":
        return parsed.hostname in ("localhost", "127.0.0.1", "::1")
    return False


def normalize_scopes(raw: str, allowed) -> list[str] | None:
    requested = []
    for scope in str(raw or "").split():
        if scope not in requested:
            requested.append(scope)
    allowed_set = set(allowed or ())
    if not requested or any(scope not in allowed_set for scope in requested):
        return None
    if "openid" not in requested:
        return None
    return requested


def _jwk_params(pem: str) -> dict:
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    numbers = key.public_key().public_numbers()

    def _integer(value: int) -> str:
        size = max(1, (value.bit_length() + 7) // 8)
        return b64url(value.to_bytes(size, "big"))

    return {"kty": "RSA", "n": _integer(numbers.n), "e": _integer(numbers.e)}


def generate_signing_key() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    return _record_from_pem(pem)


def _record_from_pem(pem: str) -> dict:
    params = _jwk_params(pem)
    thumbprint = b64url(hashlib.sha256(json.dumps(
        {"e": params["e"], "kty": "RSA", "n": params["n"]},
        separators=(",", ":"), sort_keys=True).encode("utf-8")).digest())
    jwk = {
        "kty": "RSA", "use": "sig", "alg": "RS256",
        "kid": thumbprint, "n": params["n"], "e": params["e"],
    }
    return {"pem": pem, "kid": thumbprint, "jwk": jwk}


def public_jwk(pem: str) -> dict:
    return _record_from_pem(pem)["jwk"]


def jwt_encode(pem: str, kid: str, claims: dict) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    signing_input = (
        b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        + "." +
        b64url(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    )
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return signing_input + "." + b64url(signature)

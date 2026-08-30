from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from pathlib import Path

import requests

from fpl.config import (
    FPL_AUTHORIZE_URL,
    FPL_CLIENT_ID,
    FPL_REDIRECT_URI,
    FPL_SCOPE,
    FPL_TOKEN_FILE,
    FPL_TOKEN_URL,
)


def _base64url(data: bytes) -> str:
    """Base64 URL encoding without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_pkce() -> tuple[str, str]:
    """Generate a PKCE verifier and S256 challenge."""
    verifier = _base64url(secrets.token_bytes(32))

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = _base64url(digest)

    return verifier, challenge


def _save_tokens(tokens: dict) -> None:
    """Save OAuth tokens locally."""
    FPL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

    FPL_TOKEN_FILE.write_text(
        json.dumps(tokens, indent=2),
        encoding="utf-8",
    )


def _load_tokens() -> dict | None:
    """Load locally cached OAuth tokens."""
    if not FPL_TOKEN_FILE.exists():
        return None

    return json.loads(
        FPL_TOKEN_FILE.read_text(encoding="utf-8")
    )


def _refresh_access_token(refresh_token: str) -> dict:
    """Use a refresh token to obtain a new access token."""

    response = requests.post(
        FPL_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": FPL_CLIENT_ID,
        },
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def _interactive_login() -> dict:
    """
    Open the FPL login page and obtain an OAuth authorisation code.

    This uses the current FPL OAuth/OIDC + PKCE flow.
    """

    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    params = {
        "client_id": FPL_CLIENT_ID,
        "redirect_uri": FPL_REDIRECT_URI,
        "response_type": "code",
        "scope": FPL_SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "language": "en",
    }

    request = requests.Request(
        "GET",
        FPL_AUTHORIZE_URL,
        params=params,
    ).prepare()

    print("\nOpening FPL login in your browser...")
    print("\nAfter logging in, copy the URL from your browser's address bar.")
    print("It should contain ?code=...&state=...\n")

    webbrowser.open(request.url)

    redirect_url = input(
        "Paste the full redirected URL here: "
    ).strip()

    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(redirect_url)
    query = parse_qs(parsed.query)

    returned_state = query.get("state", [None])[0]
    code = query.get("code", [None])[0]

    if returned_state != state:
        raise RuntimeError(
            "OAuth state mismatch. The authorisation response could not "
            "be verified."
        )

    if not code:
        error = query.get("error", ["unknown"])[0]

        raise RuntimeError(
            f"FPL authorisation failed: {error}"
        )

    response = requests.post(
        FPL_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": FPL_REDIRECT_URI,
            "client_id": FPL_CLIENT_ID,
            "code_verifier": verifier,
        },
        timeout=30,
    )

    response.raise_for_status()

    tokens = response.json()

    _save_tokens(tokens)

    return tokens


def get_access_token() -> str:
    """
    Return a valid FPL access token.

    Uses the cached refresh token where possible.
    Falls back to an interactive browser login.
    """

    tokens = _load_tokens()

    if tokens:
        expires_at = tokens.get("expires_at", 0)

        # Refresh slightly before expiry.
        if time.time() < expires_at - 60:
            return tokens["access_token"]

        refresh_token = tokens.get("refresh_token")

        if refresh_token:
            try:
                new_tokens = _refresh_access_token(refresh_token)

                # Some OAuth providers don't return a new refresh token.
                if "refresh_token" not in new_tokens:
                    new_tokens["refresh_token"] = refresh_token

                new_tokens["expires_at"] = (
                    time.time() + new_tokens["expires_in"]
                )

                _save_tokens(new_tokens)

                return new_tokens["access_token"]

            except requests.HTTPError:
                print(
                    "Cached FPL refresh token is no longer valid. "
                    "Starting a new login."
                )

    tokens = _interactive_login()

    tokens["expires_at"] = (
        time.time() + tokens["expires_in"]
    )

    _save_tokens(tokens)

    return tokens["access_token"]
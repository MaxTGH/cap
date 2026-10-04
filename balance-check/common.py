"""Shared helpers: Keychain storage and the Plaid client.

Nothing secret is ever written to disk. Plaid credentials and bank access tokens
live in the macOS Keychain under the service name below.
"""
import json
import sys

import keyring
import plaid
from plaid.api import plaid_api

SERVICE = "balance-check"


def get_secret(name: str) -> str | None:
    return keyring.get_password(SERVICE, name)


def set_secret(name: str, value: str) -> None:
    keyring.set_password(SERVICE, name, value)


def load_tokens() -> dict:
    """{institution name: Plaid access token} for every linked bank."""
    raw = get_secret("access_tokens")
    return json.loads(raw) if raw else {}


def save_tokens(tokens: dict) -> None:
    set_secret("access_tokens", json.dumps(tokens))


def plaid_client() -> plaid_api.PlaidApi:
    client_id, secret = get_secret("plaid_client_id"), get_secret("plaid_secret")
    if not client_id or not secret:
        sys.exit("Plaid keys not found in Keychain. Run: .venv/bin/python setup_keys.py")
    config = plaid.Configuration(
        host=plaid.Environment.Production,  # the free Trial plan uses Production
        api_key={"clientId": client_id, "secret": secret},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(config))

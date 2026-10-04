"""Store your Plaid client ID and secret in the macOS Keychain (one-time setup).

Input is read from the terminal with echo off, so it never appears on screen, in
scrollback, or in shell history. The values go straight from this process into
the Keychain via the macOS Security framework; nothing is written to disk.
"""
import getpass
import subprocess
import warnings

from common import set_secret

# If the terminal can't hide input, getpass would fall back to echoing it. Abort instead.
warnings.simplefilter("error", getpass.GetPassWarning)

try:
    client_id = getpass.getpass("Plaid client_id (hidden): ").strip()
    secret = getpass.getpass("Plaid Production secret (hidden): ").strip()
except getpass.GetPassWarning:
    raise SystemExit("This terminal can't hide input; run setup_keys.py from Terminal.app or VS Code's terminal.")

if not client_id or not secret:
    raise SystemExit("Both values are required; nothing saved.")

set_secret("plaid_client_id", client_id)
set_secret("plaid_secret", secret)

# The secret was probably copied from the browser; don't leave it on the clipboard.
subprocess.run(["pbcopy"], input=b"", check=False)
print("Saved to Keychain (service: balance-check). Clipboard cleared.")

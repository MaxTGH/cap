"""Connect a bank through Plaid Link, or repair an existing connection.

    .venv/bin/python link.py                 # connect a new bank
    .venv/bin/python link.py --update "My Bank"  # re-login when a bank asks you to

Opens a page on http://127.0.0.1 (only reachable from this Mac). You log in to
your bank inside Plaid's window, so this program never sees your bank password.
The resulting read-only access token goes straight into the Keychain. The local
page only accepts requests addressed to itself, and the result is only accepted
with a one-time code embedded in that page, so other websites can't feed it data.

Note: the Trial plan allows 10 connections total and removing one does not free
a slot, so only link each bank once and use --update to repair it.
"""
import argparse
import hmac
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products

from common import load_tokens, plaid_client, save_tokens

PORT = 8765

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Connect bank</title>
<body style="font-family: system-ui; max-width: 32rem; margin: 4rem auto; padding: 0 1rem">
<h1>Connect a bank</h1>
<button id="go" style="font-size: 1.1rem; padding: .6rem 1.2rem">Open Plaid</button>
<p id="msg"></p>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<script>
const msg = document.getElementById("msg");
const handler = Plaid.create({
  token: "__LINK_TOKEN__",
  onSuccess: (public_token, metadata) => {
    msg.textContent = "Saving...";
    fetch("/done", {method: "POST", body: JSON.stringify({
      nonce: "__NONCE__", public_token, institution: metadata.institution && metadata.institution.name
    })}).then(() => msg.textContent = "Done. You can close this tab.");
  },
  onExit: (err) => { msg.textContent = err ? "Error: " + (err.display_message || err.error_code) : "Cancelled."; },
});
document.getElementById("go").onclick = () => handler.open();
</script>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", metavar="BANK", help="repair an existing connection by name")
    args = parser.parse_args()

    client = plaid_client()
    tokens = load_tokens()

    request = dict(
        client_name="Balance Check",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id="local-user"),
    )
    if args.update:
        if args.update not in tokens:
            raise SystemExit(f"No bank named {args.update!r}. Linked: {', '.join(tokens) or 'none'}")
        request["access_token"] = tokens[args.update]  # update mode: no products
    else:
        # Transactions works for both checking and credit cards; we only ever read balances.
        request["products"] = [Products("transactions")]
    link_token = client.link_token_create(LinkTokenCreateRequest(**request))["link_token"]

    result = {}
    nonce = secrets.token_urlsafe(16)
    hosts = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

    class Handler(BaseHTTPRequestHandler):
        def addressed_to_us(self) -> bool:
            # Refuse other hostnames (DNS rebinding) and requests sent from other websites.
            origin = self.headers.get("Origin")
            if self.headers.get("Host") in hosts and (not origin or origin in {f"http://{h}" for h in hosts}):
                return True
            self.send_response(403)
            self.end_headers()
            return False

        def do_GET(self):
            if not self.addressed_to_us():
                return
            body = PAGE.replace("__LINK_TOKEN__", link_token).replace("__NONCE__", nonce).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self.addressed_to_us():
                return
            if self.path == "/done":
                length = min(int(self.headers.get("Content-Length", 0)), 10_000)
                try:
                    data = json.loads(self.rfile.read(length))
                except json.JSONDecodeError:
                    data = {}
                if not hmac.compare_digest(str(data.get("nonce", "")), nonce):
                    self.send_response(403)
                    self.end_headers()
                    return
                result.update(data)
                self.send_response(204)
                self.end_headers()
                threading.Thread(target=server.shutdown).start()

        def log_message(self, *_):
            pass  # keep tokens out of the terminal

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Opening {url} (Ctrl-C to cancel)")
    webbrowser.open(url)
    server.serve_forever()

    if args.update:
        print(f"{args.update} reconnected.")
        return

    name = result.get("institution") or "Bank"
    if name in tokens:
        name = f"{name} ({len(tokens) + 1})"
    exchange = ItemPublicTokenExchangeRequest(public_token=result["public_token"])
    tokens[name] = client.item_public_token_exchange(exchange)["access_token"]
    save_tokens(tokens)
    print(f"Linked {name}. Banks connected: {', '.join(tokens)}")


if __name__ == "__main__":
    main()

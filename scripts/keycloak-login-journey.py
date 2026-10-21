#!/usr/bin/env python3
"""Browser journeys of the realm's login hardening (T-5120, components/keycloak/README.md).

  steward  a holder of `mfa-required` signs in with password and TOTP code
  plain    a person without it signs in with the password alone
  enrol    a throwaway holder of `mfa-required` without TOTP is sent to enrolment
  lockout  a throwaway person is locked after 10 wrong passwords, the right one is refused

Secrets come from the environment, never argv: JC_LOGIN_PASSWORD and JC_LOGIN_TOTP (the seed
in Secret keycloak-user-<name>, key `totp`) for steward/plain; KC_ADMIN_USER and
KC_ADMIN_PASSWORD (Secret keycloak-admin-user) for the throwaway checks, which delete their
user again whatever the outcome.

  scripts/keycloak-login-journey.py --base https://idp.example --realm dev steward --user demo.steward@hel.fi
"""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import struct
import sys
import time
import urllib.parse
import urllib.request

FAILURE_FACTOR = 10  # components/keycloak/values/config/base-values.yaml.gotmpl failureFactor


def totp(seed: str, at: float, step: int = 30, digits: int = 6) -> str:
    """RFC 6238 with HMAC-SHA256 over the seed's UTF-8 bytes, as Keycloak keeps an OTP secret."""
    mac = hmac.new(seed.encode(), struct.pack(">Q", int(at) // step), hashlib.sha256).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % 10**digits).zfill(digits)


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"keycloak-login-journey: {name} is not set")
    return value


class Admin:
    """The realm's admin REST API, for the throwaway users only."""

    def __init__(self, base: str, realm: str):
        self.base, self.realm = base, realm
        form = urllib.parse.urlencode(
            {"grant_type": "password", "client_id": "admin-cli",
             "username": env("KC_ADMIN_USER"), "password": env("KC_ADMIN_PASSWORD")}
        ).encode()
        with urllib.request.urlopen(f"{base}/realms/master/protocol/openid-connect/token", form, timeout=30) as r:
            self.token = json.load(r)["access_token"]

    def call(self, method: str, path: str, body=None):
        req = urllib.request.Request(
            f"{self.base}/admin/realms/{self.realm}{path}", method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def throwaway(self, role: str | None) -> tuple[str, str, str]:
        email = f"journey-{secrets.token_hex(4)}@example.invalid"
        password = "Jr1-" + secrets.token_urlsafe(18)
        self.call("POST", "/users", {
            "username": email, "email": email, "enabled": True, "emailVerified": True,
            "firstName": "Journey", "lastName": "Throwaway", "requiredActions": [],
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        })
        uid = self.call("GET", f"/users?username={urllib.parse.quote(email)}&exact=true")[0]["id"]
        if role:
            self.call("POST", f"/users/{uid}/role-mappings/realm", [self.call("GET", f"/roles/{role}")])
        return uid, email, password


def open_login(page, base: str, realm: str) -> None:
    page.goto(f"{base}/realms/{realm}/account", wait_until="load")
    page.wait_for_selector("#username", timeout=30_000)


def submit_password(page, user: str, password: str) -> None:
    page.fill("#username", user)
    page.fill("#password", password)
    with page.expect_navigation(wait_until="load"):
        page.click("#kc-login")


def landed(page, base: str, realm: str) -> bool:
    return page.url.startswith(f"{base}/realms/{realm}/account") and not page.locator("#kc-form-login, #kc-otp-login-form").count()


def run(args) -> list[str]:
    from playwright.sync_api import sync_playwright

    failures: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(locale="en").new_page()
        if args.check in ("steward", "plain"):
            open_login(page, args.base, args.realm)
            submit_password(page, args.user, env("JC_LOGIN_PASSWORD"))
            asked = page.locator("#otp").count() > 0
            if args.check == "plain":
                if asked:
                    failures.append(f"{args.user} was asked for a TOTP code it never configured")
            elif not asked:
                failures.append(f"{args.user} signed in without a second factor")
            else:
                page.fill("#otp", totp(env("JC_LOGIN_TOTP"), time.time()))
                with page.expect_navigation(wait_until="load"):
                    page.click("#kc-login")
            if args.screenshot:
                page.screenshot(path=args.screenshot, full_page=True)
            if not failures and not landed(page, args.base, args.realm):
                failures.append(f"{args.user} did not reach the account console: {page.url}")
        else:
            admin = Admin(args.admin_base or args.base, args.realm)
            uid, email, password = admin.throwaway("mfa-required" if args.check == "enrol" else None)
            try:
                open_login(page, args.base, args.realm)
                if args.check == "enrol":
                    submit_password(page, email, password)
                    if args.screenshot:
                        page.screenshot(path=args.screenshot, full_page=True)
                    # Keycloak's CONFIGURE_TOTP page: the QR code and the code field to confirm it.
                    if not page.locator("#kc-totp-settings-form").count():
                        failures.append(f"a holder of mfa-required without TOTP was not sent to enrolment: {page.url}")
                else:
                    for _ in range(FAILURE_FACTOR):
                        # Slower than quickLoginCheckMilliSeconds, so the counter and not the
                        # quick-login rule is what locks.
                        time.sleep(1.2)
                        submit_password(page, email, password + "x")
                    status = admin.call("GET", f"/attack-detection/brute-force/users/{uid}")
                    if not status.get("disabled"):
                        failures.append(f"{FAILURE_FACTOR} wrong passwords did not lock the account: {status}")
                    submit_password(page, email, password)
                    if args.screenshot:
                        page.screenshot(path=args.screenshot, full_page=True)
                    if landed(page, args.base, args.realm):
                        failures.append("the locked account signed in with its right password")
            finally:
                admin.call("DELETE", f"/users/{uid}")
        browser.close()
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="Keycloak base URL, e.g. https://idp.dev.example")
    parser.add_argument("--admin-base", help="admin API base when the edge hides /admin (a port-forward)")
    parser.add_argument("--realm", required=True)
    parser.add_argument("--user", help="the person for steward/plain")
    parser.add_argument("--screenshot", help="PNG of the last page")
    parser.add_argument("check", choices=["steward", "plain", "enrol", "lockout"])
    args = parser.parse_args()
    args.base = args.base.rstrip("/")
    if args.check in ("steward", "plain") and not args.user:
        parser.error("--user is required for steward and plain")
    failures = run(args)
    for failure in failures:
        print(f"KO {args.check}: {failure}")
    if not failures:
        print(f"ok {args.check}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

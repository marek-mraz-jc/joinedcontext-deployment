"""T-5120: the realm's login hardening renders the same on dev and on production.

Every holder of `mfa-required` (the composite of portal-approver and platform-admin) must give a
TOTP code and enrols at the next login; brute-force detection locks after 10 wrong passwords;
the password policy refuses the username, the e-mail and the last 5; the lifetimes are the
documented ones. scripts/keycloak-login-journey.py walks the same rules in a browser.
"""

import base64
import json

import pytest

ENVIRONMENTS = ("dev", "production", "smartcity")
MFA_ROLES = {"portal-approver", "platform-admin"}


def realms(docs):
    for doc in docs:
        if doc.get("kind") == "Secret" and doc["metadata"]["name"].endswith("config-cli-config-realms"):
            return {k: json.loads(base64.b64decode(v)) for k, v in doc["data"].items()}
    pytest.fail("no keycloak-config-cli realm Secret in the render")


@pytest.fixture(scope="module", params=ENVIRONMENTS)
def env_docs(request, rendered):
    return request.param, rendered(request.param)


@pytest.fixture(scope="module")
def realm(env_docs):
    env, docs = env_docs
    found = [r for name, r in realms(docs).items() if name != "master.json"]
    assert len(found) == 1, (env, [r.get("realm") for r in found])
    return found[0]


def flow(realm, alias):
    return next(f for f in realm["authenticationFlows"] if f["alias"] == alias)


def steps(realm, alias):
    return [(e.get("authenticator") or e.get("flowAlias"), e["requirement"], e.get("authenticatorConfig"))
            for e in sorted(flow(realm, alias)["authenticationExecutions"], key=lambda e: e["priority"])]


def role_condition(realm, alias):
    return next(c for c in realm["authenticatorConfig"] if c["alias"] == alias)["config"]


def test_approvers_and_admins_carry_mfa_required(realm):
    roles = {r["name"]: r for r in realm["roles"]["realm"]}
    assert "mfa-required" in roles
    for name in MFA_ROLES:
        assert roles[name]["composite"] is True, name
        assert roles[name]["composites"]["realm"] == ["mfa-required"], name


def test_the_browser_flow_demands_totp_of_mfa_required_and_offers_2fa_to_the_rest(realm):
    assert realm["browserFlow"] == "custom browser"
    assert steps(realm, "custom browser forms") == [
        ("auth-username-password-form", "REQUIRED", None),
        ("custom browser required 2fa", "CONDITIONAL", None),
        ("custom browser 2fa", "CONDITIONAL", None),
    ]
    # REQUIRED OTP with no credential: Keycloak adds CONFIGURE_TOTP, the enrolment at next login.
    assert steps(realm, "custom browser required 2fa") == [
        ("conditional-user-role", "REQUIRED", "mfa required"),
        ("auth-otp-form", "REQUIRED", None),
    ]
    assert role_condition(realm, "mfa required") == {"condUserRole": "mfa-required", "negate": "false"}
    # The optional subflow excludes the same role, so nobody is asked for a code twice.
    assert steps(realm, "custom browser 2fa") == [
        ("conditional-user-role", "REQUIRED", "mfa not required"),
        ("conditional-user-configured", "REQUIRED", None),
        ("auth-otp-form", "ALTERNATIVE", None),
        ("webauthn-authenticator", "ALTERNATIVE", None),
    ]
    assert role_condition(realm, "mfa not required") == {"condUserRole": "mfa-required", "negate": "true"}


def test_brute_force_locks_after_ten_failures_with_back_off(realm):
    assert realm["bruteForceProtected"] is True
    assert realm["permanentLockout"] is False
    assert realm["failureFactor"] == 10
    assert realm["waitIncrementSeconds"] == 60
    assert realm["maxFailureWaitSeconds"] == 900
    assert realm["minimumQuickLoginWaitSeconds"] == 60
    assert realm["maxDeltaTimeSeconds"] == 43200


def test_password_policy(realm):
    policy = realm["passwordPolicy"].split(" and ")
    for rule in ("length(12)", "upperCase(1)", "lowerCase(1)", "digits(1)",
                 "notUsername(undefined)", "notEmail(undefined)", "passwordHistory(5)"):
        assert rule in policy, rule


def test_totp_policy_and_lifetimes(env_docs, realm):
    env, _ = env_docs
    assert (realm["otpPolicyType"], realm["otpPolicyAlgorithm"], realm["otpPolicyDigits"], realm["otpPolicyPeriod"]) == (
        "totp", "HmacSHA256", 6, 30)
    assert realm["ssoSessionIdleTimeout"] == 3600
    assert realm["ssoSessionMaxLifespan"] == 36000
    assert realm["rememberMe"] is False
    # The development values give an hour (dev, and smartcity whose valuesProfile is development);
    # the production profile keeps the base 5 min.
    assert realm["accessTokenLifespan"] == {"dev": 3600, "production": 300, "smartcity": 3600}[env]


def test_every_demo_person_with_an_mfa_role_has_a_totp_seed_from_its_secret(env_docs, realm):
    env, docs = env_docs
    seeded = {d["metadata"]["name"]: set(d.get("data") or {}) for d in docs
              if d.get("kind") == "Secret" and d["metadata"]["name"].startswith("keycloak-user-demo-")}
    for user in realm["users"]:
        if not user["username"].startswith("demo."):
            continue
        name = user["username"].split("@")[0]
        secret = "keycloak-user-" + name.replace(".", "-")
        otp = [c for c in user.get("credentials", []) if c["type"] == "otp"]
        if MFA_ROLES & set(user.get("realmRoles") or []):
            assert len(otp) == 1, (env, name)
            var = "USER_TOTP_" + name.upper().replace(".", "_")
            # The seed reaches the import by variable, never as a literal in Git or the render.
            assert json.loads(otp[0]["secretData"]) == {"value": f"$({var})"}
            assert json.loads(otp[0]["credentialData"])["algorithm"] == "HmacSHA256"
            assert "totp" in seeded.get(secret, set()), (env, secret)
        else:
            assert not otp, (env, name)
            assert "totp" not in seeded.get(secret, set()), (env, secret)


def test_the_initial_owner_gets_no_seed_and_enrols_at_first_login(realm):
    # A real person's second factor is enrolled on their own device, never seeded.
    for user in realm["users"]:
        if not user["username"].startswith(("demo.", "service-account-")):
            assert not [c for c in user.get("credentials", []) if c["type"] == "otp"], user["username"]


def test_the_config_cli_reads_each_seed_from_its_secret(env_docs):
    env, docs = env_docs
    for doc in docs:
        if doc.get("kind") == "Job" and "config-cli" in doc["metadata"]["name"]:
            envs = {e["name"]: e for c in doc["spec"]["template"]["spec"]["containers"] for e in c.get("env") or []}
            for name, e in envs.items():
                if name.startswith("USER_TOTP_"):
                    ref = e["valueFrom"]["secretKeyRef"]
                    assert ref["key"] == "totp" and ref["name"].startswith("keycloak-user-"), (env, name)
            return
    pytest.fail(f"no keycloak-config-cli Job in the {env} render")


def test_the_password_grant_demands_totp_of_mfa_required(realm):
    # Keycloak's built-in "direct grant" asks OTP only of people who enrolled one, so a new
    # approver would get a password-only token from apisix-gateway; the custom flow refuses it.
    assert realm["directGrantFlow"] == "custom direct grant"
    assert flow(realm, "custom direct grant")["topLevel"] is True
    assert steps(realm, "custom direct grant") == [
        ("direct-grant-validate-username", "REQUIRED", None),
        ("direct-grant-validate-password", "REQUIRED", None),
        ("custom direct grant required otp", "CONDITIONAL", None),
        ("custom direct grant otp", "CONDITIONAL", None),
    ]
    assert steps(realm, "custom direct grant required otp") == [
        ("conditional-user-role", "REQUIRED", "mfa required"),
        ("direct-grant-validate-otp", "REQUIRED", None),
    ]
    assert steps(realm, "custom direct grant otp") == [
        ("conditional-user-role", "REQUIRED", "mfa not required"),
        ("conditional-user-configured", "REQUIRED", None),
        ("direct-grant-validate-otp", "REQUIRED", None),
    ]

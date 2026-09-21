"""T-2476: apps are served on the apex, never on the Portal's own host.

On `portal.{domain}` an app's `connect-src 'self'` would be the Portal API, and the session
cookie would ride along with every call it makes. The Portal refuses that host for `/apps/*`
only when it knows the apps origin, so every environment has to hand it one: the apex the
`apps-surface` route serves, and not the Portal's host.
"""

from urllib.parse import urlsplit

import pytest


def portal_env(docs):
    portal = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "portal")
    return {e["name"]: e.get("value") for e in portal["spec"]["template"]["spec"]["containers"][0].get("env", [])}


@pytest.mark.parametrize("environment", ["dev", "local"])
def test_the_portal_knows_the_apps_origin_and_it_is_not_its_own(rendered, environment):
    env = portal_env(rendered(environment))
    apps = urlsplit(env["JC_PORTAL_APPS_URL"])
    portal = urlsplit(env["JC_PORTAL_PUBLIC_URL"])

    assert apps.scheme == "https"
    assert apps.path in ("", "/") and not apps.query, "an origin, nothing after it"
    assert apps.hostname != portal.hostname
    assert portal.hostname == f"portal.{apps.hostname}", "the apex the apps-surface route serves"

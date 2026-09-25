"""T-2476, T-2839: apps are served on hosts of their own, never on the Portal's host.

On `portal.{domain}` an app's `connect-src 'self'` would be the Portal API, and the session
cookie would ride along with every call it makes. Every App is served on `{name}.apps.{apex}`
(ADR-N-037, AP-133), and the Portal refuses any other host for an App only when it knows the
apex, so every environment has to hand it one: the domain, not the Portal's host. An App pod
reaches its endpoint on the gateway's Service in the cluster (AP-134), so the Portal is handed
that address too, never a public one.
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
    assert portal.hostname == f"portal.{apps.hostname}", "the apex every App's host sits under"

    gateway = urlsplit(env["JC_PORTAL_GATEWAY_URL"])
    assert gateway.scheme == "http" and gateway.hostname.endswith(".svc.cluster.local"), (
        "an App pod calls its endpoint in the cluster, where its NetworkPolicy names the gateway"
    )
    assert gateway.hostname.startswith("context-gateway."), gateway.hostname

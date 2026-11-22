"""charts/logins (T-7496): the s1 automation's cluster logins grant no verb beyond their lists and
nothing cluster-scoped."""
import subprocess
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parent.parent / "charts" / "logins"

# (namespace, apiGroup, resource) -> verbs, resourceNames (None: every name)
WATCH = {
    ("jc-prod", "", "pods"): ({"get", "list"}, None),
    ("jc-prod", "", "pods/log"): ({"get"}, None),
    ("jc-prod", "apps", "deployments"): ({"get", "list"}, None),
    ("jc-prod", "apps", "replicasets"): ({"get", "list"}, None),
    ("jc-prod", "", "configmaps"): ({"get"}, {"jc"}),
    ("jc-prod", "", "services"): ({"get", "list"}, None),
    ("jc-prod", "", "endpoints"): ({"get", "list"}, None),
    ("jc-prod", "postgresql.cnpg.io", "clusters"): ({"get"}, None),
    ("jc-prod", "", "pods/exec"): ({"get", "create"}, {"postgres-cluster-1"}),
    ("dev", "", "pods"): ({"get", "list"}, None),
    ("dev", "", "pods/exec"): ({"get", "create"}, {"prometheus-prometheus-0"}),
}
WRITE = {"get", "list", "watch", "create", "update", "patch", "delete"}
READ = {"get", "list", "watch"}
PROMOTE = {
    **{("jc-prod", "", r): (WRITE, None) for r in ("configmaps", "secrets", "services", "serviceaccounts", "pods")},
    ("jc-prod", "", "persistentvolumeclaims"): (WRITE - {"delete"}, None),
    **{("jc-prod", "", r): (READ, None) for r in ("pods/log", "events", "endpoints")},
    **{("jc-prod", "apps", r): (WRITE, None) for r in ("deployments", "replicasets")},
    ("jc-prod", "batch", "jobs"): (WRITE, None),
    ("jc-prod", "policy", "poddisruptionbudgets"): (WRITE, None),
    **{("jc-prod", "policy.linkerd.io", r): (WRITE, None)
       for r in ("servers", "authorizationpolicies", "meshtlsauthentications")},
    ("jc-dev", "", "pods"): ({"get", "list"}, None),
}


def render(*sets: str) -> list[dict]:
    args = ["helm", "template", "jc-logins", str(CHART), "-n", "jc-prod"]
    for s in sets:
        args += ["--set", s]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def grants(docs: list[dict], account: str) -> dict:
    roles = {(d["metadata"]["namespace"], d["metadata"]["name"]): d for d in docs if d["kind"] == "Role"}
    got = {}
    for b in (d for d in docs if d["kind"] == "RoleBinding"):
        if not any(s["kind"] == "ServiceAccount" and s["name"] == account for s in b["subjects"]):
            continue
        ns = b["metadata"]["namespace"]
        assert b["roleRef"]["kind"] == "Role"
        for rule in roles[(ns, b["roleRef"]["name"])]["rules"]:
            for group in rule["apiGroups"]:
                for resource in rule["resources"]:
                    names = set(rule["resourceNames"]) if "resourceNames" in rule else None
                    assert (ns, group, resource) not in got, (ns, group, resource)
                    got[(ns, group, resource)] = (set(rule["verbs"]), names)
    return got


def test_logins_grant_exactly_their_lists_and_nothing_cluster_scoped():
    docs = render("orgsWatch.prometheusNamespace=dev", "prodPromote.enabled=true", "prodPromote.readNamespace=jc-dev")
    assert not [d for d in docs if d["kind"] in ("ClusterRole", "ClusterRoleBinding")]
    assert grants(docs, "orgs-watch") == WATCH
    assert grants(docs, "prod-promote") == PROMOTE
    for d in docs:
        if d["kind"] == "Role":
            for rule in d["rules"]:
                assert "*" not in rule["verbs"] + rule["resources"] + rule["apiGroups"]
                assert "escalate" not in rule["verbs"] and "bind" not in rule["verbs"]
    tokens = {d["metadata"]["annotations"]["kubernetes.io/service-account.name"]
              for d in docs if d["kind"] == "Secret"}
    assert tokens == {"orgs-watch", "prod-promote"}
    assert all("data" not in d and "stringData" not in d for d in docs if d["kind"] == "Secret")


def test_the_watch_alone_by_default_and_no_prometheus_grant_without_its_namespace():
    docs = render()
    assert {d["metadata"]["name"] for d in docs if d["kind"] == "ServiceAccount"} == {"orgs-watch"}
    assert {d["metadata"]["namespace"] for d in docs} == {"jc-prod"}

"""charts/logins (T-7496): the orgs watch's login grants no verb beyond its list, nothing
cluster-scoped, and no write or exec outside the Prometheus pod."""
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
    ("dev", "", "pods"): ({"get", "list"}, None),
    ("dev", "", "pods/exec"): ({"get", "create"}, {"prometheus-prometheus-0"}),
}
READ = {"get", "list", "watch"}


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


def test_the_watch_reads_only_and_execs_only_into_prometheus():
    docs = render("orgsWatch.prometheusNamespace=dev")
    assert not [d for d in docs if d["kind"] in ("ClusterRole", "ClusterRoleBinding")]
    got = grants(docs, "orgs-watch")
    assert got == WATCH
    # Read-only: every grant but the one Prometheus exec is read verbs, and no exec, attach,
    # port-forward, proxy or Secret anywhere else (T-7496 review).
    for (ns, group, resource), (verbs, names) in got.items():
        if resource == "pods/exec":
            assert (ns, names) == ("dev", {"prometheus-prometheus-0"})
        else:
            assert verbs <= READ, (ns, resource, verbs)
            assert resource not in ("secrets", "pods/attach", "pods/portforward", "services/proxy")
    for d in docs:
        if d["kind"] == "Role":
            for rule in d["rules"]:
                assert "*" not in rule["verbs"] + rule["resources"] + rule["apiGroups"]
    tokens = [d for d in docs if d["kind"] == "Secret"]
    assert [t["metadata"]["annotations"]["kubernetes.io/service-account.name"] for t in tokens] == ["orgs-watch"]
    assert all("data" not in t and "stringData" not in t for t in tokens)


def test_no_prometheus_grant_without_its_namespace():
    docs = render()
    assert {d["metadata"]["name"] for d in docs if d["kind"] == "ServiceAccount"} == {"orgs-watch"}
    assert {d["metadata"]["namespace"] for d in docs} == {"jc-prod"}

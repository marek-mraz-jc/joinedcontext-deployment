"""jc-assistant's crawl worker, judged as the deployment renders it (T-3052, Architecture/22 §1).

No environment lists the component until a platform image that carries the binary is pinned,
so the tests render dev with it added. What is coupled across files: the database and the role
the worker connects as, the forge token git-sync reads and the bootstrap that mints it into the
worker's namespace and restarts the worker, and the NetworkPolicies that let the worker reach
its database, the forge, DNS and public web addresses only."""

import pytest

PRIVATE = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8", "100.64.0.0/10"}


def add_assistant(tree):
    path = tree / "deployment/environments/dev/global.yaml.gotmpl"
    text = path.read_text()
    assert "\n  - functions\n" in text
    path.write_text(text.replace("\n  - functions\n", "\n  - functions\n  - assistant\n", 1))


RENDERED: list = []


@pytest.fixture
def docs(rendered_variant):
    # rendered_variant is function-scoped; the one render serves both tests.
    if not RENDERED:
        RENDERED.append(rendered_variant("dev", add_assistant))
    return RENDERED[0]


def one(docs, kind, name):
    return next(d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name)


def env_of(container):
    return {e["name"]: e.get("value") for e in container.get("env", [])}


def test_the_worker_rendered_with_its_database_checkout_and_network(docs):
    pod = one(docs, "Deployment", "jc-assistant")["spec"]["template"]["spec"]
    worker = next(c for c in pod["containers"] if c["name"] != "git-sync" and c["name"] != "checkouts")
    assert worker["command"] == ["/usr/local/bin/jc-assistant"]
    assert "@sha256:" in worker["image"]
    env = env_of(worker)
    assert env["JC_ASSISTANT_DATABASE_URL"] == (
        "postgresql://assistant:$(PGPASSWORD)@postgres-cluster-rw.dev.svc.cluster.local:5432/assistant"
    )
    assert env["JC_ASSISTANT_REPO_DIR"] == "/repo/current"
    assert env["JC_ASSISTANT_ORG_DOMAIN"]
    password = next(e for e in worker["env"] if e["name"] == "PGPASSWORD")
    assert password["valueFrom"]["secretKeyRef"] == {"name": "db-assistant", "key": "password"}
    assert worker["securityContext"]["readOnlyRootFilesystem"] is True
    assert pod["automountServiceAccountToken"] is False
    assert worker["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert worker["resources"]["limits"]["memory"] == "1Gi"
    sidecars = {c["name"] for c in pod["containers"]} - {worker["name"]}
    assert "git-sync" in sidecars
    tokens = [v["secret"]["secretName"] for v in pod["volumes"] if "secret" in v]
    assert set(tokens) <= {"gitea-token-gateway"}, "the read-only forge token, nothing else"

    # Its own database, owned by its own role, with the vector extension the role job creates.
    database = one(docs, "Database", "assistant")["spec"]
    assert database["owner"] == "assistant"
    assert {"ensure": "present", "name": "vector"} in database["extensions"]

    # The forge bootstrap may restart the worker when it mints the token again.
    restartable = {
        name
        for d in docs if d.get("kind") == "Role"
        for rule in d.get("rules", []) if "deployments" in rule.get("resources", [])
        for name in rule.get("resourceNames", [])
    }
    assert "jc-assistant" in restartable


def test_the_worker_reaches_its_database_the_forge_dns_and_public_addresses_only(docs):
    policy = one(docs, "NetworkPolicy", "assistant-worker")
    assert policy["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "assistant-worker"}
    assert "ingress" not in policy["spec"] or policy["spec"]["ingress"] in (None, [])
    assert set(policy["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    web = [r for r in policy["spec"]["egress"] if "ipBlock" in r["to"][0]]
    (rule,) = web
    block = rule["to"][0]["ipBlock"]
    assert block["cidr"] == "0.0.0.0/0"
    assert set(block["except"]) == PRIVATE
    assert sorted(p["port"] for p in rule["ports"]) == [80, 443]
    peers = sorted(
        (tuple(sorted(r["to"][0]["podSelector"]["matchLabels"].items())), tuple(p["port"] for p in r["ports"]))
        for r in policy["spec"]["egress"] if "podSelector" in r["to"][0]
    )
    assert peers == sorted([
        ((("cnpg.io/cluster", "postgres-cluster"),), (5432,)),
        ((("app.kubernetes.io/instance", "gitea-forge"), ("app.kubernetes.io/name", "gitea")), (3000,)),
        ((("k8s-app", "kube-dns"),), (53, 53)),
    ])
    for name, port in (("postgres-from-assistant", 5432), ("gitea-from-assistant", 3000)):
        (inbound,) = one(docs, "NetworkPolicy", name)["spec"]["ingress"]
        assert [f["podSelector"]["matchLabels"] for f in inbound["from"]] == [{"app.kubernetes.io/name": "assistant-worker"}]
        assert [p["port"] for p in inbound["ports"]] == [port]

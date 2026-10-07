"""The pipelines' token service (PL-19, T-1508, joinedcontext-docs Architecture/12 §3).

One pod beside the runner mints each pipeline's token from its own Kubernetes ServiceAccount.
These read the rendered manifests: off by default, and when on, the service holds one verb on
one subresource, reaches the Kubernetes API, and admits the runner alone, while the runner
itself still reaches no Kubernetes API.
"""

import pytest

pytestmark = pytest.mark.xdist_group("render-pipeline-tokens")


def one(docs, kind, name):
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert len(found) == 1, f"{kind}/{name}: {len(found)}"
    return found[0]


def ports(rule):
    return {p["port"] for p in rule.get("ports", [])}


def test_the_service_is_off_by_default_and_the_runner_still_reaches_no_kubernetes_api(rendered):
    docs = rendered("local")
    assert not [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "pipeline-tokens"]
    runner = one(docs, "NetworkPolicy", "pipeline-runner")["spec"]
    assert all(6443 not in ports(rule) for rule in runner["egress"]), "the runner never reaches the Kubernetes API"
    tokens_rule = [rule for rule in runner["egress"] if 4180 in ports(rule)]
    assert len(tokens_rule) == 1, "the runner reaches the token service on 4180"
    env = {e["name"]: e.get("value") for c in one(docs, "Deployment", "pipeline-runner")["spec"]["template"]["spec"]["containers"]
           for e in c.get("env", [])}
    assert env["JC_PIPELINE_TOKEN_URL"].startswith("http://pipeline-tokens.") and env["JC_PIPELINE_TOKEN_URL"].endswith(":4180/token")


def test_the_token_services_policy_admits_the_runner_alone_and_reaches_the_api(rendered):
    policy = one(rendered("local"), "NetworkPolicy", "pipeline-tokens")["spec"]
    (ingress,) = policy["ingress"]
    assert ports(ingress) == {4180}
    assert [peer["podSelector"]["matchLabels"] for peer in ingress["from"]] == [
        {"app.kubernetes.io/name": "pipeline-runner-runner"}]
    assert all("namespaceSelector" in peer for peer in ingress["from"])
    assert any(6443 in ports(rule) for rule in policy["egress"])


def enable_tokens(tree):
    path = tree / "components/pipeline-runner/default-environment.yaml.gotmpl"
    text = path.read_text()
    for part in ("tokens", "identities"):
        assert f"  {part}:\n    enabled: false\n" in text, part
        text = text.replace(f"  {part}:\n    enabled: false\n", f"  {part}:\n    enabled: true\n")
    path.write_text(text)


def test_switched_on_the_service_mints_only_in_the_pipelines_namespace_with_its_own_token(rendered_variant):
    docs = rendered_variant("dev", enable_tokens)
    deployment_doc = one(docs, "Deployment", "pipeline-tokens")
    tokens_namespace = deployment_doc["metadata"]["namespace"]
    deployment = deployment_doc["spec"]["template"]["spec"]
    (container,) = [c for c in deployment["containers"] if c["name"] != "linkerd-proxy"]
    assert container["command"] == ["/usr/local/bin/jc-token-sidecar"]
    assert deployment["automountServiceAccountToken"] is False
    mounts = {m["mountPath"]: m for m in container["volumeMounts"]}
    assert mounts["/var/run/secrets/kubernetes.io/serviceaccount"]["readOnly"] is True
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert env["JC_SIDECAR_LISTEN"] == "0.0.0.0:4180", "the service is called across the pod network"
    assert env["JC_TOKEN_URL"].startswith(env["JC_TOKEN_AUDIENCE"] + "/protocol/openid-connect/token")

    # The one grant: create serviceaccounts/token in the pipelines' own namespace, which is not
    # the namespace of the runner or of the service, so no workload's ServiceAccount is in reach.
    identities = env["JC_PIPELINE_NAMESPACE"]
    runner_namespace = one(docs, "Deployment", "pipeline-runner")["metadata"]["namespace"]
    assert identities not in {tokens_namespace, runner_namespace}
    roles = [d for d in docs if d.get("kind") == "Role" and d["metadata"]["name"] == "pipeline-tokens"]
    assert [r["metadata"]["namespace"] for r in roles] == [identities]
    assert roles[0]["rules"] == [{"apiGroups": [""], "resources": ["serviceaccounts/token"], "verbs": ["create"]}]
    binding = one(docs, "RoleBinding", "pipeline-tokens")
    assert binding["metadata"]["namespace"] == identities
    assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "pipeline-tokens", "namespace": tokens_namespace}]

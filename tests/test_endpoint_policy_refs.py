"""Every seed Endpoint names the Policies it binds (P-18, T-6735).

An Endpoint without `policyRefs` evaluates every Policy of its space, so a Policy written for one
Endpoint opens every other Endpoint of that space. scripts/policy-refs-migrate.py wrote the
Policies each seed Endpoint bound into it (a space a Pipeline writes or reads waits for T-6736);
these tests keep the seed that way and keep each reference binding a Policy, as the gateway
resolves it (`store.rs` `bound_policies`).
"""

import importlib.util
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("policy_refs_migrate", ROOT / "scripts/policy-refs-migrate.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


def seed():
    return list(migrate.documents(sorted(migrate.SEED.rglob("*.yaml"))))


def test_every_seed_endpoint_names_its_policies():
    todo, _ = migrate.plan(seed())
    assert not todo, (
        "Endpoints without policyRefs bind every Policy of their space; run scripts/policy-refs-migrate.py --write: "
        + ", ".join(f"{path.relative_to(ROOT)} {name}" for path, name, _ in todo)
    )


def test_each_reference_binds_a_policy_of_its_space():
    docs = seed()
    by_kind = {}
    for _, doc in docs:
        by_kind.setdefault(doc["kind"], []).append(doc)
    orgs = {d["metadata"]["name"]: (d.get("spec") or {}).get("domain") for d in by_kind["Organization"]}
    domains = {}
    for d in by_kind["Project"]:
        s = d.get("spec") or {}
        domains[d["metadata"]["name"]] = {s.get("domain"), orgs.get(migrate.ref_name(s.get("organizationRef")))} - {None}
    segments = {
        (d["metadata"].get("namespace"), d["metadata"]["name"]): (d.get("spec") or {}).get("urnSegment")
        for d in by_kind["ContextSpace"]
    }
    policies = {
        (d["metadata"].get("namespace"), migrate.ref_name(d["spec"].get("contextSpaceRef")), d["metadata"]["name"].split("#")[0])
        for d in by_kind["Policy"]
    }
    unbound = []
    for d in by_kind["Endpoint"]:
        project, s = d["metadata"].get("namespace"), d.get("spec") or {}
        space = migrate.ref_name(s.get("contextSpaceRef"))
        segment = segments.get((project, space)) or f"{project}-{space}"
        for ref in s.get("policyRefs") or [s.get("policyRef")] * bool(s.get("policyRef")):
            _, _, kind, domain, ref_segment, local_id = ref.split(":")
            known = domains.get(project) or {migrate.INSTALLATION_DOMAIN}
            if kind != "Policy" or domain not in known or ref_segment != segment or (project, space, local_id) not in policies:
                unbound.append(f"{d['metadata']['name']}: {ref}")
    assert not unbound, "references that bind no Policy of the Endpoint's space: " + ", ".join(unbound)


FIXTURE = """
apiVersion: joinedcontext.com/v1alpha1
kind: Endpoint
metadata:
  name: air-public
  namespace: city
spec:
  contextSpaceRef: air
  audience: public
"""


def test_migration_writes_exactly_todays_bound_set():
    path = Path("city/endpoint.yaml")
    docs = [
        (Path("org.yaml"), {"kind": "Organization", "metadata": {"name": "city"}, "spec": {"domain": "city.sk"}}),
        (Path("p.yaml"), {"kind": "Project", "metadata": {"name": "city"}, "spec": {"organizationRef": "city"}}),
        (Path("s.yaml"), {"kind": "ContextSpace", "metadata": {"name": "air", "namespace": "city"}, "spec": {}}),
        (Path("a.yaml"), {"kind": "Policy", "metadata": {"name": "read", "namespace": "city"}, "spec": {"contextSpaceRef": "air"}}),
        (Path("b.yaml"), {"kind": "Policy", "metadata": {"name": "write", "namespace": "city"}, "spec": {"contextSpaceRef": {"kind": "ContextSpace", "name": "air"}}}),
        (Path("c.yaml"), {"kind": "Policy", "metadata": {"name": "other", "namespace": "city"}, "spec": {"contextSpaceRef": "noise"}}),
        (Path("d.yaml"), {"kind": "Policy", "metadata": {"name": "read", "namespace": "town"}, "spec": {"contextSpaceRef": "air"}}),
        (Path("app.yaml"), {"kind": "App", "metadata": {"name": "map", "namespace": "city"}, "spec": {}}),
        (Path("e1.yaml"), {"kind": "Endpoint", "metadata": {"name": "app-map", "namespace": "city"}, "spec": {"contextSpaceRef": "air"}}),
        (Path("e2.yaml"), {"kind": "Endpoint", "metadata": {"name": "empty", "namespace": "city"}, "spec": {"contextSpaceRef": "bare"}}),
        (Path("e3.yaml"), {"kind": "Endpoint", "metadata": {"name": "named", "namespace": "city"}, "spec": {"contextSpaceRef": "air", "policyRef": "urn:ngsi-ld:Policy:city.sk:city-air:read"}}),
        (Path("e4.yaml"), {"kind": "Endpoint", "metadata": {"name": "feed-door", "namespace": "city"}, "spec": {"contextSpaceRef": "feed"}}),
        (Path("f.yaml"), {"kind": "Policy", "metadata": {"name": "feed-read", "namespace": "city"}, "spec": {"contextSpaceRef": "feed"}}),
        (Path("g.yaml"), {"kind": "Pipeline", "metadata": {"name": "ingest", "namespace": "city"}, "spec": {"targetEndpoint": "urn:ngsi-ld:Endpoint:city.sk:city-feed:feed-door"}}),
        (path, yaml.safe_load(FIXTURE)),
    ]
    todo, skipped = migrate.plan(docs)
    refs = ["urn:ngsi-ld:Policy:city.sk:city-air:read", "urn:ngsi-ld:Policy:city.sk:city-air:write"]
    assert todo == [(path, "air-public", refs)]
    # feed-door's space takes the derived write of Pipeline ingest, which binds only a door naming no Policy (PL-20).
    assert [name for _, name, _ in skipped] == ["app-map", "empty", "feed-door"]

    written = yaml.safe_load(migrate.write_refs(textwrap.dedent(FIXTURE), "air-public", refs))
    assert written["spec"]["policyRefs"] == refs
    assert written["spec"]["contextSpaceRef"] == "air" and written["spec"]["audience"] == "public"

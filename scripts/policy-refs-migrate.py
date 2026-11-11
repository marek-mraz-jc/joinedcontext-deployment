#!/usr/bin/env python3
"""Writes into every seed Endpoint without Policy references the Policies it binds today (P-18, T-6735).

An Endpoint without `policyRefs` (or `policyRef`) evaluates every Policy of its space, so a
Policy written for one Endpoint also opens every other Endpoint of that space. Before the
platform binds nothing for such an Endpoint (deny by default), each one has to name the Policies
it serves. This script writes them: for each Endpoint without references it lists every Policy
of the Endpoint's space as the gateway binds it today (`context-gateway/src/store.rs`
`endpoints_with_models`), so the migrated seed serves exactly what it serves now.

Left alone, each reported:
- an App's generated Endpoint (`app-{name}` beside an App `{name}` of its project): it binds the
  App's own grants and the space's prohibitions (AP-139), a rule of its own;
- an Endpoint whose space holds no Policy: it grants nothing today, and an empty list is refused
  (ADR-N-057);
- an Endpoint of a space a Pipeline writes or reads through an Endpoint: each Pipeline brings
  Policies derived with it, `pl-{pipeline}-w-{n}` and `-r-{n}` (PL-20, `jc_core::kinds::pipeline_identity`),
  which bind only an Endpoint naming no references; naming the manifest Policies alone would
  answer every Pipeline write 404. Those Endpoints wait until a Pipeline's derived grants bind the
  Endpoint it names (T-6736).

A reference is `urn:ngsi-ld:Policy:{domain}:{segment}:{name}`: the Project's `spec.domain`, else
its Organization's, else the installation's (`--installation-domain`); the space's
`spec.urnSegment`, else `{project}-{space}` (PF-84).

    scripts/policy-refs-migrate.py            # lists what it would write, exit 1 when anything
    scripts/policy-refs-migrate.py --write    # writes it
"""

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed"
# The installation's domain on dev and prod: the domain the seeds' existing references to a
# Policy of a Project without a domain carry (slovensko).
INSTALLATION_DOMAIN = "joinedcontext.com"
COMMENT = (
    "  # The Policies this Endpoint evaluates; a Policy added to the space later binds only once named here (P-18).\n"
)


def ref_name(value):
    """A reference written `name` or `{kind, name}`."""
    return value.get("name") if isinstance(value, dict) else value


def documents(paths):
    """(path, manifest) of every joinedcontext manifest in the files."""
    for path in paths:
        try:
            docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if isinstance(doc, dict) and doc.get("kind") and isinstance(doc.get("metadata"), dict):
                yield path, doc


def plan(manifests, installation_domain=INSTALLATION_DOMAIN):
    """(path, endpoint name, [refs]) for each Endpoint to migrate, and (path, name, reason) for each left alone."""
    by_kind = {}
    for path, doc in manifests:
        by_kind.setdefault(doc["kind"], []).append((path, doc))

    def spec(doc):
        return doc.get("spec") or {}

    org_domains = {d["metadata"]["name"]: spec(d).get("domain") for _, d in by_kind.get("Organization", [])}
    project_domains = {}
    for _, d in by_kind.get("Project", []):
        domain = spec(d).get("domain") or org_domains.get(ref_name(spec(d).get("organizationRef")))
        project_domains[d["metadata"]["name"]] = domain
    segments = {
        (d["metadata"].get("namespace"), d["metadata"]["name"]): spec(d).get("urnSegment")
        for _, d in by_kind.get("ContextSpace", [])
    }
    apps = {(d["metadata"].get("namespace"), d["metadata"]["name"]) for _, d in by_kind.get("App", [])}
    policies = {}
    for _, d in by_kind.get("Policy", []):
        key = (d["metadata"].get("namespace"), ref_name(spec(d).get("contextSpaceRef")))
        policies.setdefault(key, set()).add(d["metadata"]["name"].split("#", 1)[0])

    endpoint_spaces = {
        (d["metadata"].get("namespace"), d["metadata"]["name"]): ref_name(spec(d).get("contextSpaceRef"))
        for _, d in by_kind.get("Endpoint", [])
    }
    piped = set()
    for _, d in by_kind.get("Pipeline", []):
        project, s = d["metadata"].get("namespace"), spec(d)
        outputs = [s, *(s.get("outputs") or [])]
        sources = [s.get("source") or {}, *(s.get("sources") or [])]
        names = [o["targetEndpoint"].rsplit(":", 1)[-1] for o in outputs if isinstance(o, dict) and o.get("targetEndpoint")]
        names += [ref_name(x["endpointRef"]) for x in sources if isinstance(x, dict) and x.get("endpointRef")]
        piped |= {(project, endpoint_spaces.get((project, n))) for n in names}

    migrate, skipped = [], []
    for path, d in by_kind.get("Endpoint", []):
        project, name, s = d["metadata"].get("namespace"), d["metadata"]["name"], spec(d)
        if s.get("policyRefs") or s.get("policyRef"):
            continue
        space = ref_name(s.get("contextSpaceRef"))
        if name.startswith("app-") and (project, name[len("app-"):]) in apps:
            skipped.append((path, name, "App Endpoint: binds the App's own grants (AP-139)"))
            continue
        if (project, space) in piped:
            skipped.append((path, name, f"space {space} carries Pipeline grants derived per Pipeline (PL-20): T-6736"))
            continue
        names = sorted(policies.get((project, space), ()))
        if not names:
            skipped.append((path, name, f"space {space} holds no Policy: it grants nothing today"))
            continue
        domain = project_domains.get(project) or installation_domain
        segment = segments.get((project, space)) or f"{project}-{space}"
        migrate.append((path, name, [f"urn:ngsi-ld:Policy:{domain}:{segment}:{n}" for n in names]))
    return migrate, skipped


def write_refs(text, name, refs):
    """The file's text with `policyRefs` written after the named Endpoint's `contextSpaceRef` line."""
    lines = text.splitlines(keepends=True)
    in_endpoint, in_spec = False, False
    for i, line in enumerate(lines):
        if line.startswith("kind:"):
            in_endpoint, in_spec = line.strip() == "kind: Endpoint", False
        elif in_endpoint and line.rstrip() == f"  name: {name}":
            in_endpoint = "named"
        elif in_endpoint == "named" and line.rstrip() == "spec:":
            in_spec = True
        elif in_spec and line.startswith("  contextSpaceRef:"):
            if line.rstrip().endswith(":"):
                raise ValueError(f"Endpoint {name}: write contextSpaceRef on one line to migrate it")
            block = COMMENT + "  policyRefs:\n" + "".join(f"    - {ref}\n" for ref in refs)
            return "".join(lines[: i + 1]) + block + "".join(lines[i + 1 :])
    raise ValueError(f"no `  contextSpaceRef:` line under Endpoint {name}'s spec")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--write", action="store_true", help="write the references into the seed files")
    parser.add_argument("--seed", type=Path, default=SEED, help="seed root (default: %(default)s)")
    parser.add_argument("--installation-domain", default=INSTALLATION_DOMAIN)
    args = parser.parse_args(argv)
    migrate, skipped = plan(documents(sorted(args.seed.rglob("*.yaml"))), args.installation_domain)
    for path, name, reason in skipped:
        print(f"left {path.relative_to(args.seed)} {name}: {reason}")
    for path, name, refs in migrate:
        print(f"{'wrote' if args.write else 'would write'} {path.relative_to(args.seed)} {name}: {len(refs)} Policies")
        if args.write:
            path.write_text(write_refs(path.read_text(encoding="utf-8"), name, refs), encoding="utf-8")
    return 0 if args.write or not migrate else 1


if __name__ == "__main__":
    sys.exit(main())

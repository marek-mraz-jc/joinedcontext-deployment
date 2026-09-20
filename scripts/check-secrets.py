#!/usr/bin/env python3
"""Verify the generated bootstrap Secrets in a rendered manifest (T-0018, OPS-37).

    scripts/check-secrets.py <rendered.yaml> [components-dir]

Every Secret the in-cluster generator produces must carry `helm.sh/resource-policy: keep`
(so a `helm uninstall` cannot take the credentials with it) and every generated value must
be at least 32 characters long, which is what the component's own `secrets.yaml` declares.
The check reads those declarations rather than trusting the render, so shortening a
password in a component file fails here instead of quietly weakening a credential.
"""

import base64
import sys
from pathlib import Path

import yaml

MIN_LENGTH = 32
# Confidential Keycloak client secrets are not declared in any component `secrets.yaml`;
# defaults/environment/secrets.yaml.gotmpl derives them from `keycloak-clients.yaml`.
DERIVED_PREFIX = "keycloak-client-"
DERIVED_KEYS = {"client-secret": 32}
# The demo realm logins are derived the same way, from `components/keycloak/demo-users.yaml`
# (development profile only), so their declaration is read from that file rather than from a
# component `secrets.yaml`. The names are read, not matched by prefix: a generated
# `keycloak-user-*` Secret for a user that file does not name still fails.
DEMO_USER_KEYS = {"password": 32}


def declarations(components_dir: Path) -> dict[str, dict[str, int]]:
    """secret name -> {key: declared length} for every generated key."""
    out: dict[str, dict[str, int]] = {}
    for path in sorted(components_dir.glob("*/secrets.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for parts in doc.values():
            for secrets in parts.values():
                for name, keys in secrets.items():
                    for key, spec in keys.items():
                        if key == "componentNamespaces" or not isinstance(spec, dict):
                            continue
                        if spec.get("generate") and "length" in spec:
                            out.setdefault(name, {})[key] = int(spec["length"])
    return out


def demo_user_declarations(components_dir: Path) -> dict[str, dict[str, int]]:
    """secret name -> {key: declared length} for the demo realm logins."""
    path = components_dir / "keycloak" / "demo-users.yaml"
    if not path.exists():
        return {}
    users = yaml.safe_load(path.read_text()) or {}
    return {f"keycloak-user-{name.replace('.', '-')}": dict(DEMO_USER_KEYS) for name in users}


def main() -> int:
    rendered = Path(sys.argv[1])
    components = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("components")
    declared = declarations(components) | demo_user_declarations(components)

    docs = [d for d in yaml.safe_load_all(rendered.read_text()) if isinstance(d, dict)]
    generated = [
        d for d in docs
        if d.get("kind") == "Secret"
        and (d.get("metadata", {}).get("annotations") or {}).get("helm.sh/resource-policy") == "keep"
    ]

    problems: list[str] = []
    checked = 0
    for secret in generated:
        meta = secret["metadata"]
        where = f"{meta.get('namespace', '-')}/{meta['name']}"
        expected = declared.get(meta["name"])
        if expected is None and meta["name"].startswith(DERIVED_PREFIX):
            expected = DERIVED_KEYS
        if expected is None:
            problems.append(f"{where}: generated Secret with no declaration in any components/*/secrets.yaml")
            continue
        data = secret.get("data") or {}
        for key, length in expected.items():
            if key not in data:
                problems.append(f"{where}: declared key '{key}' is missing from the rendered Secret")
                continue
            value = base64.b64decode(data[key])
            checked += 1
            if length < MIN_LENGTH:
                problems.append(f"{where}: key '{key}' is declared {length} characters, below the {MIN_LENGTH} minimum")
            if len(value) != length:
                problems.append(f"{where}: key '{key}' decodes to {len(value)} characters, declared {length}")

    if not generated:
        problems.append(f"{rendered}: no generated Secret found — the secrets component did not render")

    for line in problems:
        print(f"FAIL {line}")
    print(f"{len(generated)} generated Secret(s), {checked} value(s) checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

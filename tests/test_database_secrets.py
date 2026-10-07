"""Every database a component declares has its password generated (T-3189).

`databases.yaml` names the Secret a database's role reads its password from; only a
`secrets.yaml` entry of the same component makes `components/secrets` generate it. jc-assistant
declared `db-assistant` without one, and its pod waited on a Secret nothing creates.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def managed(component: Path) -> set[str]:
    path = component / "secrets.yaml"
    if not path.exists():
        return set()
    names = set()
    for parts in (yaml.safe_load(path.read_text()) or {}).values():
        for secrets in (parts or {}).values():
            names.update(secrets or {})
    return names


def test_every_declared_database_secret_is_generated_by_its_component():
    missing = []
    for databases in sorted(ROOT.glob("components/*/databases.yaml")):
        component = databases.parent
        for name, db in (yaml.safe_load(databases.read_text()) or {}).items():
            secret = (db or {}).get("secret") or {}
            if secret.get("generate") and secret.get("name") not in managed(component):
                missing.append(f"{component.name}/{name}: {secret.get('name')}")
    assert not missing, f"declared but never generated: {missing}"

"""T-0018: bootstrap secret generation and SOPS-encrypted environment secrets."""

import base64
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHECK = PROJECT_ROOT / "scripts" / "check-secrets.py"
GENERATOR_CHART = PROJECT_ROOT / "components" / "secrets" / "charts" / "secrets-generator"

requires_sops = pytest.mark.skipif(
    not (shutil.which("sops") and shutil.which("age-keygen") and shutil.which("helmfile")),
    reason="sops, age-keygen and helmfile are needed for the SOPS round trip",
)


def check(rendered: str, components: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess:
    """Run the verification script against a throwaway render + component tree."""
    manifest = tmp_path / "rendered.yaml"
    manifest.write_text(rendered)
    comp_dir = tmp_path / "components"
    for component, body in components.items():
        (comp_dir / component).mkdir(parents=True, exist_ok=True)
        (comp_dir / component / "secrets.yaml").write_text(body)
    return subprocess.run(
        ["python3", str(CHECK), str(manifest), str(comp_dir)],
        capture_output=True,
        text=True,
    )


def secret_manifest(name: str, keys: dict[str, str], keep: bool = True) -> str:
    data = {k: base64.b64encode(v.encode()).decode() for k, v in keys.items()}
    doc = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": name,
            "namespace": "local",
            "annotations": {"helm.sh/resource-policy": "keep"} if keep else {},
        },
        "data": data,
    }
    return yaml.safe_dump(doc)


DECLARATION = textwrap.dedent(
    """\
    ---
    demo:
      part:
        db-demo:
          username: 'demo'
          password:
            length: 32
            generate: true
          componentNamespaces:
            - demo
    """
)


def test_declared_and_rendered_secret_passes(tmp_path):
    result = check(secret_manifest("db-demo", {"password": "a" * 32}), {"demo": DECLARATION}, tmp_path)
    assert result.returncode == 0, result.stdout


def test_short_declaration_is_refused(tmp_path):
    """A component may not weaken a credential by declaring fewer than 32 characters."""
    weak = DECLARATION.replace("length: 32", "length: 16")
    result = check(secret_manifest("db-demo", {"password": "a" * 16}), {"demo": weak}, tmp_path)
    assert result.returncode == 1
    assert "below the 32 minimum" in result.stdout


def test_rendered_value_shorter_than_declared_is_refused(tmp_path):
    result = check(secret_manifest("db-demo", {"password": "a" * 8}), {"demo": DECLARATION}, tmp_path)
    assert result.returncode == 1
    assert "decodes to 8 characters, declared 32" in result.stdout


def test_undeclared_generated_secret_is_refused(tmp_path):
    """A Secret nobody declared is a credential nobody reviews."""
    result = check(secret_manifest("mystery", {"password": "a" * 32}), {"demo": DECLARATION}, tmp_path)
    assert result.returncode == 1
    assert "no declaration" in result.stdout


def demo_users(tmp_path: Path, *names: str) -> None:
    """components/keycloak/demo-users.yaml, the file the password generator reads."""
    keycloak = tmp_path / "components" / "keycloak"
    keycloak.mkdir(parents=True, exist_ok=True)
    (keycloak / "demo-users.yaml").write_text(yaml.safe_dump({n: {"firstName": "Demo"} for n in names}))


def test_demo_user_password_is_declared_by_the_demo_users_file(tmp_path):
    """The generated demo logins are declared in demo-users.yaml, not in a component secrets.yaml."""
    demo_users(tmp_path, "demo.steward")
    result = check(
        secret_manifest("keycloak-user-demo-steward", {"password": "a" * 32}),
        {"demo": DECLARATION},
        tmp_path,
    )
    assert result.returncode == 0, result.stdout


def test_demo_user_password_shorter_than_32_is_refused(tmp_path):
    demo_users(tmp_path, "demo.steward")
    result = check(
        secret_manifest("keycloak-user-demo-steward", {"password": "a" * 8}),
        {"demo": DECLARATION},
        tmp_path,
    )
    assert result.returncode == 1
    assert "decodes to 8 characters, declared 32" in result.stdout


def test_demo_user_secret_for_an_unnamed_user_is_refused(tmp_path):
    """A `keycloak-user-*` Secret nobody named in demo-users.yaml is still undeclared."""
    demo_users(tmp_path, "demo.steward")
    result = check(
        secret_manifest("keycloak-user-someone-else", {"password": "a" * 32}),
        {"demo": DECLARATION},
        tmp_path,
    )
    assert result.returncode == 1
    assert "no declaration" in result.stdout


def test_secret_without_keep_policy_is_not_counted(tmp_path):
    """Without resource-policy: keep a helm uninstall would take the credentials with it."""
    result = check(secret_manifest("db-demo", {"password": "a" * 32}, keep=False), {"demo": DECLARATION}, tmp_path)
    assert result.returncode == 1
    assert "the secrets component did not render" in result.stdout


@requires_sops
def test_sops_encrypted_value_reaches_the_generated_secret(tmp_path):
    """An operator-supplied credential travels `ref+sops://` -> helmfile -> Secret.

    helmfile resolves `ref+sops://` itself (vals), so no helm plugin is involved and the
    plaintext exists only in memory: what the environment file holds is a named reference,
    which is exactly what ADR-N-012 asks manifests to store.
    """
    key = tmp_path / "age.key"
    subprocess.run(["age-keygen", "-o", str(key)], check=True, capture_output=True)
    recipient = subprocess.run(
        ["age-keygen", "-y", str(key)], check=True, capture_output=True, text=True
    ).stdout.strip()

    plain = tmp_path / "plain.yaml"
    plain.write_text("keycloak:\n  adminPassword: sops-supplied-password-0123456789\n")
    encrypted = tmp_path / "secrets.enc.yaml"
    encrypted.write_text(
        subprocess.run(
            ["sops", "--encrypt", "--age", recipient, str(plain)],
            check=True, capture_output=True, text=True,
        ).stdout
    )
    assert "sops-supplied-password" not in encrypted.read_text(), "sops left the value in plaintext"

    helmfile = tmp_path / "helmfile.yaml"
    helmfile.write_text(
        textwrap.dedent(
            f"""\
            releases:
              - name: secrets-keycloak-admin-user
                chart: {GENERATOR_CHART}
                namespace: local
                values:
                  - secrets:
                      - name: keycloak-admin-user
                        namespaces: [local]
                        keys:
                          password: ref+sops://{encrypted}#/keycloak/adminPassword
            """
        )
    )
    env = dict(os.environ, SOPS_AGE_KEY_FILE=str(key))
    out = subprocess.run(
        ["helmfile", "-f", str(helmfile), "template", "--skip-deps"],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )
    assert out.returncode == 0, out.stderr
    docs = [d for d in yaml.safe_load_all(out.stdout) if isinstance(d, dict)]
    secrets = [d for d in docs if d.get("kind") == "Secret"]
    assert len(secrets) == 1, out.stdout
    assert base64.b64decode(secrets[0]["data"]["password"]).decode() == "sops-supplied-password-0123456789"
    assert secrets[0]["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"

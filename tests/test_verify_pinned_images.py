"""T-5564: no apply reaches a cluster with a platform digest our workflows did not sign.

scripts/verify-pinned-images.py runs in `just dev-apply` and `just prod-apply` between the render and
`helmfile sync`. The first test signs one image and leaves another unsigned in a throwaway registry
(a local key pair stands in for the keyless identity; no cluster, no ghcr.io); the second puts a fake
`cosign` on PATH to see which references of a render are verified, and with which identity.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/verify-pinned-images.py"
OWNER = "marek-mraz-jc"


def verify(render: Path, *args, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "dev", "--render", str(render), *args],
        check=False, capture_output=True, text=True, timeout=300, env=env,
    )


def pod(*images: str) -> str:
    containers = "\n".join(f"        - name: c{i}\n          image: {image}" for i, image in enumerate(images))
    return f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: p\nspec:\n  containers:\n{containers}\n"


@pytest.fixture
def registry(tmp_path):
    """A registry:2 on a free localhost port; yields `localhost:<port>`."""
    if shutil.which("docker") is None or shutil.which("cosign") is None:
        pytest.skip("docker and cosign are needed for the throwaway registry")
    cid = subprocess.run(["docker", "run", "-d", "--rm", "-p", "127.0.0.1::5000", "registry:2"],
                         capture_output=True, text=True, check=True).stdout.strip()
    try:
        port = subprocess.run(["docker", "port", cid, "5000"], capture_output=True, text=True,
                              check=True).stdout.split(":")[-1].strip()
        yield f"localhost:{port}"
    finally:
        subprocess.run(["docker", "stop", cid], check=False, capture_output=True)


def push(registry: str, name: str, content: str, workdir: Path) -> str:
    """Push a one-file image; its `repo@digest`."""
    context = workdir / name
    context.mkdir()
    (context / "f").write_text(content)
    (context / "Dockerfile").write_text("FROM scratch\nCOPY f /f\n")
    tag = f"{registry}/{OWNER}/{name}:t"
    subprocess.run(["docker", "build", "-q", "-t", tag, str(context)], capture_output=True, check=True)
    pushed = subprocess.run(["docker", "push", tag], capture_output=True, text=True, check=True).stdout
    digest = re.search(r"digest: (sha256:[0-9a-f]{64})", pushed).group(1)
    return f"{registry}/{OWNER}/{name}@{digest}"


def test_an_unsigned_digest_stops_the_apply(registry, tmp_path):
    env = {**os.environ, "COSIGN_PASSWORD": ""}
    subprocess.run(["cosign", "generate-key-pair", "--output-key-prefix", str(tmp_path / "k")],
                   capture_output=True, check=True, env=env)
    signed = push(registry, "signed", "a", tmp_path)
    unsigned = push(registry, "unsigned", "b", tmp_path)
    subprocess.run(["cosign", "sign", "--key", str(tmp_path / "k.key"), "--use-signing-config=false",
                    "--tlog-upload=false", "--yes", signed], capture_output=True, check=True, env=env)
    key = ["--registry", registry, "--key", str(tmp_path / "k.pub")]

    render = tmp_path / "render.yaml"
    render.write_text(pod(signed))
    ok = verify(render, *key)
    assert ok.returncode == 0, ok.stderr
    assert "1 marek-mraz-jc digest(s) of dev carry our signature" in ok.stdout

    render.write_text(pod(signed, unsigned))
    refused = verify(render, *key)
    assert refused.returncode == 1, refused.stdout
    assert unsigned in refused.stderr
    assert signed not in refused.stderr
    assert "nothing was applied" in refused.stderr


def test_every_platform_image_of_the_render_is_checked(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "cosign.log"
    fake = bin_dir / "cosign"
    # Records each call; refuses the one digest named in REFUSE.
    fake.write_text(f"""#!/bin/sh
echo "$*" >> {log}
case "$*" in *"$REFUSE"*) echo "no matching signatures" >&2; exit 1;; esac
""")
    fake.chmod(0o755)
    d = lambda c: "sha256:" + c * 64
    container = f"ghcr.io/{OWNER}/joinedcontext-portal@{d('1')}"
    init = f"ghcr.io/{OWNER}/joinedcontext-platform/checkouts@{d('2')}"
    in_env = f"ghcr.io/{OWNER}/joinedcontext-platform/model-tools:v1@{d('3')}"
    third_party = f"ghcr.io/cloudnative-pg/postgis@{d('4')}"
    by_tag = f"ghcr.io/{OWNER}/joinedcontext-viz:latest"
    render = tmp_path / "render.yaml"
    render.write_text(
        pod(container, third_party, by_tag)
        + f"---\nkind: Job\nspec:\n  template:\n    spec:\n      initContainers:\n        - image: '{init}'\n"
        + f"---\nkind: ConfigMap\ndata:\n  MODEL_TOOLS_IMAGE: \"{in_env}\"\n"
    )
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "REFUSE": d("2")}

    result = verify(render, env=env)

    calls = log.read_text().splitlines()
    checked = sorted(call.split()[-1] for call in calls)
    assert checked == sorted([container, init, in_env.replace(":v1@", "@")])
    for call in calls:
        assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in call
        assert "--certificate-identity-regexp ^https://github\\.com/marek-mraz-jc/" in call
    assert result.returncode == 1
    assert init in result.stderr and "no matching signatures" in result.stderr
    assert f"{by_tag} is not pinned by digest" in result.stderr
    assert container not in result.stderr


def test_both_applies_verify_before_they_sync():
    justfile = (ROOT / "justfile").read_text()
    for recipe, env in (("dev-apply", "dev"), ("prod-apply", "smartcity")):
        body = justfile.split(f"\n{recipe}:\n", 1)[1].split("\n\n", 1)[0]
        assert body.index(f"verify-pinned-images.py {env}") < body.index(f"-e {env} sync"), recipe

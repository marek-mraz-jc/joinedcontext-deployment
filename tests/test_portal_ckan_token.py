"""T-2469: the Portal's reconciler holds the CKAN API token it publishes with (EP-62, EP-67).

`src/reconciler/ckan.rs` publishes every Endpoint's `publish.ckan` block on each sync and resolves
the token from the CkanInstance's `apiTokenRef`: the variable it names, `CKAN_API_TOKEN`. The Portal
pod had no such variable, so a publication declared in the repository was carried out by nobody and
every dataset on the catalogue had been published by hand with `jcctl publish ckan`.

The token is minted by the catalogue's own post-install Job into Secret `ckan-api-token`, key
`token` (T-0493). A `secretKeyRef` naming a Secret that does not exist yet holds the pod in
CreateContainerConfigError, so the catalogue is deployed before the Portal on an environment that
carries both — the same rule the forge's tokens follow.
"""

import shutil
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENTS = PROJECT_ROOT / ".ci/example-deployments/environments"

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")


def portal_env(docs):
    portal = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "portal")
    return portal["metadata"]["namespace"], portal["spec"]["template"]["spec"]["containers"][0].get("env", [])


@requires_helmfile
def test_the_portal_reads_the_ckan_token_from_the_secret_the_catalogue_mints(rendered):
    """EP-62: `CKAN_API_TOKEN` is a `secretKeyRef` to `ckan-api-token`/`token`, never a value."""
    docs = rendered("dev")
    namespace, env = portal_env(docs)
    token = [e for e in env if e["name"] == "CKAN_API_TOKEN"]
    assert len(token) == 1, "the Portal's reconciler has no CKAN token to publish with"
    assert "value" not in token[0], "a token in the manifest is a token in Git"
    assert token[0]["valueFrom"]["secretKeyRef"] == {"name": "ckan-api-token", "key": "token"}

    # The Job writes into its own namespace (fieldRef metadata.namespace); a secretKeyRef only
    # resolves a Secret of the pod's namespace, so the two have to be the same one.
    job = next(d for d in docs if d.get("kind") == "Job" and d["metadata"]["name"] == "ckan-api-token")
    assert job["metadata"]["namespace"] == namespace


@requires_helmfile
def test_an_environment_without_the_catalogue_asks_the_portal_for_no_token(rendered):
    """Without CKAN there is no Secret, and a reference to it would hold the pod in ConfigError."""
    _, env = portal_env(rendered("local"))
    assert "CKAN_API_TOKEN" not in {e["name"] for e in env}


@pytest.mark.parametrize("env", sorted(p.name for p in ENVIRONMENTS.iterdir() if (p / "global.yaml.gotmpl").is_file()))
def test_the_catalogue_is_deployed_before_the_portal_that_reads_its_token(env):
    """The Secret exists before the pod that references it, so a first apply does not stall."""
    text = (ENVIRONMENTS / env / "global.yaml.gotmpl").read_text()
    own = yaml.safe_load("\n".join(line for line in text.splitlines() if "{{" not in line)) or {}
    # An environment without a list of its own takes the defaults'.
    defaults = yaml.safe_load((PROJECT_ROOT / "defaults/environment/global.yaml").read_text())
    components = own.get("components") or defaults["components"]
    if "ckan" in components and "portal" in components:
        assert components.index("ckan") < components.index("portal")

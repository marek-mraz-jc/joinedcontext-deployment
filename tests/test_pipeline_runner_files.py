"""The resident runner's files volume (PL-50, Architecture/08 §6): a `csv`, `file`, `file_tail`
or `parquet` DataSource names paths under /data/, and /data is a PersistentVolumeClaim of the
runner's own, kept across a redeploy."""

import shutil

import pytest

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def by_name(docs, kind, name):
    return next(d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name)


@requires_helmfile
def test_the_runner_mounts_its_files_claim_at_data(dev):
    claim = by_name(dev, "PersistentVolumeClaim", "pipeline-runner-files")
    assert claim["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert claim["spec"]["resources"]["requests"]["storage"] == "1Gi"
    # A redeploy must not lose a file somebody dropped in.
    assert claim["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"

    pod = by_name(dev, "Deployment", "pipeline-runner")["spec"]["template"]["spec"]
    volume = next(v for v in pod["volumes"] if v["name"] == "files")
    assert volume["persistentVolumeClaim"]["claimName"] == "pipeline-runner-files"
    mount = next(m for m in pod["containers"][0]["volumeMounts"] if m["name"] == "files")
    assert mount["mountPath"] == "/data"
    assert claim["metadata"]["namespace"] == by_name(dev, "Deployment", "pipeline-runner")["metadata"]["namespace"]

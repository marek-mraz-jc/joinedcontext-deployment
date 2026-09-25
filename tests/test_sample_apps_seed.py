"""The sample applications, each in its own repository on the forge (T-2599, AP-75, AP-77, AP-80).

The bootstrap Job creates `helsinki_<name>` with the Portal's token, pushes the application's
tree to `main` in one commit when it differs from what is there, and commits the App manifest
into the project pinned to that commit. These run the Job's real script against the fake forge,
and read the dev render for what the Job is handed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")

ROOT = Path(__file__).resolve().parent.parent
VENDORED = ROOT / "components/gitea/apps"

MANIFEST = """apiVersion: joinedcontext.com/v1alpha1
kind: App
metadata:
  name: helsinki-bikes
  namespace: helsinki
spec:
  kind: static
  source:
    git:
      url: https://example.test/git/joinedcontext/helsinki_helsinki-bikes.git
      ref: main
"""

TREE = {
    "README.md": "# Helsinki city bikes\n",
    "src/App.tsx": "export default function App() { return null; }\n",
    # No newline at the end: the blob id has to be taken over the bytes as they are.
    ".gitea/workflows/build.yml": "on: push",
}


def one(docs, kind, name):
    return next(d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name)


@pytest.fixture(scope="module")
def local(rendered):
    return rendered("local")


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


@pytest.fixture(scope="module")
def script(local):
    return one(local, "Job", "gitea-bootstrap")["spec"]["template"]["spec"]["containers"][0]["args"][0]


def seeded(tmp_path, tree=TREE):
    from test_forge_seed_converges import Forge

    forge = Forge(tmp_path, {})
    app = tmp_path / "apps" / "helsinki-bikes"
    app.mkdir(parents=True)
    for path, text in tree.items():
        (app / path.replace("/", "__")).write_text(text)
    (app / "app.yaml").write_text(MANIFEST)
    return forge, app


def run(forge, script):
    return forge.run(
        script,
        APPS_DIR=str(forge.root / "apps"),
        APPS_PROJECT="helsinki",
        APPS_PUBLIC_BASE="https://joinedcontext.test/git",
    )


def repos(forge):
    import json

    return json.loads(forge.state.read_text())["repos"]


@requires_helmfile
def test_each_app_gets_a_private_repository_holding_its_tree_and_a_manifest_pinned_to_it(script, tmp_path):
    """AP-75, AP-80: the repository is created private under the Portal's naming, holds the tree
    and not the manifest, and the manifest committed into the project names that repository at
    its public clone address and its head commit, never `main`."""
    forge, _ = seeded(tmp_path)
    result = run(forge, script)
    assert result.returncode == 0, result.stderr
    repo = repos(forge)["helsinki_helsinki-bikes"]
    assert repo["private"] is True
    assert repo["files"] == TREE, "the auto-init README is replaced and app.yaml stays out"
    assert len(repo["commits"]) == 1, "the tree goes in as one commit"

    manifest = yaml.safe_load(forge.contents["projects/helsinki/apps/helsinki-bikes/app.yaml"])
    git = manifest["spec"]["source"]["git"]
    assert git["url"] == "https://joinedcontext.test/git/joinedcontext/helsinki_helsinki-bikes.git"
    assert git["ref"] == repo["head"] and len(git["ref"]) == 40
    assert "Authorization: token" not in result.stdout + result.stderr


@requires_helmfile
def test_a_second_run_changes_nothing_and_says_so(script, tmp_path):
    """AP-75: the blob ids match, so no commit and no manifest write; the log says both."""
    forge, _ = seeded(tmp_path)
    assert run(forge, script).returncode == 0
    head = repos(forge)["helsinki_helsinki-bikes"]["head"]
    calls = forge.calls.read_text()

    second = run(forge, script)
    assert second.returncode == 0, second.stderr
    assert repos(forge)["helsinki_helsinki-bikes"]["head"] == head
    assert len(repos(forge)["helsinki_helsinki-bikes"]["commits"]) == 1
    assert "app helsinki-bikes: joinedcontext/helsinki_helsinki-bikes already holds this tree" in second.stdout
    assert f"app helsinki-bikes: projects/helsinki/apps/helsinki-bikes/app.yaml already names {head}" in second.stdout
    written = forge.calls.read_text()[len(calls):]
    assert "POST http://forge.test/api/v1/orgs/joinedcontext/repos" not in written, "never recreated"
    assert "PUT http://forge.test/api/v1/repos/joinedcontext/configuration/contents/projects/helsinki/apps" not in written


@requires_helmfile
def test_a_rerun_keeps_the_build_the_lane_wrote_for_the_same_head(script, tmp_path):
    """T-2633, AP-13a: the Portal rewrote the manifest with status.build; a rerun at the same head
    leaves it, and a new head still moves the manifest. T-2948, AP-80: the new head keeps the
    previous head's build, which serves until the lane proposes the new one; a failed build of
    the new head must not take the App off the air."""
    forge, app = seeded(tmp_path)
    assert run(forge, script).returncode == 0
    path = "projects/helsinki/apps/helsinki-bikes/app.yaml"
    head = repos(forge)["helsinki_helsinki-bikes"]["head"]
    built = yaml.safe_load(forge.contents[path])
    built["status"] = {"build": {"commit": head, "digest": "sha256:" + "a" * 64}}
    state = json.loads(forge.state.read_text())
    state["contents"][path] = yaml.safe_dump(built, sort_keys=False)
    forge.state.write_text(json.dumps(state))

    second = run(forge, script)
    assert second.returncode == 0, second.stderr
    assert f"{path} already names {head} and its build" in second.stdout
    assert yaml.safe_load(forge.contents[path])["status"]["build"]["commit"] == head

    (app / "README.md").write_text("# changed\n")
    third = run(forge, script)
    assert third.returncode == 0, third.stderr
    moved = yaml.safe_load(forge.contents[path])
    new_head = repos(forge)["helsinki_helsinki-bikes"]["head"]
    assert moved["spec"]["source"]["git"]["ref"] == new_head != head
    assert moved["status"] == {"build": {"commit": head, "digest": "sha256:" + "a" * 64}}
    assert f"{path} now names {new_head}, the build of {head} serving until its own" in third.stdout

    # The next run at that head finds the carried build and leaves the file as it is.
    fourth = run(forge, script)
    assert fourth.returncode == 0, fourth.stderr
    assert f"{path} already names {new_head} and its build" in fourth.stdout


@requires_helmfile
def test_a_new_head_of_an_app_that_never_built_carries_no_status(script, tmp_path):
    """T-2948, AP-13a: only a build the lane wrote is carried; the seed never invents one."""
    forge, app = seeded(tmp_path)
    assert run(forge, script).returncode == 0
    path = "projects/helsinki/apps/helsinki-bikes/app.yaml"
    (app / "README.md").write_text("# changed\n")
    second = run(forge, script)
    assert second.returncode == 0, second.stderr
    moved = yaml.safe_load(forge.contents[path])
    assert moved["spec"]["source"]["git"]["ref"] == repos(forge)["helsinki_helsinki-bikes"]["head"]
    assert "status" not in moved


@requires_helmfile
def test_a_changed_and_a_dropped_file_are_one_commit_and_the_manifest_follows(script, tmp_path):
    """AP-80: an edit of the platform's copy reaches the repository as one commit that updates
    and deletes against the blobs there, and the manifest moves to the new head."""
    forge, app = seeded(tmp_path)
    assert run(forge, script).returncode == 0
    (app / "src__App.tsx").write_text("export default function App() { return 'bikes'; }\n")
    (app / "README.md").unlink()

    result = run(forge, script)
    assert result.returncode == 0, result.stderr
    repo = repos(forge)["helsinki_helsinki-bikes"]
    assert "README.md" not in repo["files"]
    assert repo["files"]["src/App.tsx"].endswith("'bikes'; }\n")
    assert len(repo["commits"]) == 2
    assert "committed 2 file(s)" in result.stdout
    manifest = yaml.safe_load(forge.contents["projects/helsinki/apps/helsinki-bikes/app.yaml"])
    assert manifest["spec"]["source"]["git"]["ref"] == repo["head"]


@requires_helmfile
def test_the_blob_id_is_the_one_git_computes(script, tmp_path):
    """AP-75: the Job's `blob_id` is `git hash-object`, or every run would push the whole tree."""
    body = script.split("blob_id() {", 1)[1].split("}\n", 1)[0] + "}"
    sample = tmp_path / "no-newline"
    sample.write_text("on: push")
    ours = subprocess.run(["sh", "-c", f"blob_id() {{{body}\nblob_id {sample}"], capture_output=True, text=True)
    theirs = subprocess.run(["git", "hash-object", str(sample)], capture_output=True, text=True)
    assert ours.stdout.strip() == theirs.stdout.strip() != ""


@requires_helmfile
def test_dev_hands_the_job_every_vendored_file_byte_for_byte(dev):
    """AP-75: each app is one ConfigMap, every file of the vendored tree under its `__` key with
    its exact bytes (a rewritten trailing newline would make every run commit again), all of it
    mounted, and the Job told where a person clones from."""
    index = yaml.safe_load((VENDORED / "index.yaml").read_text())
    job = one(dev, "Job", "gitea-bootstrap")
    volume = next(v for v in job["spec"]["template"]["spec"]["volumes"] if v["name"] == "apps")
    mounted = {
        item["path"] for source in volume["projected"]["sources"] for item in source["configMap"]["items"]
    }
    assert sorted(index["apps"]) == [
        "air-quality", "helsinki-alerts", "helsinki-bikes", "helsinki-events", "hsl-transport",
    ]
    for app, files in index["apps"].items():
        on_disk = sorted(str(p.relative_to(VENDORED / app)) for p in (VENDORED / app).rglob("*") if p.is_file())
        assert sorted(files) == on_disk, f"{app}: index.yaml and the vendored tree disagree"
        data = one(dev, "ConfigMap", f"gitea-bootstrap-app-{app}")["data"]
        for path in files:
            key = path.replace("/", "__")
            assert "__" not in path, f"{app}/{path} would not survive the key encoding"
            assert data[key] == (VENDORED / app / path).read_text(), f"{app}/{path} changed on the way"
            assert f"{app}/{key}" in mounted
        assert len(yaml.safe_dump(data).encode()) < 1024 * 1024, f"{app} does not fit one ConfigMap"
        manifest = (VENDORED / app / "app.yaml").read_text()
        assert manifest.count("\n      url: ") == 1 and manifest.count("\n      ref: ") == 1, (
            f"{app}/app.yaml: the Job rewrites exactly one source.git url and ref"
        )
        assert yaml.safe_load(manifest)["metadata"]["namespace"] == "helsinki"
    env = {e["name"]: e.get("value") for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["APPS_PROJECT"] == "helsinki"
    assert env["APPS_PUBLIC_BASE"].endswith("/git") and env["APPS_PUBLIC_BASE"].startswith("https://")


@requires_helmfile
def test_layout_2_commits_the_manifest_into_the_project_repository(script, tmp_path):
    """CC-85: in layout 2 the project's apps live in its own repository, so the manifest goes
    there at `apps/{name}/app.yaml` and the organization repository gets none."""
    from test_forge_seed_converges import HELSINKI

    forge, _ = seeded(tmp_path)
    forge.state.write_text(forge.state.read_text().replace('"contents": {}', '"contents": {".jc/layout": "2\\n"}'))
    forge.put("projects/helsinki/project.yaml", HELSINKI)
    result = forge.run(
        script,
        LAYOUT="2",
        APPS_DIR=str(forge.root / "apps"),
        APPS_PROJECT="helsinki",
        APPS_PUBLIC_BASE="https://joinedcontext.test/git",
    )
    assert result.returncode == 0, result.stderr
    manifest = yaml.safe_load(repos(forge)["helsinki"]["files"]["apps/helsinki-bikes/app.yaml"])
    assert manifest["spec"]["source"]["git"]["ref"] == repos(forge)["helsinki_helsinki-bikes"]["head"]
    assert not [path for path in forge.contents if "/apps/" in path], forge.contents.keys()


GRANT_ENDPOINT = "projects__helsinki__spaces__helsinki__endpoints__app-helsinki-bikes.yaml"
GRANT_POLICY = "projects__helsinki__policies__app-helsinki-bikes-1.yaml"
GRANTS = {
    f"grants__{GRANT_ENDPOINT}": "kind: Endpoint\nmetadata:\n  name: app-helsinki-bikes\n",
    f"grants__{GRANT_POLICY}": "kind: Policy\nmetadata:\n  name: app-helsinki-bikes-1\n",
}


def with_grants(app):
    for key, text in GRANTS.items():
        (app / key).write_text(text)


@requires_helmfile
def test_the_grants_the_portal_compiled_go_beside_the_manifest_and_never_into_the_app(script, tmp_path):
    """T-2667, CC-61, AP-96: the gateway reads an App's Endpoint and Policies from the
    configuration repository alone, so the seed commits them there, at the paths the Portal's door
    uses, and the application's own repository never sees them."""
    forge, app = seeded(tmp_path)
    with_grants(app)
    result = run(forge, script)
    assert result.returncode == 0, result.stderr
    assert repos(forge)["helsinki_helsinki-bikes"]["files"] == TREE
    for key, text in GRANTS.items():
        path = key.removeprefix("grants__").replace("__", "/")
        assert forge.contents[path] == text, path

    second = run(forge, script)
    assert second.returncode == 0, second.stderr
    assert "projects/helsinki/policies/app-helsinki-bikes-1.yaml is current" in second.stdout


@requires_helmfile
def test_layout_2_commits_the_grants_into_the_project_repository(script, tmp_path):
    """CC-85: in layout 2 a grant's path loses the `projects/{project}/` prefix."""
    from test_forge_seed_converges import HELSINKI

    forge, app = seeded(tmp_path)
    with_grants(app)
    forge.state.write_text(forge.state.read_text().replace('"contents": {}', '"contents": {".jc/layout": "2\\n"}'))
    forge.put("projects/helsinki/project.yaml", HELSINKI)
    result = forge.run(
        script,
        LAYOUT="2",
        APPS_DIR=str(forge.root / "apps"),
        APPS_PROJECT="helsinki",
        APPS_PUBLIC_BASE="https://joinedcontext.test/git",
    )
    assert result.returncode == 0, result.stderr
    files = repos(forge)["helsinki"]["files"]
    assert "spaces/helsinki/endpoints/app-helsinki-bikes.yaml" in files
    assert "policies/app-helsinki-bikes-1.yaml" in files


DEFAULT_GROUP = "users__groups__helsinki-bikes-viewer.yaml"


@requires_helmfile
def test_layout_2_keeps_the_default_groups_in_the_organization_repository(script, tmp_path):
    """AP-118, CC-85: an App's default groups are organization files, so the seed commits them
    to the organization repository in layout 2 too, never into the project's."""
    from test_forge_seed_converges import HELSINKI

    forge, app = seeded(tmp_path)
    with_grants(app)
    group = "kind: Group\nmetadata:\n  name: helsinki-bikes-viewer\n"
    (app / f"grants__{DEFAULT_GROUP}").write_text(group)
    forge.state.write_text(forge.state.read_text().replace('"contents": {}', '"contents": {".jc/layout": "2\\n"}'))
    forge.put("projects/helsinki/project.yaml", HELSINKI)
    result = forge.run(
        script,
        LAYOUT="2",
        APPS_DIR=str(forge.root / "apps"),
        APPS_PROJECT="helsinki",
        APPS_PUBLIC_BASE="https://joinedcontext.test/git",
    )
    assert result.returncode == 0, result.stderr
    assert forge.contents["users/groups/helsinki-bikes-viewer.yaml"] == group
    files = repos(forge)["helsinki"]["files"]
    assert not [path for path in files if path.startswith("users/")], sorted(files)
    assert "policies/app-helsinki-bikes-1.yaml" in files


def test_every_person_a_sample_app_admits_is_admitted_by_its_endpoint():
    """T-2672, EP-14: the gateway admits a person to a `project-list` Endpoint only when a group
    in their token names one of its projects, before it reads any Policy. An App whose `access`
    names a demo person, or whose visibility is `project`, is read through such an Endpoint; a
    demo person in no group of the project gets `403 Access Denied by Policy` on every row, as
    helsinki-alerts did on dev for its own viewer and steward."""
    demo = yaml.safe_load((ROOT / "components/keycloak/demo-users.yaml").read_text())
    checked = 0
    for endpoint_file in sorted(VENDORED.glob("*/grants/projects/*/spaces/*/endpoints/*.yaml")):
        endpoint = yaml.safe_load(endpoint_file.read_text())
        if endpoint["spec"]["audience"] != "project-list":
            continue
        admitted = {endpoint["metadata"]["namespace"], *endpoint["spec"].get("allowedProjects", [])}
        app = yaml.safe_load((endpoint_file.parents[6] / "app.yaml").read_text())
        people = {
            subject["user"].split("@")[0]
            for entry in app["spec"].get("access", [])
            for subject in entry["subjects"]
            if "user" in subject
        }
        # A role given to a default group reaches its members (AP-118).
        for group_file in (endpoint_file.parents[6] / "grants/users/groups").glob("*.yaml"):
            group = yaml.safe_load(group_file.read_text())
            people |= {member["user"].split("@")[0] for member in group["spec"].get("members", [])}
        # The live journeys open every sample as these people (ui/e2e/live/apps-*.spec.ts).
        people |= {"demo.viewer", "demo.steward"}
        for person in sorted(people):
            groups = set(demo[person].get("groups", []))
            assert groups & admitted, (
                f"{endpoint_file.relative_to(VENDORED)} admits {sorted(admitted)}; {person} is in {sorted(groups)}"
            )
            checked += 1
    assert checked, "no sample app reads through a project-list endpoint any more: drop this test"

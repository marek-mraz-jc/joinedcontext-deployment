"""The vendor script refuses a sample the build lane would refuse (T-2635, SDK-12).

helsinki-bikes and helsinki-alerts were vendored with `@playwright/test` in their package.json
and never built on dev. The refusal comes before anything is written, so these runs never touch
the vendored tree.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/vendor-sample-apps.py"
VENDORED = ROOT / "components/gitea/apps"

TEMPLATE = {"dependencies": {"react": "^19.2.8"}, "devDependencies": {"vitest": "^5.0.0"}}


def portal(tmp_path, app_package):
    repo = tmp_path / "portal"
    (repo / "sdk/template").mkdir(parents=True)
    (repo / "sdk/template/package.json").write_text(json.dumps(TEMPLATE))
    (repo / "apps/sample").mkdir(parents=True)
    (repo / "apps/sample/index.html").write_text("<!doctype html>\n")
    if app_package is not None:
        (repo / "apps/sample/package.json").write_text(json.dumps(app_package))
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.test"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "sample"], check=True)
    return repo


def vendor(repo):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(repo), "HEAD", "sample"], capture_output=True, text=True
    )


def test_a_sample_asking_for_a_package_the_template_lacks_is_refused_before_anything_is_written(tmp_path):
    before = (VENDORED / "index.yaml").read_text()
    repo = portal(
        tmp_path,
        {"dependencies": {"react": "^19"}, "devDependencies": {"vitest": "^5", "@playwright/test": "1.63.0"}},
    )
    result = vendor(repo)
    assert result.returncode == 1, result.stderr
    assert "@playwright/test" in result.stderr and "SDK-12" in result.stderr
    assert not (VENDORED / "sample").exists()
    assert (VENDORED / "index.yaml").read_text() == before


def test_the_refusal_names_every_foreign_package_and_accepts_the_templates_own(tmp_path):
    spec = importlib.util.spec_from_file_location("vendor_sample_apps", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo = portal(tmp_path, {"dependencies": {"react": "18", "left-pad": "1"}, "devDependencies": {"evil": "1"}})
    assert module.refused(repo, "HEAD", "sample") == ["evil", "left-pad"]

    clean = portal(tmp_path / "clean", {"dependencies": {"react": "18"}, "devDependencies": {"vitest": "*"}})
    assert module.refused(clean, "HEAD", "sample") == []

    plain = portal(tmp_path / "plain", None)
    assert module.refused(plain, "HEAD", "sample") == [], "a plain-HTML app installs nothing"


def test_the_vendored_samples_ask_for_no_playwright():
    for manifest in VENDORED.glob("*/package.json"):
        names = set(json.loads(manifest.read_text()).get("devDependencies") or {})
        assert "@playwright/test" not in names, manifest

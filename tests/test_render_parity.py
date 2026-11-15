"""T-6982: scripts/render-parity.py compares full manifests, not the goldens' names."""

import subprocess
import sys

from conftest import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts/render-parity.py"
RENDER = """---
apiVersion: v1
kind: ConfigMap
metadata: {name: a, namespace: x, annotations: {checksum/config: "1111"}}
data: {k: v}
---
kind: Secret
metadata: {name: b, namespace: x}
stringData: {p: q}
"""


def compare(tmp_path, old: str, new: str):
    for side, text in (("old", old), ("new", new)):
        (tmp_path / side).mkdir(exist_ok=True)
        (tmp_path / side / "e.yaml").write_text(text)
    return subprocess.run([sys.executable, str(SCRIPT), "--compare", str(tmp_path / "old"), str(tmp_path / "new"), "e"],
                          capture_output=True, text=True, check=False)


def test_identical_renders_match(tmp_path):
    assert compare(tmp_path, RENDER, RENDER).returncode == 0


def test_document_order_key_order_and_checksums_do_not_count(tmp_path):
    docs = RENDER.split("---\n")[1:]
    moved = "---\n" + docs[1] + "---\n" + docs[0].replace('"1111"', '"2222"').replace("data: {k: v}", "data:\n  k: v")
    result = compare(tmp_path, RENDER, moved)
    assert result.returncode == 0, result.stdout


def test_one_changed_value_fails_and_names_the_document(tmp_path):
    result = compare(tmp_path, RENDER, RENDER.replace("{p: q}", "{p: r}"))
    assert result.returncode == 1
    assert "Secret x/b" in result.stdout and "+  p: r" in result.stdout


def test_a_missing_render_or_a_bad_name_is_a_usage_error(tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    base = [sys.executable, str(SCRIPT), "--compare", str(tmp_path / "old"), str(tmp_path / "new")]
    assert subprocess.run([*base, "e"], capture_output=True, check=False).returncode == 2
    assert subprocess.run([*base, "../e"], capture_output=True, check=False).returncode == 2


def test_a_generated_value_is_masked_only_where_two_old_renders_differ(tmp_path):
    for side, text in (("old", RENDER), ("again", RENDER.replace("{k: v}", "{k: w}")),
                       ("new", RENDER.replace("{k: v}", "{k: z}").replace("{p: q}", "{p: r}"))):
        (tmp_path / side).mkdir()
        (tmp_path / side / "e.yaml").write_text(text)
    result = subprocess.run([sys.executable, str(SCRIPT), "--compare", str(tmp_path / "old"), str(tmp_path / "new"),
                             "--again", str(tmp_path / "again"), "e"], capture_output=True, text=True, check=False)
    assert result.returncode == 1 and "ConfigMap x/a" not in result.stdout and "Secret x/b" in result.stdout
    assert "1 generated values masked" in result.stderr

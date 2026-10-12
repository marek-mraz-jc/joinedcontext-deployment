"""T-3953: the runner's inflate.wasm stops a zip member's inflate at its declared size (PL-72).

The committed module runs in the pinned Bento as the rendered archive read runs it: mounted at
/streams/inflate.wasm, the limit in `inflate_limit`, a refusal in `inflate_error`.
"""

import json
import hashlib
import re
import subprocess
from pathlib import Path

from open_data import BENTO, requires_docker

STREAMS = Path(__file__).resolve().parent.parent / "components/pipeline-runner/streams"
MODULE = STREAMS / "inflate.wasm"

# Each case: the deflated text, and the size the directory claims (None: a stored member).
CASES = """
let text = range(0, 2000).map_each(i -> "row,%v\\n".format(i)).join("")
let n = count("c")
root = if $n == 4 { "0".repeat(5000000).compress("flate") } else if $n == 5 { "not deflate" } else { $text.compress("flate") }
meta case = ["", "exact", "lies", "stored", "bomb", "garbage"].index($n)
meta inflate_limit = if $n == 1 { $text.length().string() } else if $n == 3 { deleted() } else { "100" }
"""


def run_cases() -> dict:
    config = {
        "input": {"generate": {"count": 5, "interval": "", "mapping": CASES}},
        "pipeline": {"processors": [
            {"wasm": {"module_path": "/streams/inflate.wasm", "function": "inflate"}},
            {"mapping": 'root = {"case": @case, "bytes": content().length(), "error": @inflate_error.or("")}'},
        ]},
        "output": {"stdout": {}},
        "logger": {"level": "error"},
    }
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{MODULE}:/streams/inflate.wasm:ro", "-e", f"CONFIG={json.dumps(config)}",
         "--entrypoint", "sh", BENTO, "-c", 'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode()
    return {row["case"]: row for row in map(json.loads, result.stdout.decode().splitlines())}


@requires_docker
def test_a_member_inflates_to_its_declared_size_and_a_lying_one_is_refused_at_it():
    rows = run_cases()
    assert rows["exact"] == {"case": "exact", "bytes": 16890, "error": ""}
    # The packed bytes stay as they came; the check after the step throws the reason.
    assert rows["lies"]["error"] == "inflates past the 100 bytes its directory says"
    assert rows["bomb"]["error"] == "inflates past the 100 bytes its directory says"
    assert rows["garbage"]["error"].startswith("is no deflate stream")
    # A stored member carries no limit and passes untouched.
    assert rows["stored"]["error"] == "" and rows["stored"]["bytes"] < 16890


def test_the_readme_names_the_module_it_ships():
    named = re.search(r"sha256\s+is `([0-9a-f]{64})`", (STREAMS / "README.md").read_text())
    assert named and named.group(1) == hashlib.sha256(MODULE.read_bytes()).hexdigest()

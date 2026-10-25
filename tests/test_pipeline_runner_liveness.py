"""The runner's per-stream caps (T-5370): a step that never returns or that eats memory is
stopped and the other streams, and every other project's runner, keep running.

Bento cannot free a stream whose step loops: DELETE /streams/{id} hangs and leaves it listed
`"active":false` with its core still held. The Portal caps each run (run_queue.rs) and deletes
it; the runner's liveness command fails on a stream held stopped two probes in a row, and the
kubelet's restart frees the core. A memory bomb meets the container's own limit. The chaos test
runs the pinned image under the probe the chart renders, one container per project as the
`runner.project` release is one process per project.
"""

import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
requires_helmfile = pytest.mark.skipif(shutil.which("helmfile") is None, reason="helmfile not installed")


def docker_works():
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], check=False, capture_output=True).returncode == 0


requires_docker = pytest.mark.skipif(not docker_works(), reason="no docker daemon")

GOOD = {"input": {"generate": {"interval": "200ms", "mapping": "root.n = counter()"}}, "output": {"drop": {}}}
ONE = {"generate": {"interval": "1s", "count": 1, "mapping": "root = {}"}}
LOOP = {"input": ONE, "pipeline": {"processors": [{"jq": {"query": "def f: f; f"}}]}, "output": {"drop": {}}}
BOMB = {
    "input": ONE,
    "pipeline": {"processors": [{"mapping": "root = range(0, 100000000).map_each(i -> i.string())"}]},
    "output": {"drop": {}},
}


@pytest.fixture(scope="module")
def dev(rendered):
    return rendered("dev")


def runner_liveness(docs):
    deployment = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "pipeline-runner")
    return deployment["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]


@requires_helmfile
def test_the_runner_lives_by_a_stop_that_ends(dev):
    probe = runner_liveness(dev)
    assert "httpGet" not in probe
    command = probe["exec"]["command"]
    assert command[:2] == ["sh", "-c"] and "/streams" in command[2]
    # Two failures a minute apart: a stream held stopped for two to three minutes.
    assert (probe["periodSeconds"], probe["failureThreshold"]) == (60, 2)


def probe_command():
    """The command base-values renders, read from its YAML block (it holds no template)."""
    text = (ROOT / "components/pipeline-runner/values/runner/base-values.yaml.gotmpl").read_text()
    start = text.index("  liveness:\n    exec:")
    end = text.index("\n    periodSeconds", start)
    return yaml.safe_load(text[start:end])["liveness"]["exec"]


def test_the_probe_command_is_the_one_the_chart_renders():
    command = probe_command()
    assert command[:2] == ["sh", "-c"]
    assert "comm -12 /tmp/stopped /tmp/stopped.now" in command[2]


def image():
    pin = yaml.safe_load((ROOT / "components/pipeline-runner/images.yaml").read_text())["pipeline-runner"]["runner"]
    return f"{pin['repository']}:{pin['tag']}@{pin['digest']}"


class Runner:
    """One project's runner: the pinned image in its own container, capped like the pod."""

    def __init__(self, name, port, memory="512m"):
        self.name, self.url = name, f"http://localhost:{port}"
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
        subprocess.run(
            ["docker", "run", "-d", "--name", name, "--cpus", "1", "--memory", memory, "--read-only",
             "--tmpfs", "/tmp", "-p", f"{port}:4195", image(), "streams"],
            check=True, capture_output=True,
        )
        self.wait()

    def wait(self):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                self.call("GET", "/ping", timeout=1)
                return
            except OSError:
                time.sleep(0.3)
        raise AssertionError(f"{self.name} did not start")

    def call(self, verb, path, body=None, timeout=2.0):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=verb)
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            text = answer.read()
            return json.loads(text) if text and text[:1] in b"{[" else None

    def timed(self, verb, path, body=None):
        began = time.monotonic()
        answer = self.call(verb, path, body)
        return answer, time.monotonic() - began

    def live(self):
        result = subprocess.run(["docker", "exec", self.name, *probe_command()], check=False, capture_output=True)
        return result.returncode == 0

    def cpu(self):
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}", self.name],
                             capture_output=True, text=True, check=True).stdout
        return float(out.strip().rstrip("%"))

    def restarted(self):
        subprocess.run(["docker", "restart", "-t", "1", self.name], check=True, capture_output=True)
        self.wait()

    def oom_killed(self):
        out = subprocess.run(["docker", "inspect", "-f", "{{.State.OOMKilled}}", self.name],
                             capture_output=True, text=True, check=True).stdout
        return out.strip() == "true"

    def remove(self):
        subprocess.run(["docker", "rm", "-f", self.name], check=False, capture_output=True)


@pytest.fixture
def runners():
    made = []

    def make(name, port, **kw):
        made.append(Runner(name, port, **kw))
        return made[-1]

    yield make
    for runner in made:
        runner.remove()


def answers_within_2s(runner):
    held, seconds = runner.timed("GET", "/streams")
    assert seconds < 2, f"{runner.name} took {seconds:.1f} s"
    return held


@requires_docker
def test_a_looping_stream_is_stopped_and_every_other_stream_runs_on(runners):
    a = runners("t5370-project-a", 42011)
    b = runners("t5370-project-b", 42012)
    a.call("POST", "/streams/a.good", GOOD)
    b.call("POST", "/streams/b.good", GOOD)
    a.call("POST", "/streams/a.loop", LOOP)
    time.sleep(3)
    assert a.cpu() > 80, "the loop holds a core"
    assert a.live(), "a stream that runs is alive"

    # The Portal's delete at the cap: Bento never answers it, and a parallel read still does.
    with pytest.raises(OSError):
        a.call("DELETE", "/streams/a.loop", timeout=3)
    assert answers_within_2s(a)["a.loop"]["active"] is False
    assert answers_within_2s(b)["b.good"]["active"] is True
    assert a.call("GET", "/streams/a.good")["active"] is True

    # Held stopped at two probes in a row: liveness fails and the kubelet restarts the process.
    assert a.live(), "the first sight of a stopped stream is a finished run"
    assert not a.live(), "the same stream still held is a stop that never ended"
    a.restarted()
    assert a.live()
    time.sleep(2)
    assert a.cpu() < 20, "the restart freed the core"
    assert answers_within_2s(a) == {}
    assert answers_within_2s(b)["b.good"]["active"] is True


@requires_docker
def test_a_finished_run_deleted_between_probes_keeps_the_runner_alive(runners):
    a = runners("t5370-finished", 42013)
    a.call("POST", "/streams/a.once", {"input": ONE, "output": {"drop": {}}})
    time.sleep(3)
    assert answers_within_2s(a)["a.once"]["active"] is False
    assert a.live()
    a.call("DELETE", "/streams/a.once")
    assert a.live()


@requires_docker
def test_a_memory_bomb_meets_its_own_limit_and_the_other_project_answers(runners):
    a = runners("t5370-bomb", 42014, memory="256m")
    b = runners("t5370-neighbour", 42015)
    b.call("POST", "/streams/b.good", GOOD)
    try:
        a.call("POST", "/streams/a.bomb", BOMB, timeout=10)
    except OSError:
        pass  # the bomb may take the process down before it answers
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not a.oom_killed():
        assert answers_within_2s(b)["b.good"]["active"] is True
        time.sleep(1)
    assert a.oom_killed(), "the bomb was stopped by its container's limit"
    assert answers_within_2s(b)["b.good"]["active"] is True

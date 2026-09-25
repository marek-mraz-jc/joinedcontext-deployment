"""The 30-bus cap of hsl-hfp-vehicles holds slots, not a count (T-2961, PL-22).

Run by Bento over HFP frames fed in three phases, with the committed mapping and the runner's
cache resources, their ttls shortened so a slot's expiry fits in a test. The cap once handed
slots out with `counter()`, which never goes back: half an hour after a start the first thirty
had expired, every bus drew a number above thirty, and the pipeline read the feed and wrote
nothing while its status said Live.
"""

import json
import queue
import subprocess
import threading
import time
from pathlib import Path

import yaml

from open_data import BENTO, requires_docker

ROOT = Path(__file__).resolve().parent.parent
MAPPING = ROOT / "components/context-gateway/seed/helsinki/helsinki-pipeline-hfp-bento.yaml"
RESOURCES = ROOT / "components/pipeline-runner/streams/resources.yaml"
TTL_S = 2


def frame(vehicle: int, phase: str) -> str:
    return json.dumps({"VP": {
        "oper": 22, "veh": vehicle, "long": 24.94, "lat": 60.17, "spd": 8.5, "hdg": 90,
        "route": "2550", "tst": f"2026-09-25T16:{phase}:00.000Z",
    }})


def caches() -> list[dict]:
    resources = yaml.safe_load(RESOURCES.read_text())["cache_resources"]
    for cache in resources:
        # The slot silence window, shortened; the throttle off, so every frame is a write.
        cache["memory"]["default_ttl"] = f"{TTL_S}s" if cache["label"] == "fleet" else "1ms"
        cache["memory"]["compaction_interval"] = "1s"
    return resources


@requires_docker
def test_a_slot_is_freed_by_silence_and_kept_by_reporting():
    config = {
        "input": {"stdin": {"scanner": {"lines": {}}}},
        "pipeline": yaml.safe_load(MAPPING.read_text())["pipeline"],
        "cache_resources": caches(),
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "error"},
    }
    runner = subprocess.Popen(
        ["docker", "run", "--rm", "-i", "-e", "JC_ORG_DOMAIN=hel.fi", "-e", "JC_SPACE=helsinki",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO, "-c",
         'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    def send(*lines: str) -> None:
        runner.stdin.write("".join(line + "\n" for line in lines))
        runner.stdin.flush()

    # The phases wait on what Bento wrote, never on a clock alone (T-2992): on a loaded runner
    # the container started late, the frames queued up and ran in one burst, and the gaps the
    # sleeps were meant to keep were gone.
    out: list[str] = []
    arrived: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(target=lambda: [arrived.put(line) for line in runner.stdout], daemon=True)
    reader.start()

    def take(count: int, within: float) -> None:
        deadline = time.monotonic() + within
        for _ in range(count):
            try:
                out.append(arrived.get(timeout=max(0.0, deadline - time.monotonic())))
            except queue.Empty:
                raise AssertionError(f"Bento wrote {len(out)} line(s), waiting for {count}: {out}") from None

    try:
        # Bus 1 alone first, so it holds a slot; its line also says Bento is up.
        send(frame(1, "01"))
        take(1, within=120)
        # Then 39 more race for the other 29 slots.
        send(*(frame(v, "01") for v in range(2, 41)))
        take(29, within=30)
        # Bus 1 keeps reporting past the ttl, each frame out before the next; buses 2..40 fall
        # silent. The window counts from the last slot Bento handed out, not from a send.
        silent_since = time.monotonic()
        while time.monotonic() - silent_since < 3 * TTL_S:
            time.sleep(0.5)
            send(frame(1, "02"))
            take(1, within=30)
        send(*(frame(v, "03") for v in range(41, 81)))
        take(29, within=30)
        runner.stdin.close()
        runner.wait(timeout=60)
        reader.join(timeout=10)
        err = runner.stderr.read()
    finally:
        if runner.poll() is None:
            runner.kill()
    while not arrived.empty():
        out.append(arrived.get())
    assert runner.returncode == 0, err

    written: dict[str, list[int]] = {}
    for line in out:
        entity = json.loads(line)
        phase = entity["location"]["observedAt"][14:16]
        written.setdefault(phase, []).append(int(entity["fleetVehicleId"]["value"].split("-")[1]))

    # The cap: thirty of the forty, each once (frames run on several threads, so which 29 join
    # bus 1 is theirs to race for).
    first = written["01"]
    assert len(first) == len(set(first)) == 30 and 1 in first and set(first) <= set(range(1, 41)), first
    # A bus that keeps reporting keeps its slot across the ttl.
    assert set(written["02"]) == {1}
    # The silent buses' slots are free again: 29 new buses take them, beside bus 1's.
    later = written.get("03", [])
    assert len(later) == len(set(later)) == 29 and set(later) <= set(range(41, 81)), later

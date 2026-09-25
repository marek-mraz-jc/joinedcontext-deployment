"""The 30-bus cap of hsl-hfp-vehicles holds slots, not a count (T-2961, PL-22).

Run by Bento over HFP frames fed in three phases, with the committed mapping and the runner's
cache resources, their ttls shortened so a slot's expiry fits in a test. The cap once handed
slots out with `counter()`, which never goes back: half an hour after a start the first thirty
had expired, every bus drew a number above thirty, and the pipeline read the feed and wrote
nothing while its status said Live.
"""

import json
import subprocess
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

    try:
        time.sleep(3)  # Bento up before the first frame, so the phases keep their gaps
        # Bus 1 alone first, so it holds a slot; then 39 more race for the other 29.
        send(frame(1, "01"))
        time.sleep(0.5)
        send(*(frame(v, "01") for v in range(2, 41)))
        # Bus 1 keeps reporting past the ttl; buses 2..40 fall silent.
        for _ in range(3 * TTL_S * 2):
            time.sleep(0.5)
            send(frame(1, "02"))
        send(*(frame(v, "03") for v in range(41, 81)))
        time.sleep(1)
        out, err = runner.communicate(timeout=60)
    finally:
        if runner.poll() is None:
            runner.kill()
    assert runner.returncode == 0, err

    written: dict[str, list[int]] = {}
    for line in out.splitlines():
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

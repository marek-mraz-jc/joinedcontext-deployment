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

import open_data
from open_data import BENTO, requires_docker

ROOT = Path(__file__).resolve().parent.parent
MAPPING = ROOT / "components/context-gateway/seed/helsinki/helsinki-pipeline-hfp-bento.yaml"
RESOURCES = ROOT / "components/pipeline-runner/streams/resources.yaml"
TTL_S = 2


def topic(mode: str, oper: int, vehicle: int, route: str, next_stop: str = "1040601") -> str:
    """The HFP topic a frame arrives on; the mapping reads the mode and the next stop from it."""
    return f"/hfp/v2/journey/ongoing/vp/{mode}/{oper:04d}/{vehicle:05d}/{route}/1/Kamppi/16:00/{next_stop}/5/60;24/19/75/45"


def frame(vehicle: int, phase: str, mode: str = "bus", oper: int = 22, route: str = "2550", **fields) -> str:
    vp = {"oper": oper, "veh": vehicle, "long": 24.94, "lat": 60.17, "spd": 8.5, "hdg": 90,
          "route": route, "tst": f"2026-09-25T16:{phase}:00.000Z"} | fields
    return json.dumps({"topic": topic(mode, oper, vehicle, route), "VP": vp})


def pipeline(then: tuple[dict, ...] = (), **extra) -> dict:
    """The committed mapping behind a step that sets the topic as the runner's MQTT input does,
    and before the steps `then` (the reconciler's lifetime step, T-4843)."""
    committed = yaml.safe_load(MAPPING.read_text())["pipeline"]
    as_mqtt = {"mapping": 'meta mqtt_topic = this.topic\nroot = this.without("topic")'}
    return {**committed, "processors": [as_mqtt, *committed["processors"], *then], **extra}


def caches() -> list[dict]:
    resources = yaml.safe_load(RESOURCES.read_text())["cache_resources"]
    for cache in resources:
        # The slot silence window, shortened.
        cache["memory"]["default_ttl"] = f"{TTL_S}s"
        cache["memory"]["compaction_interval"] = "1s"
    return resources


@requires_docker
def test_a_slot_is_freed_by_silence_and_kept_by_reporting():
    config = {
        "input": {"stdin": {"scanner": {"lines": {}}}},
        "pipeline": pipeline(),
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


@requires_docker
def test_a_report_without_a_gps_fix_is_dropped_and_a_missing_speed_is_left_out():
    """T-3129: HFP sends position reports with no fix (`loc: "ODO"`, lat/long/spd/hdg null).

    Built into a Vehicle they failed on `long.number()` and every one was kept as a rejected
    record: 1,000 piled up on dev and buried the real ones. A report without coordinates says
    nothing about where the bus is and is dropped before it takes a fleet slot; a report with
    coordinates and no speed or heading is written without them.
    """
    def report(vehicle: int, **fields) -> str:
        vp = {"oper": 22, "veh": vehicle, "long": 24.94, "lat": 60.17, "spd": 8.5, "hdg": 90,
              "route": "2510", "tst": "2026-10-06T17:26:30.575Z", "loc": "GPS"}
        vp.update(fields)
        return json.dumps({"topic": topic("bus", 22, vehicle, "2510"), "VP": vp})

    config = {
        "input": {"stdin": {"scanner": {"lines": {}}}},
        "pipeline": pipeline(),
        "cache_resources": caches(),
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "error"},
    }
    frames = [
        report(1, lat=None, long=None, spd=None, hdg=None, loc="ODO"),
        report(2, spd=None, hdg=None),
        report(3),
    ]
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", "JC_ORG_DOMAIN=hel.fi", "-e", "JC_SPACE=helsinki",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO, "-c",
         'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input="".join(line + "\n" for line in frames), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "error" not in result.stderr.lower(), result.stderr
    written = {
        entity["fleetVehicleId"]["value"]: entity
        for entity in (json.loads(line) for line in result.stdout.splitlines() if line.strip())
    }
    assert sorted(written) == ["22-2", "22-3"]
    without_speed, whole = written["22-2"], written["22-3"]
    assert without_speed["location"]["value"]["coordinates"] == [24.94, 60.17]
    assert "speed" not in without_speed and "heading" not in without_speed
    assert whole["speed"]["value"] == 8.5 and whole["heading"]["value"] == 90


@requires_docker
def test_a_full_fleet_and_a_repeat_count_no_processor_error():
    """T-3186: dev counted 5.4 M errors of 792 k frames. The mapping probed its caches with
    `get` and `add` and caught the misses, and Bento counts every caught miss in
    `processor_error`, which the Portal shows as the pipeline's errors: 40 buses for 30 slots
    made 805. Probing with `exists` first, a fleet that is full, a bus that repeats and a bus
    without a slot are no error at all."""
    config = {
        "input": {"stdin": {"scanner": {"lines": {}}}},
        # One thread: what is measured is the probing. On several threads two new buses can
        # still race for one free slot, and the loser's `add` is the one error left (the
        # mapping's ponytail note).
        "pipeline": pipeline(threads=1),
        # The runner's own ttl: a slot is held.
        "cache_resources": yaml.safe_load(RESOURCES.read_text())["cache_resources"],
        "output": {"stdout": {"codec": "lines"}},
        "metrics": {"logger": {"push_interval": "", "flush_metrics": True}},
        "logger": {"level": "info", "format": "json"},
    }
    frames = [frame(v, "01") for v in range(1, 41)] + [frame(v, "02") for v in range(1, 41)]
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", "JC_ORG_DOMAIN=hel.fi", "-e", "JC_SPACE=helsinki",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO, "-c",
         'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input="".join(line + "\n" for line in frames), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    counters = [json.loads(line) for line in result.stderr.splitlines() if '"Counter metric"' in line]
    errors = sum(int(c["value"]) for c in counters if c["name"] == "processor_error")
    received = sum(int(c["value"]) for c in counters if c["name"] == "input_received")
    assert received == 80, counters
    # The cap still holds: thirty buses written, each twice (T-3906), the other ten never.
    written = [json.loads(line)["fleetVehicleId"]["value"] for line in result.stdout.splitlines() if line.strip()]
    assert len(written) == 60 and len(set(written)) == 30, written
    assert all(written.count(bus) == 2 for bus in set(written)), written
    assert errors == 0, f"{errors} processor errors for {received} frames"


@requires_docker
def test_an_admitted_bus_writes_one_report_in_thirty_seconds():
    """T-4624: a write a second per vehicle (T-3906) held every broker connection and starved the
    visitors' reads, so one report in thirty seconds is written: a minute and a second of reports,
    one a second, are three writes, those stamped :00 and :30. A report without a readable time is
    none of them."""
    config = {
        "input": {"stdin": {"scanner": {"lines": {}}}},
        "pipeline": pipeline(),
        "cache_resources": yaml.safe_load(RESOURCES.read_text())["cache_resources"],
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "error"},
    }
    stamps = [f"2026-10-12T08:{i // 60:02d}:{i % 60:02d}.{i * 7 % 1000:03d}Z" for i in range(61)]
    frames = [
        json.dumps({"topic": topic("bus", 22, 7, "2550"), "VP": {
            "oper": 22, "veh": 7, "long": 24.94 + i / 1000, "lat": 60.17, "spd": 8.5, "hdg": 90,
            "route": "2550", "tst": tst}})
        for i, tst in enumerate(stamps + ["", "soon"])
    ]
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", "JC_ORG_DOMAIN=hel.fi", "-e", "JC_SPACE=helsinki",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO, "-c",
         'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input="".join(line + "\n" for line in frames), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    written = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert sorted(e["location"]["observedAt"] for e in written) == [stamps[0], stamps[30], stamps[60]], written
    assert {e["fleetVehicleId"]["value"] for e in written} == {"22-7"}


def bento(frames: list[str], known: tuple[str, ...] = (), then: tuple[dict, ...] = (), **extra) -> list[dict]:
    """The mapping over `frames`, the `gtfs` cache holding the URNs `known` as the daily GTFS read
    leaves them."""
    resources = yaml.safe_load(RESOURCES.read_text())["cache_resources"]
    for cache in resources:
        if cache["label"] == "gtfs":
            cache["memory"]["init_values"] = {urn: "1" for urn in known}
    config = {
        "input": {"stdin": {"scanner": {"lines": {}}}},
        "pipeline": pipeline(then, **extra),
        "cache_resources": resources,
        "output": {"stdout": {"codec": "lines"}},
        "logger": {"level": "error"},
    }
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", "JC_ORG_DOMAIN=hel.fi", "-e", "JC_SPACE=helsinki",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO, "-c",
         'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input="".join(line + "\n" for line in frames), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


@requires_docker
def test_each_mode_has_its_own_cap_and_a_full_one_never_takes_another_modes_slot():
    """T-3893: 30 buses, 30 trams, 10 metros, 15 trains, 5 ferries. Twelve metros and seven
    ferries arrive first and fill their modes; the trams and buses after them are all admitted,
    and a mode outside the list is never written."""
    frames = (
        [frame(v, "01", "metro", 50, "31M1") for v in range(1, 13)]
        + [frame(v, "01", "ferry", 60, "1019") for v in range(1, 8)]
        + [frame(v, "01", "tram", 40, "1009") for v in range(1, 21)]
        + [frame(v, "01", "train", 90, "3001K") for v in range(1, 4)]
        + [frame(v, "01") for v in range(1, 6)]
        + [frame(v, "01", "ubus", 12, "1500") for v in range(1, 3)]
    )
    written: dict[str, set[str]] = {}
    for entity in bento(frames, threads=1):
        written.setdefault(entity["transportMode"]["value"], set()).add(entity["fleetVehicleId"]["value"])
    assert {mode: len(vehicles) for mode, vehicles in written.items()} == {
        "metro": 10, "ferry": 5, "tram": 20, "train": 3, "bus": 5}
    # The first ten metros hold the slots, so the last two are the ones left out.
    assert written["metro"] == {f"50-{v}" for v in range(1, 11)}


@requires_docker
def test_a_vehicle_links_its_line_and_next_stop_and_says_how_late_and_full_it_runs():
    urn = "urn:ngsi-ld:{}:hel.fi:helsinki:{}"
    known = (urn.format("GtfsRoute", "1009"), urn.format("GtfsRoute", "3001K"), urn.format("GtfsStop", "1040601"))
    tram, at_end, quiet = bento([
        frame(3, "01", "tram", 40, "1009", dl=-95, occu=100),
        json.dumps({"topic": topic("train", 90, 7, "3001K", "EOL"), "VP": {
            "oper": 90, "veh": 7, "long": 24.94, "lat": 60.17, "route": "3001K",
            "tst": "2026-09-25T16:01:00.000Z", "dl": 30, "occu": 0}}),
        json.dumps({"topic": topic("ferry", 60, 4, "1019"), "VP": {
            "oper": 60, "veh": 4, "long": 24.98, "lat": 60.15, "route": None, "tst": "2026-09-25T16:01:00.000Z"}}),
    ], known, threads=1)
    assert tram["onRoute"]["object"] == urn.format("GtfsRoute", "1009")
    assert tram["nextStop"]["object"] == urn.format("GtfsStop", "1040601")
    # HSL's dl counts ahead of the timetable (-95: 95 s late); delay counts behind it.
    assert tram["delay"]["value"] == 95 and tram["occupancy"]["value"] == 100
    assert tram["transportMode"]["value"] == "tram" and tram["vehicleType"]["value"] == "tram"
    # Past its last stop a train has no next stop.
    assert "nextStop" not in at_end and at_end["delay"]["value"] == -30 and at_end["occupancy"]["value"] == 0
    assert at_end["vehicleType"]["value"] == "other" and at_end["onRoute"]["object"] == urn.format("GtfsRoute", "3001K")
    # A ferry frame without a route names no line.
    assert not {"route", "onRoute"} & set(quiet) and quiet["vehicleType"]["value"] == "passengerVessel"
    for entity in (tram, at_end, quiet):
        assert not open_data.schema_errors(ROOT / "components/context-gateway/seed/helsinki/helsinki.v1.schema.json", entity), entity


@requires_docker
def test_a_line_or_stop_the_space_does_not_hold_is_left_out_and_the_position_still_lands():
    """T-4052: HFP runs lines GTFS does not list (train 3002X3 on 2026-10-12), and the space's view
    refuses a whole Vehicle whose relationship names an entity it does not hold (threat model
    D7). Only a URN the daily GTFS read left in the `gtfs` cache is linked."""
    urn = "urn:ngsi-ld:{}:hel.fi:helsinki:{}"
    known = (urn.format("GtfsRoute", "3001K"), urn.format("GtfsStop", "1040601"))
    frames = [
        json.dumps({"topic": topic("train", 90, v, route, stop), "VP": {
            "oper": 90, "veh": v, "long": 24.94, "lat": 60.17, "route": route, "tst": "2026-10-12T09:30:00.000Z"}})
        for v, route, stop in [(1, "3001K", "1040601"), (2, "3002X3", "1040601"), (3, "3001K", "9999999"), (4, "3002X3", "9999999")]
    ]
    written = {e["fleetVehicleId"]["value"]: e for e in bento(frames, known, threads=1)}
    assert sorted(written) == ["90-1", "90-2", "90-3", "90-4"]
    links = {vehicle: (e.get("onRoute", {}).get("object"), e.get("nextStop", {}).get("object")) for vehicle, e in written.items()}
    assert links == {
        "90-1": (urn.format("GtfsRoute", "3001K"), urn.format("GtfsStop", "1040601")),
        "90-2": (None, urn.format("GtfsStop", "1040601")),
        "90-3": (urn.format("GtfsRoute", "3001K"), None),
        "90-4": (None, None),
    }
    # The line's number and the position land either way.
    assert all(e["route"]["value"] in ("3001K", "3002X3") and e["location"]["value"]["coordinates"] == [24.94, 60.17]
               for e in written.values())
    # Before the first GTFS read of a fresh runner the cache is empty: nothing is linked.
    assert not any({"onRoute", "nextStop"} & set(e) for e in bento(frames, threads=1))


def test_the_topics_are_the_owners_five_lines_and_never_a_whole_mode():
    """T-4624: bus 550, tram 4, metro M1 and M2, the Suomenlinna ferry; one line per topic."""
    topics = yaml.safe_load(
        (ROOT / "components/context-gateway/seed/helsinki/helsinki-datasource-hfp.yaml").read_text()
    )["spec"]["mqtt"]["topics"]
    vp = "/hfp/v2/journey/ongoing/vp/"
    assert topics == [vp + f"{mode}/+/+/{route}/#" for mode, route in
                      [("bus", "2550"), ("tram", "1004"), ("metro", "31M1"), ("metro", "31M2"), ("ferry", "1019")]]

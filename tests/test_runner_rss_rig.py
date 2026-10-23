"""scripts/runner-rss-rig.py (T-5285): the arguments and image it reads, and its arithmetic."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "runner_rss_rig", Path(__file__).resolve().parents[1] / "scripts" / "runner-rss-rig.py")
rig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rig)


def test_set_args_reads_each_pair_and_unquotes():
    values = "args:\n  - -w\n  - --set\n  - a.b=true\n  # note\n  - --set\n  - 'm=root = if x { deleted() }'\n  - streams\n"
    assert rig.set_args(values) == ["a.b=true", "m=root = if x { deleted() }"]


def test_the_shipped_values_carry_the_mapping():
    sets = rig.set_args(rig.VALUES.read_text())
    assert "metrics.prometheus.use_histogram_timing=true" in sets
    assert any(s.startswith("metrics.mapping=") for s in sets), sets


def test_image_is_the_pinned_runner_digest():
    assert rig.image(rig.IMAGES.read_text()).startswith("ghcr.io/warpstreamlabs/bento@sha256:")


def test_rss_and_per_name():
    assert rig.rss_anon_kb("VmRSS:\t 1 kB\nRssAnon:\t   38740 kB\n") == 38740
    assert rig.per_name_mb(1024, 1024 + 512 * 1024, 1024) == 0.5


def test_the_stream_has_two_writes_among_its_steps():
    labels = [p["label"] for p in rig.stream(10)["pipeline"]["processors"]]
    assert len(labels) == 10 and labels[-2:] == ["write_0", "route_1_write_0"]

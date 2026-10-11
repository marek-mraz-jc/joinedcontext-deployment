"""The pipeline runner's Go soft memory limit follows its container limit (T-3537)."""

import pytest

ENVIRONMENTS = ("local", "dev", "production")


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_the_runner_s_gomemlimit_is_85_percent_of_its_limit(rendered, environment):
    runner = next(d for d in rendered(environment) if d.get("kind") == "Deployment" and d["metadata"]["name"] == "pipeline-runner")
    container = next(c for c in runner["spec"]["template"]["spec"]["containers"] if c["name"] == "pipeline-runner-runner")
    limit = container["resources"]["limits"]["memory"]
    units = {"Mi": 2**20, "Gi": 2**30}
    limit_bytes = int(limit[:-2]) * units[limit[-2:]]
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert env["GOMEMLIMIT"] == str(limit_bytes * 85 // 100), limit


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_the_runner_times_with_histograms_not_summaries(rendered, environment):
    # Per-label summaries held 45 % of the runner's heap on dev; the Portal reads p99 from the
    # buckets (T-3625), so the summaries never come back (T-3537).
    runner = next(d for d in rendered(environment) if d.get("kind") == "Deployment" and d["metadata"]["name"] == "pipeline-runner")
    container = next(c for c in runner["spec"]["template"]["spec"]["containers"] if c["name"] == "pipeline-runner-runner")
    args = container["args"]
    assert "metrics.prometheus.use_histogram_timing=true" in args, args
    assert args[args.index("metrics.prometheus.use_histogram_timing=true") - 1] == "--set", args
    assert "http.debug_endpoints=true" not in args, args

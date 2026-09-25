"""The Portal and the context gateway keep answering while they roll (T-2927, OPS-07).

Both run one replica on dev. A rollout that stops the old pod before a new one is ready leaves
APISIX with no endpoint, and every App and Open page answers 503/504 until the new pod is up.
So each rolls with maxUnavailable 0 and a surge, and the new pod takes traffic only once its
readiness probe (the Portal's waits for the mirror to load) passes. Readiness must be a
different check from liveness: a liveness probe that waits on the mirror would restart a pod
that is only loading.
"""

import pytest

ROLLING = ("portal", "context-gateway")


@pytest.mark.parametrize("env", ["dev", "production"])
@pytest.mark.parametrize("name", ROLLING)
def test_a_rollout_starts_the_new_pod_before_the_old_one_stops(rendered, env, name):
    found = [
        d for d in rendered(env)
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == name
    ]
    assert len(found) == 1, f"{env} renders {len(found)} Deployments named {name}"
    spec = found[0]["spec"]
    strategy = spec.get("strategy", {})
    assert strategy.get("type", "RollingUpdate") == "RollingUpdate", f"{env}/{name}: {strategy}"
    rolling = strategy.get("rollingUpdate", {})
    assert rolling.get("maxUnavailable") == 0, f"{env}/{name} stops a pod before its successor is ready"
    assert rolling.get("maxSurge") not in (None, 0, "0", "0%"), f"{env}/{name} has no room to surge"

    containers = {c["name"]: c for c in spec["template"]["spec"]["containers"]}
    main = containers.get(name) or next(iter(containers.values()))
    readiness = main.get("readinessProbe")
    assert readiness, f"{env}/{name} takes traffic before it can answer"
    liveness = main.get("livenessProbe")
    if liveness:
        assert readiness.get("httpGet", {}).get("path") != liveness.get("httpGet", {}).get("path"), (
            f"{env}/{name}: liveness and readiness are one check, so a loading pod gets restarted"
        )

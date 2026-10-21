#!/usr/bin/env python3
"""Print `apiVersion/Kind namespace/name` for every object in a rendered manifest,
sorted. The committed .ci/golden/<environment>.txt is this output for each environment
ci.yml renders (T-4956), so a review sees exactly which objects a change adds or drops.
Helm test hooks are left out: `helmfile sync` never applies them."""
import sys

import yaml


def is_test_hook(doc):
    hooks = ((doc.get("metadata") or {}).get("annotations") or {}).get("helm.sh/hook", "")
    return "test" in str(hooks).split(",")


with open(sys.argv[1]) as fh:
    docs = [d for d in yaml.safe_load_all(fh) if isinstance(d, dict) and not is_test_hook(d)]
for line in sorted(
    "{}/{} {}/{}".format(
        d.get("apiVersion"), d.get("kind"),
        (d.get("metadata") or {}).get("namespace", "-"),
        (d.get("metadata") or {}).get("name"),
    )
    for d in docs
):
    print(line)

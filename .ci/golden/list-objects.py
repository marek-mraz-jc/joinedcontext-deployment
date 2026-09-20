#!/usr/bin/env python3
"""Print `apiVersion/Kind namespace/name` for every object in a rendered manifest,
sorted. The committed .ci/golden/local.txt is this output for the `local`
environment, so a review sees exactly which objects a change adds or drops."""
import sys

import yaml

docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if isinstance(d, dict)]
for line in sorted(
    "{}/{} {}/{}".format(
        d.get("apiVersion"), d.get("kind"),
        (d.get("metadata") or {}).get("namespace", "-"),
        (d.get("metadata") or {}).get("name"),
    )
    for d in docs
):
    print(line)

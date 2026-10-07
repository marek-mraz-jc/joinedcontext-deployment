# The Žilina seed: four spaces, one model each

The `zilina` project (T-3137): the city of Žilina and the University of Žilina, seeded the same way
as `bbsk/` and `banskabystrica/`. `index.yaml` maps each file to its path in the configuration
repository (jc-core `PATH_TEMPLATE`s), and the gateway mounts each under its own name.

Neither the city nor the university publishes in the national catalogue, and the city's own GIS
layers carry no licence, so the project is built on what national publishers release about the
city and on the university's own repository. Which feed answered with which status, and which were
refused and why, is `joinedcontext-docs/Research/zilina-open-data-sources.md`.

| space | model | holds |
|---|---|---|
| `zilina-mesto` | `statistical-observation` | ŠÚ SR rows for the city `SK031B517402`, one entity per cube cell, codes verbatim |
| `zilina-verejne` | `zilina-verejne` | the EEA station SK0020A, the city's monuments placed by address, its railway stations |
| `zilina-uniza` | `zilina-uniza` | DREPO's openly licensed works, without author names |
| `zilina-kpi` | `key-performance-indicator` | the indicators computed from the two city spaces (PF-54, PF-55) |

`statistical-observation` and `key-performance-indicator` are the same models as in `../bbsk/`
(copied, not edited: `tests/test_bystrica_seed.py` holds the copies identical); only their
examples name this project's spaces. Regenerate the artifacts of the two own models after editing
their LinkML:

```sh
T=../../../../../joinedcontext-platform/tools/model-tools/src   # the platform checkout
for m in zilina-verejne zilina-uniza; do
  python3 $T/gen_json_schema.py $m.linkml.yaml -o $m.v1.schema.json
  python3 $T/gen_context.py $m.linkml.yaml -o $m.v1.context.jsonld
  python3 $T/gen_docs.py $m.linkml.yaml -o $m.v1.md
  python3 $T/gen_example.py $m.linkml.yaml -o $m.v1.example.jsonld
done
```

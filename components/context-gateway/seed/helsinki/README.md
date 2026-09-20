# The Helsinki seed: one space, four endpoints

The demonstration instance's context data, as the development profile seeds it into the
gateway's `/repo` (T-0263) and, through the forge bootstrap, into the configuration repository
the Portal reads (T-0478). Both consumers read the files in this folder, so they cannot drift:
`index.yaml` maps each file to its path in the repository (jc-core `PATH_TEMPLATE`s), and the
gateway mounts each under its own name in the flat `/repo`.

One ContextSpace, `helsinki`, holds three things side by side: `Event` from the city's Linked
Events register, `BikeHireDockingStation` from the HSL city bike GBFS feeds, `Vehicle` from HSL's
high-frequency positioning of four trunk lines. Four public Endpoints publish it: `helsinki-events`,
`helsinki-bikes` and `helsinki-transport` each carry `spec.policyRef` to the Policy that grants
one type, so the gateway evaluates that Policy alone (EP-14, GW8); `helsinki-all` carries none
and evaluates every Policy of the space, which is also why the pipelines write through it: the
`pipelines-write` Policy is bound to the `pipelines` ServiceAccount there and nowhere else.

The streams the resident runner executes are `components/pipeline-runner/streams/`; the
`DataSource` and `Pipeline` manifests here describe the same fetches for the Portal, until the
reconciler renders the one from the other on this cluster (T-0421).

Regenerate the model artifacts after editing `helsinki.linkml.yaml`:

```sh
T=../../../../../joinedcontext-platform/tools/model-tools/src   # the platform checkout
for g in json_schema context example docs; do python3 $T/gen_$g.py helsinki.linkml.yaml -o helsinki.v1.$( [ $g = json_schema ] && echo schema.json || [ $g = context ] && echo context.jsonld || [ $g = example ] && echo example.jsonld || echo md ); done
```

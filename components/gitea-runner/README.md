# Gitea Runner

The forge's Actions runner (docs ADR-N-028, Deployment/04 §6): `gitea-runner` in host mode on
the builder image the Portal release publishes (`joinedcontext-app-builder`, AP-82). It builds
every application repository with the workflow the Portal commits into it.

Deploy the component with:
```bash
helmfile apply -i --selector component=gitea-runner
```

## What it wires

- **Forge**: `components/gitea` turns Actions and the package registry on, and its bootstrap Job
  writes the organization's registration token into `gitea-runner-registration` here.
- **The loop**: the image's `runner` (portal `builder/runner.sh`) registers `--ephemeral`, runs
  one job, kills what the job left behind, wipes `/tmp/runner` and registers again. The token is
  read once from memory and deleted, so deleting the pod is how the runner restarts.
- **Network**: no ingress; egress to the forge (3000), the Portal API (8080) and CoreDNS.

## Pinning

`images.yaml` pins `joinedcontext-app-builder`. Only a build that contains
`/usr/local/bin/runner` can run here: re-pin to it before listing the component in an
environment that applies it.

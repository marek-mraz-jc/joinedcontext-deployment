# kube-hetzner kit additions

The cluster itself comes from the owner's kube-hetzner kit (GitLab
`civitas-core-v2-terraform-hetzner-deployment-guide`, read-only to agents). Some
kube-system pieces were applied live on dev and prod without reaching the kit; a
node rebuilt from the kit loses them. This folder holds them as kit files, ready
to copy into the kit's `extra-manifests/`.

## 1. Linkerd CNI (T-5327)

Without it, Linkerd injects `linkerd-init` (NET_ADMIN, NET_RAW) and the
Pod Security `restricted` namespaces the Portal creates for Apps refuse every
meshed pod.

1. Copy `extra-manifests/25-linkerd-cni.yaml.tpl` into the kit's `extra-manifests/`.
2. In the kit's `extra-manifests/kustomization.yaml.tpl`, list it above
   `- 30-linkerd.yaml`:

   ```yaml
     - 25-linkerd-cni.yaml
   ```

3. In the kit's `extra-manifests/30-linkerd.yaml.tpl`, `linkerd-control-plane`
   `valuesContent`, add at the top level (keep `proxy.nativeSidecar: true`):

   ```yaml
   cniEnabled: true
   ```

4. Keep the `linkerd2-cni` version equal to `linkerd-crds` and
   `linkerd-control-plane` (all three `2026.10.1` today).

Order on a live cluster: the `linkerd-cni` DaemonSet Ready on the node, then
the control plane with `cniEnabled`, then a rollout restart of every meshed
workload (a pod keeps `linkerd-init` until it restarts). `just dev-smoke`
checks that every pod in `linkerd` and `linkerd-cni` is Ready.

Before a kit apply, compare with the live chart, read-only:
`kubectl -n kube-system get helmchart linkerd2-cni -o jsonpath='{.spec.valuesContent}'`.

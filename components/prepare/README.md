# Prepare

Prepares the cluster before deployment:

- Creates namespaces, if `global.createNamespaces` is true.
- Patches namespaces to use linkerd if
  - `global.serviceMesh.patchNamespaces` is true
  - `global.serviceMesh.enabled` is true
  - `global.serviceMesh.type` is `linkerd`

Next steps:
1. Configure helm charts in `components/prepare/charts.yaml`
2. Configure values for every release in `components/prepare/values`
3. Update your README.md
4. Update component to `defaults/environment/global.yaml` - `components` list

Deploy the component with:
$ # navigate to `deployment/` and run:
$ helmfile apply -i --selector component=prepare

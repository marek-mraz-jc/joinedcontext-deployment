# Releases

A release of the deployment is an annotated git tag `vX.Y.Z` (semver) on a commit of `main` that
carries `releases/vX.Y.Z.md` and its section in [CHANGELOG.md](../CHANGELOG.md). The files are the
only source: the notes list every pinned image by digest and the commit subjects, CHANGELOG.md is
rendered from the notes (`scripts/release.py changelog`; `tests/test_release.py` fails when the two
differ). Task T-4955.

## Cut

From a clean checkout of `main` as it is on origin:

```sh
just release patch          # or minor, major; prints the push
just release patch --push   # pushes main and the tag together (--atomic), never forced
```

`patch` for pins and fixes, `minor` for a new component or a new default, `major` for a change an
operator has to act on (a step in `releases/next.yaml`, a removed value). A tag is never moved or
deleted: a broken release is followed by the next patch.

## Apply

- `just prod-apply` applies only a commit that `scripts/release.py verify` accepts: an annotated
  `vX.Y.Z` tag on exactly that commit, the same tag on origin, a clean working tree. It refuses an
  untagged commit before `helmfile` runs.
- `just dev-apply` applies any commit of `main`.
- Both write the ConfigMap `jc-release` in the instance namespace (`dev`, `smartcity`): `version`
  (the tag, or `untagged`), `commit`, `describe`, `environment`, `appliedBy` (git `user.email`),
  `appliedAt`. `just upgrade` writes the same ConfigMap. Every smoke prints its first line from it:
  `release: v0.2.0 (v0.2.0) applied by … at …`.

## Roll back

Apply the previous tag the same way:

```sh
git fetch --tags origin
git switch --detach v0.1.1
KUBECONFIG=.secrets/kubeconfig-prod.yaml just prod-apply
KUBECONFIG=.secrets/kubeconfig-prod.yaml just prod-smoke   # prints release: v0.1.1
git switch main
```

The recipes of the tag run, so a tag cut before v0.2.0 applies without writing `jc-release`.
Database migrations stay applied: a rollback over a migration follows
`docs Deployment/07-backup-restore` §3, as `just upgrade` prints. The Argo CD `release` branch keeps
its own promotion tags (`prod-<UTC>`, annotated) through `just promote` and `just rollback`.

## Images of the platform's own repositories

The platform, Portal and Antares images go by digest; the CHANGELOG section of each release names
the three digests it pins. The same scheme holds there: an image is identified by its digest, a
release tag `vX.Y.Z` is annotated and never moved, and the deployment release that pins a digest
is what an environment runs.

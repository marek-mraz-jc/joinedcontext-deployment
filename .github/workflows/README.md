# Reusable workflows

The gates every repository of the platform runs, written once here and called from the others
(T-0010…T-0016). Each is `workflow_call` only; the caller decides when it runs.

| Workflow | What it gates | Requirements |
|---|---|---|
| `reusable-rust-ci.yml` | `cargo fmt --check`, `clippy -D warnings`, `cargo test` | TS-01, TS-04, OPS-40 |
| `reusable-rust-security.yml` | `cargo audit`, `cargo deny check advisories bans licenses sources` | TS-04, TS-24, OPS-41 |
| `reusable-gitleaks.yml` | secrets over the whole git history | OPS-37, CC-06, TS-24 |
| `reusable-manifest-lint.yml` | `kubeconform -strict`, then `conftest` over `policies/` | TS-18, TS-19, CC-12 |
| `reusable-helmfile-test.yml` | `helmfile template` per environment into `kyverno apply` | OPS-40, TS-19 |
| `reusable-container-scan.yml` | Trivy on the tree and the image, plus the CycloneDX SBOM | TS-23, OPS-41 |
| `reusable-container-sign.yml` | `cosign sign` and verify, refusing anything not named by digest | OPS-28, TS-23 |

```yaml
jobs:
  rust:
    uses: marek-mraz-jc/joinedcontext-deployment/.github/workflows/reusable-rust-ci.yml@main
    with: { test-args: "--workspace --lib --bins" }
```

Within this repository the same workflows are called by path
(`uses: ./.github/workflows/reusable-gitleaks.yml`); this repository runs the same scan as a step of the `tests` job of `ci.yml` (one billed job fewer, T-0521).

`ci.yml` is the only lane that runs on its own: one render job over the four environments and one
test job. This repository is private and its Actions minutes are metered, so `ci-full.yml` (Kyverno
on the rendered output, the eight k3d deployment variants, the nightly k3d deployment) runs on
`workflow_dispatch` only until the minutes are back; `kyverno test .ci/policies` also runs in the
test job, and the dev cluster (`just dev-apply` + `just dev-smoke`) is what proves a deployment
before anyone relies on it.

## What a caller has to know

- **Actions are pinned by commit**, never by tag. A tag is mutable, and a supply-chain gate
  that trusts a mutable reference is not a gate. `tests/test_reusable_workflows.py` fails on a
  `uses:` that is not a 40-character sha.
- **Two of them carry a copy of shared configuration** (`.ci/shared/deny.toml` and
  `.ci/shared/gitleaks.toml`) inside the workflow, because a caller's `GITHUB_TOKEN` cannot
  check out this private repository to read a file from it. The same test executes the step
  that writes the copy and fails when it stops matching the source. A repository that ships
  its own `deny.toml` or `.gitleaks.toml` keeps it: an exception needs a reason written beside
  it, and this is only what applies when there is none.
- **A private repository's reusable workflow reaches only other private repositories of the
  same account** (`access_level: user`), and this repository is private. So
  `joinedcontext-portal`, `joinedcontext-conformace` and `joinedcontext-docs` can call these;
  `joinedcontext-platform`, which is public, cannot, and keeps the jobs in its own `ci.yml`
  until either it or this repository changes visibility. The account setting that opens the
  first three is Settings → Actions → General → Access on this repository, and only the owner
  can set it.

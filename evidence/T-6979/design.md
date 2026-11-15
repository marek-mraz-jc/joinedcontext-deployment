# T-6979 design: one code repository (deployment code into jc `deploy/`)

Author: worker-t6979, 2026-11-15. Facts measured on joinedcontext-deployment main 4e8f960eb and jc
main c61599fb (git ls-files, git grep, gitleaks 8.30.1). Nothing is moved by T-6979.

## 1. Target layout

### 1.1 jc (public, github.com/marek-mraz-jc/joinedcontext) gains `deploy/`

```
deploy/
  README.md                 existing (single-host form); gains a "cluster form" section
  rehearsal/                existing, unchanged
  helmfile-root.yaml.gotmpl     from deployment/ root
  helmfile-components.yaml.gotmpl
  component.schema.json
  justfile                  from deployment/justfile; node IPs and domains become settings (§3)
  tools.env  renovate.json  copier.yaml
  charts/  components/  defaults/  policies/  gitops/  images/  mcp-registry/
  template-component/  seeds/  scripts/  tests/  demos/  dev-deployment/  docs/
  cluster/hetzner/module/   the terraform module only (no clusters/*.tfvars)
  ci/                       from .ci/ minus the private parts:
    example-deployments/helmfile.yaml   environment list (all names, values: [] as today)
    example-deployments/environments/   the PUBLIC examples only:
        _layers addons broker-only local minimal production staging smoke-test recovery-test
    golden/  <public env>.txt only, ENVIRONMENTS lists public envs only
    configs kyverno linkerd policies shared vcluster gitleaks-rendered.toml model-tools.lock
    pinned-images-ignore.yaml release-gate-known-red.txt test-durations.json
  releases/  CHANGELOG.md   after the scrub in §2 (or left private, see §2.3)
```

Image pins (`components/*/images.yaml`) are digests and move with their component.

### 1.2 Private workspace repo (marek-mraz-jc/joinedcontext-workspace) gains `environments/`

```
environments/
  README.md                 what lives here and why (addresses, recipients, sops files)
  .sops.yaml                creation rules + age recipients (from deployment/.sops.yaml)
  jc-dev/  jc-prod/  smartcity/  stage/  dev/   (dev keeps RETIRED)   from .ci/example-deployments/environments/
  secrets/praha/praha-secrets-golemio.enc.yaml  (from components/context-gateway/seed/praha/)
  recipients.yaml           the ageRecipients today in components/{postgres,apps-db}/default-environment.yaml.gotmpl
  clusters/{dev,smartcity,stage}.tfvars          (from cluster/hetzner/clusters/; agents' server IP, acme e-mail)
  nodes.yaml                dev/stage/prod node IPs the justfile guards compare (today justfile:458, 999, 1059)
  golden/{jc-dev,jc-prod,smartcity,stage,dev}.txt  the private goldens
  tests/                    the env-specific assertions split out of deployment tests (§4.3)
  demos/bbsk/{dev,smartcity}.yaml   env values of the bbsk demo (critic #10)
  gitleaksignore.private    deployment's old .gitleaksignore (private commit fingerprints, critic #7)
  tools/render-parity.sh    full-manifest parity of old vs new checkout (§4.4)
```

The other private-only content of deployment (`evidence/`, 4 files incl. a 10k-line trivy.json)
goes to the workspace repo's `evidence/` or is dropped; it is not code.

Decided (worker-t6979, owner may override): `environments/` changes go by branch and merge on the
workspace repo like code (agent/<worker>/<id>, the integrator merges), and the hourly board
snapshot (board-snapshot.sh v2) keeps `environments/` OFF its allow-list, so a half-edited value is
never snapshotted. Options: snapshot it too (unreviewed values reach the deployer's checkout), a
third repo `joinedcontext-environments` (the supervisor decided two repos).

## 2. Public check (gate before any move)

### 2.1 gitleaks

`gitleaks dir` over the whole deployment work tree (47.95 MB, its .gitleaksignore applied): 1 hit,
`generic-api-key scripts/open-data/sdm/pins.json:6`. Read: the value is a git commit sha of a Smart
Data Models repository (`"dataModel.CPSV-AP": "a05d…"`), a false positive. The import adds its
fingerprint to jc's .gitleaksignore (or renames the key so the rule does not fire). No history moves
(§5), so `gitleaks git` is run on the one import commit only (`gitleaks git --log-opts=-1`), in the
import task.

### 2.2 Addresses, private hostnames, people, sops

| What | Where (deployment main) | Verdict |
|---|---|---|
| 116.203.134.249 dev node | justfile:458, jc-prod/global.yaml.gotmpl:188, releases/v0.1.0.md, tests/test_ci_changes.py + 3 more (7 files) | setting `JC_DEV_NODE_IP` from environments/nodes.yaml; tests use 203.0.113.10 (TEST-NET-3) |
| 2.28.56.179 prod node | justfile:999, tests/test_smartcity.py, tests/test_stage.py | setting; tests 203.0.113.20 |
| 2.31.157.248 stage node | justfile:1059, tests/test_stage.py | setting; tests 203.0.113.30 |
| 2.28.67.127 old dev node | tests/test_production_is_not_dev.py | test value 203.0.113.40 |
| 89.167.20.156 the agents' server (firewall allow-list) | cluster/hetzner/clusters/*.tfvars, tests/test_cluster_hetzner.py | tfvars stay private; test uses 198.51.100.7 |
| age recipients (3 keys; critic #2) | .sops.yaml, praha-secrets-golemio.enc.yaml, components/postgres + apps-db default-environment.yaml.gotmpl, tests/test_dr_drill.py:564, tests/test_stage.py:46 | private. The value moves into each private env's own `global.yaml.gotmpl` (jc-dev, jc-prod, smartcity, dev; stage already overrides it), which helmfile-components already loads; the component default becomes a documented test recipient generated once for the public examples (its private half discarded), so public renders keep working and differ in that one field only. tests/test_sops_recipients.py moves to environments/tests. Tests use a recipient generated in tmp_path |
| sops/ENC[] files | praha-secrets-golemio.enc.yaml (2 ENC values), named by components/context-gateway/seed/praha/index.yaml:199 | private (environments/secrets/praha/). The seed index gets the file from a value `seed.encryptedFiles` the env sets to `$JC_ENVIRONMENTS/secrets/...`; the public index.yaml drops line 199; absent value = entry skipped. Parity case for `_layers/hosted`, jc-dev, jc-prod (critic #3) |
| marek.mraz@joinedcontext.com | tfvars acme_email, smartcity/stage initialUserEmail, tests/test_keycloak_people.py:114, test_parity.py:95, test_smartcity.py:69 | env values private; tests use owner@example.org |
| contact@marek-mraz.com (security.txt contact) | dev/jc-dev/jc-prod/smartcity/stage global, tests/test_security_txt.py:52 | it is published in security.txt by design, but a personal address: env private, test uses security@example.org |
| marek-mraz-jcx (old org) | tests/test_runtime_policies.py:532 | public org name, fine (it is a negative test case) |
| `*.internal` | host.k3d.internal, registry.internal, host.docker.internal | generic names, no private system: public |
| *.joinedcontext.com domains, env names in example helmfile.yaml, demos/bbsk/environments/{dev,smartcity}.yaml | env values, docs, tests, demos | Rule (critic #10): our own public FQDNs and environment NAMES may be public; IPs, recipients, personal e-mails, tfvars, ENC never. demos/bbsk/environments/{dev,smartcity}.yaml move to the private overlay (they are env values); the example helmfile.yaml keeps the names, its comments lose the instance descriptions |
| org contacts in seeds (…@vkmk.sk, …@hel.fi) | seeds and gitea sample apps | published open-data or synthetic demo users: public |
| 1.1.1.1, 8.8.8.8, 185.199.109.133 (GitHub Pages) | cluster module, smoke.sh, test_render_retry.py | public services: public |

Already public in jc today (found by this check): 116.203.134.249 in
`deploy/rehearsal/tests/test_rehearsal.py:175`, `vendor/joinedcontext-platform/crates/jc-core/src/address.rs:176`
and `crates/jc-core/src/kinds/sync.rs:792` (test inputs). The address is the A record of
dev.joinedcontext.com, so it leaks nothing DNS does not, but the import task replaces it with
203.0.113.10 in the same commit so the rule "no server address in jc" holds and a grep test can
enforce it (§4.4).

Also private (critic #7): deployment's `.gitleaksignore` (35 `commit:file` fingerprints from private
history). jc's entries start fresh with the import commit's own fingerprint only; public-check fails on
a 40-hex sha in an ignore file that is not in jc's history.

### 2.3 Release notes and changelog

releases/v0.1.*.md (26 files) and CHANGELOG.md (72 hits on hetzner/marek names) are history, not
code. Decided: they stay private (environments repo `releases/`); jc gets only a one-line pointer
in deploy/README.md. Option: scrub and move (costs a review of 27 files for little value).

### 2.4 The gate script

The import task ships `deploy/ci/public-check.sh` (run in jc ci.yml `deploy` job and in the
import branch before push): fails on any global IPv4 outside an allow-list (1.1.1.1, 8.8.8.8,
9.9.9.9, GitHub Pages, TEST-NET ranges), any `age1[0-9a-z]{58}`, any `ENC[` or `sops:` mapping, any
`.tfvars`, and any address from environments/nodes.yaml (the last one runs only where the private
checkout exists: tasks/autocheck). Its own test feeds it one file per rule.

It runs BEFORE anything reaches GitHub (critic #4): jc is public and ci.yml runs on push to
`agent/**`, so a red check after the push is already a leak that no force-push may remove.
`tasks/push` and `tasks/merge` run `deploy/ci/public-check.sh` plus `gitleaks git` on the outgoing
range for every jc push and refuse on a hit; CI is the second line. Allow-list baseline (critic
#11): task 2 runs the check over the archived tree, matches dotted quads only outside version
fields, and commits the allow-list with a reason per entry before the first jc push.

## 3. How helmfile reads private values: one path setting

Today `just _dev-assemble` copies `.ci/example-deployments/environments/.` into `deployment/environments/`
and the helmfiles read `deployment/environments/<env>/*.yaml.gotmpl`. That copy step is the seam:

```
JC_ENVIRONMENTS ?= ""   # e.g. /workspace/agents/deployer/joinedcontext-workspace/environments
_dev-assemble:
  cp -r ci/example-deployments/environments/. deployment/environments/       # public examples
  [ -n "$JC_ENVIRONMENTS" ] && cp -r "$JC_ENVIRONMENTS"/. deployment/environments/   # private overlay
```

- A private env name with no `JC_ENVIRONMENTS` set fails before helmfile with
  `environment jc-dev is private: set JC_ENVIRONMENTS to the environments/ checkout`.
- A private dir that also exists as a public example is refused (no silent shadowing).
- Node IPs: the justfile reads `nodes.yaml` from `$JC_ENVIRONMENTS` (`yq .dev`); no default IP.
- The deployer's checkout is a clean clone of workspace main at a recorded sha, never the live
  /workspace tree, and dev-apply writes that sha into the `jc-release` configmap beside the jc
  commit (`envCommit`), so a render is reproducible from two shas.

## 4. CI

### 4.1 jc ci.yml: path-filtered `deploy` jobs

`.github/scripts/changes.sh` gains `deploy`: a rule `/^deploy\// { on["deploy"]="true"; next }`
placed BEFORE the catch-all at changes.sh:50-51, which today sets root=true (and so ship=true) for any
unmatched path, deploy/rehearsal included (critic #5); rehearsal keeps its trigger by a rule above it. New jobs gated on it, all on public examples only:
`deploy-render` (helmfile template + kubeconform + conftest + goldens of the public envs),
`deploy-tests` (pytest deploy/tests, sharded as deployment ci.yml `tests` is today),
`deploy-public-check` (§2.4). The Rust/UI/image outputs stay false for a deploy-only change.

smoke.yml (the 62-minute gate) gains `paths-ignore: ['deploy/**', 'docs/**']` on its push trigger,
and image.yml/ship do not run for deploy-only diffs. Test: `changes.sh` cases in its selftest
(deploy-only diff -> deploy=true, root/portal/antares/ui/image/ship=false; a crates/ diff ->
deploy=false).

### 4.1a The deployment repo's own workflows (critic #6)

Each of its 23 `.github/` files gets a verdict in the import task: ci.yml jobs merge into jc ci.yml
path-filtered with every private `-e dev|smartcity|jc-*` removed (deployment ci.yml:98,153 render
private envs today); image-{ckan,decidim,gitops,grafana,viz,patched}.yml, pin-images, pinned-images,
release-gate move as jc workflows gated on their deploy/images/<name>/** paths; sweep and the reusable
workflows merge or drop. The golden split also covers demo-bbsk-dev/smartcity (private) and the
orphan preview.txt (dropped).

### 4.2 Private environments: never rendered in public CI

GitHub Actions logs of a public repo are public, so jc CI never checks out environments/. The
private renders (jc-dev, jc-prod, smartcity, stage goldens and environments/tests) run:
- in tasks/autocheck on the host for every branch that touches jc `deploy/` or `environments/`
  (it already replays deployment ci.yml; it learns the overlay), and
- in the deployer's dev-apply (render before sync, as today).
The workspace repo's metered Actions minutes are not used (dispatch-only workflow kept for manual runs).

### 4.3 Tests that read private envs

23 test files read private environment dirs (test_smartcity.py, test_stage.py,
test_keycloak_people.py, test_security_txt.py, test_ci_changes.py, ...). One mechanism (critic #12):
the logic test stays in jc against a public example or a fixture env under
`deploy/tests/fixtures/environments/`; every assertion on real values ("stage reads prod",
"smartcity owner is X") moves to `environments/tests/`, which imports jc's `deploy/tests/conftest.py`
helpers via `PYTHONPATH` and runs in autocheck. No skip fixture in jc.

### 4.4 Render parity test (the cut-over proof)

For each env of `ENVIRONMENTS` (public) and each private env:
`helmfile -f deployment/helmfile.yaml -e <env> template` from the old deployment repo at sha A and
from jc deploy/ + environments/ at sha B, both through `scripts/render-all.sh`, as FULL multi-document YAML (documents sorted by kind/namespace/name, only checksum annotations and
generated random suffixes masked); `diff -r` must be empty. The goldens (`list-objects.py`, kind and
name only) stay an extra check, never the proof (critic #1). jc-dev and jc-prod are the release gate. The script
`environments/tools/render-parity.sh <old-checkout> <new-checkout> <env>...` lives in the PRIVATE
workspace repo (it needs the old private checkout, so public CI could never run it; critic #12), with a
selftest (two identical trees -> 0, one changed value -> 1). Expected, recorded diffs: none for
jc-dev/jc-prod/smartcity/stage; for public examples only the age recipient line (§2.2, critic #2).

## 5. History

Squashed import: one commit in jc, `deploy: import joinedcontext-deployment <sha> (code only)`,
built from `git archive <sha>` minus the private paths of §1.2 and §2.3 and with the §2.2
replacements applied. No `git subtree`, no `--allow-unrelated-histories`: no old commit, author line
or message of the private repo becomes public. The deployment repo is then archived read-only on
GitHub (Settings -> Archive) and stays private; its history stays there. `git log` archaeology of
deploy/ goes `jc import commit -> deployment <sha>` (named in the commit message).

## 6. How a pin bump lands

deploy-pin.yml today opens a PR `pin/jc-<sha>` on the deployment repo with DEPLOY_PIN_TOKEN. After:
the same script edits `deploy/components/jc/images.yaml` in jc and opens the PR against
jc-portal-1 (the merge branch). DEPLOY_PIN_TOKEN is re-scoped to jc only (Contents + Pull requests
write); a PR opened by GITHUB_TOKEN would start no workflow, so the token stays. Loop guard: a
pin-only diff gives `image=false` in changes.sh, so a pin never builds an image that pins again
(changes.sh selftest case). prod pins stay the prod-deployer's manual edit, now in jc.

## 7. Board tools and roles

| Tool | Change |
|---|---|
| tasks/merge (:107) | `repo: deployment` maps to jc with path deploy/; a task with `repo: jc + environments` merges the workspace branch first, then jc, in one lock |
| tasks/train | no deployment train any more; jc train includes deploy jobs; nothing else |
| tasks/autocheck (:44, plan_deployment :177, deployment_scope :231) | plan_deployment runs against jc `deploy/` with `JC_ENVIRONMENTS` = a clean worktree of the branch's workspace sha, `JC_REQUIRE_PRIVATE=1`; adds public-check.sh |
| tasks/ci (:108, :138) | drops joinedcontext-deployment from its repo map after archiving; reads jc's deploy jobs |
| tasks/deployed (:23) | the deployment repo key maps to jc; the env sha comes from jc-release `envCommit` |
| dispatcher | a `repo: deployment` task clones jc (+ workspace when it touches environments/) instead of the deployment repo |
| roles (proposal to the supervisor, not edited here) | deployer, prod-deployer, stage-deployer: `just` from `jc/deploy/` with `JC_ENVIRONMENTS` set; integrator(-2): one merge per change, environments branch first; worker.md: "deployment" means jc deploy/ |

A pin-image change no longer needs the T-6898 order "jc-prod, then deployment, then jc": the code
and its values ship in one jc merge, and only a new private value adds the environments branch,
which merges first (the jc render then fails loudly without it, §3).

## 8. Implementation tasks (each one repo, revertable)

1. **docs contract** (jc docs/): docs/Deployment pages name the layout, `JC_ENVIRONMENTS`, the
   public/private split rule and the public-check. Test: docs link check.
2. **settings first, in the deployment repo** (deployment): justfile node IPs, age recipients
   (into each env's global) and the Praha sops path read from env values / `JC_ENVIRONMENTS`; tests
   switched to TEST-NET and generated recipients; private-value assertions split out. Test: the touched
   test files + full-manifest render parity before/after on the same repo (diff empty for private envs,
   the recipient line only for public ones); public-check baseline run and allow-list.
3. **environments split** (workspace repo): `environments/` with the §1.2 tree copied from
   deployment main at the sha of task 2; the snapshot allow-list excludes it. Test:
   environments/tests green against deployment with JC_ENVIRONMENTS set.
4. **squashed import** (jc): deploy/ from `git archive` of task 2's sha minus private paths; jc's
   three test IPs replaced; the 23 deployment workflows each placed or dropped (§4.1a);
   public-check.sh wired into tasks/push first; a fresh .gitleaksignore (one entry). Test: public-check green,
   `gitleaks git --log-opts=-1`, render parity script green for every public env.
5. **CI jobs** (jc): changes.sh `deploy` output + selftest, deploy-render/tests/public-check jobs,
   smoke.yml paths-ignore, deploy-pin.yml into jc. Test: changes.sh selftest; one dispatched ci run
   by the integrator.
6. **board tools** (workspace tasks/): merge, autocheck, ci, deployed, dispatcher, each a temp file
   + selftest + mv. Test: each tool's selftest; autocheck replay of one deploy branch.
7. **cut-over** (deployer, no repo change): environments/ re-derived and diffed (empty), render parity
   old repo vs jc+environments for jc-dev and jc-prod (full manifests, diff empty, output in the task), then `just dev-apply` from jc/deploy; dev-smoke green.
   prod-deployer does the same for smartcity/stage on their windows.
8. **archive** (deployment repo + roles): last commit README "moved to jc deploy/", after the bake time above archive the
   repository read-only; supervisor applies the role-file proposal; render-parity.sh removed.

Freeze between 4 and 7: deployment main takes no merge except a red fix after task 2's sha;
any one that lands is re-imported as a follow-up jc commit (diff of the two deployment shas). At
cut-over (task 7) `environments/` is re-derived from deployment main and diffed against the workspace
copy; task 7 fails unless that diff is empty (critic #8).

Rollback (critic #9): task 8 waits for 24 h and at least 5 green dev-applies from jc plus one
prod-deployer window. Until then the deployment repo stays writable and `just dev-apply` from
deployment at the recorded sha is the rollback, written into task 7's body. render-parity.sh stays in
the workspace repo after archiving.

## Related

- T-6898 (merge order across three repos), T-6965 (jc.toml keys mirrored in deployment values)
- deployment justfile `_dev-assemble`, helmfile-root.yaml.gotmpl:14, helmfile-components.yaml.gotmpl:10-14
- jc .github/workflows/{ci,smoke,deploy-pin}.yml, .github/scripts/changes.sh

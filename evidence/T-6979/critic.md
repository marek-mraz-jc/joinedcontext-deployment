# T-6979 critic: table and answers

Critic: a separate Claude general-purpose subagent, 2026-11-15, read design.md v1 and verified
claims in both clones (read-only, 14 tool calls). Answers by worker-t6979; design.md v2 carries
each fix, marked `critic #n`.

| # | sev | finding | answer |
|---|---|---|---|
| 1 | high | Parity "normalised like goldens" proves nothing: list-objects.py prints only kind/namespace/name | Accepted. §4.4: full-manifest diff (sorted docs, checksums and random suffixes masked); goldens only an extra check |
| 2 | high | Dropping the component ageRecipients default breaks renders; nothing loads environments/recipients.yaml | Accepted. Recipient moves into each private env's global.yaml.gotmpl (already loaded); public examples get a test recipient; the one-line public diff is the recorded expectation |
| 3 | high | Praha sops file is named by public seed/praha/index.yaml:199 and used by _layers/hosted, jc-dev, jc-prod; the overlay never puts it back | Accepted. Seed reads encrypted files through a value set by the env to $JC_ENVIRONMENTS/secrets/...; public index drops the line; parity case for hosted |
| 4 | high | public-check after the push is too late: jc is public and ci.yml runs on agent/** pushes; no force-push | Accepted. public-check + gitleaks git on the outgoing range run inside tasks/push and tasks/merge before any jc push; CI is the second line |
| 5 | high | changes.sh catch-all sets root=true, ship=true for any unmatched path: a pin PR would build and pin again | Accepted. `deploy` rule with `next` before the catch-all; selftest: pin-only diff gives ship=false |
| 6 | medium | deployment's 23 .github workflows are missing from the tree; its ci.yml renders dev and smartcity | Accepted. §4.1a: a verdict per workflow, private -e removed, image builds gated by path |
| 7 | medium | .gitleaksignore carries 35 private commit shas | Accepted. Stays private; jc starts a fresh one; public-check rule for foreign shas in ignore files |
| 8 | medium | env-value fixes on deployment main during the freeze reach neither copy | Accepted. Task 7 re-derives environments/ from deployment main and requires an empty diff |
| 9 | medium | no rollback or bake time before archiving | Accepted. 24 h + 5 green dev-applies + one prod window before task 8; rollback command in task 7 |
| 10 | medium | public FQDNs and bbsk demo env files not ruled on | Accepted. Rule written (own public FQDNs and env names public; IPs, recipients, personal e-mails, tfvars, ENC never); bbsk demo envs private |
| 11 | low | IPv4 allow-list will false-positive on vendored charts | Accepted. Baseline run over the archived tree in task 2, allow-list with reasons before the first jc push |
| 12 | low | render-parity.sh in public jc can never run there; two mechanisms for the test split; task 2 "full pytest" | Accepted. Script lives in the workspace repo; one mechanism (private assertions only in environments/tests, no skip fixture); task 2 runs touched files + parity |

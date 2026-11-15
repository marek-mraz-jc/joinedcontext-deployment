# T-6979 public check (deployment main 4e8f960eb, 2026-11-15, worker-t6979)

- `gitleaks dir .` (8.30.1, repo .gitleaksignore applied), 47.95 MB: 1 finding,
  generic-api-key scripts/open-data/sdm/pins.json:6 = a Smart Data Models git commit sha, false positive.
- `gitleaks git`: not run; no history moves (squashed import). The import task runs it on its one commit.
- Global IPv4 (git grep + python ipaddress.is_global, minus 1.1.1.1/8.8.8.8/9.9.9.9): 5 server
  addresses in 14 files (dev node, prod node, stage node, old dev node, the agents' server); the
  other hits are RFC/ETSI clause numbers (2.3.1.3, 3.8.4.3, ...) and GitHub Pages. Every server
  address becomes a setting or a TEST-NET value (design §2.2).
- age recipients: 3 keys in .sops.yaml, 1 enc file, 2 component defaults, 2 tests -> private.
- sops/ENC[]: 1 file (praha-secrets-golemio.enc.yaml) -> private.
- Personal e-mails: 2 addresses in env values, tfvars and 5 tests -> private / example.org.
- Private hostnames: none (`*.internal` hits are k3d/docker/test names).
- Private commit shas: .gitleaksignore (35 lines) -> private.
- jc already public: the dev node IP in 3 test files (deploy/rehearsal/tests/test_rehearsal.py:175,
  vendor/.../jc-core/src/address.rs:176, kinds/sync.rs:792). It is the dev.joinedcontext.com A record;
  the import task replaces it with 203.0.113.10.
Verdict: the move is safe only with the design §2.2 replacements and §2.4 pre-push gate.

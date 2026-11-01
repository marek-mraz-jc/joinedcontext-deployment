# Decidim

The city's own participation platform (ADR-N-065, docs Deployment/18): Decidim 0.32 on
`participacia.{domain}`, every person signing in through the instance's realm. Its public
GraphQL API at `/api` is what the participation harvester reads (T-5065, T-6317).

Deploy the component with:
```bash
helmfile apply -i --selector component=decidim
```

## What it deploys

Three releases of `charts/workload`, one image (`images/decidim`, published by
`.github/workflows/image-decidim.yml`, run by hand only: it scans the image before it pushes,
and the six HIGH findings of ADR-N-065 section 4 stop it until Decidim lifts its gem pins or the
owner accepts them; its push and schedule triggers sit in a comment beside `on:`):

- **decidim-web**: puma on 3000 behind the edge. Its init container `migrate` runs
  `bin/rails db:migrate` and `db/joinedcontext_bootstrap.rb`, which creates the one
  organization, keeps its registration mode at `existing` (no Decidim sign-up form) and gives
  `decidim.web.adminEmail` the admin flag. Attachments go on the 5 GiB claim `decidim-web-files`.
- **decidim-sidekiq**: the background jobs (mail, notifications, exports), same image and claim.
- **decidim-redis**: Sidekiq's queue and Action Cable, persistence off.

PostgreSQL comes from CloudNativePG through `databases.yaml`: database and role `decidim`.

## Sign-in

`keycloak-clients.yaml` declares the confidential client `decidim` (standard flow, PKCE); the
image's initializer registers it as the one enabled provider and drops any e-mail address the
realm has not verified, so a sign-in never links to an account by an unverified address. The
edge refuses `/system`, `/users/password`, `/users/invitation` and `/users/sign_up`
(`apisix-plugins.yaml`), so no account gains a local password.

## Before installing

1. Pin the digest the image workflow prints in `images.yaml` (`web` and `sidekiq`). The pin in
   the repository is the T-6316 local build, which no registry serves.
2. Set `decidim.web.adminEmail`, and `decidim.web.smtp` for mail.
3. Add `decidim` to the environment's `components` and regenerate `gitops/<env>.yaml`.

Sizing and the measured run: docs Deployment/18 section 5.

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
`.github/workflows/image-decidim.yml`, which scans the image before it pushes, on every change
under `images/decidim` and monthly):

- **decidim-web**: puma on 3000 behind the edge. Its init container `migrate` runs
  `bin/rails db:migrate` and `db/joinedcontext_bootstrap.rb`, which creates the one
  organization, keeps its registration mode at `existing` (no Decidim sign-up form) and gives
  `decidim.web.adminEmail` the admin flag. Attachments go on the 5 GiB claim `decidim-web-files`.
- **decidim-sidekiq**: the background jobs (mail, notifications, exports), same image and claim.
- **decidim-redis**: Sidekiq's queue and Action Cable, persistence off.

PostgreSQL comes from CloudNativePG through `databases.yaml`: database and role `decidim`.


## The city's site (T-6453)

`decidim.web.site.content: true` runs `images/decidim/site.rb` after the bootstrap on every rollout.
It sets name, colours, time zone, logo, favicon, home page blocks and a privacy page, and creates each
process of `images/decidim/site/content.yml` that is not there yet, whole, in one transaction: a
rerun adds nothing, and what an admin changed in a process stays. `demoNotice: true` adds the demo
banner and the footer line. Stage shows the notice and takes the content with the first main-signed image that holds the site; prod has both off until the owner approves stage. The
logo and images in `images/decidim/site/` are drawn for this site, because the licence of the city's
own logo is not on record: replace the files to change them. An attachment already on the claim is
kept, so a new file needs the old one removed in the admin first. Content comes from the public record of
tvormespolu.banskabystrica.sk, without the proposer contact lines those pages open with.

## Sign-in

`keycloak-clients.yaml` declares the confidential client `decidim` (standard flow, PKCE); the
image's initializer registers it as the one enabled provider and drops any e-mail address the
realm has not verified, so a sign-in never links to an account by an unverified address. The
edge refuses `/system`, `/users/password`, `/users/invitation` and `/users/sign_up`
(`apisix-plugins.yaml`), so no account gains a local password.

## Before installing

1. Set `decidim.web.adminEmail`, and `decidim.web.smtp` for mail. On a production-profile realm
   `global.participationStewardId` seeds the person who holds that address (T-6448).
2. Add `decidim` to the environment's `components` and regenerate `gitops/<env>.yaml`.

Sizing and the measured run: docs Deployment/18 section 5.

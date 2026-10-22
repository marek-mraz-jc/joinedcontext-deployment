# Keycloak

Central identity management of the platform

Next steps:
1. Configure helm charts in `components/keycloak/charts.yaml`
2. Configure values for every release in `components/keycloak/values`
3. Update your README.md
4. Update component to `defaults/environment/global.yaml` - `components` list

Deploy the component with:
$ # navigate to `deployment/` and run:
$ helmfile apply -i --selector component=keycloak

## Login hardening (T-5120)

The realm import (`values/config/base-values.yaml.gotmpl`) sets the same rules on dev and production;
`tests/test_keycloak_login_hardening.py` asserts them for the dev, production and smartcity renders.

| Setting | Value |
|---|---|
| Second factor | TOTP required for every holder of realm role `mfa-required`: portal-approver and platform-admin carry it as a composite, and it can be granted to anyone directly. A holder without TOTP enrols at the next login (Keycloak's CONFIGURE_TOTP page). Everyone else is asked for TOTP or WebAuthn only once they configured one. |
| Password grant | Flow `custom direct grant` asks the same: a holder of `mfa-required` sends `totp=<code>` with the password, and one who has not enrolled gets no token (Keycloak answers `unknown_error` and logs an AuthenticationFlowException of direct-grant-validate-otp; enrolment happens in the browser). Everyone else sends a code only once they configured TOTP. |
| TOTP | HMAC-SHA256, 6 digits, 30 s, look-ahead 1. Use an app that honours the algorithm (FreeOTP, Aegis, 1Password, KeePassXC); some versions of Google Authenticator compute SHA-1 codes and every code fails. |
| Brute force | The 10th wrong password within 12 h locks the account for 60 s; every further 10 add 60 s, up to 15 min. A retry faster than 1 s after a failure waits 60 s. Never a permanent lockout. |
| Password policy | 12+ characters with an upper, a lower and a digit; not the username, not the e-mail, none of the last 5. |
| SSO session | 60 min idle, 10 h at most; no remember-me. |
| Access token | 5 min (production profile); 60 min where the development values apply (dev, and smartcity through `valuesProfile: development`). Refresh tokens live as long as the SSO session. |

Demo people holding an MFA role (demo.steward, demo.approver) get a generated TOTP seed beside their
password in Secret `keycloak-user-<name>`, key `totp`. The journeys compute the code from it
(`scripts/smoke-forge-login.sh`, `scripts/keycloak-login-journey.py`, the Portal's live journeys);
a real person's factor is never seeded. Read a seed only into an environment variable, never into
a file, log or task.

Check the rules in a browser after an apply (the throwaway checks create and delete their own user):

```bash
export JC_LOGIN_PASSWORD=... JC_LOGIN_TOTP=...           # keycloak-user-demo-steward: password, totp
scripts/keycloak-login-journey.py --base https://<keycloak host> --realm <slug> --user demo.steward@<org> steward
export KC_ADMIN_USER=... KC_ADMIN_PASSWORD=...           # keycloak-admin-user
scripts/keycloak-login-journey.py --base https://<keycloak host> --admin-base http://localhost:8080 --realm <slug> enrol
scripts/keycloak-login-journey.py --base https://<keycloak host> --admin-base http://localhost:8080 --realm <slug> lockout
export JC_GRANT_CLIENT_ID=apisix-gateway JC_GRANT_CLIENT_SECRET=...  # its client Secret
scripts/keycloak-login-journey.py --base https://<keycloak host> --admin-base http://localhost:8080 --realm <slug> grant
```

### Break-glass

The `master` realm's admin (Secret `keycloak-admin-user`) is the way back in when a steward loses
their phone or locks themselves out. It is reached only from inside the cluster with the kubeconfig,
which lives outside every repository; the password is never written down anywhere else.

```bash
kubectl port-forward -n <slug> svc/keycloak-app-keycloakx-http 8080:80 &
# -it and no --password: kcadm prompts for it, so the password stays out of every process list
# and shell history.
kubectl exec -it -n <slug> deploy/keycloak-app-keycloakx -- /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master --user admin
# lift a lockout:            kcadm.sh delete attack-detection/brute-force/users/<user-id> -r <slug>
# make a lost TOTP re-enrol: kcadm.sh delete users/<user-id>/credentials/<otp-credential-id> -r <slug>
```

Each step is in the admin event log (`adminEventsEnabled`); name the person and the reason in the
task or incident that needed it.

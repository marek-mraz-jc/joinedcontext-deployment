{{- /* The environment web, its migrate init container and Sidekiq share (T-6316): one list,
       rendered by `tpl` from each part's base values with (global, web, pg, host). */ -}}
env:
{{- $global := .global }}
{{- $web := .web }}
- name: DATABASE_URL
  value: {{ printf "postgres://decidim@%s:5432/decidim?sslmode=require" .pg | quote }}
- name: DATABASE_PASSWORD
  valueFrom: { secretKeyRef: { name: db-decidim, key: password } }
- name: SECRET_KEY_BASE
  valueFrom: { secretKeyRef: { name: decidim-secret-key-base, key: secret } }
- name: REDIS_URL
  value: {{ printf "redis://decidim-redis.%s.svc.cluster.local:6379/1" $web.namespace | quote }}
# Request lines carry client addresses, personal data under GDPR: warnings and errors only.
- name: RAILS_LOG_LEVEL
  value: warn
- name: RAILS_MAX_THREADS
  value: "5"
- name: DECIDIM_HOST
  value: {{ .host | quote }}
- name: DECIDIM_ORGANIZATION_NAME
  value: {{ $web.organization.name | quote }}
- name: DECIDIM_DEFAULT_LOCALE
  value: {{ $web.organization.defaultLocale | quote }}
- name: DECIDIM_LOCALES
  value: {{ join "," $web.organization.locales | quote }}
- name: DECIDIM_REFERENCE_PREFIX
  value: {{ $web.organization.referencePrefix | quote }}
- name: DECIDIM_ADMIN_EMAIL
  value: {{ $web.adminEmail | quote }}
- name: DECIDIM_SITE_CONTENT
  value: {{ $web.site.content | quote }}
- name: DECIDIM_SITE_DEMO_NOTICE
  value: {{ $web.site.demoNotice | quote }}
- name: DECIDIM_PORTAL_URL
  value: {{ printf "https://portal.%s" $global.domain | quote }}
- name: DECIDIM_CATALOGUE_URL
  value: {{ printf "https://opendata.%s" $global.domain | quote }}
- name: OIDC_ISSUER
  value: {{ printf "https://idm.%s/realms/%s" $global.domain $global.instanceSlug | quote }}
- name: OIDC_CLIENT_ID
  value: decidim
- name: OIDC_CLIENT_SECRET
  valueFrom: { secretKeyRef: { name: keycloak-client-decidim, key: client-secret } }
- name: OIDC_REDIRECT_URI
  value: {{ printf "https://%s/users/auth/keycloak/callback" .host | quote }}
{{- if $web.smtp.address }}
- name: SMTP_ADDRESS
  value: {{ $web.smtp.address | quote }}
- name: SMTP_PORT
  value: {{ $web.smtp.port | quote }}
- name: SMTP_USERNAME
  value: {{ $web.smtp.username | quote }}
- name: SMTP_DOMAIN
  value: {{ .host | quote }}
- name: SMTP_PASSWORD
  valueFrom: { secretKeyRef: { name: {{ required "decidim.web.smtp.passwordSecret names the Secret with the SMTP password" $web.smtp.passwordSecret }}, key: password } }
- name: MAILER_SENDER
  value: {{ required "decidim.web.smtp.from is the sender address" $web.smtp.from | quote }}
{{- end }}

{{- /*
  The standalone APISIX rule file, indented to sit under a `apisix.yaml: |` key. Every component
  contributes routes and plugin configs through components/<c>/apisix-routes.yaml and
  apisix-plugins.yaml. The `#END` marker is required by APISIX standalone mode.
*/}}
{{- define "configuration.standalone" }}
    plugin_configs:
{{- range $id, $config := .Values.plugins }}
      - id: {{ $id }}
        desc: {{ $config.description | default $config.name | quote }}
        {{- /* The Portal sets this chain's limit-count to the Organization's rate for the class
               when it composes the served file (ADR-N-035, T-2892). */}}
        {{- with $config.rateClass }}
        labels:
          jc-rate-class: {{ . | quote }}
        {{- end }}
        plugins:
{{/* ${DOMAIN_RE} is the domain with its dots escaped, for a plugin that matches an Origin
     with a regular expression: an unescaped dot matches any character, so `.+\.${DOMAIN}`
     also admits a look-alike host somebody else can register (T-1679). */}}
{{ ($config.plugins | default dict) | toYaml | replace "${REALM}" $.Values.realm | replace "${DOMAIN_RE}" ($.Values.domain | replace "." "[.]") | replace "${DOMAIN}" $.Values.domain | replace "${APISIX_GATEWAY_CLIENT_SECRET}" "${{APISIX_GATEWAY_CLIENT_SECRET}}" | replace "${OIDC_SESSION_SECRET}" "${{OIDC_SESSION_SECRET}}" | replace "${EDGE_CLIENT_SECRET}" "${{EDGE_CLIENT_SECRET}}" | indent 10 }}
{{- end }}
    upstreams:
{{- range $id, $config := .Values.routes }}
      - id: {{ $id }}
        type: roundrobin
        {{- if hasKey $config "scheme" }}
        scheme: {{ $config.scheme }}
        pass_host: {{ $config.passHost | default "pass" }}
        {{- end }}
        nodes:
          {{ $config.upstream | quote }}: 1
        timeout:
          connect: {{ ($config.timeout | default dict).connect | default 6 }}
          send: {{ ($config.timeout | default dict).send | default 30 }}
          read: {{ ($config.timeout | default dict).read | default 30 }}
        {{- with $config.keepalivePool }}
        keepalive_pool:
          size: {{ .size | default 320 }}
          idle_timeout: {{ .idleTimeout | default 60 }}
          requests: {{ .requests | default 1000 }}
        {{- end }}
{{- end }}
    routes:
{{- range $id, $config := .Values.routes }}
      - id: {{ $id }}
        name: {{ $config.name | quote }}
        desc: {{ $config.description | default $config.name | quote }}
        uri: {{ $config.uri | quote }}
        {{- if hasKey $config "priority" }}
        priority: {{ $config.priority }}
        {{- end }}
        {{- if hasKey $config "methods" }}
        methods: {{ $config.methods | toJson }}
        {{- end }}
        {{- if hasKey $config "vars" }}
        vars: {{ $config.vars | toJson }}
        {{- end }}
        {{- if hasKey $config "subDomain" }}
        host: {{ printf "%s.%s" $config.subDomain $.Values.domain | quote }}
        {{- else if hasKey $config "hosts" }}
        hosts: {{ $config.hosts | toJson }}
        {{- else if hasKey $config "host" }}
        host: {{ $config.host | quote }}
        {{- end }}
        upstream_id: {{ $id }}
        {{- $pluginConfig := $config.pluginConfig | default $id }}
        {{- if hasKey $.Values.plugins $pluginConfig }}
        plugin_config_id: {{ $pluginConfig }}
        {{- end }}
        {{- with $config.rateClass }}
        labels:
          jc-rate-class: {{ . | quote }}
        {{- end }}
        {{- /* A route-level plugin replaces the same plugin of its plugin config: the one way a
               route shares a chain and counts a bucket of its own (T-2892). */}}
        {{- with $config.plugins }}
        plugins:
{{ toYaml . | indent 10 }}
        {{- end }}
{{- end }}
    #END
{{- end }}

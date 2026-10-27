{{- /* The release name of one broker, as jc_core::kinds::mqtt_broker::release_name makes it:
       its ServiceAccount, so its mesh identity, and its Keycloak audience. */ -}}
{{- define "brokers.release" -}}
{{- printf "mqtt-%s-%s" .project .name -}}
{{- end }}

{{- /* The labels of a broker's objects: `managedBy` is Helm for one this chart installs and
       joinedcontext-portal for one the Portal stamps from the template, which it retires by. */ -}}
{{- define "brokers.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version }}
app.kubernetes.io/managed-by: {{ .managedBy }}
app.kubernetes.io/part-of: mqtt-brokers
{{- end }}

{{- define "brokers.image" -}}
{{- printf "%s:%s@%s" .Values.image.repository .Values.image.tag (required "image.digest pins RMQTT" .Values.image.digest) }}
{{- end }}

{{- /* Every object of one broker, from a dict: root (the chart's context), release, project, name,
       host, maxBytes, perSecond, connections, checksum, managedBy. Rendered per broker below and
       once with sentinels into the template the Portal fills (T-3994). */ -}}
{{- define "brokers.objects" -}}
{{- $root := .root }}
{{- /* The HTTP API on 6060, which the Portal reads (ADR-N-048 §2.8, T-4043): only under the mesh,
       which admits the Portal's identity on two GET routes; without it, nothing would. */}}
{{- $api := and $root.Values.serviceMesh.enabled $root.Values.portal.namespace }}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .release }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
automountServiceAccountToken: false
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .release }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
data:
  rmqtt.toml: |
    node.id = 1
    # Standard output only: the root filesystem is read-only and nothing is kept.
    log.to = "console"
    log.level = "info"
    plugins.dir = "/etc/rmqtt/plugins/"
    plugins.default_startups = ["rmqtt-acl", "rmqtt-auth-http"]
    {{- if $api }}
    # The HTTP API on 6060, reached through the mesh only (the Servers below).
    plugins.disabled_default_startups = []
    {{- else }}
    # Started by the binary unless named here: an HTTP API and dashboard on 6060 with no token.
    plugins.disabled_default_startups = ["rmqtt-http-api"]
    {{- end }}
    # The node-to-node gRPC of a cluster; one node, so loopback.
    rpc.server_addr = "127.0.0.1:5363"
    # The binary opens these by default, with the self-signed certificate inside the image.
    listener.tls.external.enable = false
    listener.ws.external.enable = false
    listener.wss.external.enable = false
    listener.quic.external.enable = false
    # RMQTT 0.24 has no per-publisher rate: `mqueue_rate_limit` caps delivery to each subscriber,
    # and the gateway's publish check refuses a client above messagesPerSecond, which
    # disconnect_if_pub_rejected turns into a disconnect (T-5562).
    {{- range $listener := list (dict "name" "internal" "port" 1883 "proxy" false) (dict "name" "external" "port" 1884 "proxy" true) }}
    {{- $l := printf "listener.tcp.%s" $listener.name }}
    {{ $l }}.enable = true
    {{ $l }}.addr = "0.0.0.0:{{ $listener.port }}"
    {{ $l }}.max_connections = {{ $.connections }}
    {{ $l }}.max_packet_size = "{{ $.maxBytes }}B"
    {{ $l }}.allow_anonymous = false
    {{ $l }}.max_qos_allowed = 1
    {{ $l }}.session_expiry_interval = "0s"
    {{ $l }}.max_session_expiry_interval = "0s"
    {{ $l }}.max_mqueue_len = 1000
    {{ $l }}.mqueue_rate_limit = "{{ $.perSecond }},1s"
    {{ $l }}.proxy_protocol = {{ $listener.proxy }}
    {{- end }}
  rmqtt-auth-http.toml: |
    http_timeout = "5s"
    disconnect_if_pub_rejected = true
    # The token's `exp` ends the connection; the device reconnects with a fresh one.
    disconnect_if_expiry = true
    # The gateway unreachable is a refusal, never a pass to the next plugin.
    deny_if_error = true
    http_auth_req.url = {{ required "authUrl names the gateway's CONNECT check" $root.Values.authUrl | quote }}
    http_auth_req.method = "post"
    http_auth_req.headers = { content-type = "application/json" }
    http_auth_req.params = { clientid = "%c", username = "%u", password = "%P", ipaddr = "%a" }
    # Every publish asks the gateway, beside the CONNECT check: the CONNECT answer carries the
    # subscriptions only, so a device whose role, account or credential ends is refused, and
    # with disconnect_if_pub_rejected disconnected, within the X-Cache time of the gateway's
    # allow (10 s) instead of at its token's exp (T-5560).
    http_acl_req.url = {{ printf "%s/acl" (trimSuffix "/auth" $root.Values.authUrl) | quote }}
    http_acl_req.method = "post"
    http_acl_req.headers = { content-type = "application/json" }
    http_acl_req.params = { access = "%A", clientid = "%c", username = "%u", topic = "%t" }
  {{- if $api }}
  rmqtt-http-api.toml: |
    http_laddr = "0.0.0.0:6060"
    max_row_limit = 1000
    http_request_log = false
    # The Portal reads the two newest samples; a week of them (the default) would sit in memory.
    history_retention = "5m"
  {{- end }}
  rmqtt-acl.toml: |
    disconnect_if_pub_rejected = true
    # The last member of the chain: whatever the gateway did not allow is refused.
    rules = [["deny", "all"]]
---
apiVersion: v1
kind: Service
metadata:
  name: {{ .release }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
  annotations:
    config.linkerd.io/opaque-ports: "1883,1884"
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: mqtt-broker
    app.kubernetes.io/instance: {{ .release }}
  ports:
    - name: mqtt-internal
      port: 1883
      targetPort: 1883
      protocol: TCP
    - name: mqtt-external
      port: 1884
      targetPort: 1884
      protocol: TCP
    {{- if $api }}
    - name: http-api
      port: 6060
      targetPort: 6060
      protocol: TCP
    {{- end }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .release }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/name: mqtt-broker
    app.kubernetes.io/instance: {{ .release }}
spec:
  replicas: 1
  # No state to hand over: a new pod starts empty and the clients reconnect.
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app.kubernetes.io/name: mqtt-broker
      app.kubernetes.io/instance: {{ .release }}
  template:
    metadata:
      labels:
        {{- include "brokers.labels" . | nindent 8 }}
        app.kubernetes.io/name: mqtt-broker
        app.kubernetes.io/instance: {{ .release }}
        joinedcontext.com/project: {{ .project | quote }}
      annotations:
        checksum/config: {{ .checksum | quote }}
        {{- if $root.Values.serviceMesh.enabled }}
        linkerd.io/inject: enabled
        config.linkerd.io/opaque-ports: "1883,1884"
        {{- end }}
    spec:
      serviceAccountName: {{ .release }}
      automountServiceAccountToken: false
      securityContext:
        {{- toYaml $root.Values.podSecurityContext | nindent 8 }}
      containers:
        - name: rmqtt
          image: {{ include "brokers.image" $root }}
          imagePullPolicy: {{ $root.Values.image.pullPolicy }}
          args: ["-f", "/etc/rmqtt/rmqtt.toml"]
          securityContext:
            {{- toYaml $root.Values.securityContext | nindent 12 }}
          ports:
            - name: mqtt-internal
              containerPort: 1883
              protocol: TCP
            - name: mqtt-external
              containerPort: 1884
              protocol: TCP
            {{- if $api }}
            - name: http-api
              containerPort: 6060
              protocol: TCP
            {{- end }}
          # No probe: a TCP probe from the kubelet is an unmeshed peer, which the Linkerd Servers
          # below refuse on both ports, and RMQTT serves no HTTP health without its HTTP API.
          resources:
            {{- toYaml $root.Values.resources | nindent 12 }}
          volumeMounts:
            - name: config
              mountPath: /etc/rmqtt
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: {{ .release }}
            items:
              - key: rmqtt.toml
                path: rmqtt.toml
              - key: rmqtt-auth-http.toml
                path: plugins/rmqtt-auth-http.toml
              - key: rmqtt-acl.toml
                path: plugins/rmqtt-acl.toml
              {{- if $api }}
              - key: rmqtt-http-api.toml
                path: plugins/rmqtt-http-api.toml
              {{- end }}
---
# TLS ends at the ingress controller with a certificate for this one host (HTTP-01, never a
# wildcard); the broker sees the client's address in the PROXY header.
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: {{ .release }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
spec:
  secretName: {{ .release }}-tls
  issuerRef:
    name: {{ $root.Values.clusterIssuer | quote }}
    kind: ClusterIssuer
  dnsNames:
    - {{ .host | quote }}
---
apiVersion: traefik.io/v1alpha1
kind: IngressRouteTCP
metadata:
  name: {{ .release }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
spec:
  entryPoints:
    - {{ $root.Values.entryPoint }}
  routes:
    - match: HostSNI(`{{ .host }}`)
      services:
        - name: {{ .release }}
          port: 1884
          proxyProtocol:
            version: 2
  tls:
    secretName: {{ .release }}-tls
    # BSI TR-02102-2, as on the HTTP edge (templates/tls-option.yaml, T-5562).
    options:
      name: mqtt-bsi-tr-02102
{{- if $root.Values.serviceMesh.enabled }}
{{- range $listener := list (dict "name" "internal" "port" 1883 "sa" $root.Values.runner.serviceAccount "ns" $root.Values.runner.namespace) (dict "name" "external" "port" 1884 "sa" $root.Values.ingress.serviceAccount "ns" $root.Values.ingress.namespace) }}
{{- $server := printf "%s-%s" $.release $listener.name }}
---
# {{ $listener.port }} refuses every identity but the ones below, whatever the NetworkPolicy lets through.
apiVersion: policy.linkerd.io/v1beta3
kind: Server
metadata:
  name: {{ $server }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" $ | nindent 4 }}
    app.kubernetes.io/instance: {{ $.release }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: mqtt-broker
      app.kubernetes.io/instance: {{ $.release }}
  port: {{ $listener.port }}
  proxyProtocol: opaque
  accessPolicy: deny
---
apiVersion: policy.linkerd.io/v1alpha1
kind: MeshTLSAuthentication
metadata:
  name: {{ $server }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" $ | nindent 4 }}
    app.kubernetes.io/instance: {{ $.release }}
spec:
  identityRefs:
    - kind: ServiceAccount
      name: {{ required "the client's ServiceAccount" $listener.sa }}
      namespace: {{ required "the client's namespace" $listener.ns }}
    {{- if and (eq $listener.name "internal") $root.Values.portal.namespace }}
    {{- /* The Portal's capture subscriber (ADR-N-048 §2.10, T-4880). The gateway admits it on a
           `capture` broker only, with subscribe and no publish; on every other broker its
           CONNECT is refused, so the mesh letting it reach 1883 grants it nothing there. */}}
    - kind: ServiceAccount
      name: {{ required "portal.serviceAccount" $root.Values.portal.serviceAccount }}
      namespace: {{ $root.Values.portal.namespace }}
    {{- end }}
---
apiVersion: policy.linkerd.io/v1alpha1
kind: AuthorizationPolicy
metadata:
  name: {{ $server }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" $ | nindent 4 }}
    app.kubernetes.io/instance: {{ $.release }}
spec:
  targetRef:
    group: policy.linkerd.io
    kind: Server
    name: {{ $server }}
  requiredAuthenticationRefs:
    - group: policy.linkerd.io
      kind: MeshTLSAuthentication
      name: {{ $server }}
{{- end }}
{{- end }}
{{- if $api }}
{{- $server := printf "%s-api" .release }}
---
# 6060 refuses every identity but the Portal's, and routes only the two reads it makes: the
# API's publish, subscribe and kick routes match no route here and answer nobody.
apiVersion: policy.linkerd.io/v1beta3
kind: Server
metadata:
  name: {{ $server }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: mqtt-broker
      app.kubernetes.io/instance: {{ .release }}
  port: 6060
  proxyProtocol: HTTP/1
  accessPolicy: deny
---
apiVersion: policy.linkerd.io/v1beta3
kind: HTTPRoute
metadata:
  name: {{ $server }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
spec:
  parentRefs:
    - group: policy.linkerd.io
      kind: Server
      name: {{ $server }}
  rules:
    - matches:
        - method: GET
          path:
            type: Exact
            value: /api/v1/metrics/history/sum
        - method: GET
          path:
            type: Exact
            value: /api/v1/clients
---
apiVersion: policy.linkerd.io/v1alpha1
kind: MeshTLSAuthentication
metadata:
  name: {{ $server }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
spec:
  identityRefs:
    - kind: ServiceAccount
      name: {{ required "portal.serviceAccount" $root.Values.portal.serviceAccount }}
      namespace: {{ $root.Values.portal.namespace }}
---
apiVersion: policy.linkerd.io/v1alpha1
kind: AuthorizationPolicy
metadata:
  name: {{ $server }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
spec:
  targetRef:
    group: policy.linkerd.io
    kind: HTTPRoute
    name: {{ $server }}
  requiredAuthenticationRefs:
    - group: policy.linkerd.io
      kind: MeshTLSAuthentication
      name: {{ $server }}
{{- end }}
{{- end }}

{{- /* A broker's dedicated port (ADR-N-048 §2.5, PL-77, T-5856), from a dict: root, release, port,
       managedBy. The port is a Traefik entrypoint `mqtt-<port>` of its own (the cluster's Traefik,
       not this chart): TLS ends there with the broker host's certificate and the 8883 TLSOption,
       `HostSNI(*)` admits a device that sends no SNI, and the PROXY header carries its address to
       1884, as on 8883. One route per entrypoint: the Portal and the loop above refuse a second. */ -}}
{{- define "brokers.port" -}}
---
apiVersion: traefik.io/v1alpha1
kind: IngressRouteTCP
metadata:
  name: {{ .release }}-port
  namespace: {{ .root.Release.Namespace }}
  labels:
    {{- include "brokers.labels" . | nindent 4 }}
    app.kubernetes.io/instance: {{ .release }}
spec:
  entryPoints:
    - mqtt-{{ .port }}
  routes:
    - match: HostSNI(`*`)
      services:
        - name: {{ .release }}
          port: 1884
          proxyProtocol:
            version: 2
  tls:
    secretName: {{ .release }}-tls
    options:
      name: mqtt-bsi-tr-02102
{{- end }}

{{- /* The release name of one broker, as jc_core::kinds::mqtt_broker::release_name makes it:
       its ServiceAccount, so its mesh identity, and its Keycloak audience. */ -}}
{{- define "brokers.release" -}}
{{- printf "mqtt-%s-%s" .project .name -}}
{{- end }}

{{- define "brokers.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: mqtt-brokers
{{- end }}

{{- define "brokers.image" -}}
{{- printf "%s:%s@%s" .Values.image.repository .Values.image.tag (required "image.digest pins RMQTT" .Values.image.digest) }}
{{- end }}

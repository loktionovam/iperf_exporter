{{/*
Expand the name of the chart.
*/}}
{{- define "iperf-exporter-server.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "iperf-exporter-server.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "iperf-exporter-server.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "iperf-exporter-server.labels" -}}
helm.sh/chart: {{ include "iperf-exporter-server.chart" . }}
{{ include "iperf-exporter-server.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "iperf-exporter-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "iperf-exporter-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Component selector labels.
*/}}
{{- define "iperf-exporter-server.componentSelectorLabels" -}}
{{ include "iperf-exporter-server.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Component resource name.
*/}}
{{- define "iperf-exporter-server.componentName" -}}
{{- printf "%s-%s" (include "iperf-exporter-server.fullname" .root) .component | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create the name of the service account to use.
*/}}
{{- define "iperf-exporter-server.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "iperf-exporter-server.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Default peer for client workload.
*/}}
{{- define "iperf-exporter-server.clientPeer" -}}
{{- if .Values.client.peer }}
{{- .Values.client.peer -}}
{{- else if .Values.server.enabled }}
{{- include "iperf-exporter-server.componentName" (dict "root" . "component" "server") -}}
{{- else -}}
{{- fail "client.peer must be set when server.enabled is false" -}}
{{- end }}
{{- end }}

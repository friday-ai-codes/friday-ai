{{/*
Chart 名称，支持 nameOverride
*/}}
{{- define "friday.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}
{{/*
完整名称，处理 fullnameOverride / nameOverride / Release.Name 组合
*/}}
{{- define "friday.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name:= default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}
{{/*
Chart 版本标签
*/}}
{{- define "friday.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}
{{/*
公共标签
*/}}
{{- define "friday.labels" -}}
helm.sh/chart: {{ include "friday.chart" . }}
{{ include "friday.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
{{/*
Selector 标签
*/}}
{{- define "friday.selectorLabels" -}}
app.kubernetes.io/name: {{ include "friday.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
{{/*
数据库 Host：postgresql.enabled 时返回内部 Service 名称
*/}}
{{- define "friday.databaseHost" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "%s-postgresql" (include "friday.fullname" .) }}
{{- end }}
{{- end }}

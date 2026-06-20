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
Secret 名称：existingSecret 优先，否则使用 Chart 创建的 <fullname>-secret
*/}}
{{- define "friday.secretName" -}}
{{- if .Values.existingSecret }}
{{- .Values.existingSecret }}
{{- else }}
{{- printf "%s-secret" (include "friday.fullname" .) }}
{{- end }}
{{- end }}
{{/*
Runner executor 是否为 k8s 模式：归一 kubernetes/k8s 两种写法，
与 runner 端 resolveExecutorKind 行为一致（避免 k8s 值渲染成 docker 形态却跑 k8s 逻辑）。
返回字符串 "true"/"false"，调用方用 `eq (include ...) "true"` 判定。
*/}}
{{- define "friday.runner.isK8s" -}}
{{- or (eq .Values.runner.executor "kubernetes") (eq .Values.runner.executor "k8s") -}}
{{- end }}
{{/*
Runner ServiceAccount 名称：runner.k8s.serviceAccountName 优先，否则 <fullname>-runner
*/}}
{{- define "friday.runner.serviceAccountName" -}}
{{- if .Values.runner.k8s.serviceAccountName }}
{{- .Values.runner.k8s.serviceAccountName }}
{{- else }}
{{- printf "%s-runner" (include "friday.fullname" .) }}
{{- end }}
{{- end }}
{{/*
数据库 Host：postgresql.enabled 时返回内部 Service 名称
*/}}
{{- define "friday.databaseHost" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "%s-postgresql" (include "friday.fullname" .) }}
{{- end }}
{{- end }}

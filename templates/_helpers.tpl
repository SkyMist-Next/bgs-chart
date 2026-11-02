{{- define "bgs.name" -}}{{ default (printf "%s-bgs" .Release.Name) .Values.fullnameOverride | trunc 40 | trimSuffix "-" }}{{- end }}
{{- define "bgs.image" -}}{{ required "image.repository is required" .Values.image.repository }}:{{ required "image.tag is required" .Values.image.tag }}{{- end }}
{{- define "bgs.dbref" -}}{{ if .Values.database.create }}{{ include "bgs.name" . }}-db{{ else }}{{ required "database.mariaDbRef required" .Values.database.mariaDbRef }}{{ end }}{{- end }}
{{- define "bgs.dbhost" -}}{{ if .Values.database.create }}{{ include "bgs.dbref" . }}{{ else }}{{ required "database.host required" .Values.database.host }}{{ end }}{{- end }}
{{- define "bgs.labels" }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
{{- end }}

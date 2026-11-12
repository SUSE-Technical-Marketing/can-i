{{- define "can-i.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* The client Deployment and its pod (<release>-client-...): the openshell CLI
     that creates the sandbox and forwards its UI. The sandbox pod, with the
     OpenShell supervisor, is named after the sandbox (sandbox.name). */}}
{{- define "can-i.clientName" -}}
{{- printf "%s-client" (include "can-i.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "can-i.labels" -}}
app.kubernetes.io/name: can-i
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "can-i.selector" -}}
app.kubernetes.io/name: can-i
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* The image the sandbox runs, from the form's dropdown. */}}
{{- define "can-i.sandboxImage" -}}
{{- if eq .Values.sandbox.image "custom" -}}
{{- required "sandbox.customImage is required when sandbox.image is custom" .Values.sandbox.customImage -}}
{{- else -}}
{{- required (printf "unknown sandbox.image %q (suse, opensuse, nvidia or custom)" .Values.sandbox.image) (get .Values.sandbox.images .Values.sandbox.image) -}}
{{- end -}}
{{- end -}}

{{/* Split a comma-separated form field into a list, dropping blanks. */}}
{{- define "can-i.csv" -}}
{{- $out := list -}}
{{- range splitList "," . -}}{{- if trim . -}}{{- $out = append $out (trim .) -}}{{- end -}}{{- end -}}
{{- toJson $out -}}
{{- end -}}

{{/* The sandbox policy as JSON {readOnly, readWrite, network}: the profile
     (policy-profiles.yaml), the grants it switches on plus those ticked in the
     form (policy-grants.yaml), policy.egress / extra paths, and policy.extraYaml.
     curl's endpoints share one can-i-egress rule; every other binary gets its
     own rule. */}}
{{- define "can-i.policyModel" -}}
{{- $p := .Values.policy -}}
{{- $profiles := .Files.Get "policy-profiles.yaml" | fromYaml -}}
{{- $grants := .Files.Get "policy-grants.yaml" | fromYaml -}}
{{- if not (hasKey $profiles $p.profile) -}}
{{- fail (printf "unknown policy.profile %q (%s)" $p.profile (keys $profiles | sortAlpha | join ", ")) -}}
{{- end -}}
{{- $prof := get $profiles $p.profile -}}
{{- $egress := $p.egress -}}
{{- if hasKey $prof "egress" }}{{ $egress = $prof.egress }}{{ end -}}
{{- $on := $prof.grants | default list -}}
{{- range $k, $v := ($p.grants | default dict) -}}{{- if $v }}{{ $on = append $on $k }}{{ end -}}{{- end -}}
{{- $ro := include "can-i.csv" $p.extraReadOnly | fromJsonArray -}}
{{- $rw := include "can-i.csv" $p.extraReadWrite | fromJsonArray -}}
{{- $curl := include "can-i.csv" $egress | fromJsonArray -}}
{{- $rules := dict -}}
{{- range $name := ($on | uniq) -}}
{{- $g := get $grants $name -}}
{{- if not $g -}}{{- fail (printf "unknown policy grant %q (see policy-grants.yaml)" $name) -}}{{- end -}}
{{- $curl = concat $curl ($g.curl | default list) -}}
{{- $ro = concat $ro ($g.readOnly | default list) -}}
{{- $rw = concat $rw ($g.readWrite | default list) -}}
{{- range $rk, $rule := ($g.network | default dict) -}}
{{- if hasKey $rules $rk -}}
{{- $_ := set (get $rules $rk) "endpoints" (concat (get $rules $rk).endpoints $rule.endpoints) -}}
{{- else -}}
{{- $_ := set $rules $rk (deepCopy $rule) -}}
{{- end -}}
{{- end -}}
{{- if and $g.pythonFromUrl $.Values.checks.susePypiUrl -}}
{{- $url := urlParse $.Values.checks.susePypiUrl -}}
{{- $port := 443 -}}
{{- $hp := splitList ":" $url.host -}}
{{- if gt (len $hp) 1 }}{{ $port = atoi (last $hp) }}{{ end -}}
{{- $py := dict "name" "can-i-python3" "endpoints" (list (dict "host" $url.hostname "port" $port)) "binaries" (list (dict "path" "/usr/bin/python3*") (dict "path" "/opt/**/bin/python3*")) -}}
{{- if hasKey $rules "can-i-python3" -}}
{{- $_ := set (get $rules "can-i-python3") "endpoints" (concat (get $rules "can-i-python3").endpoints $py.endpoints) -}}
{{- else -}}
{{- $_ := set $rules "can-i-python3" $py -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- $eps := list -}}
{{- range ($curl | uniq) -}}
{{- $hp := splitList ":" . -}}
{{- $port := 443 -}}
{{- if gt (len $hp) 1 }}{{ $port = atoi (index $hp 1) }}{{ end -}}
{{- $eps = append $eps (dict "host" (index $hp 0) "port" $port) -}}
{{- end -}}
{{- if $eps -}}
{{- $_ := set $rules "can-i-egress" (dict "name" "can-i-egress" "endpoints" $eps "binaries" (list (dict "path" "/usr/bin/curl"))) -}}
{{- end -}}
{{- with $p.extraYaml -}}
{{- $y := fromYaml . -}}
{{- if hasKey $y "Error" -}}{{- fail (printf "policy.extraYaml is not valid YAML: %s" (get $y "Error")) -}}{{- end -}}
{{- if hasKey $y "network_policies" }}{{ $y = get $y "network_policies" }}{{ end -}}
{{- range $k, $v := $y }}{{ $_ := set $rules $k $v }}{{ end -}}
{{- end -}}
{{- dict "readOnly" ($ro | uniq) "readWrite" ($rw | uniq) "network" $rules | toJson -}}
{{- end -}}

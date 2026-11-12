#!/usr/bin/env bash
# Print the sandbox policy the can-i chart would apply, before you deploy it.
#
#   scripts/preview-policy.sh [helm args...]
#
#   scripts/preview-policy.sh --set policy.profile=web-read \
#     --set policy.grants.pypi=true --set policy.grants.varTmp=true
#
# Save it and apply it to a running sandbox's network rules with
#   openshell policy set <sandbox> --policy <file>
# (filesystem rules only take effect when the sandbox is created).
set -euo pipefail
cd "$(dirname "$0")/.."
helm template preview charts/can-i "$@" -s templates/configmap.yaml \
  | python3 -c '
import sys, yaml
print(yaml.safe_load(sys.stdin)["data"]["policy.yaml"], end="")
'

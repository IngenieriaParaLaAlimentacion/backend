#!/usr/bin/env bash
# Resolve the absolute path of every repo in the Ingeniería para la Alimentación product.
#
# The research / plan / implement skills run this instead of guessing relative paths,
# because "how many ../ to the sibling repos" depends on where the current worktree
# lives, and worktrees are scattered:
#
#   /Users/x/dev/ingenieria-alimentacion/backend          (main checkout)
#   /Users/x/conductor/workspaces/backend/santo-domingo   (conductor worktree)
#   <backend>/.claude/worktrees/agent-<id>                (agent worktree)
#
# `git rev-parse --git-common-dir` points at the MAIN checkout's .git from inside any
# of them, so the backend — and therefore the product root containing the sibling repos —
# is recoverable no matter how deep the caller is. The IPA_* overrides may point at
# dedicated Conductor workspaces when client changes must not touch the main checkouts.
#
# Usage:
#   resolve-repos.sh                 # print KEY=PATH for every repo that resolved
#   resolve-repos.sh --path web      # print one path, for $(command substitution)
#   resolve-repos.sh --require web mobile
#                                    # exit 1 unless those keys resolved
#
# Override any repo with an env var when a checkout lives somewhere unusual:
#   IPA_BACKEND_DIR, IPA_WEB_DIR, IPA_MOBILE_DIR

set -uo pipefail

# key|default dir name under the product root|substring that must appear in origin's URL
# `backend` is absent on purpose: it is the worktree the caller is standing in, not a
# lookup under the product root. Edits to the backend belong in the current worktree;
# the main checkout only serves as the anchor that locates the product root.
REPOS=(
  "web|backoffice|IngenieriaParaLaAlimentacion/backoffice"
  "mobile|app_mobile|IngenieriaParaLaAlimentacion/app_mobile"
)

backend_from_git() {
  local common
  common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  [ -n "$common" ] || return 1
  dirname "$common"
}

env_override_for() {
  case "$1" in
    backend) printf '%s' "${IPA_BACKEND_DIR:-}" ;;
    web)     printf '%s' "${IPA_WEB_DIR:-}" ;;
    mobile)  printf '%s' "${IPA_MOBILE_DIR:-}" ;;
  esac
}

MAIN_CHECKOUT=$(backend_from_git)
if [ -z "${MAIN_CHECKOUT:-}" ] || [ ! -d "$MAIN_CHECKOUT" ]; then
  echo "resolve-repos: not inside the backend repo, and IPA_BACKEND_DIR is unset." >&2
  exit 1
fi
# Sibling repos live next to the main backend checkout:
#   <product-root>/{backend,backoffice,app_mobile}
PRODUCT_ROOT=$(dirname "$MAIN_CHECKOUT")

# The backend is wherever the caller is standing, so a worktree edits itself.
BACKEND=${IPA_BACKEND_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}
[ -n "${BACKEND:-}" ] || BACKEND=$MAIN_CHECKOUT

# Resolve a key to a verified checkout, or empty. Verification compares origin's URL
# against the expected slug so a same-named directory elsewhere fails loudly instead of
# being silently edited.
resolve_one() {
  local key=$1 dirname=$2 slug=$3 candidate
  candidate=$(env_override_for "$key")
  [ -n "$candidate" ] || candidate="$PRODUCT_ROOT/$dirname"
  [ -e "$candidate/.git" ] || return 1
  local url
  url=$(git -C "$candidate" remote get-url origin 2>/dev/null) || return 1
  case "$url" in
    *"$slug"*) printf '%s' "$candidate" ;;
    *) return 1 ;;
  esac
}

declare -a FOUND_KEYS=("backend") FOUND_PATHS=("$BACKEND")
for entry in "${REPOS[@]}"; do
  IFS='|' read -r key dirname slug <<<"$entry"
  if path=$(resolve_one "$key" "$dirname" "$slug"); then
    FOUND_KEYS+=("$key")
    FOUND_PATHS+=("$path")
  fi
done

path_for() {
  local want=$1 i
  for i in "${!FOUND_KEYS[@]}"; do
    if [ "${FOUND_KEYS[$i]}" = "$want" ]; then
      printf '%s' "${FOUND_PATHS[$i]}"
      return 0
    fi
  done
  return 1
}

case "${1:-}" in
  --path)
    [ $# -ge 2 ] || { echo "resolve-repos: --path needs a repo key" >&2; exit 2; }
    path_for "$2" || { echo "resolve-repos: '$2' did not resolve" >&2; exit 1; }
    echo
    ;;
  --require)
    shift
    missing=()
    for key in "$@"; do
      path_for "$key" >/dev/null || missing+=("$key")
    done
    if [ ${#missing[@]} -gt 0 ]; then
      echo "resolve-repos: missing checkout(s): ${missing[*]}" >&2
      echo "Clone them under $PRODUCT_ROOT, or set the matching IPA_*_DIR env var." >&2
      exit 1
    fi
    ;;
  "")
    for i in "${!FOUND_KEYS[@]}"; do
      key=${FOUND_KEYS[$i]}
      path=${FOUND_PATHS[$i]}
      branch=$(git -C "$path" branch --show-current 2>/dev/null)
      printf '%s=%s (on %s)\n' "$key" "$path" "${branch:-detached}"
    done
    ;;
  *)
    echo "resolve-repos: unknown argument '$1'" >&2
    exit 2
    ;;
esac

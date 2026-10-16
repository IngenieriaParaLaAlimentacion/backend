#!/usr/bin/env bash
# Create and resolve the dedicated worktrees shared by one research -> plan -> implement run.

set -uo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  feature-worktrees.sh init <N-feature-name>
  feature-worktrees.sh list <N-feature-name>
  feature-worktrees.sh path <N-feature-name> <backend|web|mobile>
  feature-worktrees.sh require <N-feature-name> <repo-key>...
EOF
  exit 2
}

[ $# -ge 2 ] || usage
COMMAND=$1
FEATURE=$2
shift 2

case "$FEATURE" in
  *[!a-z0-9-]* | "" | -* | *-)
    echo "feature-worktrees: feature must use lowercase letters, numbers, and internal hyphens." >&2
    exit 2
    ;;
esac

case "$FEATURE" in
  [0-9]*-*) ;;
  *)
    echo "feature-worktrees: expected a numbered folder such as '4-iron-values'." >&2
    exit 2
    ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BACKEND=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "feature-worktrees: run from the backend worktree." >&2
  exit 1
}
MAIN_BACKEND_GIT=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 1
PRODUCT_ROOT=$(dirname "$(dirname "$MAIN_BACKEND_GIT")")
WORKTREE_ROOT="$PRODUCT_ROOT/.worktrees/$FEATURE"
MANIFEST_DIR="$BACKEND/.context/feature-worktrees"
MANIFEST="$MANIFEST_DIR/$FEATURE.tsv"

expected_slug() {
  case "$1" in
    backend) printf '%s' "IngenieriaParaLaAlimentacion/backend" ;;
    web) printf '%s' "IngenieriaParaLaAlimentacion/backoffice" ;;
    mobile) printf '%s' "IngenieriaParaLaAlimentacion/app_mobile" ;;
    *) return 1 ;;
  esac
}

verify_repo() {
  local key=$1 path=$2 slug url
  slug=$(expected_slug "$key") || return 1
  [ -e "$path/.git" ] || return 1
  url=$(git -C "$path" remote get-url origin 2>/dev/null) || return 1
  case "$url" in
    *"$slug"*) ;;
    *) return 1 ;;
  esac
}

main_checkout_for() {
  local key=$1 resolved common
  resolved=$(bash "$SCRIPT_DIR/resolve-repos.sh" --path "$key") || return 1
  common=$(git -C "$resolved" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  dirname "$common"
}

create_client_worktree() {
  local key=$1 main target
  main=$(main_checkout_for "$key") || {
    echo "feature-worktrees: cannot resolve the $key repository." >&2
    return 1
  }
  target="$WORKTREE_ROOT/$key"

  if [ -e "$target" ]; then
    verify_repo "$key" "$target" || {
      echo "feature-worktrees: $target exists but is not the expected $key worktree." >&2
      return 1
    }
  else
    git -C "$main" fetch origin develop >&2 || return 1
    mkdir -p "$WORKTREE_ROOT" || return 1
    git -C "$main" worktree add --detach "$target" origin/develop >&2 || return 1
  fi

  printf '%s' "$target"
}

write_manifest() {
  local web mobile temp
  verify_repo backend "$BACKEND" || {
    echo "feature-worktrees: current checkout is not the backend repository." >&2
    return 1
  }
  web=$(create_client_worktree web) || return 1
  mobile=$(create_client_worktree mobile) || return 1

  mkdir -p "$MANIFEST_DIR" || return 1
  temp=$(mktemp "$MANIFEST.tmp.XXXXXX") || return 1
  {
    printf 'backend|%s\n' "$BACKEND"
    printf 'web|%s\n' "$web"
    printf 'mobile|%s\n' "$mobile"
  } >"$temp"
  mv "$temp" "$MANIFEST"
}

require_manifest() {
  [ -f "$MANIFEST" ] || {
    echo "feature-worktrees: no worktree map for $FEATURE; run 'feature-worktrees.sh init $FEATURE'." >&2
    exit 1
  }
}

path_for() {
  local wanted=$1 key path
  while IFS='|' read -r key path; do
    if [ "$key" = "$wanted" ]; then
      verify_repo "$key" "$path" || {
        echo "feature-worktrees: recorded $key worktree is missing or invalid: $path" >&2
        return 1
      }
      printf '%s\n' "$path"
      return 0
    fi
  done <"$MANIFEST"
  return 1
}

case "$COMMAND" in
  init)
    [ $# -eq 0 ] || usage
    if [ -f "$MANIFEST" ]; then
      for key in backend web mobile; do
        path_for "$key" >/dev/null || exit 1
      done
    else
      write_manifest || exit 1
    fi
    ;;
  list)
    [ $# -eq 0 ] || usage
    require_manifest
    for key in backend web mobile; do
      path=$(path_for "$key") || exit 1
      branch=$(git -C "$path" branch --show-current 2>/dev/null)
      printf '%s=%s (on %s)\n' "$key" "$path" "${branch:-detached}"
    done
    ;;
  path)
    [ $# -eq 1 ] || usage
    require_manifest
    path_for "$1" || {
      echo "feature-worktrees: unknown or unavailable repo key '$1'." >&2
      exit 1
    }
    ;;
  require)
    [ $# -gt 0 ] || usage
    require_manifest
    for key in "$@"; do
      path_for "$key" >/dev/null || {
        echo "feature-worktrees: required worktree '$key' is unavailable." >&2
        exit 1
      }
    done
    ;;
  *) usage ;;
esac

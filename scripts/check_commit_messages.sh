#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/check_commit_messages.sh --all
  scripts/check_commit_messages.sh --range <revision-range>

Commit subject format:
  type: summary
  type(scope): summary

Allowed types:
  build, chore, ci, docs, feat, fix, perf, refactor, revert, style, test
EOF
}

case "${1:-}" in
  --all)
    rev_args=(--all)
    ;;
  --range)
    if [ -z "${2:-}" ]; then
      usage >&2
      exit 2
    fi
    rev_args=("$2")
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

pattern='^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^()[:space:]]+\))?!?: [^[:space:]].*'
bad=0

while IFS=$'\t' read -r sha subject; do
  if [ -z "$sha" ]; then
    continue
  fi

  if [[ ! "$subject" =~ $pattern ]]; then
    printf 'Invalid commit subject: %s %s\n' "$sha" "$subject" >&2
    bad=1
  fi
done < <(git log --format='%H%x09%s' "${rev_args[@]}")

if [ "$bad" -ne 0 ]; then
  cat >&2 <<'EOF'

Expected commit subject format:
  feat: add hat wobble
  feat(scope): add hat wobble

Allowed types:
  build, chore, ci, docs, feat, fix, perf, refactor, revert, style, test

An optional scope in parentheses is allowed (e.g. feat(api): ...).
Do not use mixed types or whitespace inside the scope.
EOF
  exit 1
fi

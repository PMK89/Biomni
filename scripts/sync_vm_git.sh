#!/usr/bin/env bash
# Sync or initialize a local folder on a VM to track a remote Git branch.
# Default values can be overridden via flags or environment variables.
#
# Usage examples:
#   ./sync_vm_git.sh --dir /opt/biomni --repo https://github.com/PMK89/Biomni.git --branch amine-pmk
#   DIR=/opt/biomni BRANCH=amine-pmk REPO=https://github.com/PMK89/Biomni.git ./sync_vm_git.sh
#   ./sync_vm_git.sh --dir /opt/biomni --branch amine-pmk --clone-new
#   ./sync_vm_git.sh --dir /opt/biomni --branch amine-pmk --clone-new --keep .env --keep local_data
#
# Behavior:
# - If the directory is already a Git repo, it fetches and checks out the branch.
# - If not, it creates a tar.gz backup of existing contents, initializes git, adds origin,
#   fetches, and hard-resets to origin/<branch> (leaving a backup under /tmp).

set -euo pipefail

# Defaults (can be overridden)
DIR="${DIR:-/opt/biomni}"
REPO="${REPO:-https://github.com/PMK89/Biomni.git}"
BRANCH="${BRANCH:-amine-pmk}"
BACKUP="${BACKUP:-1}"
CLONE_NEW=0
# Files/paths inside DIR to preserve even on --clone-new (space-separated)
KEEP_LIST=( "${KEEP_LIST:-.env}" )

print_usage() {
  cat <<EOF
Sync or initialize a folder to a remote Git branch.

Flags:
  -d, --dir       Target directory (default: ${DIR})
  -r, --repo      Git repository URL (default: ${REPO})
  -b, --branch    Branch to checkout (default: ${BRANCH})
  --clone-new     Clone fresh into --dir (dir must be empty or not exist)
  --keep <path>   Preserve a file/dir inside --dir during --clone-new (can be repeated). Default: .env
  --no-backup     Do not create a tar.gz backup when converting a non-git dir
  -h, --help      Show this help

Examples:
  $0 --dir /opt/biomni --repo https://github.com/PMK89/Biomni.git --branch amine-pmk
  $0 --dir /opt/biomni --branch amine-pmk --clone-new
EOF
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dir) DIR="$2"; shift 2 ;;
    -r|--repo) REPO="$2"; shift 2 ;;
    -b|--branch) BRANCH="$2"; shift 2 ;;
    --clone-new) CLONE_NEW=1; shift ;;
    --keep) KEEP_LIST+=("$2"); shift 2 ;;
    --no-backup) BACKUP=0; shift ;;
    -h|--help) print_usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; print_usage; exit 1 ;;
  esac
done

# Pre-flight
if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is not installed. Install it first (e.g., sudo apt-get update && sudo apt-get install -y git)" >&2
  exit 1
fi

mkdir -p "$DIR"

if [[ "$CLONE_NEW" -eq 1 ]]; then
  # Preserve selected files/dirs within DIR by moving them aside first
  TMP_PRESERVE="/tmp/$(basename "$DIR")_preserve_$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$TMP_PRESERVE"
  for item in "${KEEP_LIST[@]}"; do
    src="$DIR/$item"
    if [[ -e "$src" ]]; then
      echo "Preserving $src -> $TMP_PRESERVE/$item"
      mkdir -p "$(dirname "$TMP_PRESERVE/$item")"
      mv "$src" "$TMP_PRESERVE/$item"
    fi
  done

  # Clean target and clone fresh
  rm -rf "$DIR"
  echo "Cloning $REPO (branch: $BRANCH) into $DIR ..."
  git clone --branch "$BRANCH" --single-branch "$REPO" "$DIR"

  # Restore preserved items
  for item in "${KEEP_LIST[@]}"; do
    src="$TMP_PRESERVE/$item"
    if [[ -e "$src" ]]; then
      echo "Restoring $src -> $DIR/$item"
      mkdir -p "$(dirname "$DIR/$item")"
      mv "$src" "$DIR/$item"
    fi
  done
  rmdir "$TMP_PRESERVE" 2>/dev/null || true
else
  if [[ -d "$DIR/.git" ]]; then
    echo "Existing Git repo detected in $DIR. Fetching and switching to $BRANCH ..."
    git -C "$DIR" remote set-url origin "$REPO" || true
    git -C "$DIR" fetch origin --prune
    git -C "$DIR" checkout -B "$BRANCH" "origin/$BRANCH"
    git -C "$DIR" reset --hard "origin/$BRANCH"
  else
    if [[ -n "$(ls -A "$DIR" 2>/dev/null || true)" ]]; then
      if [[ "$BACKUP" -eq 1 ]]; then
        TS=$(date +%Y%m%d-%H%M%S)
        BK="/tmp/$(basename "$DIR")_pre_git_${TS}.tgz"
        echo "Creating backup archive of existing contents: $BK"
        tar -C "$DIR" -czf "$BK" . || true
      else
        echo "Warning: proceeding without backup of existing contents in $DIR" >&2
      fi
    fi
    echo "Initializing Git repo in $DIR and syncing to $REPO ($BRANCH) ..."
    git -C "$DIR" init
    # Use main branch name if needed, but we're checking out from origin/$BRANCH anyway
    git -C "$DIR" remote add origin "$REPO" 2>/dev/null || git -C "$DIR" remote set-url origin "$REPO"
    git -C "$DIR" fetch origin --prune
    git -C "$DIR" checkout -B "$BRANCH" "origin/$BRANCH" || true
    git -C "$DIR" reset --hard "origin/$BRANCH"
  fi
fi

echo "--- Current repo state in $DIR ---"
( git -C "$DIR" rev-parse --abbrev-ref HEAD; git -C "$DIR" rev-parse --short HEAD; git -C "$DIR" remote -v ) | paste - - - | awk '{print "branch="$1, "commit="$2, "remote=" $3}'

# Optional: show last commit
git -C "$DIR" --no-pager log -1 --oneline || true

echo "Done."

#!/usr/bin/env bash
# Keeps Azure DevOps ("origin") and GitHub ("github") in sync for the branches
# listed below. Fast-forwards when possible; if a branch has diverged on both
# remotes it performs a real merge and stops for manual conflict resolution
# if one occurs.
#
# Usage: run manually, or from cron:
#   0 7 * * * /home/james/git/ConsoleServer/scripts/sync_azure_github.sh >> /home/james/git/sync.log 2>&1

set -euo pipefail

REPO_DIR="/home/james/git/ConsoleServer"
BRANCHES=("master" "james/yang_model")

cd "$REPO_DIR"

echo "=== sync run: $(date) ==="

git fetch origin --prune
git fetch github --prune

for branch in "${BRANCHES[@]}"; do
    echo "--- branch: $branch ---"

    if ! git show-ref --verify --quiet "refs/heads/$branch"; then
        git checkout -B "$branch" "origin/$branch"
    else
        git checkout "$branch"
    fi

    # fast-forward local branch to whichever remote is ahead; if both moved,
    # merge origin into github's view (origin/Azure is treated as source of truth
    # on conflicts you'll be asked to resolve).
    git merge --ff-only "origin/$branch" 2>/dev/null || git merge --no-edit "origin/$branch"
    git merge --ff-only "github/$branch" 2>/dev/null || git merge --no-edit "github/$branch"

    git push origin "$branch"
    git push github "$branch"
done

echo "=== sync complete: $(date) ==="

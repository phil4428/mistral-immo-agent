#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-phil4428/mistral-immo-agent}"
BRANCH="${BRANCH:-vibe/immo-agent-3c7e36}"
SRC="${1:-$PWD}"
MSG="${2:-sync: update from ${SRC}}"
WORK="${WORK:-$HOME/.sync/${REPO##*/}}"

command -v gh >/dev/null 2>&1 || { echo "gh CLI requis (https://cli.github.com)"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh non authentifie : lance 'gh auth login' d'abord"; exit 1; }

if [ ! -d "$WORK/.git" ]; then
  mkdir -p "$(dirname "$WORK")"
  gh repo clone "$REPO" "$WORK"
fi
cd "$WORK"
git fetch origin
git checkout -B "$BRANCH" "origin/$BRANCH" 2>/dev/null || git checkout -B "$BRANCH"

git ls-files -z | xargs -0 rm -f 2>/dev/null || true
tar -C "$SRC" --exclude=.git --exclude=__pycache__ --exclude='*.db' -cf - . | tar -C "$WORK" -xf -

git add -A
if git diff --cached --quiet; then
  echo "Aucun changement a pousser."
else
  git commit -m "$MSG"
  git push -u origin "$BRANCH"
  echo "Poussé sur $REPO ($BRANCH)."
fi

PR=$(gh pr list --repo "$REPO" --head "$BRANCH" --json number --jq '.[0].number // empty')
if [ -z "$PR" ]; then
  gh pr create --repo "$REPO" --head "$BRANCH" --base main --draft --title "$MSG" \
    --body "Synchronisation automatique via sync.sh depuis \`$SRC\`"
  echo "PR draft créée."
else
  echo "PR #$PR déjà ouverte : $(gh pr view "$PR" --repo "$REPO" --json url --jq .url)"
fi

#!/usr/bin/env bash
# Publish (or update) the repository on GitHub. Private by default.
#
#   bash scripts/publish_github.sh              # private repo named "reprochem"
#   bash scripts/publish_github.sh --public     # public repo
#   REPO=other-name bash scripts/publish_github.sh
#
# Safe to run again: it commits what changed and pushes. It refuses to publish if
# anything that looks like an API key is in the files, or if .env would be committed.
set -euo pipefail
cd "$(dirname "$0")/.."
VIS="--private"; [[ "${1:-}" == "--public" ]] && VIS="--public"
REPO="${REPO:-reprochem}"

# 1. No secrets, ever.
if grep -rIlE "(gsk_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,})" \
     --exclude-dir=.git --exclude-dir=.venv --exclude-dir=adapters --exclude-dir=models --exclude-dir=papers . ; then
  echo "Something that looks like an API key is in the files listed above. Nothing was published."; exit 1
fi

# 2. Local repository and commit.
[[ -d .git ]] || git init -b main
git add -A
if git ls-files --cached | grep -qE '(^|/)\.env$'; then
  echo ".env is staged: check .gitignore. Nothing was published."; git reset -q; exit 1
fi
if ! git diff --cached --quiet; then
  git commit -q -m "ReproChem: final submission for the Generative AI course

Distilled method-card extractor (Claude teacher, Qwen3-1.7B + LoRA student),
gold set, benchmark, red team, and the ReproChem Lens voice explainer.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CHckbjix3UshYTCMFUrvvR"
fi
echo "Files tracked: $(git ls-files | wc -l | tr -d ' ')"

# 3. GitHub.
if git remote get-url origin >/dev/null 2>&1; then
  git push -u origin main
elif command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh repo create "$REPO" "$VIS" --source=. --remote=origin --push
else
  echo
  echo "GitHub CLI not available or not logged in. Two options:"
  echo "  a) brew install gh && gh auth login, then run this script again"
  echo "  b) create an empty repo named $REPO on github.com, then:"
  echo "     git remote add origin https://github.com/<your-account>/$REPO.git && git push -u origin main"
fi

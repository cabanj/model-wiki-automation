#!/usr/bin/env bash
# Regenerate the public free-llm-roster README and publish it when the roster changed.
# Runs after run.sh, from the model-wiki pipeline. Never fails the pipeline: a broken
# backlink deploy must not take down site generation.
set -uo pipefail

SRC_DIR=/opt/model-wiki-automation
ROSTER_DIR=/opt/free-llm-roster
ROSTER_REMOTE=github-roster

cd "$SRC_DIR" || { echo "readme: no $SRC_DIR"; exit 0; }

python3 readme.py "$ROSTER_DIR" || { echo "readme: render failed, skipping"; exit 0; }

[ -d "$ROSTER_DIR/.git" ] || { echo "readme: no checkout at $ROSTER_DIR, skipping commit"; exit 0; }
cd "$ROSTER_DIR" || { echo "readme: cannot enter $ROSTER_DIR"; exit 0; }

git add README.md || { echo "readme: git add failed"; exit 0; }
if ! git diff --cached --quiet; then
  git -c user.name="model-wiki-bot" -c user.email="bot@llmroster.dev" \
      commit -q -m "chore: update free LLM roster" || { echo "readme: commit failed"; exit 0; }
  echo "readme: committed roster change"
else
  echo "readme: no roster change"
fi

# Push whenever the remote may be behind, not merely when this run committed.
# Keying the push off "did I commit" would strand an earlier failed push forever:
# the next run would see an unchanged tree and never retry. The remote-tracking
# ref is absent until the first successful fetch/push, so an unresolvable
# "$ROSTER_REMOTE/main" must read as "possibly unpushed" rather than "nothing to do".
if git rev-parse --verify -q "$ROSTER_REMOTE/main" >/dev/null 2>&1; then
  UNPUSHED=$(git log --oneline "$ROSTER_REMOTE/main..HEAD" 2>/dev/null | wc -l)
else
  UNPUSHED=$(git log --oneline HEAD 2>/dev/null | wc -l)
fi

if [ "$UNPUSHED" -eq 0 ]; then
  echo "readme: nothing to push"
  exit 0
fi

if git push -q "$ROSTER_REMOTE" HEAD:main 2>/tmp/readme-push.err; then
  echo "readme: published $UNPUSHED commit(s) to $ROSTER_REMOTE"
else
  echo "readme: PUSH FAILED, $UNPUSHED commit(s) still local"
  sed 's/^/  /' /tmp/readme-push.err
  rm -f /tmp/readme-push.err
  echo "  retry manually: git -C $ROSTER_DIR push $ROSTER_REMOTE HEAD:main"
fi

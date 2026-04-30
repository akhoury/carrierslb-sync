#!/usr/bin/env bash
#
# rewrite-history.sh — collapse all git history into a single commit
# pinned at the current working tree, then force-push.
#
# WHEN TO USE: only when sensitive data has leaked into earlier commits and
# you want to make the old SHAs unreferenceable from any branch/tag. This
# does NOT remove already-leaked data from anyone's local clones, search
# engine caches, or GitHub's internal storage during its ~90-day GC window.
# Rotate any committed secrets independently — assume they're compromised.
#
# WHAT IT DOES:
#   1. Sanity-checks: clean working tree, on `main`, remote configured.
#   2. Backs up the current main as `backup-pre-rewrite-<timestamp>` locally.
#   3. Creates an orphan branch with one commit containing the current tree.
#   4. Force-pushes that as the new main.
#   5. Deletes every existing tag (local + origin).
#   6. Re-tags the new commit using the version in config.yaml.
#   7. Pushes the new tag.
#
# Idempotent: safe to re-run after editing the working tree if you abort.
# Destructive: there's a single confirmation prompt; once past it, no undo.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ──────────────────────────────────────────────────────────────────────────
# Pre-flight checks
# ──────────────────────────────────────────────────────────────────────────

if [[ ! -d .git ]]; then
  echo "ERROR: not a git repository (no .git/ in $REPO_ROOT)" >&2
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "ERROR: must run from main branch (currently on '$CURRENT_BRANCH')" >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: working tree has uncommitted changes. Commit or stash first." >&2
  git status --short >&2
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "ERROR: no 'origin' remote configured" >&2
  exit 1
fi

VERSION_FILE="carriers_sync/config.yaml"
if [[ ! -f "$VERSION_FILE" ]]; then
  echo "ERROR: $VERSION_FILE not found" >&2
  exit 1
fi
VERSION="$(grep '^version:' "$VERSION_FILE" | awk '{print $2}' | tr -d '"' | tr -d "'")"
if [[ -z "$VERSION" ]]; then
  echo "ERROR: could not parse version from $VERSION_FILE" >&2
  exit 1
fi
NEW_TAG="v$VERSION"

# ──────────────────────────────────────────────────────────────────────────
# Show plan, ask for confirmation
# ──────────────────────────────────────────────────────────────────────────

ORIGIN_URL="$(git remote get-url origin)"
EXISTING_TAGS="$(git tag -l | tr '\n' ' ')"
EXISTING_REMOTE_TAGS="$(git ls-remote --tags origin 2>/dev/null \
  | awk '{print $2}' \
  | sed 's|refs/tags/||' \
  | grep -v '\^{}' \
  | tr '\n' ' ' || true)"

cat <<EOF

────────────────────────────────────────────────────────────────────────
  GIT HISTORY REWRITE — read carefully, this is destructive
────────────────────────────────────────────────────────────────────────

  Repo:     $REPO_ROOT
  Origin:   $ORIGIN_URL
  Branch:   main
  New tag:  $NEW_TAG  (from $VERSION_FILE)

  Local tags that will be deleted:
    ${EXISTING_TAGS:-(none)}

  Remote tags that will be deleted:
    ${EXISTING_REMOTE_TAGS:-(none)}

  After this completes:
    - origin/main will have ONE commit containing the current tree.
    - All previous commit SHAs become unreachable on origin (GitHub will
      garbage-collect them in ~90 days; they're not discoverable in the
      meantime without knowing the SHA).
    - All listed tags will be gone from local AND origin.
    - $NEW_TAG will be the only tag, pointing at the new orphan commit.
    - A local-only backup branch will preserve the pre-rewrite state.

  This does NOT undo data already cloned by anyone else, cached by
  search engines / archive.org, or kept in your local conversation /
  shell history. Rotate any committed secrets regardless.

────────────────────────────────────────────────────────────────────────

EOF

read -r -p "Type 'REWRITE' (uppercase, no quotes) to proceed: " CONFIRM
if [[ "$CONFIRM" != "REWRITE" ]]; then
  echo "Aborted."
  exit 0
fi

# ──────────────────────────────────────────────────────────────────────────
# Step 1: local backup branch (cheap insurance)
# ──────────────────────────────────────────────────────────────────────────

BACKUP_BRANCH="backup-pre-rewrite-$(date -u +%Y%m%dT%H%M%SZ)"
git branch "$BACKUP_BRANCH"
echo "✓ Backed up current main → $BACKUP_BRANCH (local only)"

# ──────────────────────────────────────────────────────────────────────────
# Step 2: build the new orphan branch with one commit
# ──────────────────────────────────────────────────────────────────────────

git checkout --orphan fresh-main
git add -A
git commit -m "$NEW_TAG — initial public release

Home Assistant App that syncs Lebanese mobile-carrier data usage
(Alfa, Touch, Ogero) to Home Assistant via MQTT discovery.

History before this commit was rewritten on $(date -u +%Y-%m-%d) to
remove personally identifiable information (real account credentials,
phone numbers, labels) committed during early development."

echo "✓ Built fresh-main with one commit ($(git rev-parse --short HEAD))"

# ──────────────────────────────────────────────────────────────────────────
# Step 3: replace main locally
# ──────────────────────────────────────────────────────────────────────────

git branch -D main
git branch -m main
echo "✓ Replaced local main"

# ──────────────────────────────────────────────────────────────────────────
# Step 4: force-push to origin
# ──────────────────────────────────────────────────────────────────────────

git push -f origin main
echo "✓ Force-pushed to origin/main"

# ──────────────────────────────────────────────────────────────────────────
# Step 5: delete every existing tag (local + remote)
# ──────────────────────────────────────────────────────────────────────────

# Re-fetch remote tag list since some may have been pruned by force-push
REMOTE_TAGS_NOW="$(git ls-remote --tags origin 2>/dev/null \
  | awk '{print $2}' \
  | sed 's|refs/tags/||' \
  | grep -v '\^{}' || true)"

for tag in $REMOTE_TAGS_NOW; do
  git push origin --delete "refs/tags/$tag" 2>/dev/null \
    && echo "  ✓ deleted remote tag $tag" \
    || echo "  ✗ failed to delete remote tag $tag (already gone?)"
done

# Local tags
for tag in $(git tag -l); do
  git tag -d "$tag" >/dev/null 2>&1 \
    && echo "  ✓ deleted local tag $tag" \
    || true
done

# ──────────────────────────────────────────────────────────────────────────
# Step 6 + 7: re-tag and push
# ──────────────────────────────────────────────────────────────────────────

git tag -a "$NEW_TAG" -m "$NEW_TAG — initial public release"
git push origin "$NEW_TAG"
echo "✓ Tagged $NEW_TAG and pushed"

# ──────────────────────────────────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────────────────────────────────

cat <<EOF

────────────────────────────────────────────────────────────────────────
  DONE
────────────────────────────────────────────────────────────────────────

  origin/main now has one commit ($(git rev-parse --short HEAD))
  Tag $NEW_TAG points at that commit
  Local backup of pre-rewrite state: $BACKUP_BRANCH

  Next steps (manual, on github.com):
    1. Releases page — delete any GitHub Releases that referenced
       deleted tags. Tag deletion does NOT remove a Release page.
    2. Actions → Workflow runs — delete old runs whose logs may
       contain references to pre-rewrite data.
    3. (Optional) Open GitHub Support to expedite the GC of
       unreferenced commit SHAs from their cache.

  Rotate any credentials that ever appeared in committed files:
    - Alfa account passwords
    - Touch password
    - Ogero password
    - Mosquitto broker password
    - Anything else that was in /data/options.json at any point

────────────────────────────────────────────────────────────────────────

EOF

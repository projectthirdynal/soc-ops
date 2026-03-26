#!/usr/bin/env bash
# ============================================================
# Linux release script — bump version, commit, tag, push.
# GitHub Actions handles the Windows build and publishes the
# installer to GitHub Releases automatically.
#
# Usage:
#   ./release.sh patch
#   ./release.sh minor
#   ./release.sh major
#   ./release.sh 1.2.3
#   ./release.sh patch "Fixed clustering bug"
#
# What this does:
#   1. Bumps version in version.py + version.json
#   2. Git-commits the bump with a version tag
#   3. Pushes commit + tag  →  triggers GitHub Actions
#   4. GitHub Actions (windows-latest) builds the installer
#      and publishes it to Releases automatically.
# ============================================================

set -euo pipefail

BUMP_TYPE="${1:-}"
CHANGELOG="${2:-}"

if [[ -z "$BUMP_TYPE" ]]; then
    echo "Usage: ./release.sh <patch|minor|major|X.Y.Z> [\"changelog\"]"
    echo ""
    echo "Examples:"
    echo "  ./release.sh patch"
    echo "  ./release.sh minor \"Added search and cluster export improvements\""
    echo "  ./release.sh 1.2.0"
    exit 1
fi

# --- Check prerequisites ---
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found."; exit 1; }
command -v git >/dev/null 2>&1    || { echo "ERROR: git not found."; exit 1; }

# --- Warn on dirty working tree ---
if ! git diff --quiet --exit-code 2>/dev/null; then
    echo "WARNING: You have unstaged changes:"
    git status --short
    echo ""
    read -rp "Continue anyway? (y/N): " CONT
    if [[ "${CONT,,}" != "y" ]]; then
        echo "Aborted. Commit or stash your changes first."
        exit 1
    fi
fi

echo ""
echo "============================================================"
echo " SOC Data Processor — Release Pipeline"
echo "============================================================"
echo " Bump type : $BUMP_TYPE"
[[ -n "$CHANGELOG" ]] && echo " Changelog : $CHANGELOG"
echo "============================================================"
echo ""

# ==========================================================
# STEP 1: Bump version (updates version.py + version.json)
# ==========================================================
echo "[1/3] Bumping version ($BUMP_TYPE)..."
python3 bump_version.py "$BUMP_TYPE" --commit
echo ""

# Read new version from version.json
VERSION=$(python3 -c "import json; print(json.loads(open('version.json').read())['version'])")
TAG="v$VERSION"
echo " New version: $VERSION"
echo ""

# ==========================================================
# STEP 2: Push commit + tag  →  triggers GitHub Actions
# ==========================================================
echo "[2/3] Pushing commit to remote..."
git push
echo ""

echo "[3/3] Pushing tag $TAG  (triggers CI build)..."
git push origin "$TAG"
echo ""

# ==========================================================
# Done — CI takes over
# ==========================================================
echo "============================================================"
echo " TAG PUSHED: $TAG"
echo "============================================================"
echo ""
echo " GitHub Actions will now:"
echo "   1. Build the Windows installer (PyInstaller + Inno Setup)"
echo "   2. Compute SHA256"
echo "   3. Auto-generate changelog from git commits"
echo "   4. Create GitHub Release: $TAG"
echo "   5. Upload SOCDataProcessor-Setup-$VERSION.exe"
echo ""
echo " Track progress:"
echo "   gh run list --limit 5"
echo "   gh run watch"
echo ""
echo " Users will see the update notification on next app launch."
echo "============================================================"

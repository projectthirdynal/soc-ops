"""Bump the application version.

Keeps app/core/version.py and version.json in sync — single command,
no manual editing of multiple files.

Usage:
    python bump_version.py patch          # 1.0.0 → 1.0.1
    python bump_version.py minor          # 1.0.0 → 1.1.0
    python bump_version.py major          # 1.0.0 → 2.0.0
    python bump_version.py 1.2.3          # explicit version

Options:
    --commit      Git-commit the version bump (adds tag)
    --no-tag      With --commit, skip creating the git tag
    --dry-run     Print what would change without writing files
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_PY = ROOT / "app" / "core" / "version.py"
VERSION_JSON = ROOT / "version.json"


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def read_current_version() -> str:
    """Read the current version from version.py (authoritative source)."""
    text = VERSION_PY.read_text(encoding="utf-8")
    m = re.search(r'^VERSION(?:\s*:\s*\w+)?\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not m:
        sys.exit(f"ERROR: Could not parse VERSION from {VERSION_PY}")
    return m.group(1)


def bump(current: str, bump_type: str) -> str:
    """Return the new version string."""
    # Explicit version provided
    if re.match(r"^\d+\.\d+\.\d+$", bump_type):
        return bump_type

    parts = current.split(".")
    if len(parts) != 3:
        sys.exit(f"ERROR: Current version '{current}' is not semver (X.Y.Z).")

    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if bump_type == "patch":
        patch += 1
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        sys.exit(f"ERROR: Unknown bump type '{bump_type}'. Use patch/minor/major or X.Y.Z.")

    return f"{major}.{minor}.{patch}"


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_version_py(new_version: str, build_date: str, dry_run: bool) -> None:
    """Rewrite app/core/version.py with the new version and today's date."""
    new_text = (
        '"""Application version information."""\n\n'
        f'VERSION: str = "{new_version}"\n'
        f'BUILD_DATE: str = "{build_date}"\n'
    )
    if dry_run:
        print(f"  [dry-run] Would write {VERSION_PY}:\n{new_text}")
    else:
        VERSION_PY.write_text(new_text, encoding="utf-8")
        print(f"  Updated {VERSION_PY.relative_to(ROOT)}")


def write_version_json(new_version: str, build_date: str, dry_run: bool) -> None:
    """Rewrite version.json with the new version and today's date."""
    try:
        data = json.loads(VERSION_JSON.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    data["version"] = new_version
    data["build_date"] = build_date
    data.setdefault("min_compatible_version", new_version)

    new_text = json.dumps(data, indent=2) + "\n"
    if dry_run:
        print(f"  [dry-run] Would write {VERSION_JSON}:\n{new_text}")
    else:
        VERSION_JSON.write_text(new_text, encoding="utf-8")
        print(f"  Updated {VERSION_JSON.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_commit_and_tag(new_version: str, add_tag: bool, dry_run: bool) -> None:
    """Stage version files, commit, and optionally tag."""
    files = [str(VERSION_PY.relative_to(ROOT)), str(VERSION_JSON.relative_to(ROOT))]
    tag = f"v{new_version}"

    if dry_run:
        print(f"  [dry-run] Would: git add {' '.join(files)}")
        print(f"  [dry-run] Would: git commit -m 'chore: bump version to {new_version}'")
        if add_tag:
            print(f"  [dry-run] Would: git tag {tag}")
        return

    subprocess.run(["git", "add"] + files, check=True, cwd=ROOT)
    subprocess.run(
        ["git", "commit", "-m", f"chore: bump version to {new_version}"],
        check=True,
        cwd=ROOT,
    )
    print(f"  Committed version bump.")

    if add_tag:
        subprocess.run(["git", "tag", tag], check=True, cwd=ROOT)
        print(f"  Created git tag: {tag}")
        print(f"  To push: git push && git push origin {tag}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "bump_type",
        metavar="patch|minor|major|X.Y.Z",
        help="How to increment the version, or an explicit X.Y.Z version.",
    )
    parser.add_argument("--commit", action="store_true", help="Git-commit the version bump.")
    parser.add_argument("--no-tag", action="store_true", help="With --commit, skip creating the git tag.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing files.")
    args = parser.parse_args()

    current = read_current_version()
    new_version = bump(current, args.bump_type)
    build_date = date.today().isoformat()

    print(f"\nVersion bump: {current} → {new_version}  (build_date: {build_date})")
    print()

    write_version_py(new_version, build_date, dry_run=args.dry_run)
    write_version_json(new_version, build_date, dry_run=args.dry_run)

    if args.commit:
        git_commit_and_tag(new_version, add_tag=not args.no_tag, dry_run=args.dry_run)

    print()
    print(f"Done. New version: {new_version}")
    if not args.commit:
        print("Tip: add --commit to git-commit and tag the bump automatically.")


if __name__ == "__main__":
    main()

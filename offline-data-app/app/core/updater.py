"""OTA update mechanism for the desktop application.

Supports checking for updates from:
- GitHub Releases (recommended for internet-based OTA)
- Local file paths (C:\\Updates)
- UNC network shares (\\\\server\\updates)
- HTTP/HTTPS URLs (http://internal-server/updates)

GitHub mode: set update_source to "github:owner/repo" (e.g. "github:projectthirdynal/soc-ops").
The app fetches the latest release from the GitHub API and downloads the
installer asset directly from GitHub.
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.version import VERSION

logger = logging.getLogger(__name__)

# GitHub Releases asset name pattern
_INSTALLER_PATTERN = re.compile(r"ASNClaimsProcessor-Setup.*\.exe$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Semver comparison
# ---------------------------------------------------------------------------

def _parse_semver(version_str: str) -> tuple[int, int, int]:
    """Parse a semver string into a (major, minor, patch) tuple."""
    parts = version_str.strip().lstrip("v").split(".")
    major = int(parts[0]) if len(parts) > 0 else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0
    return (major, minor, patch)


def is_newer(remote_version: str, local_version: str) -> bool:
    """Return True if *remote_version* is strictly newer than *local_version*."""
    return _parse_semver(remote_version) > _parse_semver(local_version)


def is_compatible(remote_min_compatible: str, local_version: str) -> bool:
    """Return True if *local_version* meets the minimum compatibility requirement."""
    return _parse_semver(local_version) >= _parse_semver(remote_min_compatible)


# ---------------------------------------------------------------------------
# Update configuration (persisted to disk)
# ---------------------------------------------------------------------------

def _default_config_dir() -> Path:
    """Return the directory where update configuration is stored."""
    try:
        from platformdirs import user_data_dir
        return Path(user_data_dir("offline-data-app", appauthor=False))
    except ImportError:
        return Path(__file__).resolve().parent.parent.parent / "data"


UPDATE_CONFIG_FILE = _default_config_dir() / "update_config.json"

# Default GitHub repository for updates
DEFAULT_GITHUB_REPO = "github:projectthirdynal/soc-ops"


@dataclass
class UpdateConfig:
    """Persisted update configuration."""

    update_source: str = DEFAULT_GITHUB_REPO
    check_on_startup: bool = True
    download_dir: str = ""

    @classmethod
    def load(cls) -> "UpdateConfig":
        """Load configuration from disk, returning defaults if absent."""
        try:
            if UPDATE_CONFIG_FILE.exists():
                data = json.loads(UPDATE_CONFIG_FILE.read_text(encoding="utf-8"))
                return cls(
                    update_source=data.get("update_source", DEFAULT_GITHUB_REPO),
                    check_on_startup=data.get("check_on_startup", True),
                    download_dir=data.get("download_dir", ""),
                )
        except Exception as exc:
            logger.warning("Failed to read update config: %s", exc)
        return cls()

    def save(self) -> None:
        """Persist configuration to disk."""
        try:
            UPDATE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "update_source": self.update_source,
                "check_on_startup": self.check_on_startup,
                "download_dir": self.download_dir,
            }
            UPDATE_CONFIG_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            logger.info("Update config saved to %s", UPDATE_CONFIG_FILE)
        except Exception as exc:
            logger.error("Failed to save update config: %s", exc)
            raise

    @property
    def effective_download_dir(self) -> Path:
        """Resolved download directory; falls back to a temp folder."""
        if self.download_dir:
            p = Path(self.download_dir)
        else:
            p = _default_config_dir() / "updates"
        p.mkdir(parents=True, exist_ok=True)
        return p


# ---------------------------------------------------------------------------
# Update manifest
# ---------------------------------------------------------------------------

@dataclass
class UpdateManifest:
    """Represents update information (from GitHub or update.json)."""

    version: str = ""
    build_date: str = ""
    min_compatible_version: str = "1.0.0"
    installer_filename: str = ""
    installer_size_bytes: int = 0
    sha256: str = ""
    changelog: str = ""
    mandatory: bool = False
    # GitHub-specific: direct download URL for the asset
    download_url: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "UpdateManifest":
        return cls(
            version=data.get("version", ""),
            build_date=data.get("build_date", ""),
            min_compatible_version=data.get("min_compatible_version", "1.0.0"),
            installer_filename=data.get("installer_filename", ""),
            installer_size_bytes=data.get("installer_size_bytes", 0),
            sha256=data.get("sha256", ""),
            changelog=data.get("changelog", ""),
            mandatory=data.get("mandatory", False),
            download_url=data.get("download_url", ""),
        )

    @classmethod
    def from_github_release(cls, release: dict) -> "UpdateManifest":
        """Build a manifest from a GitHub API release response."""
        tag = release.get("tag_name", "")
        version = tag.lstrip("v")
        body = release.get("body", "") or ""
        published = release.get("published_at", "")
        build_date = published[:10] if published else ""

        # Find the installer asset
        installer_filename = ""
        installer_size = 0
        download_url = ""
        sha256 = ""

        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if _INSTALLER_PATTERN.match(name):
                installer_filename = name
                installer_size = asset.get("size", 0)
                download_url = asset.get("browser_download_url", "")
                break

        # Check if body contains a SHA256 hash (convention: "SHA256: <hash>")
        sha_match = re.search(r"SHA256:\s*([a-fA-F0-9]{64})", body)
        if sha_match:
            sha256 = sha_match.group(1)

        # Check for mandatory flag in body
        mandatory = "MANDATORY" in body.upper()

        return cls(
            version=version,
            build_date=build_date,
            min_compatible_version="1.0.0",
            installer_filename=installer_filename,
            installer_size_bytes=installer_size,
            sha256=sha256,
            changelog=body,
            mandatory=mandatory,
            download_url=download_url,
        )


# ---------------------------------------------------------------------------
# Source type detection
# ---------------------------------------------------------------------------

def _is_github(source: str) -> bool:
    """Check if source is a GitHub repo reference (github:owner/repo)."""
    return source.strip().lower().startswith("github:")


def _parse_github_repo(source: str) -> str:
    """Extract 'owner/repo' from 'github:owner/repo'."""
    return source.strip()[len("github:"):].strip().strip("/")


def _is_http(source: str) -> bool:
    return source.lower().startswith("http://") or source.lower().startswith("https://")


# ---------------------------------------------------------------------------
# Fetching from different sources
# ---------------------------------------------------------------------------

def _make_ssl_context(verify: bool = True):
    """Return an SSL context, optionally disabling certificate verification."""
    import ssl
    if verify:
        return ssl.create_default_context()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _http_get(url: str, timeout: int = 30) -> bytes:
    """Fetch bytes from a URL using urllib (stdlib).

    Tries with SSL verification first; falls back to unverified if the
    local certificate store cannot verify the server (common on corporate
    Windows machines with custom CA chains).
    """
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    req = Request(url, headers={
        "User-Agent": f"ASNClaimsProcessor/{VERSION}",
        "Accept": "application/vnd.github+json",
    })
    for verify in (True, False):
        try:
            ctx = _make_ssl_context(verify)
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except URLError as exc:
            err_str = str(exc).upper()
            if not verify or ("CERTIFICATE" not in err_str and "SSL" not in err_str):
                raise ConnectionError(f"HTTP request failed for {url}: {exc}") from exc
            logger.warning("SSL verification failed for %s, retrying without cert check", url)
    raise ConnectionError(f"HTTP request failed for {url}")  # unreachable


def _http_download_stream(url: str, dest: Path, timeout: int = 300) -> int:
    """Download a large file with streaming to avoid loading into memory."""
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    req = Request(url, headers={
        "User-Agent": f"ASNClaimsProcessor/{VERSION}",
        "Accept": "application/octet-stream",
    })
    for verify in (True, False):
        try:
            ctx = _make_ssl_context(verify)
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                total = 0
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        total += len(chunk)
                return total
        except URLError as exc:
            err_str = str(exc).upper()
            if not verify or ("CERTIFICATE" not in err_str and "SSL" not in err_str):
                raise ConnectionError(f"Download failed for {url}: {exc}") from exc
            logger.warning("SSL verification failed for %s, retrying without cert check", url)
    raise ConnectionError(f"Download failed for {url}")  # unreachable


def _read_file_source(base_path: str, filename: str) -> bytes:
    """Read a file from a local or UNC path."""
    p = Path(base_path) / filename
    if not p.exists():
        raise FileNotFoundError(f"Not found: {p}")
    return p.read_bytes()


def _fetch_github_manifest(repo: str) -> UpdateManifest:
    """Fetch the latest release from GitHub API and build a manifest."""
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    logger.info("Checking GitHub releases: %s", api_url)

    try:
        raw = _http_get(api_url)
    except ConnectionError as exc:
        if "404" in str(exc):
            raise ValueError(
                f"No releases found for {repo}. "
                f"Create a release on GitHub with an attached installer .exe to enable updates."
            ) from exc
        raise

    release = json.loads(raw)

    manifest = UpdateManifest.from_github_release(release)
    if not manifest.version:
        raise ValueError("GitHub release has no valid tag/version.")
    if not manifest.installer_filename:
        raise ValueError(
            f"GitHub release v{manifest.version} has no installer asset "
            f"matching pattern '{_INSTALLER_PATTERN.pattern}'. "
            f"Make sure you attach the .exe installer to the release."
        )

    logger.info(
        "GitHub release found: v%s (%s), asset: %s (%d bytes)",
        manifest.version, manifest.build_date,
        manifest.installer_filename, manifest.installer_size_bytes,
    )
    return manifest


def fetch_manifest(source: str) -> UpdateManifest:
    """Fetch and parse update info from the configured source.

    Supports:
    - ``github:owner/repo`` — GitHub Releases API
    - ``http(s)://...`` — HTTP server with update.json
    - Local/UNC paths — folder with update.json
    """
    if not source or not source.strip():
        raise ValueError("Update source is not configured.")

    source = source.strip()
    logger.info("Fetching update manifest from: %s", source)

    if _is_github(source):
        repo = _parse_github_repo(source)
        return _fetch_github_manifest(repo)

    # Legacy: HTTP or file-based update.json
    try:
        if _is_http(source):
            raw = _http_get(source.rstrip("/") + "/update.json")
        else:
            raw = _read_file_source(source, "update.json")
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise ConnectionError(f"Cannot reach update source: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid update.json: {exc}") from exc

    manifest = UpdateManifest.from_dict(data)
    if not manifest.version:
        raise ValueError("update.json is missing the 'version' field.")

    logger.info("Remote version: %s (current: %s)", manifest.version, VERSION)
    return manifest


# ---------------------------------------------------------------------------
# Check for updates
# ---------------------------------------------------------------------------

@dataclass
class UpdateCheckResult:
    """Result returned to the UI when checking for updates."""

    update_available: bool = False
    current_version: str = VERSION
    remote_version: str = ""
    build_date: str = ""
    changelog: str = ""
    mandatory: bool = False
    installer_filename: str = ""
    installer_size_bytes: int = 0
    error: str = ""


def check_for_update(source: str) -> UpdateCheckResult:
    """Check the configured source for a newer version.

    Returns an UpdateCheckResult (never raises).
    """
    result = UpdateCheckResult()
    try:
        manifest = fetch_manifest(source)
        result.remote_version = manifest.version
        result.build_date = manifest.build_date
        result.changelog = manifest.changelog
        result.mandatory = manifest.mandatory
        result.installer_filename = manifest.installer_filename
        result.installer_size_bytes = manifest.installer_size_bytes
        result.update_available = is_newer(manifest.version, VERSION)
    except Exception as exc:
        logger.warning("Update check failed: %s", exc)
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# Download installer
# ---------------------------------------------------------------------------

def download_installer(source: str, manifest: UpdateManifest, dest_dir: Path) -> Path:
    """Download the installer file from the update source to *dest_dir*.

    For GitHub sources, downloads directly from the asset URL.
    For file/HTTP sources, downloads from the base source path.

    Returns:
        Path to the downloaded installer file.
    """
    if not manifest.installer_filename:
        raise ValueError("Manifest does not specify an installer filename.")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / manifest.installer_filename

    logger.info("Downloading %s to %s", manifest.installer_filename, dest_file)

    source = source.strip()

    if manifest.download_url:
        # GitHub: stream download from the direct asset URL
        total = _http_download_stream(manifest.download_url, dest_file)
        logger.info("Download complete: %d bytes (streamed)", total)
    elif _is_http(source):
        raw = _http_get(source.rstrip("/") + "/" + manifest.installer_filename, timeout=300)
        dest_file.write_bytes(raw)
        logger.info("Download complete: %d bytes", len(raw))
    else:
        raw = _read_file_source(source, manifest.installer_filename)
        dest_file.write_bytes(raw)
        logger.info("Download complete: %d bytes", len(raw))

    # Verify SHA256 if provided
    if manifest.sha256:
        actual_hash = hashlib.sha256(dest_file.read_bytes()).hexdigest().lower()
        expected_hash = manifest.sha256.strip().lower()
        if actual_hash != expected_hash:
            dest_file.unlink(missing_ok=True)
            raise ValueError(
                f"SHA256 mismatch: expected {expected_hash}, got {actual_hash}. "
                f"Downloaded file has been deleted."
            )
        logger.info("SHA256 verified: %s", actual_hash)
    else:
        logger.warning("No SHA256 in manifest; skipping hash verification.")

    return dest_file


# ---------------------------------------------------------------------------
# Launch installer and exit
# ---------------------------------------------------------------------------

def launch_installer(installer_path: Path) -> None:
    """Launch the downloaded installer and signal the app to exit.

    On Windows, runs the installer via subprocess.Popen detached from the
    current process. On other platforms, attempts to use the default handler.
    """
    if not installer_path.exists():
        raise FileNotFoundError(f"Installer not found: {installer_path}")

    logger.info("Launching installer: %s", installer_path)

    if platform.system() == "Windows":
        # Detach the installer process from the current app
        # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        creation_flags = 0x00000200 | 0x00000008
        subprocess.Popen(
            [str(installer_path)],
            creationflags=creation_flags,
            close_fds=True,
        )
    else:
        # On Linux/macOS, attempt xdg-open or open
        opener = "open" if platform.system() == "Darwin" else "xdg-open"
        subprocess.Popen([opener, str(installer_path)])

    logger.info("Installer launched; application should exit now.")

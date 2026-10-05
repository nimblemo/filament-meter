"""Find, download and provision an OrcaSlicer build.

PyPI installs run in an isolated, network-less sandbox, so downloading a
~50 MB slicer at ``pip install`` time is not an option. Instead the tool
provisions OrcaSlicer **lazily on first run** (or eagerly with
``--install-orca``): it looks for a system install first, and only falls
back to downloading a portable build into the user cache directory.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import platformdirs

from filament_meter.errors import OrcaDownloadError, OrcaNotFoundError, OrcaProvisionError
from filament_meter.slicer import subprocess_hide_kwargs

#: GitHub Releases API for the upstream OrcaSlicer repository.
GITHUB_RELEASES_API = "https://api.github.com/repos/SoftFever/OrcaSlicer/releases"

#: User-Agent sent with every GitHub request (GitHub requires one).
USER_AGENT = "filament-meter"

#: Environment variable pointing at an explicit OrcaSlicer executable.
ENV_ORCA = "FILAMENT_METER_ORCA"

#: Environment variable overriding the cache directory.
ENV_CACHE = "FILAMENT_METER_CACHE_DIR"

#: Application name used for the platform cache directory.
APP_NAME = "filament-meter"

#: Download chunk size (1 MiB).
DOWNLOAD_CHUNK = 1024 * 1024

#: Network timeout for metadata requests, in seconds.
HTTP_TIMEOUT = 60


def cache_root(override: str | Path | None = None) -> Path:
    """Return the directory that holds downloaded OrcaSlicer builds.

    Resolution order: ``override`` argument → ``FILAMENT_METER_CACHE_DIR``
    env var → the platform cache directory (via :mod:`platformdirs`). The
    ``orca`` sub-directory is always appended.
    """
    if override:
        base = Path(override).expanduser()
    else:
        env_value = os.getenv(ENV_CACHE)
        if env_value:
            base = Path(env_value).expanduser()
        else:
            base = Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))
    return base / "orca"


def detect_platform() -> str:
    """Return one of ``"windows"``, ``"macos"`` or ``"linux"``."""
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def machine_arch() -> str:
    """Return ``"arm64"`` on ARM machines, otherwise ``"x64"``."""
    return "arm64" if "arm" in platform.machine().lower() else "x64"


def _which_names() -> tuple[str, ...]:
    """Executable names to look up on ``PATH``."""
    return ("orca-slicer", "OrcaSlicer", "orca-slicer.exe", "OrcaSlicer.exe")


def _platform_candidates() -> list[Path]:
    """Return well-known install locations for the current platform."""
    platform_name = detect_platform()
    candidates: list[Path] = []
    if platform_name == "windows":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Programs" / "OrcaSlicer" / "orca-slicer.exe")
        candidates.append(Path("C:/Program Files/OrcaSlicer/orca-slicer.exe"))
        candidates.append(Path("C:/Program Files (x86)/OrcaSlicer/orca-slicer.exe"))
        program_files = os.getenv("PROGRAMFILES")
        if program_files:
            candidates.append(Path(program_files) / "OrcaSlicer" / "orca-slicer.exe")
    elif platform_name == "macos":
        candidates.append(Path("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"))
        candidates.append(
            Path.home() / "Applications" / "OrcaSlicer.app" / "Contents" / "MacOS" / "OrcaSlicer"
        )
    else:
        candidates.append(Path("/opt/OrcaSlicer/bin/orca-slicer"))
        candidates.append(Path("/opt/OrcaSlicer/orca-slicer"))
        candidates.append(Path("/usr/local/bin/orca-slicer"))
        candidates.append(Path.home() / ".local/bin/orca-slicer")
        apps_dir = Path.home() / "Applications"
        if apps_dir.is_dir():
            candidates.extend(sorted(apps_dir.glob("*.AppImage")))
    return candidates


def _binary_names(platform_name: str) -> tuple[str, ...]:
    """Return candidate binary file names for ``platform_name``."""
    if platform_name == "windows":
        return ("orca-slicer.exe", "OrcaSlicer.exe", "orca-slicer-console.exe")
    if platform_name == "macos":
        return ("OrcaSlicer", "orca-slicer")
    return ("orca-slicer", "OrcaSlicer", "orca_slicer")


def _find_binary(root: Path, platform_name: str) -> Path | None:
    """Search ``root`` for an OrcaSlicer executable."""
    if not root.is_dir():
        return None
    for name in _binary_names(platform_name):
        matches = sorted(root.rglob(name))
        if matches:
            return matches[0]
    if platform_name == "linux":
        appimages = sorted(root.rglob("*.AppImage"))
        if appimages:
            return appimages[0]
    return None


def find_orca(explicit: str | Path | None = None) -> Path | None:
    """Locate an OrcaSlicer executable.

    Priority order: explicit path → ``FILAMENT_METER_ORCA`` env var →
    ``PATH`` → well-known install locations → the download cache.

    Args:
        explicit: An explicit executable path (``--orca``).

    Returns:
        A path to an existing executable, or ``None``.
    """
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.is_file() else None

    env_value = os.getenv(ENV_ORCA)
    if env_value:
        candidate = Path(env_value).expanduser()
        if candidate.is_file():
            return candidate

    for name in _which_names():
        found = shutil.which(name)
        if found:
            return Path(found)

    for candidate in _platform_candidates():
        if candidate.is_file():
            return candidate

    return _find_binary(cache_root(), detect_platform())


def _http_json(url: str) -> dict[str, Any]:
    """Fetch ``url`` and decode the JSON body, mapping errors to our types."""
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT) as response:
            payload = response.read()
    except HTTPError as exc:
        raise OrcaDownloadError(f"HTTP {exc.code} while requesting {url}") from exc
    except URLError as exc:
        raise OrcaDownloadError(f"network error while requesting {url}: {exc.reason}") from exc
    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OrcaDownloadError(f"invalid JSON received from {url}") from exc
    if not isinstance(data, dict):
        raise OrcaDownloadError(f"unexpected response shape from {url}")
    return data


def fetch_release(version: str = "latest") -> dict[str, Any]:
    """Fetch GitHub release metadata for ``version``.

    Args:
        version: ``"latest"`` for the newest release, or an explicit version
            such as ``"2.4.2"`` (with or without a leading ``v``).

    Returns:
        The decoded release JSON object.

    Raises:
        OrcaDownloadError: If the release cannot be resolved.
    """
    if version and version.lower() not in ("latest", ""):
        last_error = ""
        for tag in (f"v{version}", version):
            try:
                return _http_json(f"{GITHUB_RELEASES_API}/tags/{tag}")
            except OrcaDownloadError as exc:
                last_error = str(exc)
        raise OrcaDownloadError(f"could not resolve OrcaSlicer release {version!r}: {last_error}")
    return _http_json(f"{GITHUB_RELEASES_API}/latest")


def _asset_predicates(platform_name: str, arch: str) -> list[Callable[[str], bool]]:
    """Return ordered asset-name predicates for a platform."""
    if platform_name == "windows":
        return [
            lambda n: "Windows" in n and "portable" in n and arch in n and n.endswith(".zip"),
            lambda n: "Windows" in n and "portable" in n and n.endswith(".zip"),
            lambda n: "Windows" in n and n.endswith(".zip"),
        ]
    if platform_name == "macos":
        return [
            lambda n: "Mac" in n and n.endswith(".dmg"),
            lambda n: "mac" in n.lower() and n.endswith(".dmg"),
        ]

    # Linux ships AppImage builds for both x86_64 and aarch64, and GitHub
    # lists the aarch64 asset *before* the x86_64 one. The architecture must
    # therefore be part of the match, otherwise an x64 host downloads an ARM
    # binary that cannot execute (provisioning would "succeed" with a dead
    # binary and every slice would then fail).
    def _is_arm(name: str) -> bool:
        return "aarch64" in name or "arm64" in name

    if arch == "arm64":
        return [
            lambda n: "Linux" in n and "AppImage" in n and "Ubuntu2404" in n and _is_arm(n),
            lambda n: "Linux" in n and "AppImage" in n and _is_arm(n),
            lambda n: "Linux" in n and n.endswith(".AppImage"),
        ]
    return [
        lambda n: "Linux" in n and "AppImage" in n and "Ubuntu2404" in n and not _is_arm(n),
        lambda n: "Linux" in n and "AppImage" in n and not _is_arm(n),
        lambda n: "Linux" in n and n.endswith(".AppImage") and not _is_arm(n),
    ]


def select_asset(release: dict[str, Any], platform_name: str, arch: str = "x64") -> dict[str, Any]:
    """Pick the best release asset for ``platform_name`` / ``arch``.

    Raises:
        OrcaDownloadError: If no suitable asset is found.
    """
    raw_assets = release.get("assets") or []
    assets: list[dict[str, Any]] = [asset for asset in raw_assets if asset.get("name")]
    if not assets:
        raise OrcaDownloadError("OrcaSlicer release has no downloadable assets")
    for predicate in _asset_predicates(platform_name, arch):
        for asset in assets:
            if predicate(asset["name"]):
                return asset
    names = ", ".join(asset["name"] for asset in assets)
    raise OrcaDownloadError(
        f"no OrcaSlicer asset for {platform_name}/{arch}; available assets: {names}"
    )


def _report_progress(done: int, total: int, name: str) -> None:
    """Write a single-line download progress update to stderr."""
    done_mib = done / 1048576
    if total > 0:
        total_mib = total / 1048576
        percent = done * 100 / total
        message = f"\r  downloading {name}: {done_mib:.1f}/{total_mib:.1f} MiB ({percent:.0f}%)"
    else:
        message = f"\r  downloading {name}: {done_mib:.1f} MiB"
    sys.stderr.write(message)
    sys.stderr.flush()


def _download_file(url: str, dest: Path, *, progress: bool, expected: int | None = None) -> None:
    """Download ``url`` to ``dest`` atomically, with optional progress."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT) as response, part.open("wb") as handle:
            header_length = response.headers.get("Content-Length")
            total = int(header_length) if header_length else int(expected or 0)
            downloaded = 0
            while True:
                chunk = response.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if progress:
                    _report_progress(downloaded, total, dest.name)
    except HTTPError as exc:
        part.unlink(missing_ok=True)
        raise OrcaDownloadError(f"HTTP {exc.code} while downloading {url}") from exc
    except URLError as exc:
        part.unlink(missing_ok=True)
        raise OrcaDownloadError(f"network error while downloading {url}: {exc.reason}") from exc
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise OrcaDownloadError(f"failed to write {dest}: {exc}") from exc
    if progress:
        sys.stderr.write("\n")
        sys.stderr.flush()
    part.replace(dest)


def _make_executable(path: Path) -> None:
    """Best-effort ``chmod +x`` on a provisioned binary."""
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def _run_process(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` via :func:`subprocess.run`.

    A thin indirection so tests can patch :data:`_run_process` instead of the
    global :func:`subprocess.run` (which would also affect unrelated callers).
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(cmd, **kwargs)
    return result


def _install_dmg(archive: Path, target: Path, platform_name: str) -> Path:
    """Mount a macOS ``.dmg`` and copy the ``.app`` bundle into ``target``."""
    if detect_platform() != "macos":
        raise OrcaProvisionError(
            "cannot install a macOS .dmg on this platform; "
            "install OrcaSlicer manually and pass --orca"
        )
    mount_point = target / "_mnt"
    mount_point.mkdir(parents=True, exist_ok=True)
    attach = _run_process(
        ["hdiutil", "attach", str(archive), "-nobrowse", "-mountpoint", str(mount_point)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if attach.returncode != 0:
        raise OrcaProvisionError(f"hdiutil attach failed: {attach.stderr.strip()}")
    try:
        apps = sorted(mount_point.glob("*.app"))
        if not apps:
            raise OrcaProvisionError("no .app bundle found inside the mounted image")
        dest_app = target / apps[0].name
        if dest_app.exists():
            shutil.rmtree(dest_app, ignore_errors=True)
        shutil.copytree(apps[0], dest_app)
    finally:
        _run_process(
            ["hdiutil", "detach", str(mount_point)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    binary = _find_binary(target, platform_name)
    if binary is None:
        raise OrcaProvisionError("copied .app bundle has no OrcaSlicer executable")
    return binary


def _install_asset(archive: Path, target: Path, platform_name: str, asset_name: str) -> Path:
    """Extract / install a downloaded asset and return the binary path."""
    lowered = asset_name.lower()
    if lowered.endswith(".zip"):
        try:
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(target)
        except (zipfile.BadZipFile, OSError) as exc:
            raise OrcaProvisionError(f"failed to extract {asset_name}: {exc}") from exc
        binary = _find_binary(target, platform_name)
        if binary is None:
            raise OrcaProvisionError(
                f"no OrcaSlicer executable found after extracting {asset_name}"
            )
        return binary
    if lowered.endswith(".appimage"):
        _make_executable(archive)
        return archive
    if lowered.endswith(".dmg"):
        return _install_dmg(archive, target, platform_name)
    raise OrcaProvisionError(f"unsupported archive format: {asset_name}")


def download_orca(
    version: str = "latest",
    cache_dir: str | Path | None = None,
    *,
    progress: bool = True,
) -> Path:
    """Download and provision OrcaSlicer into the cache directory.

    Idempotent: if a working binary is already present for the requested
    version, it is returned without any network traffic.

    Args:
        version: ``"latest"`` or an explicit version such as ``"2.4.2"``.
        cache_dir: Optional cache-directory override.
        progress: Whether to print download progress to stderr.

    Returns:
        The path to the provisioned OrcaSlicer executable.

    Raises:
        OrcaDownloadError: On network / release-resolution failures.
        OrcaProvisionError: If the downloaded build cannot be installed.
    """
    root = cache_root(cache_dir)
    platform_name = detect_platform()

    # A pinned version can be served entirely from the cache, without any
    # network round-trip; "latest" needs the release metadata to resolve.
    if version and version.lower() not in ("latest", ""):
        pinned = root / (version.lstrip("vV") or version)
        cached = _find_binary(pinned, platform_name)
        if cached is not None:
            return cached

    release = fetch_release(version)
    resolved = str(release.get("tag_name") or version)
    slug = resolved.lstrip("vV") or resolved
    target = root / slug

    existing = _find_binary(target, platform_name)
    if existing is not None:
        return existing

    asset = select_asset(release, platform_name, machine_arch())
    target.mkdir(parents=True, exist_ok=True)
    archive = target / str(asset["name"])
    expected = asset.get("size")
    _download_file(
        str(asset["browser_download_url"]),
        archive,
        progress=progress,
        expected=int(expected) if expected else None,
    )

    binary = _install_asset(archive, target, platform_name, str(asset["name"]))
    _make_executable(binary)

    if not binary.is_file() or binary.stat().st_size == 0:
        raise OrcaProvisionError(f"downloaded OrcaSlicer binary is missing or empty: {binary}")

    if str(asset["name"]).lower().endswith((".zip", ".dmg")):
        archive.unlink(missing_ok=True)

    (target / "VERSION").write_text(resolved + "\n", encoding="utf-8")
    _verify_binary(binary)
    return binary


def orca_version(binary: str | Path) -> str | None:
    """Return the OrcaSlicer version string, best-effort.

    Never raises: an unresponsive binary simply yields ``None``.
    """
    try:
        proc = _run_process(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            stdin=subprocess.DEVNULL,
            **subprocess_hide_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    match = re.search(r"(\d+\.\d+\.\d+)", output)
    if match:
        return match.group(1)
    first_line = output.splitlines()[0].strip() if output else ""
    lowered = first_line.lower()
    if first_line and "invalid" not in lowered and "option" not in lowered:
        return first_line
    return None


def _verify_binary(binary: Path) -> None:
    """Best-effort sanity check that ``binary`` can be launched."""
    orca_version(binary)


def ensure_orca(
    explicit: str | Path | None = None,
    *,
    auto_install: bool = True,
    version: str = "latest",
    cache_dir: str | Path | None = None,
    progress: bool = True,
) -> Path:
    """Return a usable OrcaSlicer path, downloading it if necessary.

    Args:
        explicit: Explicit executable path (``--orca``).
        auto_install: Whether downloading is permitted.
        version: Version to download when provisioning.
        cache_dir: Optional cache-directory override.
        progress: Whether to show download progress.

    Returns:
        The path to an OrcaSlicer executable.

    Raises:
        OrcaNotFoundError: If nothing is found and ``auto_install`` is off.
    """
    found = find_orca(explicit)
    if found is not None:
        return found
    if not auto_install:
        raise OrcaNotFoundError(
            "OrcaSlicer was not found. Install it, pass --orca <path>, set "
            f"{ENV_ORCA}, or drop --no-auto-install to download it automatically."
        )
    return download_orca(version=version, cache_dir=cache_dir, progress=progress)

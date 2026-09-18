"""
Cross-Platform Build Script for Download Anything
===================================================
1. Ensures platform-specific static `ffmpeg` binary exists in `bin/`.
2. Compiles DownloadAnything into a standalone executable with versioning.
"""

from __future__ import annotations

import gzip
import os
import pathlib
import platform
import shutil
import ssl
import sys
import urllib.request

# Ensure UTF-8 output even in limited terminals (e.g. Windows cp1252)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
BIN_DIR = PROJECT_ROOT / "bin"
BIN_DIR.mkdir(exist_ok=True)

FFMPEG_GZ_URLS: dict[tuple[str, str], str] = {
    ("darwin", "arm64"): "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/ffmpeg-darwin-arm64.gz",
    ("darwin", "x86_64"): "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/ffmpeg-darwin-x64.gz",
    ("linux", "x86_64"): "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/ffmpeg-linux-x64.gz",
    ("linux", "arm64"): "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/ffmpeg-linux-arm64.gz",
    ("win32", "x86_64"): "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/ffmpeg-win32-x64.gz",
}


def get_version() -> str:
    env_ver = os.getenv("APP_VERSION")
    if env_ver:
        return env_ver if env_ver.startswith("v") else f"v{env_ver}"
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from main import __version__
        return f"v{__version__}"
    except Exception:
        return "v1.0.0"


def get_platform_key() -> tuple[str, str]:
    if sys.platform.startswith("win"):
        os_name = "win32"
    elif sys.platform.startswith("darwin"):
        os_name = "darwin"
    else:
        os_name = "linux"

    mach = platform.machine().lower()
    if mach in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = "x86_64"

    return os_name, arch


def _create_ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            return ssl._create_unverified_context()


def ensure_ffmpeg() -> pathlib.Path:
    ffmpeg_exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    target_bin = BIN_DIR / ffmpeg_exe

    if target_bin.exists() and os.access(target_bin, os.X_OK):
        print(f"[OK] Found working ffmpeg binary at: {target_bin}")
        return target_bin

    # Try local system ffmpeg first
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        print(f"[OK] Copying system ffmpeg from {system_ffmpeg} to {target_bin}")
        shutil.copy2(system_ffmpeg, target_bin)
        target_bin.chmod(0o755)
        return target_bin

    # Download prebuilt static ffmpeg
    plat_key = get_platform_key()
    url = FFMPEG_GZ_URLS.get(plat_key)
    if not url:
        # Fallback to x86_64 if specific arch not found
        url = FFMPEG_GZ_URLS.get((plat_key[0], "x86_64"))

    if not url:
        raise RuntimeError(f"No prebuilt ffmpeg found for platform {plat_key}")

    print(f"[+] Downloading static ffmpeg for {plat_key[0]}-{plat_key[1]} from {url} ...")
    gz_archive = BIN_DIR / f"{ffmpeg_exe}.gz"

    ctx = _create_ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (DownloadAnything Build)"})
    with urllib.request.urlopen(req, context=ctx) as resp, open(gz_archive, "wb") as f_out:
        shutil.copyfileobj(resp, f_out)

    print(f"[*] Extracting {gz_archive.name} -> {target_bin.name} ...")
    with gzip.open(gz_archive, "rb") as f_in, open(target_bin, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    gz_archive.unlink(missing_ok=True)
    target_bin.chmod(0o755)

    if target_bin.exists():
        print(f"[OK] Successfully prepared ffmpeg at {target_bin}")
    else:
        raise RuntimeError(f"Failed to prepare ffmpeg at {target_bin}")

    return target_bin


def run_pyinstaller():
    import PyInstaller.__main__

    version_str = get_version()
    app_name = f"DownloadAnything-{version_str}"
    ffmpeg_bin = ensure_ffmpeg()

    sep = ";" if sys.platform.startswith("win") else ":"

    add_data = [
        f"{PROJECT_ROOT / 'static'}{sep}static",
        f"{PROJECT_ROOT / 'templates'}{sep}templates",
    ]

    add_binary = [
        f"{ffmpeg_bin}{sep}bin",
    ]

    hidden_imports = [
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "starlette",
        "sse_starlette",
        "fastapi",
        "yt_dlp",
    ]

    args = [
        str(PROJECT_ROOT / "main.py"),
        f"--name={app_name}",
        "--onefile",
        "--noconfirm",
        "--clean",
    ]

    for d in add_data:
        args.append(f"--add-data={d}")

    for b in add_binary:
        args.append(f"--add-binary={b}")

    for h in hidden_imports:
        args.append(f"--hidden-import={h}")

    print(f"[>] Running PyInstaller for {app_name} with args:", args)
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    ensure_ffmpeg()
    run_pyinstaller()

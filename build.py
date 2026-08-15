"""
Cross-Platform Build Script for Download Anything
===================================================
1. Ensures platform-specific static `ffmpeg` binary exists in `bin/`.
2. Compiles DownloadAnything into a standalone executable with versioning.
"""

from __future__ import annotations

import os
import pathlib
import platform
import shutil
import sys
import urllib.request
import zipfile
import tarfile

PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
BIN_DIR = PROJECT_ROOT / "bin"
BIN_DIR.mkdir(exist_ok=True)

FFBINARIES_URLS = {
    "linux": "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-linux-64.zip",
    "win32": "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-win-64.zip",
    "darwin": "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-osx-64.zip",
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


def ensure_ffmpeg() -> pathlib.Path:
    ffmpeg_exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    target_bin = BIN_DIR / ffmpeg_exe

    if target_bin.exists():
        print(f"✓ Found ffmpeg binary at: {target_bin}")
        return target_bin

    # Try local system ffmpeg first
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        print(f"✓ Copying system ffmpeg from {system_ffmpeg} to {target_bin}")
        shutil.copy2(system_ffmpeg, target_bin)
        target_bin.chmod(0o755)
        return target_bin

    # Download prebuilt static ffmpeg
    plat_key = "win32" if sys.platform.startswith("win") else ("darwin" if sys.platform.startswith("darwin") else "linux")
    url = FFBINARIES_URLS.get(plat_key)
    print(f"⬇ Downloading static ffmpeg for {plat_key} from {url} ...")

    archive_path = BIN_DIR / "ffmpeg_download.zip"
    urllib.request.urlretrieve(url, archive_path)

    with zipfile.ZipFile(archive_path, "r") as zip_ref:
        zip_ref.extractall(BIN_DIR)

    if archive_path.exists():
        archive_path.unlink()

    if target_bin.exists():
        target_bin.chmod(0o755)
        print(f"✓ Successfully extracted ffmpeg to {target_bin}")
    else:
        print(f"⚠️ Warning: ffmpeg extraction finish check: {target_bin} not found directly.")

    return target_bin


def run_pyinstaller():
    import PyInstaller.__main__

    version_str = get_version()
    app_name = f"DownloadAnything-{version_str}"
    ffmpeg_bin = ensure_ffmpeg()

    sep = ";" if sys.platform.startswith("win") else ":"
    
    add_data = [
        f"static{sep}static",
        f"templates{sep}templates",
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
        "sse_starlette",
        "fastapi",
        "yt_dlp",
    ]

    args = [
        str(PROJECT_ROOT / "main.py"),
        f"--name={app_name}",
        "--onefile",
        "--clean",
    ]

    for d in add_data:
        args.append(f"--add-data={d}")

    for b in add_binary:
        args.append(f"--add-binary={b}")

    for h in hidden_imports:
        args.append(f"--hidden-import={h}")

    print(f"🚀 Running PyInstaller for {app_name} with args:", args)
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    ensure_ffmpeg()
    run_pyinstaller()

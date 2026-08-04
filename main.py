"""
Download Anything – FastAPI Backend
====================================
Endpoints:
  POST /api/info                      – fetch video metadata via yt-dlp
  GET  /api/progress/{task_id}        – SSE progress stream & background download trigger
  GET  /api/file/{task_id}            – instant file delivery after 100% completion
  GET  /                              – serve index.html
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import re
import shutil
import time
import urllib.parse
from contextlib import asynccontextmanager
from typing import AsyncIterator

import yt_dlp
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DOWNLOAD_DIR = pathlib.Path("/tmp/download_anything")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Shared in-memory task registry
task_progress: dict[str, dict] = {}

# Node.js runtime configuration for yt-dlp JS challenges
NODE_PATH = shutil.which("node")
JS_RUNTIMES_OPT = {"js_runtimes": {"node": {"path": NODE_PATH}}} if NODE_PATH else {}

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Clean up stale temp files on startup and shutdown."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for f in DOWNLOAD_DIR.iterdir():
        try:
            f.unlink()
        except Exception:
            pass
    yield
    for f in DOWNLOAD_DIR.iterdir():
        try:
            f.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Download Anything", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class InfoRequest(BaseModel):
    url: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_error_message(raw_msg: str) -> str:
    """Remove ANSI escape sequences and verbose yt-dlp error prefixes."""
    clean = re.sub(r"\x1b\[[0-9;]*[mGKB]", "", raw_msg)
    clean = re.sub(r"^ERROR:\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\[youtube\]\s*", "", clean, flags=re.IGNORECASE)
    return clean.strip()


def _clean_filename(name: str | None, ext: str) -> str:
    """Sanitize video title into a clean filename for download headers."""
    if not name:
        return f"download.{ext}"
    clean = re.sub(r'[\\/*?:\x22<>|\r\n\t]', "", name)
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        clean = "download"
    return f"{clean}.{ext}"


def _make_progress_hook(task_id: str):
    """Return a yt-dlp progress hook that updates task_progress[task_id]."""
    def hook(d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            downloaded = d.get("downloaded_bytes", 0) or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total > 0:
                pct = int(downloaded / total * 100)
                if task_id in task_progress:
                    task_progress[task_id]["progress"] = min(pct, 99)
        elif status == "finished":
            if task_id in task_progress:
                task_progress[task_id]["progress"] = 100
                task_progress[task_id]["done"] = True
        elif status == "error":
            if task_id in task_progress:
                task_progress[task_id]["error"] = "Download error"
                task_progress[task_id]["done"] = True
    return hook


def _ydl_opts_for_quality(quality: str, task_id: str, output_template: str) -> dict:
    """Build yt-dlp options dict for the requested quality."""
    common = {
        "outtmpl": output_template,
        "progress_hooks": [_make_progress_hook(task_id)],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        **JS_RUNTIMES_OPT,
    }

    if quality == "mp3":
        return {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }
            ],
        }

    match = re.match(r"^(\d+)p$", quality)
    if match:
        h = int(match.group(1))
        return {
            **common,
            "format": f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best[height<={h}]/best",
            "merge_output_format": "mp4",
        }

    return {
        **common,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
    }


def _estimated_filesize(info: dict, quality: str) -> int:
    """Return an estimated filesize in bytes for the chosen quality."""
    duration = info.get("duration") or 0
    if quality == "mp3":
        return int(duration * 320 * 1000 / 8)
    
    match = re.match(r"^(\d+)p$", quality)
    if match:
        target_h = int(match.group(1))
        formats = info.get("formats") or []
        best = None
        for f in formats:
            h = f.get("height") or 0
            if h <= target_h and f.get("filesize"):
                if best is None or h > (best.get("height") or 0):
                    best = f
        if best and best.get("filesize"):
            return best["filesize"]
        
        bitrate_mbps = {2160: 15.0, 1440: 8.0, 1080: 4.5, 720: 2.5, 480: 1.2, 360: 0.7, 240: 0.4, 144: 0.2}
        mbps = bitrate_mbps.get(target_h, 2.0)
        return int(duration * mbps * 1_000_000 / 8)
    
    return 0


def _extract_available_formats(info: dict) -> list[dict]:
    """Extract all available video resolutions and MP3 audio option."""
    formats_list = info.get("formats") or []
    detected_heights = set()
    
    for f in formats_list:
        h = f.get("height")
        vcodec = f.get("vcodec", "none")
        if h and isinstance(h, int) and h >= 144 and vcodec != "none":
            detected_heights.add(h)
    
    sorted_heights = sorted(list(detected_heights), reverse=True)
    if not sorted_heights:
        sorted_heights = [1080, 720, 480, 360]

    formats = []
    for h in sorted_heights:
        if h >= 2160:
            quality_tag = "4K Ultra HD"
        elif h >= 1440:
            quality_tag = "2K QHD"
        elif h >= 1080:
            quality_tag = "Full HD"
        elif h >= 720:
            quality_tag = "HD Quality"
        elif h >= 480:
            quality_tag = "Standard Quality"
        else:
            quality_tag = "Standard"

        formats.append({
            "id": f"{h}p",
            "label": f"MP4 Video",
            "sublabel": f"{h}p • {quality_tag}",
            "ext": "mp4",
            "filesize": _estimated_filesize(info, f"{h}p"),
        })

    formats.append({
        "id": "mp3",
        "label": "MP3 Audio",
        "sublabel": "320kbps • High Quality",
        "ext": "mp3",
        "filesize": _estimated_filesize(info, "mp3"),
    })

    return formats


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    html_path = pathlib.Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/api/info")
async def get_info(body: InfoRequest):
    """Extract video metadata using yt-dlp without downloading."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "noplaylist": True,
        "skip_download": True,
        **JS_RUNTIMES_OPT,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(body.url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        clean_msg = _clean_error_message(str(exc))
        raise HTTPException(status_code=400, detail=clean_msg) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch info: {exc}") from exc

    if not info:
        raise HTTPException(status_code=400, detail="No information returned for this URL.")

    title = info.get("title") or "Unknown Title"
    thumbnail = info.get("thumbnail") or ""
    duration = int(info.get("duration") or 0)
    author = info.get("uploader") or info.get("channel") or info.get("creator") or "Unknown"

    formats = _extract_available_formats(info)

    return {
        "title": title,
        "thumbnail": thumbnail,
        "duration": duration,
        "author": author,
        "formats": formats,
    }


@app.get("/api/progress/{task_id}")
async def progress_stream(
    task_id: str,
    request: Request,
    url: str = Query(None),
    quality: str = Query(None),
):
    """
    SSE Progress Stream & Background Download Executor.
    Triggers download if url and quality are provided, and streams {"progress": N, "done": bool}.
    """
    # Initialize task state
    if task_id not in task_progress:
        task_progress[task_id] = {"progress": 0, "done": False, "error": None, "started": False}

    # Start download in thread pool if url and quality are passed
    if url and quality and not task_progress[task_id].get("started"):
        task_progress[task_id]["started"] = True
        safe_task = task_id.replace("-", "")[:16]
        output_template = str(DOWNLOAD_DIR / f"{safe_task}.%(ext)s")
        opts = _ydl_opts_for_quality(quality, task_id, output_template)

        def _run_bg_download():
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
            except yt_dlp.utils.DownloadError as exc:
                clean_err = _clean_error_message(str(exc))
                if task_id in task_progress:
                    task_progress[task_id]["error"] = clean_err
                    task_progress[task_id]["done"] = True
            except Exception as exc:
                clean_err = _clean_error_message(str(exc))
                if task_id in task_progress:
                    task_progress[task_id]["error"] = clean_err
                    task_progress[task_id]["done"] = True

        asyncio.get_event_loop().run_in_executor(None, _run_bg_download)

    async def event_generator():
        last_pct = -1
        timeout = 600
        start = time.monotonic()

        while True:
            if await request.is_disconnected():
                break

            state = task_progress.get(task_id)
            if state is None:
                await asyncio.sleep(0.2)
                if time.monotonic() - start > 5:
                    yield "data: {\"progress\": 0, \"done\": false}\n\n"
                    break
                continue

            pct = state.get("progress", 0)
            is_done = state.get("done", False)
            err = state.get("error")

            if err:
                yield f"data: {{\"progress\": 0, \"error\": \"{err}\"}}\n\n"
                break

            if pct != last_pct or is_done:
                last_pct = pct
                if is_done:
                    yield f"data: {{\"progress\": 100, \"done\": true, \"task_id\": \"{task_id}\"}}\n\n"
                    break
                else:
                    yield f"data: {{\"progress\": {pct}, \"done\": false}}\n\n"

            if time.monotonic() - start > timeout:
                break

            await asyncio.sleep(0.3)

    from starlette.responses import StreamingResponse
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/file/{task_id}")
async def deliver_file(
    task_id: str,
    background_tasks: BackgroundTasks,
    title: str = Query(None, description="Optional video title for download filename"),
):
    """
    Instant file delivery endpoint called AFTER 100% completion.
    Delivers file instantly and auto-deletes from disk immediately after.
    """
    safe_task = task_id.replace("-", "")[:16]
    candidates = list(DOWNLOAD_DIR.glob(f"{safe_task}.*"))

    if not candidates:
        raise HTTPException(status_code=404, detail="File expired or not found. Please try downloading again.")

    file_path = candidates[0]
    actual_ext = file_path.suffix.lstrip(".")

    target_filename = _clean_filename(title, actual_ext)
    quoted_filename = urllib.parse.quote(target_filename)

    def _cleanup():
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass

    background_tasks.add_task(_cleanup)

    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=target_filename,
        background=background_tasks,
        headers={
            "Content-Disposition": f"attachment; filename=\"{target_filename}\"; filename*=utf-8''{quoted_filename}",
        },
    )

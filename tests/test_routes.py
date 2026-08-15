"""
Integration tests for all HTTP routes in main.py.
yt-dlp is fully mocked — no real network calls are made.
"""
from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# pytest-asyncio mode configuration
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

class TestPageRoutes:
    async def test_serve_index(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<title>" in response.text
        assert "Download Anything" in response.text

    async def test_serve_privacy_policy(self, client):
        response = await client.get("/privacy-policy")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Privacy" in response.text

    async def test_serve_about(self, client):
        response = await client.get("/about")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_heartbeat(self, client):
        response = await client.post("/api/heartbeat")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"


# ---------------------------------------------------------------------------
# POST /api/info
# ---------------------------------------------------------------------------

class TestGetInfo:
    def _mock_ydl(self, fake_info: dict):
        """Return a context-manager mock that returns fake_info from extract_info."""
        ydl_instance = MagicMock()
        ydl_instance.extract_info.return_value = fake_info
        ydl_ctx = MagicMock()
        ydl_ctx.__enter__ = MagicMock(return_value=ydl_instance)
        ydl_ctx.__exit__ = MagicMock(return_value=False)
        return ydl_ctx

    async def test_success(self, client, fake_info):
        with patch("main.yt_dlp.YoutubeDL", return_value=self._mock_ydl(fake_info)):
            response = await client.post("/api/info", json={"url": "https://youtube.com/watch?v=test"})

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Video Title"
        assert data["thumbnail"] == "https://example.com/thumb.jpg"
        assert data["duration"] == 180
        assert data["author"] == "Test Channel"
        assert isinstance(data["formats"], list)
        assert len(data["formats"]) > 0
        assert "preview_url" in data
        assert "embed_url" in data
        assert "is_youtube" in data

    async def test_formats_include_mp3(self, client, fake_info):
        with patch("main.yt_dlp.YoutubeDL", return_value=self._mock_ydl(fake_info)):
            response = await client.post("/api/info", json={"url": "https://youtube.com/watch?v=test"})

        data = response.json()
        format_ids = [f["id"] for f in data["formats"]]
        assert "mp3" in format_ids

    async def test_download_error_returns_400(self, client):
        import yt_dlp

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(
            side_effect=yt_dlp.utils.DownloadError("\x1b[31mERROR: [youtube] Private video\x1b[0m")
        )
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch("main.yt_dlp.YoutubeDL", return_value=mock_cm):
            response = await client.post("/api/info", json={"url": "https://youtube.com/watch?v=private"})

        assert response.status_code == 400
        detail = response.json()["detail"]
        # ANSI codes and "[youtube]" prefix should be cleaned
        assert "\x1b" not in detail
        assert "[youtube]" not in detail

    async def test_generic_exception_returns_400(self, client):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(side_effect=RuntimeError("Unexpected failure"))
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch("main.yt_dlp.YoutubeDL", return_value=mock_cm):
            response = await client.post("/api/info", json={"url": "https://example.com/video"})

        assert response.status_code == 400
        assert "Unexpected failure" in response.json()["detail"]

    async def test_none_info_returns_400(self, client):
        ydl_instance = MagicMock()
        ydl_instance.extract_info.return_value = None
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=ydl_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch("main.yt_dlp.YoutubeDL", return_value=mock_cm):
            response = await client.post("/api/info", json={"url": "https://example.com/video"})

        assert response.status_code == 400
        assert "No information" in response.json()["detail"]

    async def test_missing_url_field_returns_422(self, client):
        response = await client.post("/api/info", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/progress/{task_id}
# ---------------------------------------------------------------------------

class TestProgressStream:
    async def test_returns_streaming_response(self, client):
        """Without url/quality params the SSE stream starts and terminates gracefully."""
        response = await client.get("/api/progress/some-task-id", timeout=10.0)
        # SSE always returns 200 with the event-stream media type
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    async def test_sse_without_params_emits_no_download(self, client):
        """When url and quality are missing, no background download is triggered."""
        import main as m
        task_id = "no-params-task"
        response = await client.get(f"/api/progress/{task_id}", timeout=10.0)
        # After the stream closes the task should have been cleaned up
        assert task_id not in m.task_progress


# ---------------------------------------------------------------------------
# GET /api/file/{task_id}
# ---------------------------------------------------------------------------

class TestDeliverFile:
    async def test_file_not_found_returns_404(self, client):
        response = await client.get("/api/file/nonexistent-task-id-xyz")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_file_delivery_success(self, client, temp_download_file):
        task_id, fake_file, tmp_path = temp_download_file

        response = await client.get(
            f"/api/file/{task_id}",
            params={"title": "My Test Video"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert response.content == b"fake video content"

    async def test_content_disposition_header(self, client, temp_download_file):
        task_id, fake_file, tmp_path = temp_download_file

        response = await client.get(
            f"/api/file/{task_id}",
            params={"title": "Test Video"},
            follow_redirects=True,
        )
        cd = response.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "filename" in cd

    async def test_content_disposition_unicode_title(self, client, temp_download_file):
        task_id, fake_file, tmp_path = temp_download_file

        response = await client.get(
            f"/api/file/{task_id}",
            params={"title": "Ünïcödé Tïtle"},
            follow_redirects=True,
        )
        cd = response.headers.get("content-disposition", "")
        # Must contain the RFC 5987 utf-8'' prefix for the encoded filename
        assert "filename*=utf-8''" in cd

from __future__ import annotations

import os
import pathlib
import tempfile
import sys
import pytest

from main import (
    BASE_DIR,
    STATIC_DIR,
    TEMPLATES_DIR,
    DOWNLOAD_DIR,
    _find_ffmpeg,
    _ydl_opts_for_quality,
    __version__,
)


def test_version_defined():
    assert __version__ == "1.0.0"


def test_paths_and_templates_exist():
    assert BASE_DIR.exists()
    assert STATIC_DIR.exists()
    assert TEMPLATES_DIR.exists()
    assert (TEMPLATES_DIR / "index.html").is_file()
    assert (TEMPLATES_DIR / "privacy_policy.html").is_file()
    assert (TEMPLATES_DIR / "about.html").is_file()


def test_download_dir_in_temp():
    assert DOWNLOAD_DIR.exists()
    expected_parent = pathlib.Path(tempfile.gettempdir()).resolve()
    assert expected_parent in DOWNLOAD_DIR.resolve().parents or DOWNLOAD_DIR.resolve() == expected_parent / "download_anything"


def test_find_ffmpeg_mocked(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    exe_name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    fake_ffmpeg = fake_bin / exe_name
    fake_ffmpeg.write_text("#!/bin/sh\necho ffmpeg")
    fake_ffmpeg.chmod(0o755)

    monkeypatch.setattr("main.BASE_DIR", tmp_path)
    res = _find_ffmpeg()
    assert res == str(fake_bin)


def test_ydl_opts_common():
    opts = _ydl_opts_for_quality("mp3", "test-task", "/tmp/test.mp3")
    assert opts["outtmpl"] == "/tmp/test.mp3"
    assert opts["quiet"] is True
    assert "postprocessors" in opts

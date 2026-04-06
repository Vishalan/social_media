"""Unit 4 — pipeline_runner subprocess launcher tests."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar import pipeline_runner  # noqa: E402


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "sidecar.sqlite3")
    db_module.init_db(db_path)
    return db_path


@pytest.fixture
def scripts_dir(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    return str(d)


@pytest.fixture
def fake_settings(tmp_db, scripts_dir):
    return SimpleNamespace(
        SIDECAR_DB_PATH=tmp_db,
        PIPELINE_SCRIPTS_PATH=scripts_dir,
        ANTHROPIC_API_KEY="sk-ant-test",
        ELEVENLABS_API_KEY="el-test",
        VEED_API_KEY="veed-test",
        FAL_API_KEY="fal-test",
        PEXELS_API_KEY="pex-test",
    )


@pytest.fixture
def patch_settings(fake_settings):
    from sidecar.config import settings_manager as sm
    with patch.object(sm, "_settings", fake_settings), patch.object(
        sm.__class__, "settings", property(lambda self: fake_settings)
    ):
        yield fake_settings


@pytest.fixture
def seed_run(tmp_db):
    conn = db_module.connect(tmp_db)
    try:
        rid = db_module.insert_pipeline_run(
            conn,
            topic_title="Veo 3.1 Lite launches",
            topic_url="https://example.com/veo",
            topic_score=42.0,
            selection_rationale="big deal",
            source_newsletter_date="2026-04-05",
        )
    finally:
        conn.close()
    return rid


# --- fake subprocess plumbing ----------------------------------------------


class _FakeProc:
    def __init__(self, rc: int, stdout: bytes, stderr: bytes, hang: bool = False):
        self._rc = rc
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.returncode = None
        self.pid = 12345
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(10)
        self.returncode = self._rc
        return self._stdout, self._stderr

    async def wait(self):
        self.returncode = self._rc if self._rc is not None else -9
        return self.returncode


def _install_fake_subprocess(monkeypatch, proc, captured_env: dict):
    async def _fake_create(*args, **kwargs):
        captured_env["cmd"] = list(args)
        captured_env["cwd"] = kwargs.get("cwd")
        captured_env["env"] = kwargs.get("env")
        return proc

    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", _fake_create
    )
    # killpg is best-effort; stub it so tests don't try to kill real PIDs.
    monkeypatch.setattr(
        "os.killpg", lambda pid, sig: setattr(proc, "killed", True)
    )
    monkeypatch.setattr("os.getpgid", lambda pid: pid)


HAPPY_STDOUT = """\
[1. Script generation]
  ✓  Script generated in 3.2s  (120 words)

[2. Thumbnail]
  ✓  thumbnail: output/thumbnails/veo31/thumbnail.png

[3. Voice]
  ✓  Voiceover saved: output/audio/veo31.mp3

[6. Assemble]
  ✓  Assembled in 12.3s  (45.6 MB → output/video/veo31_final.mp4)

============================================================
COST REPORT
============================================================
  Claude Sonnet    1500 in /   800 out tokens   $0.0123
  Claude Haiku      300 in /   150 out tokens   $0.0007
  ElevenLabs       1234 chars                   $0.3700
  VEED Fabric      15.5s  (480p, $0.10/s)       $1.5700
  --------------------------------------------------
  TOTAL                                          $1.9530
============================================================
"""


# --- tests ------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_closed() else asyncio.new_event_loop().run_until_complete(coro)


@pytest.mark.asyncio
async def test_happy_path_parses_paths_and_costs(
    patch_settings, seed_run, monkeypatch
):
    proc = _FakeProc(0, HAPPY_STDOUT.encode(), b"")
    captured: dict = {}
    _install_fake_subprocess(monkeypatch, proc, captured)
    monkeypatch.setattr(
        pipeline_runner.caption_gen_module,
        "generate_captions",
        lambda **kw: {"instagram": {}, "youtube": {}},
    )

    result = await pipeline_runner.run_pipeline_for_run(seed_run)
    assert result["ok"] is True

    conn = db_module.connect(patch_settings.SIDECAR_DB_PATH)
    try:
        row = db_module.get_pipeline_run(conn, seed_run)
    finally:
        conn.close()
    assert row["status"] == "generated"
    assert row["video_path"].endswith("output/video/veo31_final.mp4")
    assert row["thumbnail_path"].endswith("output/thumbnails/veo31/thumbnail.png")
    assert row["audio_path"].endswith("output/audio/veo31.mp3")
    assert abs(row["cost_sonnet"] - 0.0123) < 1e-6
    assert abs(row["cost_haiku"] - 0.0007) < 1e-6
    assert abs(row["cost_elevenlabs"] - 0.37) < 1e-6
    assert abs(row["cost_veed"] - 1.57) < 1e-6


@pytest.mark.asyncio
async def test_nonzero_exit_marks_failed_generation(
    patch_settings, seed_run, monkeypatch
):
    proc = _FakeProc(1, b"", b"BOOM: something broke\n")
    _install_fake_subprocess(monkeypatch, proc, {})
    monkeypatch.setattr(
        pipeline_runner.caption_gen_module,
        "generate_captions",
        lambda **kw: {},
    )

    result = await pipeline_runner.run_pipeline_for_run(seed_run)
    assert result["ok"] is False

    conn = db_module.connect(patch_settings.SIDECAR_DB_PATH)
    try:
        row = db_module.get_pipeline_run(conn, seed_run)
    finally:
        conn.close()
    assert row["status"] == "failed_generation"
    assert "BOOM" in (row["error_log"] or "")


@pytest.mark.asyncio
async def test_timeout_kills_and_marks_failed(
    patch_settings, seed_run, monkeypatch
):
    proc = _FakeProc(0, b"", b"", hang=True)
    _install_fake_subprocess(monkeypatch, proc, {})

    result = await pipeline_runner.run_pipeline_for_run(
        seed_run, timeout_seconds=0.1
    )
    assert result["ok"] is False
    assert result.get("timed_out") is True
    assert proc.killed is True

    conn = db_module.connect(patch_settings.SIDECAR_DB_PATH)
    try:
        row = db_module.get_pipeline_run(conn, seed_run)
    finally:
        conn.close()
    assert row["status"] == "failed_timeout"


@pytest.mark.asyncio
async def test_subprocess_env_constructed_from_settings_not_inherited(
    patch_settings, seed_run, monkeypatch
):
    # Set an unrelated sidecar env var that MUST NOT leak into the subprocess.
    monkeypatch.setenv("SIDECAR_SECRET_SAUCE", "should-not-leak")
    proc = _FakeProc(0, HAPPY_STDOUT.encode(), b"")
    captured: dict = {}
    _install_fake_subprocess(monkeypatch, proc, captured)
    monkeypatch.setattr(
        pipeline_runner.caption_gen_module,
        "generate_captions",
        lambda **kw: {},
    )

    await pipeline_runner.run_pipeline_for_run(seed_run)

    env = captured["env"]
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert env["ELEVENLABS_API_KEY"] == "el-test"
    assert env["VEED_API_KEY"] == "veed-test"
    assert env["FAL_API_KEY"] == "fal-test"
    assert env["PEXELS_API_KEY"] == "pex-test"
    assert env["SMOKE_TOPIC"] == "Veo 3.1 Lite launches"
    assert env["SMOKE_URL"] == "https://example.com/veo"
    assert "SIDECAR_SECRET_SAUCE" not in env


@pytest.mark.asyncio
async def test_output_paths_resolved_to_absolute(
    patch_settings, seed_run, monkeypatch
):
    proc = _FakeProc(0, HAPPY_STDOUT.encode(), b"")
    _install_fake_subprocess(monkeypatch, proc, {})
    monkeypatch.setattr(
        pipeline_runner.caption_gen_module,
        "generate_captions",
        lambda **kw: {},
    )

    result = await pipeline_runner.run_pipeline_for_run(seed_run)
    assert os.path.isabs(result["video_path"])
    assert os.path.isabs(result["thumbnail_path"])
    assert os.path.isabs(result["audio_path"])
    assert result["video_path"].startswith(patch_settings.PIPELINE_SCRIPTS_PATH)


@pytest.mark.asyncio
async def test_cost_report_parsed_correctly(
    patch_settings, seed_run, monkeypatch
):
    proc = _FakeProc(0, HAPPY_STDOUT.encode(), b"")
    _install_fake_subprocess(monkeypatch, proc, {})
    monkeypatch.setattr(
        pipeline_runner.caption_gen_module,
        "generate_captions",
        lambda **kw: {},
    )

    result = await pipeline_runner.run_pipeline_for_run(seed_run)
    costs = result["costs"]
    assert costs["cost_sonnet"] == 0.0123
    assert costs["cost_haiku"] == 0.0007
    assert costs["cost_elevenlabs"] == 0.37
    assert costs["cost_veed"] == 1.57


@pytest.mark.asyncio
async def test_caption_gen_called_after_successful_subprocess(
    patch_settings, seed_run, monkeypatch
):
    proc = _FakeProc(0, HAPPY_STDOUT.encode(), b"")
    _install_fake_subprocess(monkeypatch, proc, {})

    calls = {}

    def _fake_gen(script_text, headline, topic_url, client):
        calls["script_text"] = script_text
        calls["headline"] = headline
        calls["topic_url"] = topic_url
        return {"instagram": {"caption": "x"}, "youtube": {"title": "y"}}

    monkeypatch.setattr(
        pipeline_runner.caption_gen_module, "generate_captions", _fake_gen
    )

    await pipeline_runner.run_pipeline_for_run(seed_run)
    assert calls["headline"] == "Veo 3.1 Lite launches"
    assert calls["topic_url"] == "https://example.com/veo"

    conn = db_module.connect(patch_settings.SIDECAR_DB_PATH)
    try:
        row = db_module.get_pipeline_run(conn, seed_run)
    finally:
        conn.close()
    assert row["captions_json"] is not None
    assert "instagram" in row["captions_json"]


@pytest.mark.asyncio
async def test_caption_gen_failure_does_not_block_run_marking_generated(
    patch_settings, seed_run, monkeypatch
):
    proc = _FakeProc(0, HAPPY_STDOUT.encode(), b"")
    _install_fake_subprocess(monkeypatch, proc, {})

    def _boom(**kwargs):
        raise RuntimeError("caption_gen boom")

    monkeypatch.setattr(
        pipeline_runner.caption_gen_module, "generate_captions", _boom
    )

    result = await pipeline_runner.run_pipeline_for_run(seed_run)
    assert result["ok"] is True

    conn = db_module.connect(patch_settings.SIDECAR_DB_PATH)
    try:
        row = db_module.get_pipeline_run(conn, seed_run)
    finally:
        conn.close()
    assert row["status"] == "generated"
    # Captions should have been persisted as the empty fallback dict.
    assert row["captions_json"] == "{}"


@pytest.mark.asyncio
async def test_subprocess_command_is_python3_smoke_e2e_in_scripts_cwd(
    patch_settings, seed_run, monkeypatch
):
    proc = _FakeProc(0, HAPPY_STDOUT.encode(), b"")
    captured: dict = {}
    _install_fake_subprocess(monkeypatch, proc, captured)
    monkeypatch.setattr(
        pipeline_runner.caption_gen_module,
        "generate_captions",
        lambda **kw: {},
    )

    await pipeline_runner.run_pipeline_for_run(seed_run)
    cmd = captured["cmd"]
    assert cmd[0] == "python3"
    assert cmd[1] == "smoke_e2e.py"
    assert captured["cwd"] == str(Path(patch_settings.PIPELINE_SCRIPTS_PATH).resolve())

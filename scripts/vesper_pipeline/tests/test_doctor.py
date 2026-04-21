"""Tests for :mod:`scripts.vesper_pipeline.doctor`.

Hermetic — doctor injects env + filesystem probes so the test suite
doesn't touch the real filesystem beyond a per-test tmpdir.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline.doctor import (  # noqa: E402
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Doctor,
    format_results,
    main,
)


def _full_env() -> dict:
    return {
        "ANTHROPIC_API_KEY": "sk-ant-x",
        "REDIS_URL": "redis://localhost:6379",
        "COMFYUI_URL": "http://server:8188",
        "POSTIZ_URL": "http://server:3000",
        "POSTIZ_API_KEY": "po-xyz",
        "TELEGRAM_BOT_TOKEN": "tg-123",
        "TELEGRAM_OWNER_USER_ID": "4242",
        "FAL_API_KEY": "fal-456",
        "CHATTERBOX_REFERENCE_AUDIO": "/app/refs/archivist.wav",
    }


class _FakeFs:
    """Records which paths "exist" and their modes so tests declare
    the world they want without touching a real tmpdir."""

    def __init__(self):
        self.files: set[Path] = set()
        self.dirs: set[Path] = set()
        self.modes: dict[Path, int] = {}

    def exists(self, p: Path) -> bool:
        p = Path(p)
        return p in self.files or p in self.dirs

    def is_file(self, p: Path) -> bool:
        return Path(p) in self.files

    def is_dir(self, p: Path) -> bool:
        return Path(p) in self.dirs

    def mode(self, p: Path) -> int:
        return self.modes.get(Path(p), 0o644)


def _seed_full_happy_fs(fs: _FakeFs, repo: Path, channel: str = "vesper") -> None:
    """Seed every check's happy-path file/dir."""
    # Directories
    for d in (
        repo / "data",
        repo / "data" / "backups",
        repo / "output" / channel,
        repo / "assets" / channel / "sfx",
        repo / "assets" / channel / "overlays",
    ):
        fs.dirs.add(d)
    # Files
    fs.files.update({
        repo / "assets" / channel / "refs" / "archivist.wav",
        repo / "assets" / channel / "sfx" / "cut_heavy.wav",
        repo / "assets" / channel / "overlays" / "grain.mp4",
        repo / "assets" / channel / "overlays" / "dust.mp4",
        repo / "assets" / channel / "overlays" / "flicker.mp4",
        repo / "assets" / channel / "overlays" / "fog.mp4",
        repo / "assets" / "fonts" / "CormorantGaramond-Bold.ttf",
        repo / "comfyui_workflows" / "flux_still.json",
        repo / "comfyui_workflows" / "depth_parallax.json",
    })


def _build_doctor(
    repo: Path,
    *,
    env: dict | None = None,
    fs: _FakeFs | None = None,
    real_iterdir: bool = True,
) -> Doctor:
    fs = fs or _FakeFs()
    return Doctor(
        repo_root=repo,
        env=env or _full_env(),
        exists_fn=fs.exists,
        is_file_fn=fs.is_file,
        is_dir_fn=fs.is_dir,
        mode_fn=fs.mode,
    )


# ─── Env var tests ────────────────────────────────────────────────────────


class EnvVarCheckTests(unittest.TestCase):
    def test_full_env_passes_required(self):
        fs = _FakeFs()
        doctor = _build_doctor(Path("/fake/repo"), fs=fs)
        results = doctor._check_env_vars()
        required = [r for r in results if r.severity == CheckSeverity.REQUIRED]
        self.assertTrue(all(
            r.status == CheckStatus.PASS for r in required
        ), [r for r in required if r.status != CheckStatus.PASS])

    def test_missing_required_env_fails(self):
        env = _full_env()
        del env["ANTHROPIC_API_KEY"]
        doctor = _build_doctor(Path("/fake/repo"), env=env)
        results = doctor._check_env_vars()
        failed = [r for r in results
                  if r.status == CheckStatus.FAIL and r.name == "env:ANTHROPIC_API_KEY"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].severity, CheckSeverity.REQUIRED)
        self.assertTrue(failed[0].is_blocking)

    def test_missing_recommended_env_warns(self):
        env = _full_env()
        del env["FAL_API_KEY"]
        doctor = _build_doctor(Path("/fake/repo"), env=env)
        results = doctor._check_env_vars()
        warned = [r for r in results
                  if r.status == CheckStatus.WARN and r.name == "env:FAL_API_KEY"]
        self.assertEqual(len(warned), 1)
        self.assertFalse(warned[0].is_blocking)


# ─── Channel profile tests ────────────────────────────────────────────────


class ChannelProfileCheckTests(unittest.TestCase):
    def test_vesper_profile_loads(self):
        """Real load_channel_config('vesper') must succeed — this is an
        integration sanity check but hermetic because the profile lives
        in this repo."""
        doctor = _build_doctor(Path("/fake/repo"))
        results = doctor._check_channel_profile()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, CheckStatus.PASS)


# ─── Asset check tests ────────────────────────────────────────────────────


class VoiceReferenceCheckTests(unittest.TestCase):
    def test_present_file_passes(self):
        repo = Path("/fake/repo")
        fs = _FakeFs()
        fs.files.add(repo / "assets" / "vesper" / "refs" / "archivist.wav")
        doctor = _build_doctor(repo, fs=fs)
        results = doctor._check_voice_reference()
        self.assertEqual(results[0].status, CheckStatus.PASS)

    def test_missing_file_warns_not_fails(self):
        doctor = _build_doctor(Path("/fake/repo"), fs=_FakeFs())
        results = doctor._check_voice_reference()
        self.assertEqual(results[0].status, CheckStatus.WARN)
        self.assertFalse(results[0].is_blocking)


class SfxPackCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor-sfx-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_dir_warns(self):
        doctor = Doctor(repo_root=self.tmp, env=_full_env())
        results = doctor._check_sfx_pack()
        # SFX dir doesn't exist → WARN (real filesystem probes here
        # since iterdir is used).
        self.assertEqual(results[0].status, CheckStatus.WARN)

    def test_empty_dir_warns(self):
        sfx_dir = self.tmp / "assets" / "vesper" / "sfx"
        sfx_dir.mkdir(parents=True)
        doctor = Doctor(repo_root=self.tmp, env=_full_env())
        results = doctor._check_sfx_pack()
        self.assertEqual(results[0].status, CheckStatus.WARN)
        self.assertIn("no .wav files", results[0].message)

    def test_dir_with_wav_passes(self):
        sfx_dir = self.tmp / "assets" / "vesper" / "sfx"
        sfx_dir.mkdir(parents=True)
        (sfx_dir / "cut_heavy.wav").write_bytes(b"wav-stub")
        doctor = Doctor(repo_root=self.tmp, env=_full_env())
        results = doctor._check_sfx_pack()
        self.assertEqual(results[0].status, CheckStatus.PASS)


class OverlayPackCheckTests(unittest.TestCase):
    def test_all_four_present_passes(self):
        repo = Path("/fake/repo")
        fs = _FakeFs()
        fs.dirs.add(repo / "assets" / "vesper" / "overlays")
        for name in ("grain", "dust", "flicker", "fog"):
            fs.files.add(repo / "assets" / "vesper" / "overlays" / f"{name}.mp4")
        doctor = _build_doctor(repo, fs=fs)
        results = doctor._check_overlay_pack()
        self.assertEqual(results[0].status, CheckStatus.PASS)

    def test_partial_pack_warns_with_missing_list(self):
        repo = Path("/fake/repo")
        fs = _FakeFs()
        fs.dirs.add(repo / "assets" / "vesper" / "overlays")
        fs.files.add(repo / "assets" / "vesper" / "overlays" / "grain.mp4")
        doctor = _build_doctor(repo, fs=fs)
        results = doctor._check_overlay_pack()
        self.assertEqual(results[0].status, CheckStatus.WARN)
        self.assertIn("missing:", results[0].message)
        self.assertIn("dust", results[0].message)
        self.assertIn("flicker", results[0].message)
        self.assertIn("fog", results[0].message)


class FontCheckTests(unittest.TestCase):
    def test_present_font_passes(self):
        repo = Path("/fake/repo")
        fs = _FakeFs()
        fs.files.add(repo / "assets" / "fonts" / "CormorantGaramond-Bold.ttf")
        doctor = _build_doctor(repo, fs=fs)
        self.assertEqual(doctor._check_font()[0].status, CheckStatus.PASS)


class ComfyuiWorkflowCheckTests(unittest.TestCase):
    def test_missing_workflows_warn_not_fail(self):
        doctor = _build_doctor(Path("/fake/repo"), fs=_FakeFs())
        results = doctor._check_comfyui_workflows()
        for r in results:
            self.assertEqual(r.status, CheckStatus.WARN)
            self.assertEqual(r.severity, CheckSeverity.INTEGRATION)
            self.assertFalse(r.is_blocking)

    def test_both_present_pass(self):
        repo = Path("/fake/repo")
        fs = _FakeFs()
        for n in ("flux_still.json", "depth_parallax.json"):
            fs.files.add(repo / "comfyui_workflows" / n)
        doctor = _build_doctor(repo, fs=fs)
        results = doctor._check_comfyui_workflows()
        for r in results:
            self.assertEqual(r.status, CheckStatus.PASS)


class RateLedgerCheckTests(unittest.TestCase):
    def test_absent_ledger_passes_as_will_be_created(self):
        doctor = _build_doctor(Path("/fake/repo"), fs=_FakeFs())
        results = doctor._check_rate_ledger()
        self.assertEqual(results[0].status, CheckStatus.PASS)
        self.assertIn("created", results[0].message)

    def test_wrong_mode_warns(self):
        repo = Path("/fake/repo")
        fs = _FakeFs()
        ledger = repo / "data" / "postiz_rate_budget.jsonl"
        fs.files.add(ledger)
        fs.modes[ledger] = 0o644
        doctor = _build_doctor(repo, fs=fs)
        results = doctor._check_rate_ledger()
        self.assertEqual(results[0].status, CheckStatus.WARN)
        self.assertIn("0o644", results[0].message)
        self.assertIn("0o600", results[0].message)

    def test_correct_mode_passes(self):
        repo = Path("/fake/repo")
        fs = _FakeFs()
        ledger = repo / "data" / "postiz_rate_budget.jsonl"
        fs.files.add(ledger)
        fs.modes[ledger] = 0o600
        doctor = _build_doctor(repo, fs=fs)
        results = doctor._check_rate_ledger()
        self.assertEqual(results[0].status, CheckStatus.PASS)


# ─── End-to-end + blocking classifier ─────────────────────────────────────


class EndToEndTests(unittest.TestCase):
    def test_full_happy_path_no_blocking(self):
        repo = Path("/fake/repo")
        fs = _FakeFs()
        _seed_full_happy_fs(fs, repo)
        # Data dirs required/recommended
        for d in (
            repo / "data",
            repo / "data" / "backups",
            repo / "output" / "vesper",
        ):
            fs.dirs.add(d)
        fs.modes[repo / "data" / "postiz_rate_budget.jsonl"] = 0o600
        doctor = _build_doctor(repo, fs=fs)
        results = doctor.run()
        self.assertEqual(doctor.blocking_failures(results), [])

    def test_missing_env_produces_blocking_failure(self):
        env = _full_env()
        del env["ANTHROPIC_API_KEY"]
        repo = Path("/fake/repo")
        fs = _FakeFs()
        # Seed everything else happy so the only blocker is the env.
        _seed_full_happy_fs(fs, repo)
        for d in (
            repo / "data",
            repo / "data" / "backups",
            repo / "output" / "vesper",
        ):
            fs.dirs.add(d)
        doctor = _build_doctor(repo, env=env, fs=fs)
        results = doctor.run()
        blockers = doctor.blocking_failures(results)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0].name, "env:ANTHROPIC_API_KEY")


class FormatResultsTests(unittest.TestCase):
    def test_format_groups_by_severity(self):
        results = [
            CheckResult("a", CheckStatus.PASS, CheckSeverity.REQUIRED),
            CheckResult("b", CheckStatus.WARN, CheckSeverity.RECOMMENDED,
                        message="small issue"),
            CheckResult("c", CheckStatus.FAIL, CheckSeverity.REQUIRED,
                        message="big problem"),
        ]
        text = format_results(results)
        self.assertIn("REQUIRED", text)
        self.assertIn("RECOMMENDED", text)
        self.assertIn("[ok]", text)
        self.assertIn("[warn]", text)
        self.assertIn("[FAIL]", text)
        self.assertIn("Summary:", text)
        self.assertIn("1 blocking", text)


class MainExitCodeTests(unittest.TestCase):
    """``main()`` must exit 0 only when no REQUIRED check fails."""

    def test_happy_env_exits_zero(self):
        # Patch Doctor inside main() so we don't hit the real filesystem.
        import vesper_pipeline.doctor as doc_mod

        class _AlwaysPass(Doctor):
            def run(self):
                return [CheckResult(
                    name="x", status=CheckStatus.PASS,
                    severity=CheckSeverity.REQUIRED,
                )]

        original = doc_mod.Doctor
        doc_mod.Doctor = _AlwaysPass  # type: ignore[assignment]
        try:
            self.assertEqual(main(), 0)
        finally:
            doc_mod.Doctor = original  # type: ignore[assignment]

    def test_blocking_failure_exits_two(self):
        import vesper_pipeline.doctor as doc_mod

        class _Failing(Doctor):
            def run(self):
                return [CheckResult(
                    name="x", status=CheckStatus.FAIL,
                    severity=CheckSeverity.REQUIRED,
                    message="blocked",
                )]

        original = doc_mod.Doctor
        doc_mod.Doctor = _Failing  # type: ignore[assignment]
        try:
            self.assertEqual(main(), 2)
        finally:
            doc_mod.Doctor = original  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main(verbosity=2)

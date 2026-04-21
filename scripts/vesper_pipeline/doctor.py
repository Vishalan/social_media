"""Pre-launch readiness doctor.

Automates the pre-flight checklist from
``docs/runbooks/vesper/vesper-launch-runbook.md`` so the operator
can run one command and see every T-0 requirement evaluated:

    python -m vesper_pipeline.doctor

Exit status:
  * 0 — every required check passes (warnings allowed).
  * 2 — at least one required check failed.

Checks split into three severity tiers:

  * **required** — pipeline cannot run at all without this.
    Missing env vars, missing channel profile, missing write
    permission on ``data/``.
  * **recommended** — pipeline will run but produce degraded output.
    Missing voice ref (chatterbox falls back to a default voice, not
    the Archivist), missing SFX pack (raw voice ships), missing
    overlays (no film-grain texture), missing font (Inter fallback).
  * **integration** — server-side deliverables. Missing ComfyUI
    workflows mean Flux falls back to fal.ai, parallax fails per
    beat. Non-fatal for an "is the laptop side ready" doctor run.

The doctor NEVER performs network calls. Redis / chatterbox / Postiz
reachability is the job of the launch runbook (T-1 infra probes),
not this module — keeping the doctor hermetic means CI can run it.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Mapping, Optional

logger = logging.getLogger(__name__)


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class CheckSeverity(str, Enum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    INTEGRATION = "integration"


@dataclass(frozen=True)
class CheckResult:
    """One line of the doctor's output."""

    name: str
    status: CheckStatus
    severity: CheckSeverity
    message: str = ""

    @property
    def is_blocking(self) -> bool:
        """A REQUIRED + FAIL combination is the only state that blocks
        launch. Recommended fails become WARN-in-effect so operators
        can ship a degraded short deliberately."""
        return (
            self.severity == CheckSeverity.REQUIRED
            and self.status == CheckStatus.FAIL
        )


# ─── Configuration ─────────────────────────────────────────────────────────


_REQUIRED_ENV = (
    "ANTHROPIC_API_KEY",
    "REDIS_URL",
    "COMFYUI_URL",
    "POSTIZ_URL",
    "POSTIZ_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OWNER_USER_ID",
)

# Present-but-optional: degrades the pipeline if missing.
_RECOMMENDED_ENV = (
    "FAL_API_KEY",                  # Flux fallback
    "CHATTERBOX_REFERENCE_AUDIO",   # Archivist voice
)


# ─── Doctor ────────────────────────────────────────────────────────────────


@dataclass
class Doctor:
    """Walks the launch-runbook checklist and reports per-item status.

    Every file-system + env-var lookup is injectable so tests run
    without mutating the real environment.
    """

    repo_root: Path
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    channel_id: str = "vesper"

    # Injectable existence/mode probes — tests pass stubs; prod uses
    # the defaults wired below.
    exists_fn: Callable[[Path], bool] = Path.exists
    is_file_fn: Callable[[Path], bool] = Path.is_file
    is_dir_fn: Callable[[Path], bool] = Path.is_dir
    mode_fn: Optional[Callable[[Path], int]] = None

    # ─── Public entry ──────────────────────────────────────────────────

    def run(self) -> List[CheckResult]:
        """Run every check and return the results in display order."""
        results: List[CheckResult] = []
        results.extend(self._check_env_vars())
        results.extend(self._check_channel_profile())
        results.extend(self._check_data_directories())
        results.extend(self._check_voice_reference())
        results.extend(self._check_sfx_pack())
        results.extend(self._check_overlay_pack())
        results.extend(self._check_font())
        results.extend(self._check_comfyui_workflows())
        results.extend(self._check_rate_ledger())
        return results

    def blocking_failures(self, results: List[CheckResult]) -> List[CheckResult]:
        return [r for r in results if r.is_blocking]

    # ─── Individual check groups ───────────────────────────────────────

    def _check_env_vars(self) -> List[CheckResult]:
        out: List[CheckResult] = []
        for name in _REQUIRED_ENV:
            val = self.env.get(name, "").strip()
            if val:
                out.append(CheckResult(
                    name=f"env:{name}",
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.REQUIRED,
                ))
            else:
                out.append(CheckResult(
                    name=f"env:{name}",
                    status=CheckStatus.FAIL,
                    severity=CheckSeverity.REQUIRED,
                    message=(
                        f"missing required env var {name}. "
                        "See scripts/vesper_pipeline/__main__.py docstring."
                    ),
                ))
        for name in _RECOMMENDED_ENV:
            val = self.env.get(name, "").strip()
            status = CheckStatus.PASS if val else CheckStatus.WARN
            msg = "" if val else (
                f"{name} not set; pipeline will run in degraded mode. "
                "See launch runbook T-7/T-3."
            )
            out.append(CheckResult(
                name=f"env:{name}",
                status=status,
                severity=CheckSeverity.RECOMMENDED,
                message=msg,
            ))
        return out

    def _check_channel_profile(self) -> List[CheckResult]:
        try:
            # Import the real loader — this also exercises the SFX
            # pack registration at import time (channels/vesper.py).
            from channels import load_channel_config
            profile = load_channel_config(self.channel_id)
        except Exception as exc:
            return [CheckResult(
                name="channel_profile",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.REQUIRED,
                message=f"cannot load channel '{self.channel_id}': {exc}",
            )]
        # Sanity: palette + thumbnail fields populated.
        if not getattr(profile, "palette", None):
            return [CheckResult(
                name="channel_profile",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.REQUIRED,
                message="profile loaded but palette field is empty",
            )]
        return [CheckResult(
            name="channel_profile",
            status=CheckStatus.PASS,
            severity=CheckSeverity.REQUIRED,
            message=f"loaded '{self.channel_id}' profile",
        )]

    def _check_data_directories(self) -> List[CheckResult]:
        out: List[CheckResult] = []
        for subdir, sev in [
            ("data", CheckSeverity.REQUIRED),
            ("data/backups", CheckSeverity.RECOMMENDED),
            (f"output/{self.channel_id}", CheckSeverity.RECOMMENDED),
        ]:
            path = self.repo_root / subdir
            if self.is_dir_fn(path):
                out.append(CheckResult(
                    name=f"dir:{subdir}",
                    status=CheckStatus.PASS,
                    severity=sev,
                ))
            else:
                out.append(CheckResult(
                    name=f"dir:{subdir}",
                    status=(
                        CheckStatus.FAIL if sev == CheckSeverity.REQUIRED
                        else CheckStatus.WARN
                    ),
                    severity=sev,
                    message=(
                        f"{subdir}/ missing; will be created on first "
                        "pipeline write but check is useful early."
                    ),
                ))
        return out

    def _check_voice_reference(self) -> List[CheckResult]:
        """Check laptop-side repo copy. The server-side copy (the one
        chatterbox actually reads) lives at
        /opt/commoncreed/assets/vesper/archivist.wav on the server —
        verified by the network probe, not here."""
        path = (
            self.repo_root / "assets" / self.channel_id / "refs" / "archivist.wav"
        )
        if self.is_file_fn(path):
            return [CheckResult(
                name="asset:voice_ref",
                status=CheckStatus.PASS,
                severity=CheckSeverity.RECOMMENDED,
            )]
        return [CheckResult(
            name="asset:voice_ref",
            status=CheckStatus.WARN,
            severity=CheckSeverity.RECOMMENDED,
            message=(
                f"{path} missing (laptop copy). Server-side chatterbox "
                "reads /app/refs/vesper/archivist.wav — verify via probe. "
                "See server-bringup runbook S1."
            ),
        )]

    def _check_sfx_pack(self) -> List[CheckResult]:
        sfx_dir = self.repo_root / "assets" / self.channel_id / "sfx"
        if not self.is_dir_fn(sfx_dir):
            return [CheckResult(
                name="asset:sfx_pack",
                status=CheckStatus.WARN,
                severity=CheckSeverity.RECOMMENDED,
                message=(
                    f"{sfx_dir} missing; SFX mix will no-op (raw voice "
                    "ships). See launch runbook T-3."
                ),
            )]
        # Need at least one .wav in the directory to consider usable.
        # Use a tolerant check — we don't enforce every category here,
        # that's the pack's own responsibility at pick_sfx time.
        try:
            entries = list(sfx_dir.iterdir())
        except OSError as exc:
            return [CheckResult(
                name="asset:sfx_pack",
                status=CheckStatus.WARN,
                severity=CheckSeverity.RECOMMENDED,
                message=f"cannot list {sfx_dir}: {exc}",
            )]
        wavs = [p for p in entries if p.suffix.lower() == ".wav"]
        if not wavs:
            return [CheckResult(
                name="asset:sfx_pack",
                status=CheckStatus.WARN,
                severity=CheckSeverity.RECOMMENDED,
                message=f"{sfx_dir} has no .wav files",
            )]
        return [CheckResult(
            name="asset:sfx_pack",
            status=CheckStatus.PASS,
            severity=CheckSeverity.RECOMMENDED,
            message=f"{len(wavs)} .wav file(s) in pack",
        )]

    def _check_overlay_pack(self) -> List[CheckResult]:
        overlay_dir = self.repo_root / "assets" / self.channel_id / "overlays"
        canonical = ("grain", "dust", "flicker", "fog")
        if not self.is_dir_fn(overlay_dir):
            return [CheckResult(
                name="asset:overlay_pack",
                status=CheckStatus.WARN,
                severity=CheckSeverity.RECOMMENDED,
                message=(
                    f"{overlay_dir} missing; overlay pass will no-op. "
                    "See launch runbook T-3."
                ),
            )]
        present = [n for n in canonical
                   if self.is_file_fn(overlay_dir / f"{n}.mp4")]
        if not present:
            return [CheckResult(
                name="asset:overlay_pack",
                status=CheckStatus.WARN,
                severity=CheckSeverity.RECOMMENDED,
                message="no overlay .mp4s present",
            )]
        if len(present) < len(canonical):
            missing = set(canonical) - set(present)
            return [CheckResult(
                name="asset:overlay_pack",
                status=CheckStatus.WARN,
                severity=CheckSeverity.RECOMMENDED,
                message=(
                    f"{len(present)}/{len(canonical)} overlay layers "
                    f"present (missing: {', '.join(sorted(missing))})"
                ),
            )]
        return [CheckResult(
            name="asset:overlay_pack",
            status=CheckStatus.PASS,
            severity=CheckSeverity.RECOMMENDED,
            message="all 4 overlay layers present",
        )]

    def _check_font(self) -> List[CheckResult]:
        # Vesper's CormorantGaramond-Bold; fall back to Inter is
        # automatic in the compositor.
        font = (
            self.repo_root / "assets" / "fonts"
            / "CormorantGaramond-Bold.ttf"
        )
        if self.is_file_fn(font):
            return [CheckResult(
                name="asset:font",
                status=CheckStatus.PASS,
                severity=CheckSeverity.RECOMMENDED,
            )]
        return [CheckResult(
            name="asset:font",
            status=CheckStatus.WARN,
            severity=CheckSeverity.RECOMMENDED,
            message=(
                f"{font} missing; thumbnail/caption will fall back to "
                "Inter-Black. See launch runbook T-3."
            ),
        )]

    def _check_comfyui_workflows(self) -> List[CheckResult]:
        out: List[CheckResult] = []
        for name in ("flux_still.json", "depth_parallax.json"):
            path = self.repo_root / "comfyui_workflows" / name
            if self.is_file_fn(path):
                out.append(CheckResult(
                    name=f"workflow:{name}",
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.INTEGRATION,
                ))
            else:
                out.append(CheckResult(
                    name=f"workflow:{name}",
                    status=CheckStatus.WARN,
                    severity=CheckSeverity.INTEGRATION,
                    message=(
                        f"{path} missing; server-side deliverable. "
                        "Flux falls back to fal.ai; parallax beats fail."
                    ),
                ))
        return out

    def _check_rate_ledger(self) -> List[CheckResult]:
        path = self.repo_root / "data" / "postiz_rate_budget.jsonl"
        if not self.is_file_fn(path):
            # Ledger is auto-created on first use; not having it
            # yet is fine.
            return [CheckResult(
                name="rate_ledger",
                status=CheckStatus.PASS,
                severity=CheckSeverity.RECOMMENDED,
                message="will be created on first write",
            )]
        mode_fn = self.mode_fn
        if mode_fn is None:
            try:
                actual = stat.S_IMODE(path.stat().st_mode)
            except OSError as exc:
                return [CheckResult(
                    name="rate_ledger",
                    status=CheckStatus.WARN,
                    severity=CheckSeverity.RECOMMENDED,
                    message=f"cannot stat {path}: {exc}",
                )]
        else:
            actual = mode_fn(path)
        if actual != 0o600:
            return [CheckResult(
                name="rate_ledger",
                status=CheckStatus.WARN,
                severity=CheckSeverity.RECOMMENDED,
                message=(
                    f"{path} mode is {oct(actual)}, expected 0o600 "
                    "(Security Posture S7). Run `chmod 600` on it."
                ),
            )]
        return [CheckResult(
            name="rate_ledger",
            status=CheckStatus.PASS,
            severity=CheckSeverity.RECOMMENDED,
            message="mode 0o600",
        )]


# ─── Reporting ─────────────────────────────────────────────────────────────


_SYMBOLS = {
    CheckStatus.PASS: "[ok]",
    CheckStatus.WARN: "[warn]",
    CheckStatus.FAIL: "[FAIL]",
}


def format_results(results: List[CheckResult]) -> str:
    """Plain-text summary for terminal output. Groups by severity so
    the blocking REQUIRED fails are unmissable at the top."""
    lines: List[str] = []
    for sev in (
        CheckSeverity.REQUIRED,
        CheckSeverity.RECOMMENDED,
        CheckSeverity.INTEGRATION,
    ):
        rows = [r for r in results if r.severity == sev]
        if not rows:
            continue
        lines.append(f"\n{sev.value.upper()}:")
        for r in rows:
            sym = _SYMBOLS[r.status]
            tail = f" — {r.message}" if r.message else ""
            lines.append(f"  {sym} {r.name}{tail}")
    blocking = [r for r in results if r.is_blocking]
    totals = {s.value: len([r for r in results if r.status == s])
              for s in CheckStatus}
    lines.append(
        f"\nSummary: {totals['pass']} ok, {totals['warn']} warn, "
        f"{totals['fail']} fail — {len(blocking)} blocking"
    )
    return "\n".join(lines)


# ─── CLI ───────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    repo_root = Path(__file__).resolve().parent.parent.parent
    # channels/ lives at repo root, not under scripts/ — mirror the
    # sys.path bootstrap commoncreed_pipeline uses so the profile
    # loader resolves in-process.
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    doctor = Doctor(repo_root=repo_root)
    results = doctor.run()
    print(format_results(results))
    return 2 if doctor.blocking_failures(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CheckResult",
    "CheckSeverity",
    "CheckStatus",
    "Doctor",
    "format_results",
    "main",
]

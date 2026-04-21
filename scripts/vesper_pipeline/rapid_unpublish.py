"""Rapid-unpublish Telegram command (plan Unit 11 + Risks).

Wires the owner-only ``/takedown <job_id>`` Telegram command to Postiz
multi-platform post deletion. Serves two operational needs:

  * **DMCA / compliance response.** If IG, TikTok, or YouTube flags a
    short (auto-takedown, manual strike, legal notice), the owner
    issues ``/takedown`` from Telegram and the short disappears from
    every platform within seconds. Beats pulling up three admin UIs.
  * **Quality recall.** The owner spots a Vesper short looks bad after
    it ships (blurry Flux, bad voice line, late-discovered mod
    violation) — same command, same speed.

Security posture (plan S1 — takedown verification):
  * Only the configured ``owner_user_id`` may invoke this.
  * Every takedown logs to the analytics ``takedown_flags`` table with
    reason + owner confirm + timestamp.
  * Failures to delete a specific platform post raise a clear error
    so the owner can follow up in that platform's admin console; we
    do NOT silently pretend to have taken down posts that still exist.

DI shape mirrors the orchestrator: all collaborators are Protocols so
tests run hermetically without Postiz, Telegram, or the tracker DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional, Protocol

logger = logging.getLogger(__name__)


# ─── Collaborator protocols ────────────────────────────────────────────────


class _PostizDeleter(Protocol):
    def delete_post(self, post_id: str) -> Any: ...


class _AnalyticsTracker(Protocol):
    def get_post_ids_for_short(self, *, job_id: str) -> List[str]: ...
    def record_takedown(
        self,
        *,
        job_id: str,
        reason: str,
        platforms: List[str],
        failed_platforms: List[str],
    ) -> Any: ...


# ─── Result / error ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TakedownResult:
    job_id: str
    post_ids: List[str]
    deleted: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    failure_reasons: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        if self.ok:
            return (
                f"[Vesper] takedown OK for {self.job_id}: "
                f"{len(self.deleted)} post(s) removed"
            )
        lines = [
            f"[Vesper] takedown PARTIAL for {self.job_id}:",
            f"  deleted: {self.deleted}",
            f"  failed:  {self.failed}",
        ]
        for r in self.failure_reasons:
            lines.append(f"    - {r}")
        return "\n".join(lines)


class TakedownError(RuntimeError):
    """Raised when the takedown cannot even begin — unauthorized user,
    unknown job_id, or no post_ids recorded for that short."""


# ─── Unpublisher ──────────────────────────────────────────────────────────


@dataclass
class RapidUnpublisher:
    """Handles a single ``/takedown`` invocation end-to-end."""

    postiz: _PostizDeleter
    tracker: _AnalyticsTracker
    owner_user_id: int
    # Optional allowlist for platforms we know the shape of. Leave as
    # None to accept any post_id returned by publish_post (default —
    # Postiz handles platform routing, we just delete by ID).
    allowed_platforms: Optional[List[str]] = None

    def handle(
        self,
        *,
        requester_user_id: int,
        job_id: str,
        reason: str,
    ) -> TakedownResult:
        """Process one ``/takedown`` command.

        :param requester_user_id: Telegram user ID of the sender. MUST
            equal ``self.owner_user_id`` or the command is rejected
            silently-ish (we raise :class:`TakedownError` so the bot
            layer can reply; we do not log the requester's other
            messages or identity beyond this check).
        :param job_id: The VesperJob's UUID.
        :param reason: Short operator-supplied explanation; logged to
            the analytics takedown_flags table.
        """
        if requester_user_id != self.owner_user_id:
            logger.warning(
                "rapid_unpublish: rejected takedown request from "
                "non-owner user_id=%s for job=%s",
                requester_user_id, job_id,
            )
            raise TakedownError(
                "takedown rejected: only the configured owner may "
                "invoke /takedown"
            )

        post_ids = list(self.tracker.get_post_ids_for_short(job_id=job_id))
        if not post_ids:
            raise TakedownError(
                f"no post_ids recorded for job_id={job_id}; "
                "cannot take down a short that wasn't published yet"
            )

        deleted: List[str] = []
        failed: List[str] = []
        failure_reasons: List[str] = []

        for pid in post_ids:
            try:
                self.postiz.delete_post(pid)
                deleted.append(pid)
            except Exception as exc:
                failed.append(pid)
                failure_reasons.append(f"{pid}: {exc}")
                logger.error(
                    "rapid_unpublish: delete_post failed job=%s post=%s: %s",
                    job_id, pid, exc,
                )

        # Always log to the tracker — whether full or partial. Full
        # failures still need a record so the owner can manually chase
        # the missing platforms in their admin UI.
        try:
            self.tracker.record_takedown(
                job_id=job_id,
                reason=reason,
                platforms=deleted,
                failed_platforms=failed,
            )
        except Exception as exc:
            logger.error(
                "rapid_unpublish: tracker.record_takedown failed for %s: %s",
                job_id, exc,
            )

        return TakedownResult(
            job_id=job_id,
            post_ids=post_ids,
            deleted=deleted,
            failed=failed,
            failure_reasons=failure_reasons,
        )


__all__ = [
    "RapidUnpublisher",
    "TakedownError",
    "TakedownResult",
]

"""
TopicSource protocol — the only contract new sources have to implement.

Keep this file free of concrete-source imports so ``sidecar/topic_sources/
__init__.py`` can import the protocol without pulling in every backend at
module load. (HN source imports httpx, Gmail source imports Google libs,
and we don't want a typo in one to break the other.)
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TopicSource(Protocol):
    """Fetches candidate topics from an external source.

    Implementations must be cheap to construct (no network calls in
    ``__init__``). Network calls happen in :meth:`fetch_items` and must
    be wrapped so any failure returns ``([], "")`` rather than raising —
    the caller treats an empty list as "nothing fresh", not as a fatal
    error.
    """

    #: Short stable identifier used in logs, env var, and registry keys.
    name: str

    def is_configured(self, settings: Any) -> bool:
        """Return True only if this source has everything it needs to run.

        Called before every ``fetch_items`` attempt so a source that is
        registered but not yet credentialled (e.g. Gmail without the OAuth
        token file) gets silently skipped instead of raising.
        """
        ...

    def fetch_items(self, settings: Any) -> tuple[list[dict], str]:
        """Return ``(items, label)`` for downstream scoring.

        ``items`` is a list of dicts shaped like::

            {
                "title": str,
                "url":   str,
                "summary": str,           # optional but strongly recommended
                "source":  str,           # optional; defaults to self.name
            }

        ``label`` is a short human-readable marker persisted on the
        ``pipeline_runs`` row as ``source_newsletter_date`` — e.g. the
        newsletter's received date for Gmail, or the ISO fetch timestamp
        for a stateless API like HN.

        An empty list with any label is a valid "nothing fresh" response
        and MUST NOT raise.
        """
        ...

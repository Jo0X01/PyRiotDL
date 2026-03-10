"""
Download progress tracking and live display with customisable formatting.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from pyriotdl.helper import fmt_eta, fmt_size, fmt_speed

log = logging.getLogger(__name__)


@dataclass
class BarStyle:
    """
    Controls the visual appearance of the progress bar and what info is shown.

    Parameters
    ----------
    fill       : character for the completed portion  (default ``"█"``)
    empty      : character for the remaining portion  (default ``"░"``)
    left       : left bracket character               (default ``"["``)
    right      : right bracket character              (default ``"]"``)
    width      : bar character width                  (default ``20``)
    show_bar   : show the progress bar                (default ``True``)
    show_speed : show download speed                  (default ``True``)
    show_eta   : show estimated time remaining        (default ``True``)
    show_size  : show bytes downloaded / total        (default ``True``)
    show_count : show chunks processed / total        (default ``True``)
    show_fail  : show failed chunk count              (default ``True``)

    Presets
    -------
    Use as class attributes, e.g. ``style=BarStyle.BLOCKS``:

    * ``BarStyle.BLOCKS``   →  ``[████████░░░░]  61.3%  …``  (default)
    * ``BarStyle.ARROW``    →  ``[======>   ]  61.3%  …``
    * ``BarStyle.DOTS``     →  ``[●●●●●●○○○○]  61.3%  …``
    * ``BarStyle.HASH``     →  ``[######    ]  61.3%  …``  (wider bar)
    * ``BarStyle.MINIMAL``  →  ``61.3%  1.2 MB/s  ETA 01:23``
    * ``BarStyle.SIMPLE``   →  ``61.3%  615/1000``

    .. note::
       Previously the presets were documented but not actually defined as class
       attributes — they could not be used as ``BarStyle.BLOCKS``.  Fixed.
    """

    fill: str = "█"
    empty: str = "░"
    left: str = "["
    right: str = "]"
    width: int = 20
    show_bar: bool = True
    show_speed: bool = True
    show_eta: bool = True
    show_size: bool = True
    show_count: bool = True
    show_fail: bool = True

    @staticmethod
    def default() -> "BarStyle":
        return BarStyle()

    @staticmethod
    def arrow_bar() -> "BarStyle":
        return BarStyle(fill="=", empty=" ", left="[", right="]")

    @staticmethod
    def dots_bar() -> "BarStyle":
        return BarStyle(fill="●", empty="○", left="[", right="]")

    @staticmethod
    def hash_bar() -> "BarStyle":
        return BarStyle(fill="#", empty=" ", left="[", right="]", width=30)

    @staticmethod
    def minimal_bar() -> "BarStyle":
        return BarStyle(show_bar=False, show_count=False, show_fail=False)

    @staticmethod
    def simple_bar() -> "BarStyle":
        return BarStyle(
            show_bar=False, show_size=False, show_speed=False,
            show_eta=False, show_fail=False,
        )


class ProgressTracker:
    """
    In-memory set of completed chunk IDs.

    Useful for persisting resume state between sessions if serialised to disk.
    """

    def __init__(self) -> None:
        self._completed: set[str] = set()

    def is_done(self, chunk_id: str) -> bool:
        """Return ``True`` if *chunk_id* has been marked complete."""
        return chunk_id in self._completed

    def mark_done(self, chunk_id: str) -> None:
        """Mark a single chunk as complete."""
        self._completed.add(chunk_id)

    def mark_done_batch(self, chunk_ids: list[str]) -> None:
        """Mark multiple chunks as complete in one call."""
        self._completed.update(chunk_ids)

    def remove_mark_done(self, chunk_id: str) -> None:
        """Unmark a chunk (e.g. after a write failure)."""
        self._completed.discard(chunk_id)

    def count(self) -> int:
        """Number of completed chunks."""
        return len(self._completed)

    def clear(self) -> None:
        """Reset all completion state."""
        self._completed.clear()

    def __contains__(self, chunk_id: str) -> bool:
        return self.is_done(chunk_id)

    def __len__(self) -> int:
        return self.count()


class DownloadProgress:
    """
    Live in-memory download stats with customisable progress display.

    Thread-safe for reads; callers in ``GameDownloader`` protect writes with
    their own ``progress_lock``.

    Parameters
    ----------
    total_chunks : int
        Total chunks in the download plan (including skipped / resumed).
    total_bytes : int
        Total compressed bytes that need to be fetched (excludes skipped).
    style : BarStyle, optional
        Visual style for :meth:`print_line`.  Defaults to ``BarStyle.BLOCKS``.
    """

    def __init__(
        self,
        total_chunks: int = 0,
        total_bytes: int = 0,
        style: BarStyle | None = None,
    ) -> None:
        self.total_chunks = total_chunks
        self.total_bytes = total_bytes
        self.style = style or BarStyle()

        self._done_chunks = 0
        self._skipped_chunks = 0
        self._resumed_chunks = 0
        self._downloaded_bytes = 0
        self._failed: list[str] = []

        self._start_time = time.time()
        self._window_time = self._start_time
        self._window_bytes = 0
        self._current_speed = 0.0

    def add(self, compressed_bytes: int = 0) -> None:
        """Record one successfully downloaded and written chunk."""
        self._done_chunks += 1
        self._downloaded_bytes += compressed_bytes

    def skip(self) -> None:
        """Record one chunk that was identical to the previous manifest (no download needed)."""
        self._skipped_chunks += 1

    def resume(self) -> None:
        """Record one chunk that was verified on disk (no download needed)."""
        self._resumed_chunks += 1

    def fail(self, chunk_id: str) -> None:
        """Record a chunk that failed permanently after all retries."""
        self._failed.append(chunk_id)
        log.warning("Chunk permanently failed: %s", chunk_id)

    def is_finish(self) -> bool:
        """``True`` when every chunk has been accounted for."""
        return self.processed_chunks >= self.total_chunks

    @property
    def done_chunks(self) -> int:
        """Number of successfully downloaded chunks."""
        return self._done_chunks

    @property
    def skipped_chunks(self) -> int:
        """Number of chunks skipped (unchanged from previous version)."""
        return self._skipped_chunks

    @property
    def resumed_chunks(self) -> int:
        """Number of chunks verified already on disk."""
        return self._resumed_chunks

    @property
    def downloaded_bytes(self) -> int:
        """Total compressed bytes downloaded so far."""
        return self._downloaded_bytes

    @property
    def failed(self) -> list[str]:
        """Copy of the failed chunk ID list."""
        return list(self._failed)

    @property
    def has_failures(self) -> bool:
        """``True`` if at least one chunk failed permanently."""
        return bool(self._failed)

    @property
    def processed_chunks(self) -> int:
        """Total chunks processed (done + skipped + resumed + failed)."""
        return (
            self._done_chunks
            + self._skipped_chunks
            + self._resumed_chunks
            + len(self._failed)
        )

    @property
    def percent(self) -> float:
        """Completion percentage clamped to [0, 100]."""
        if self.total_chunks == 0:
            return 0.0
        return min(self.processed_chunks / self.total_chunks * 100, 100.0)

    @property
    def avg_speed_bps(self) -> float:
        """Average download speed in bytes/second since start"""
        elapsed = time.time() - self._start_time
        if elapsed <= 0:
            return 0.0
        return self._downloaded_bytes / elapsed

    @property
    def eta_seconds(self) -> float | None:
        """Estimated seconds remaining, or ``None`` if speed is unknown"""
        if self._current_speed <= 0:
            return None
        remaining = self.total_bytes - self._downloaded_bytes
        return max(0.0, remaining / self._current_speed)

    @property
    def elapsed_seconds(self) -> float:
        """Seconds elapsed since download start."""
        return time.time() - self._start_time

    def print_line(self, end: str = "\r") -> None:
        """
        Print a single updating progress line using the current :class:`BarStyle`.

        Parameters
        ----------
        end : str
            Line ending character (default ``"\\r"`` for in-place updates).
        """
        self._update_speed()
        s = self.style
        parts: list[str] = []

        if s.show_bar:
            parts.append(self._bar())

        parts.append(f"{self.percent:5.1f}%")

        if s.show_count:
            parts.append(f"{self.processed_chunks}/{self.total_chunks}")

        if s.show_size:
            parts.append(f"{fmt_size(self._downloaded_bytes)}/{fmt_size(self.total_bytes)}")

        if s.show_speed:
            parts.append(fmt_speed(self._current_speed))

        if s.show_eta:
            parts.append(f"ETA {fmt_eta(self.eta_seconds)}")

        if s.show_fail:
            parts.append(f"fail={len(self._failed)}")

        print("  " + "  ".join(parts), end=end, flush=True)

    def _update_speed(self) -> None:
        now = time.time()
        elapsed = now - self._window_time
        if elapsed >= 0.1:
            new_speed = (self._downloaded_bytes - self._window_bytes) / elapsed
            self._current_speed = max(0.0, 0.7 * self._current_speed + 0.3 * new_speed)
            self._window_time = now
            self._window_bytes = self._downloaded_bytes

    def _bar(self) -> str:
        s = self.style
        filled = int(self.percent / 100 * s.width)
        empty = s.width - filled
        return f"{s.left}{s.fill * filled}{s.empty * empty}{s.right}"

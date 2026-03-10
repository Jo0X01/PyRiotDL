"""
GameDownloader — multi-threaded chunk downloader with diff and resume support

Flow
----
1. Compare new plan chunks against old plan (if provided) → mark unchanged chunks as skipped.
2. Optionally verify already-downloaded chunks on disk → mark as resumed.
3. Pre-allocate output files.
4. Fetch remaining chunks in parallel via HTTP Range requests.
5. Zstd-decompress and seek-write each chunk to the correct offset.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from collections import defaultdict
from typing import Optional

import requests
import zstandard as zstd

from pyriotdl.models import FilePlan, PlanChunk
from pyriotdl.progress import BarStyle, DownloadProgress
from pyriotdl.helper import fmt_size

log = logging.getLogger(__name__)


class GameDownloader:
    """
    Chunk downloader — takes ``FilePlan`` lists, handles diff and resume

    Parameters
    ----------
    new_plan : list[FilePlan]
        FilePlan list built from the target (new) manifest.
    old_plan : list[FilePlan], optional
        FilePlan list built from the current (installed) manifest.
        Chunks present in both plans are skipped entirely.
        ``None`` means fresh install — no diffing.
    game_dir : str, optional
        Path to the existing game folder used for on-disk verification.
        When provided, chunks not in ``old_plan`` are verified on disk before
        downloading.  ``None`` disables verification.
    """

    def __init__(
        self,
        new_plan: list[FilePlan],
        old_plan: Optional[list[FilePlan]] = None,
        game_dir: Optional[str] = None,
    ) -> None:
        self.new_plan = new_plan
        self.game_dir = game_dir

        self._all: list[tuple[FilePlan, PlanChunk]] = [
            (fp, c) for fp in new_plan for c in fp.chunks
        ]

        self._skip_ids: set[str] = (
            {c.chunk_id for fp in old_plan for c in fp.chunks} if old_plan else set()
        )

        self._to_skip: list[tuple[FilePlan, PlanChunk]] = []
        self._to_verify: list[tuple[FilePlan, PlanChunk]] = []
        self._to_download: list[tuple[FilePlan, PlanChunk]] = []

        for fp, c in self._all:
            if c.chunk_id in self._skip_ids:
                self._to_skip.append((fp, c))
            elif game_dir:
                self._to_verify.append((fp, c))
            else:
                self._to_download.append((fp, c))

        self._resumed: list[tuple[FilePlan, PlanChunk]] = []
        if self._to_verify:
            self._resumed, self._to_download = self._verify_all(self._to_verify, game_dir)

        self.total_chunks = len(self._all)
        self.chunks_to_skip = len(self._to_skip)
        self.chunks_to_resume = len(self._resumed)
        self.chunks_to_dl = len(self._to_download)
        self.bytes_to_dl = sum(c.compressed_size for _, c in self._to_download)
        self.total_size = sum(fp.size for fp in new_plan)

        log.info(
            "GameDownloader ready — total=%d  skip=%d  resume=%d  download=%d  (%s)",
            self.total_chunks, self.chunks_to_skip, self.chunks_to_resume,
            self.chunks_to_dl,
            fmt_size(self.bytes_to_dl),
        )

    def start_download(
        self,
        output_dir: str,
        workers: int = 8,
        retries: int = 3,
        style: Optional[BarStyle] = None,
    ) -> DownloadProgress:
        """
        Download all needed chunks and write game files.

        Parameters
        ----------
        output_dir : str
            Directory to write game files into.
        workers : int, optional
            Number of parallel download threads (default ``8``).
        retries : int, optional
            Maximum retry attempts per failed chunk (default ``3``).
        style : BarStyle, optional
            Progress bar style.  Defaults to ``BarStyle.BLOCKS``.

        Returns
        -------
        DownloadProgress
            Populated with final stats after all threads finish.
        """
        progress = DownloadProgress(
            total_chunks=self.total_chunks,
            total_bytes=self.bytes_to_dl,
            style=style or BarStyle(),
        )

        for _ in self._to_skip:
            progress.skip()
        for _ in self._resumed:
            progress.resume()

        if not self._to_download:
            log.info("Nothing to download — all chunks already up to date.")
            return progress

        log.info(
            "Starting download — %d chunks  workers=%d  retries=%d  output=%s",
            self.chunks_to_dl, workers, retries, output_dir,
        )
        self._allocate_files(self.new_plan, output_dir)
        self._run(self._to_download, output_dir, progress, workers, retries)
        return progress


    def _run(
        self,
        work: list[tuple[FilePlan, PlanChunk]],
        output_dir: str,
        progress: DownloadProgress,
        workers: int,
        retries: int,
    ) -> None:
        """Spin up worker threads and process the work queue."""
        q: queue.Queue[tuple[FilePlan, PlanChunk]] = queue.Queue()
        progress_lock = threading.Lock()
        file_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

        for item in work:
            q.put(item)

        def worker() -> None:
            session = requests.Session()
            session.headers.update({"User-Agent": "RiotClient/99.0.0.9999999 riot-client"})
            decompressor = zstd.ZstdDecompressor()

            while True:
                try:
                    fp, chunk = q.get_nowait()
                except queue.Empty:
                    return

                data: Optional[bytes] = None
                last_err: Optional[Exception] = None

                for attempt in range(1, retries + 1):
                    try:
                        data = self._fetch_chunk(chunk, session, decompressor)
                        break
                    except Exception as exc:
                        last_err = exc
                        log.warning(
                            "Chunk %s  attempt %d/%d failed: %s",
                            chunk.chunk_id, attempt, retries, exc,
                        )
                        if attempt < retries:
                            time.sleep(0.5 * attempt)

                if data is None:
                    log.error(
                        "Chunk %s permanently failed after %d attempts: %s",
                        chunk.chunk_id, retries, last_err,
                    )

                wrote_ok = False
                if data is not None:
                    file_lock = file_locks[fp.path]
                    try:
                        with file_lock:
                            self._write_chunk(data, fp, chunk, output_dir)
                        wrote_ok = True
                    except Exception as exc:
                        log.error(
                            "Write failed for chunk %s → %s: %s",
                            chunk.chunk_id, fp.path, exc,
                        )

                with progress_lock:
                    if wrote_ok:
                        progress.add(compressed_bytes=chunk.compressed_size)
                    else:
                        progress.fail(chunk.chunk_id)
                    progress.print_line()

                q.task_done()

        thread_count = min(workers, len(work))
        threads = [threading.Thread(target=worker, daemon=True) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        log.debug("All worker threads finished.")

    def _verify_all(
        self,
        items: list[tuple[FilePlan, PlanChunk]],
        game_dir: str | None,
    ) -> tuple[list[tuple[FilePlan, PlanChunk]], list[tuple[FilePlan, PlanChunk]]]:
        """
        Check which chunks are already fully written on disk.

        A file is considered complete for a chunk if the on-disk file exists
        **and** is large enough to contain the chunk's byte range.

        Parameters
        ----------
        items    : (FilePlan, PlanChunk) pairs to check
        game_dir : game installation directory

        Returns
        -------
        tuple[resumed, to_download]
        """
        by_file: dict[str, list[tuple[FilePlan, PlanChunk]]] = defaultdict(list)
        for fp, c in items:
            by_file[fp.path].append((fp, c))

        resumed: list[tuple[FilePlan, PlanChunk]] = []
        to_download: list[tuple[FilePlan, PlanChunk]] = []

        for path, chunk_items in by_file.items():
            out_path = os.path.join(game_dir or "", path)

            if not os.path.exists(out_path):
                log.debug("File missing on disk: %s", out_path)
                to_download.extend(chunk_items)
                continue

            min_required = max(
                (c.uncompressed_offset + c.uncompressed_size for _, c in chunk_items),
                default=0,
            )
            if os.path.getsize(out_path) < min_required:
                log.debug(
                    "File too small on disk: %s  (need %d B, have %d B)",
                    out_path, min_required, os.path.getsize(out_path),
                )
                to_download.extend(chunk_items)
            else:
                resumed.extend(chunk_items)

        log.debug("Verify: %d resumed  %d to download", len(resumed), len(to_download))
        return resumed, to_download

    def _fetch_chunk(
        self,
        chunk: PlanChunk,
        session: requests.Session,
        decompressor: zstd.ZstdDecompressor,
    ) -> bytes:
        """
        Download one chunk via HTTP Range request and zstd-decompress it.

        Parameters
        ----------
        chunk        : the chunk to fetch
        session      : reusable ``requests.Session``
        decompressor : shared ``ZstdDecompressor`` instance

        Returns
        -------
        bytes
            Decompressed chunk data ready to write to disk.

        Raises
        ------
        ValueError
            If the downloaded or decompressed size does not match the manifest.
        requests.HTTPError
            On non-2xx HTTP responses.
        """
        start = chunk.compressed_offset
        end = chunk.compressed_offset + chunk.compressed_size - 1

        resp = session.get(
            chunk.bundle_url,
            headers={"Range": f"bytes={start}-{end}"},
            timeout=30,
        )
        resp.raise_for_status()

        if len(resp.content) != chunk.compressed_size:
            raise ValueError(
                f"Size mismatch: expected {chunk.compressed_size} B "
                f"got {len(resp.content)} B"
            )

        raw = decompressor.stream_reader(resp.content).read()

        if len(raw) != chunk.uncompressed_size:
            raise ValueError(
                f"Decompressed mismatch: expected {chunk.uncompressed_size} B "
                f"got {len(raw)} B"
            )

        return raw

    def _write_chunk(
        self,
        data: bytes,
        fp: FilePlan,
        chunk: PlanChunk,
        output_dir: str,
    ) -> None:
        """
        Write decompressed chunk data to the correct byte offset in the output file.

        Parameters
        ----------
        data       : decompressed bytes to write
        fp         : FilePlan that owns this chunk
        chunk      : chunk metadata (contains ``uncompressed_offset``)
        output_dir : root game directory
        """
        out_path = os.path.join(output_dir, fp.path)
        with open(out_path, "r+b") as f:
            f.seek(chunk.uncompressed_offset)
            f.write(data)

    def _allocate_files(self, plan: list[FilePlan], output_dir: str) -> None:
        """
        Parameters
        ----------
        plan       : list of files to pre-allocate
        output_dir : root output directory
        """
        created = 0
        for fp in plan:
            out_path = os.path.join(output_dir, fp.path)
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            if os.path.exists(out_path):
                continue
            with open(out_path, "wb") as f:
                if fp.size > 0:
                    f.seek(fp.size - 1)
                    f.write(b"\x00")
            created += 1

        if created:
            log.debug("Pre-allocated %d new files in %s", created, output_dir)


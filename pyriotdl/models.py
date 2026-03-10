"""
Data models used throughout PyRiotDL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from pyriotdl.helper import fmt_size

log = logging.getLogger(__name__)


@dataclass
class UpdateStatus:
    """
    Result of a version comparison between the installed and latest manifest.

    Attributes
    ----------
    current_url : CDN URL of the currently installed manifest (None = not installed)
    current_id  : 16-char hex ID of the current manifest
    latest_url  : CDN URL of the newest available manifest
    latest_id   : 16-char hex ID of the newest manifest
    game        : human-readable game name
    region      : region code this check was made for
    """

    current_url: Optional[str]
    current_id: Optional[str]
    latest_url: Optional[str]
    latest_id: Optional[str]
    game: str
    region: Optional[str]

    @property
    def has_update(self) -> bool:
        """True when a different (newer) manifest is available."""
        return self.latest_url is not None and self.latest_url != self.current_url

    def __str__(self) -> str:
        if not self.latest_url:
            return f"  [{self.game}] Could not fetch latest version"
        if not self.current_url:
            return f"  [{self.game}] No local version — latest: {self.latest_id}"
        if not self.has_update:
            return f"  [{self.game}] Up to date  ({self.latest_id})"
        return (
            f"  [{self.game}]  Update available\n"
            f"    current => {self.current_id}\n"
            f"    latest  => {self.latest_id}"
        )


@dataclass
class FileDiff:
    """
    Describes how a single file changed between two manifests.

    Attributes
    ----------
    path       : relative game file path
    status     : "added" | "removed" | "modified" | "unchanged"
    old_size   : byte size in old manifest (0 if added)
    size       : byte size in new manifest (0 if removed)
    old_chunks : chunk count in old manifest
    chunks     : chunk count in new manifest
    """

    path: str
    status: str
    old_size: int = 0
    size: int = 0
    old_chunks: int = 0
    chunks: int = 0

    @property
    def size_delta(self) -> int:
        """Signed byte difference: positive = grew, negative = shrank."""
        return self.size - self.old_size


@dataclass
class DiffResult:
    """
    Full comparison between two manifest builds

    Attributes
    ----------
    old_plan  : FilePlan list from the previous manifest
    new_plan  : FilePlan list from the newer manifest
    added     : files present only in new_plan
    removed   : files present only in old_plan
    modified  : files present in both but with different chunk sets
    unchanged : files present in both with identical chunk sets
    """

    old_plan: list[FilePlan]
    new_plan: list[FilePlan]
    added: list[FileDiff] = field(default_factory=list)
    removed: list[FileDiff] = field(default_factory=list)
    modified: list[FileDiff] = field(default_factory=list)
    unchanged: list[FileDiff] = field(default_factory=list)

    @property
    def total_files(self) -> int:
        """Total number of distinct files across both manifests"""
        return len(self.added) + len(self.removed) + len(self.modified) + len(self.unchanged)

    @property
    def size_delta(self) -> int:
        """Net byte change across all added / removed / modified files"""
        return sum(d.size_delta for d in self.added + self.removed + self.modified)

    def _build(self, nfile: FilePlan, ofile: Optional[FilePlan], status: str) -> FileDiff:
        return FileDiff(
            path=nfile.path,
            status=status,
            size=nfile.size,
            chunks=len(nfile.chunks),
            old_size=ofile.size if ofile else 0,
            old_chunks=len(ofile.chunks) if ofile else 0,
        )

    def __post_init__(self) -> None:
        old_map = {fp.path: fp for fp in self.old_plan}
        new_map = {fp.path: fp for fp in self.new_plan}

        for path, fp in new_map.items():
            if path not in old_map:
                self.added.append(self._build(fp, None, "added"))

        for path, fp in old_map.items():
            if path not in new_map:
                self.removed.append(self._build(fp, None, "removed"))

        for path in old_map.keys() & new_map.keys():
            old_fp = old_map[path]
            new_fp = new_map[path]
            old_ids = {c.chunk_id for c in old_fp.chunks}
            new_ids = {c.chunk_id for c in new_fp.chunks}
            if old_ids != new_ids:
                self.modified.append(self._build(new_fp, old_fp, "modified"))
            else:
                self.unchanged.append(self._build(new_fp, old_fp, "unchanged"))

        log.debug(
            "DiffResult: +%d added  -%d removed  ~%d modified  =%d unchanged",
            len(self.added), len(self.removed), len(self.modified), len(self.unchanged),
        )


@dataclass
class LanguageSize:
    """
    Aggregated size info for a single language pack

    Attributes
    ----------
    name        : language name as it appears in the manifest, e.g. "en_US"
    file_count  : number of locale-specific files
    total_bytes : combined uncompressed size of those files
    """

    name: str
    file_count: int
    total_bytes: int

    def __str__(self) -> str:
        return f"  {self.name:<12}  {self.file_count:>5} files  {fmt_size(self.total_bytes)}"


@dataclass
class DownloadStatus:
    """
    Pre-flight download size estimate

    Attributes
    ----------
    total_files          : total files in the new manifest
    total_chunks         : total chunks across all files
    total_size           : uncompressed install size in bytes
    compressed_total     : total compressed size of all chunks
    compressed_to_dl     : compressed bytes that still need to be fetched
    compressed_on_disk   : compressed bytes already present on disk
    compressed_unchanged : compressed bytes shared with old manifest (skipped)
    chunks_to_dl         : number of chunks to download
    chunks_on_disk       : number of chunks already on disk
    chunks_unchanged     : number of chunks shared with old manifest
    """

    total_files: int = 0
    total_chunks: int = 0
    total_size: int = 0
    compressed_total: int = 0
    compressed_to_dl: int = 0
    compressed_on_disk: int = 0
    compressed_unchanged: int = 0
    chunks_to_dl: int = 0
    chunks_on_disk: int = 0
    chunks_unchanged: int = 0


@dataclass
class FilePlan:
    """
    Everything needed to download and write one game file

    Attributes
    ----------
    path         : relative path inside the game directory, e.g. "Game/Content/foo.pak"
    size         : expected uncompressed size in bytes
    locale_flags : bitmask identifying which languages this file belongs to (0 = neutral)
    chunks       : ordered list of chunks that make up this file
    """

    path: str
    size: int
    locale_flags: int
    chunks: list[PlanChunk]


@dataclass
class PlanChunk:
    """
    A single downloadable chunk within a ``FilePlan``.

    Attributes
    ----------
    chunk_id            : 16-char hex identifier
    bundle_id           : 16-char hex ID of the parent ``.bundle`` file
    bundle_url          : full CDN URL of the parent bundle
    compressed_offset   : byte offset of this chunk inside the bundle
    compressed_size     : compressed size in bytes (HTTP Range request size)
    uncompressed_offset : byte offset to write the decompressed data into the output file
    uncompressed_size   : expected decompressed size in bytes
    """

    chunk_id: str
    bundle_id: str
    bundle_url: str
    compressed_offset: int
    compressed_size: int
    uncompressed_offset: int
    uncompressed_size: int


@dataclass
class Chunk:
    """
    One raw chunk entry decoded from a FlatBuffer bundle table

    Attributes
    ----------
    chunk_id            : raw integer chunk ID (u64)
    compressed_offset   : byte offset inside the ``.bundle`` file
    compressed_size     : on-wire size in bytes
    uncompressed_offset : write offset in the assembled output file
    uncompressed_size   : decompressed size in bytes
    """

    chunk_id: int
    compressed_offset: int
    compressed_size: int
    uncompressed_offset: int
    uncompressed_size: int


@dataclass
class Bundle:
    """
    ``.bundle`` file on Riot's CDN.

    Attributes
    ----------
    bundle_id : raw integer bundle ID (u64)
    chunks    : ordered list of chunks stored in this bundle
    """

    bundle_id: int
    chunks: list[Chunk]


@dataclass
class Language:
    """
    locale entry from the manifest languages table

    Attributes
    ----------
    lang_id : 1-based bit index
    name    : locale string, e.g. "en_US"
    """

    lang_id: int
    name: str


@dataclass
class Directory:
    """
    directory node in the manifest path tree

    Attributes
    ----------
    dir_id    : unique integer directory ID
    parent_id : ID of the parent directory (equals dir_id for root)
    name      : directory name segment, e.g. "Content"
    """

    dir_id: int
    parent_id: int
    name: str


@dataclass
class GameFile:
    """
    one game file entry decoded from the manifest

    Attributes
    ----------
    file_id      : unique integer file ID
    directory_id : ID of the parent directory
    name         : filename, e.g. "foo_en_US.pak"
    size         : uncompressed file size in bytes
    locale_flags : language bitmask (0 = neutral / always include)
    chunk_ids    : ordered list of raw integer chunk IDs that compose this file
    """

    file_id: int
    directory_id: int
    name: str
    size: int
    locale_flags: int
    chunk_ids: list[int]


@dataclass
class Manifest:
    """
    fully decoded RMAN manifest

    Attributes
    ----------
    manifest_id : 16-char uppercase hex ID
    version     : FlatBuffer schema version string, e.g. "2.0"
    bundles     : all bundle entries
    languages   : all language entries
    directories : all directory nodes
    files       : all game file entries
    """

    manifest_id: str
    version: str
    bundles: list[Bundle]
    languages: list[Language]
    directories: list[Directory]
    files: list[GameFile]

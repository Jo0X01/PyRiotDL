from __future__ import annotations

import fnmatch
import json
import logging
from typing import Optional

from PyRiotDL.decoder import GameFile, ManifestDecoder
from PyRiotDL.helper import fmt_size
from PyRiotDL.models import FilePlan, PlanChunk

log = logging.getLogger(__name__)


class ManifestBuilder:
    """
    Converts a raw RMAN manifest into a list of ``FilePlan`` objects.

    Parameters
    ----------
    manifest_raw : str | bytes
        Local file path, CDN URL, or raw manifest bytes.
    cdn : str, optional
        CDN hostname (e.g. ``"lol.secure.dyn.riotcdn.net"``).
        Prepended with ``https://`` automatically.
        Required for constructing ``bundle_url`` values in each chunk.
    """

    def __init__(self, manifest_raw: str | bytes, cdn: Optional[str] = None):
        self.cdn = f"https://{cdn}".rstrip("/") if cdn else ""
        self.decoder = ManifestDecoder(manifest_raw)
        self.manifest = self.decoder.manifest
        log.debug(
            "ManifestBuilder ready — manifest_id=%s  bundles=%d  files=%d  languages=%d",
            self.manifest.manifest_id,
            len(self.manifest.bundles),
            len(self.manifest.files),
            len(self.manifest.languages),
        )

    def __build_chunk_to_bundle_map(self) -> dict[int, tuple[int, int, int, int, int]]:
        """Build a chunk_id → (bundle_id, co, cs, uco, ucs) lookup table."""
        lookup: dict[int, tuple[int, int, int, int, int]] = {}
        for bundle in self.manifest.bundles:
            for chunk in bundle.chunks:
                lookup[chunk.chunk_id] = (
                    bundle.bundle_id,
                    chunk.compressed_offset,
                    chunk.compressed_size,
                    chunk.uncompressed_offset,
                    chunk.uncompressed_size,
                )
        log.debug("chunk→bundle map: %d entries", len(lookup))
        return lookup

    def __build_path_lookup(self) -> dict[int, str]:
        """
        Reconstruct full directory paths from the flat directory table.

        Directories are sorted by ``parent_id`` so parents are always resolved
        before their children.
        """
        dirs = sorted(self.manifest.directories, key=lambda d: d.parent_id)
        path_cache: dict[int, str] = {}
        for d in dirs:
            parent_path = path_cache.get(d.parent_id, "")
            path = f"{parent_path}/{d.name}" if parent_path and d.name else d.name or parent_path
            path_cache[d.dir_id] = path
        return path_cache

    def __resolve_file_paths(self) -> list[tuple[str, GameFile]]:
        """Return ``(full_relative_path, GameFile)`` for every file in the manifest."""
        path_lookup = self.__build_path_lookup()
        result = []
        for f in self.manifest.files:
            dir_path = path_lookup.get(f.directory_id, "")
            full_path = f"{dir_path}/{f.name}".lstrip("/") if dir_path else f.name
            result.append((full_path, f))
        return result

    def __build_lang_mask(self, languages: list[str] | None) -> int:
        """
        Convert a list of language name strings into a locale bitmask.

        Parameters
        ----------
        languages : list[str] | None
            * ``None``  → include all languages (mask = 0, no filtering)
            * ``[]``    → neutral files only    (mask = -1, special sentinel)
            * list      → bitmask of requested languages

        Returns
        -------
        int
            * ``0``   — no language filter (include everything)
            * ``-1``  — neutral-only sentinel
            * other   — bitmask of included languages
        """
        if languages is None:
            return 0
        if len(languages) == 0:
            return -1

        mask = 0
        available = {lang.name: lang for lang in self.manifest.languages}
        for name in languages:
            lang = available.get(name)
            if lang:
                if lang.lang_id >= 1:
                    mask |= (1 << (lang.lang_id - 1))
            else:
                log.warning(
                    "Language %r not found in manifest. Available: %s",
                    name,
                    ", ".join(available.keys()),
                )
        return mask

    def __file_matches_lang(self, gf: GameFile, lang_mask: int) -> bool:
        """
        Decide whether to include a file given the language mask.

        Rules
        -----
        * ``locale_flags == 0``  → language-neutral → **always** include
        * ``lang_mask == 0``     → no filter        → **always** include
        * ``lang_mask == -1``    → neutral-only mode → include only if ``locale_flags == 0``
        * otherwise              → include only if flags and mask overlap
        """
        if lang_mask == -1:
            return gf.locale_flags == 0
        if gf.locale_flags == 0 or lang_mask == 0:
            return True
        return bool(gf.locale_flags & lang_mask)

    def _matches_glob(self, full_path: str, patterns: list[str]) -> bool:
        """
        Return ``True`` if *full_path* matches **any** of the given glob patterns.

        Path separators are normalised to ``/`` before matching.
        """
        path_normalised = full_path.replace("\\", "/")
        for pattern in patterns:
            if fnmatch.fnmatch(path_normalised, pattern.replace("\\", "/")):
                return True
        return False

    @property
    def languages(self) -> list[str]:
        """All language name strings available in this manifest."""
        return [lang.name for lang in self.manifest.languages]

    def build(
        self,
        languages: Optional[list[str]] = [],
        platform: Optional[str] = None,
        json_path: Optional[str] = None,
        txt_path: Optional[str] = None,
        urls_path: Optional[str] = None,
        glob_filter: Optional[list[str] | str] = None,
    ) -> list[FilePlan]:
        """
        Build a download plan from this manifest.

        Parameters
        ----------
        languages : list[str] | None, optional
            * ``None``    → include **all** languages (~full download size)
            * ``[]``      → include **only** language-neutral files (base game, no voice)
            * list        → include neutral files **plus** the listed locales,
                            e.g. ``["en_US", "ar_AE"]``
        platform : str, optional
            When set, appended to the language filter list.
            Use ``"windows"`` or ``"mac"`` to handle per-platform locale files.
        json_path : str, optional
            If given, write the full plan to this path as JSON.
        txt_path : str, optional
            If given, write a human-readable summary to this path.
        urls_path : str, optional
            If given, write one unique bundle URL per line to this path.
        glob_filter : str | list[str], optional
            **Include-only** glob pattern(s).  Only files whose path matches at
            least one pattern will be included in the plan.
            Example: ``"ShooterGame/Content/Characters/**"``
                     ``["**/*.pak", "**/*.uasset"]``

            .. note::
               Previously this parameter was named ``filter`` (shadowed the
               Python built-in) and the logic was **inverted** — matching files
               were incorrectly *skipped*.  Both issues are now fixed.

        Returns
        -------
        list[FilePlan]
        """
        if glob_filter and isinstance(glob_filter, str):
            glob_filter = [glob_filter]

        names = list(languages) if languages is not None else None
        if names is not None and platform:
            names.append(platform)

        chunk_map = self.__build_chunk_to_bundle_map()
        file_paths = self.__resolve_file_paths()
        lang_mask = self.__build_lang_mask(names)

        plan: list[FilePlan] = []
        skipped = 0

        for full_path, gf in file_paths:
            if not self.__file_matches_lang(gf, lang_mask):
                skipped += 1
                continue
            if glob_filter and not self._matches_glob(full_path, glob_filter):
                skipped += 1
                continue

            _chunks: list[PlanChunk] = []
            for chunk_id in gf.chunk_ids:
                entry = chunk_map.get(chunk_id)
                if entry is None:
                    log.warning(
                        "Chunk %016X referenced by '%s' not found in any bundle — skipping chunk",
                        chunk_id, full_path,
                    )
                    continue
                bid, co, cs, uco, ucs = entry
                bid_hex = f"{bid:016X}"
                _chunks.append(PlanChunk(
                    chunk_id=f"{chunk_id:016X}",
                    bundle_id=bid_hex,
                    bundle_url=f"{self.cdn}/channels/public/bundles/{bid_hex}.bundle",
                    compressed_offset=co,
                    compressed_size=cs,
                    uncompressed_offset=uco,
                    uncompressed_size=ucs,
                ))
            plan.append(FilePlan(
                path=full_path,
                size=gf.size,
                locale_flags=gf.locale_flags,
                chunks=_chunks,
            ))

        total_size = sum(f.size for f in plan)
        log.info(
            "Build complete — %d files  %d skipped  %s  manifest=%s",
            len(plan), skipped, fmt_size(total_size), self.manifest.manifest_id,
        )

        if json_path:
            self.save_json(plan, json_path)
        if txt_path:
            self.save_txt(plan, txt_path)
        if urls_path:
            self.save_urls(plan, urls_path)

        return plan

    def save_json(self, plan: list[FilePlan], path: str) -> None:
        """
        Serialise the download plan to a JSON file.

        Parameters
        ----------
        plan : list[FilePlan]
            The plan returned by :meth:`build`.
        path : str
            Destination file path.
        """
        data = [
            {
                "path": f.path,
                "size": f.size,
                "locale_flags": f.locale_flags,
                "chunks": [
                    {
                        "chunk_id": c.chunk_id,
                        "bundle_id": c.bundle_id,
                        "bundle_url": c.bundle_url,
                        "compressed_offset": c.compressed_offset,
                        "compressed_size": c.compressed_size,
                        "uncompressed_offset": c.uncompressed_offset,
                        "uncompressed_size": c.uncompressed_size,
                    }
                    for c in f.chunks
                ],
            }
            for f in plan
        ]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            log.debug("Saved JSON plan → %s  (%d files)", path, len(plan))
        except OSError as exc:
            raise OSError(f"save_json: could not write to '{path}': {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"save_json: JSON serialisation failed: {exc}") from exc

    def save_txt(self, plan: list[FilePlan], path: str) -> None:
        """
        Write a human-readable manifest summary to a text file.

        Parameters
        ----------
        plan : list[FilePlan]
        path : str
            Destination file path.
        """
        total_size = sum(f.size for f in plan)
        total_chunks = sum(len(f.chunks) for f in plan)
        total_bundles = len({c.bundle_id for f in plan for c in f.chunks})

        lines = [
            "MANIFEST DUMP",
            "=" * 60,
            f"Files   : {len(plan)}",
            f"Chunks  : {total_chunks}",
            f"Bundles : {total_bundles}",
            f"Size    : {fmt_size(total_size)}",
            "",
            "Languages in manifest:",
        ]
        for lang in self.manifest.languages:
            lines.append(f"  bit {lang.lang_id:2d}  {lang.name}")
        lines.append("=" * 60)
        lines.append("")

        for f in plan:
            lang_label = self.__lang_label(f.locale_flags)
            lines.append(f"FILE: {f.path}  [{lang_label}]")
            lines.append(f"  size   : {fmt_size(f.size)}")
            lines.append(f"  chunks : {len(f.chunks)}")
            for c in f.chunks:
                lines.append(
                    f"  [{c.chunk_id}]  "
                    f"bundle={c.bundle_id}  "
                    f"offset={c.compressed_offset}  "
                    f"compressed={fmt_size(c.compressed_size)}  "
                    f"raw={fmt_size(c.uncompressed_size)}"
                )
            lines.append("")

        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
            log.debug("Saved TXT summary → %s", path)
        except OSError as exc:
            raise OSError(f"save_txt: could not write to '{path}': {exc}") from exc

    def save_urls(self, plan: list[FilePlan], path: str) -> None:
        """
        Write unique bundle URLs (one per line) to a text file

        Parameters
        ----------
        plan : list[FilePlan]
        path : str
            Destination file path.
        """
        seen: set[str] = set()
        urls: list[str] = []
        for f in plan:
            for c in f.chunks:
                if c.bundle_url not in seen:
                    seen.add(c.bundle_url)
                    urls.append(c.bundle_url)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(urls))
            log.debug("Saved %d bundle URLs → %s", len(urls), path)
        except OSError as exc:
            raise OSError(f"save_urls: could not write to '{path}': {exc}") from exc

    def __lang_label(self, locale_flags: int) -> str:
        if locale_flags == 0:
            return "neutral"
        names = [
            lang.name
            for lang in self.manifest.languages
            if lang.lang_id >= 1 and (locale_flags & (1 << (lang.lang_id - 1)))
        ]
        return ", ".join(names) if names else f"flags=0x{locale_flags:X}"
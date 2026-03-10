"""
the main entry point for all Riot Games manifest operations
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Optional

from pyriotdl.builder import ManifestBuilder
from pyriotdl.config import RiotConfig
from pyriotdl.decoder import ManifestDecoder
from pyriotdl.downloader import GameDownloader
from pyriotdl.game import GameConfig
from pyriotdl.helper import extract_id, save_manifest_file
from pyriotdl.history import ManifestVersion, RiotManifestHistory
from pyriotdl.models import (
    DiffResult,
    DownloadStatus,
    FilePlan,
    LanguageSize,
    PlanChunk,
    UpdateStatus,
)
from pyriotdl.progress import BarStyle, DownloadProgress

log = logging.getLogger(__name__)


class PyRiotDL:
    """
    High-level API for downloading, updating, and inspecting Riot Games files

    All operations are driven by RMAN ``.manifest`` files fetched from Riot's CDN
    or from `Morilli/riot-manifests <https://github.com/Morilli/riot-manifests>`_
    archive.

    Parameters
    ----------
    game : str | GameConfig
        Game key string (``"lol"``, ``"val"``, ``"tft"``, ``"lor"``, ``"2xko"``, ``"rc"``)
    region : str, optional
        Region override, e.g. ``"NA1"`` for LoL or ``"eu"`` for VALORANT.
        Uses the game's default region when omitted.
    platform : str, optional
        Platform override ``"windows"`` | ``"macos"`` | ``"android"`` | ``"ios"``.
        Uses the game's default platform when omitted.
    Examples
    --------
    >>> dl = PyRiotDL("lol", region="NA1")
    >>> dl = PyRiotDL("val", region="eu")
    >>> dl = PyRiotDL(PyRiotDL.VALORANT.copy_with(region="na"))
    """

    LOL        = RiotConfig.LOL
    TFT        = RiotConfig.TFT
    VALORANT   = RiotConfig.VALORANT
    RUNETERRA  = RiotConfig.RUNETERRA
    KO2        = RiotConfig.KO2
    WILDRIFT   = RiotConfig.WILDRIFT
    RIOTCLIENT = RiotConfig.RC
    RC         = RiotConfig.RC

    def __init__(
        self,
        game: str | GameConfig,
        region: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> None:
        if isinstance(game, str):
            cfg = RiotConfig.get(game)
            if cfg is None:
                raise ValueError(
                    f"Unknown game key: {game!r}. "
                    f"Valid keys: {[k for g in RiotConfig.all() for k in g.key]}"
                )
            game = cfg

        self.cfg = game.copy_with(region=region, platform=platform)
        self.version_control = RiotManifestHistory(self.cfg)
        log.info("PyRiotDL initialised — game=%s  region=%s", self.cfg.name, self.cfg.region)

    @staticmethod
    def setup_logging(level: int = logging.INFO) -> None:
        """
        Configure a basic ``StreamHandler`` for the ``pyriotdl`` logger hierarchy.

        Call this once at application startup if you want log output.

        Parameters
        ----------
        level : int
            Logging level, e.g. ``logging.DEBUG`` or ``logging.INFO``.
        """
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
        )
        root = logging.getLogger()
        root.setLevel(level)
        root.addHandler(handler)

    def latest_manifest_url(self, mac_os: bool = False) -> Optional[str]:
        """
        Fetch the latest manifest CDN URL for this game from Riot's API.

        Parameters
        ----------
        mac_os : bool
            Request the macOS manifest instead of Windows.

        Returns
        -------
        str | None
            CDN URL string, or ``None`` on failure.
        """
        try:
            url = self.cfg.dispatch_manifest_url(support_macos=mac_os)
            log.debug("Latest manifest URL: %s", url)
            return url
        except Exception as exc:
            log.warning("Could not fetch latest manifest URL: %s", exc)
            return None

    def check_for_update(self, current: str, mac_os: bool = False) -> UpdateStatus:
        """
        Compare the installed manifest against the latest available version.

        Parameters
        ----------
        current : str
            Local ``.manifest`` file path or CDN URL of the installed version.
        mac_os : bool
            Check macOS manifest instead of Windows.

        Returns
        -------
        UpdateStatus
        """
        latest_url = self.latest_manifest_url(mac_os=mac_os)
        current_id = ManifestDecoder(current).manifest_id
        current_url = self.cfg.manifest_url(current_id)
        status = UpdateStatus(
            current_url=current_url,
            current_id=current_id,
            latest_url=latest_url,
            latest_id=extract_id(latest_url),
            game=self.cfg.name,
            region=self.cfg.region,
        )
        log.info("Update check: %s", status)
        return status

    def install(
        self,
        output_dir: Optional[str] = None,
        languages: list[str] = [],
        workers: int = 8,
        retries: int = 3,
        style: Optional[BarStyle] = None,
        mac_os: bool = False,
        save_manifest: Optional[str] = None,
        download: bool = True,
    ) -> DownloadProgress | list[FilePlan]:
        """
        fresh install — download all game files from scratch.

        Parameters
        ----------
        output_dir : str, optional
            Directory to install game files into.
        languages : list[str]
            * ``[]``   → neutral / base files only (no voice packs)
            * ``None`` → all languages (largest download)
            * list     → specific locales, e.g. ``["en_US", "fr_FR"]``
        workers : int
            Parallel download threads (default ``8``).
        retries : int
            Retry attempts per failed chunk (default ``3``).
        mac_os : bool
            Download the macOS build instead of Windows.
        save_manifest : str, optional
            Path to save the fetched ``.manifest`` binary for future updates.
        download : bool
            When ``False``, return the ``list[FilePlan]`` without downloading.

        Returns
        -------
        DownloadProgress | list[FilePlan]
        """
        url = self.latest_manifest_url(mac_os=mac_os)
        if not url:
            log.error("install: could not resolve latest manifest URL")
            return DownloadProgress() if download else []

        plan = ManifestBuilder(url, self.cfg.cdn).build(languages)
        if not plan:
            log.warning("install: empty plan")
            return DownloadProgress() if download else []

        if save_manifest:
            save_manifest_file(url, save_manifest)

        if download:
            return self._start_download(plan, output_dir=output_dir,
                                        workers=workers, retries=retries, style=style)
        return plan

    def update(
        self,
        current: str,
        output_dir: Optional[str] = None,
        languages: list[str] = [],
        workers: int = 8,
        retries: int = 3,
        style: Optional[BarStyle] = None,
        mac_os: bool = False,
        save_manifest_path: Optional[str] = None,
        download: bool = True,
    ) -> DownloadProgress | list[FilePlan]:
        """
        only download chunks that changed since the installed version

        Parameters
        ----------
        current : str
            Local ``.manifest`` path or CDN URL of the currently installed version.
        output_dir : str, optional
            Game directory to update in place.
        languages : list[str]
            Language filter (same semantics as :meth:`install`).
        workers : int
            Parallel download threads.
        retries : int
            Retry attempts per failed chunk.
        mac_os : bool
            Update the macOS build.
        save_manifest_path : str, optional
            Path to save the new ``.manifest`` (pass the same path as ``current``
            to replace it in place).
        download : bool
            When ``False``, return the plan without downloading.

        Returns
        -------
        DownloadProgress | list[FilePlan]
        """
        status = self.check_for_update(current, mac_os=mac_os)
        if not status.has_update or not status.latest_url:
            log.info("update: already up to date")
            return DownloadProgress() if download else []

        if save_manifest_path:
            save_manifest_file(status.latest_url, save_manifest_path)

        new_plan = ManifestBuilder(status.latest_url, self.cfg.cdn).build(languages)
        if not new_plan:
            return DownloadProgress() if download else []

        old_plan: list[FilePlan] = []
        if status.current_url:
            old_plan = ManifestBuilder(status.current_url, self.cfg.cdn).build(languages)

        if download:
            return self._start_download(new_plan, old_plan=old_plan, output_dir=output_dir,
                                        workers=workers, retries=retries, style=style)
        return new_plan + old_plan

    def repair(
        self,
        output_dir: str,
        manifest_src: Optional[str] = None,
        languages: list[str] = [],
        workers: int = 8,
        retries: int = 3,
        style: Optional[BarStyle] = None,
        download: bool = True,
    ) -> DownloadProgress | list[FilePlan]:
        """
        verify existing files on disk and re-download any missing or corrupt chunks.

        Parameters
        ----------
        output_dir : str
            Game directory to verify and repair.
        manifest_src : str, optional
            Local ``.manifest`` path, CDN URL, or manifest ID.
            Defaults to the latest manifest from the API when ``None``.
        languages : list[str]
            Language filter.
        workers : int
            Parallel download threads.
        retries : int
            Retry attempts per failed chunk.
        download : bool
            When ``False``, return the plan without downloading.

        Returns
        -------
        DownloadProgress | list[FilePlan]
        """
        src, _ = self._resolve_manifest_src(manifest_src)
        if not src:
            log.error("repair: could not resolve manifest source")
            return DownloadProgress() if download else []

        plan = ManifestBuilder(src, self.cfg.cdn).build(languages)
        if not plan:
            return DownloadProgress() if download else []

        if download:
            return self._start_download(plan, output_dir=output_dir,
                                        workers=workers, retries=retries, style=style)
        return plan

    def save_manifest(self, save_path: str, mac_os: bool = False) -> Optional[str]:
        """
        Download the latest ``.manifest`` binary to disk.

        Parameters
        ----------
        save_path : str
            Destination file path.
        mac_os : bool
            Fetch the macOS manifest.

        Returns
        -------
        str | None
            The ``save_path`` on success, ``None`` on failure.
        """
        url = self.latest_manifest_url(mac_os=mac_os)
        if url:
            return save_manifest_file(url, save_path)
        return None

    def diff(
        self,
        old: str,
        new: Optional[str] = None,
        languages: Optional[list[str]] = [],
    ) -> DiffResult:
        """
        compare two manifests and return structured change report

        Parameters
        ----------
        old : str
            Old ``.manifest`` path, CDN URL, or manifest ID hex string.
        new : str, optional
            New ``.manifest`` path, URL, or ID.
            Defaults to the latest from the API when ``None``.
        languages : list[str] | None
            Language filter applied to both manifests.

        Returns
        -------
        DiffResult

        Raises
        ------
        ValueError
            If either manifest cannot be resolved or parsed.
        """
        new_src, old_src = self._resolve_manifest_src(new, old)
        if not old_src or not new_src:
            raise ValueError(f"Could not resolve manifests — OLD: {old!r}  NEW: {new!r}")

        old_plan = ManifestBuilder(old_src, self.cfg.cdn).build(languages)
        new_plan = ManifestBuilder(new_src, self.cfg.cdn).build(languages)
        if not old_plan or not new_plan:
            raise ValueError("Could not parse one or both manifests")

        return DiffResult(old_plan, new_plan)

    def extract(
        self,
        manifest: Optional[str] = None,
        output_dir: Optional[str] = None,
        pattern_filter: Optional[str | list[str]] = None,
        languages: Optional[list[str]] = [],
        workers: int = 8,
        retries: int = 3,
        style: Optional[BarStyle] = None,
        download: bool = True,
    ) -> DownloadProgress | list[FilePlan]:
        """
        extract specific files from a manifest using glob patterns.
        Only files whose path matches at least one pattern are downloaded

        Parameters
        ----------
        manifest : str, optional
            Local ``.manifest`` path, CDN URL, or manifest ID.
            Defaults to latest from the API.
        output_dir : str, optional
            Where to write extracted files.
        pattern_filter : str | list[str], optional
            Glob pattern(s) to select files.
            Example: ``"ShooterGame/Content/Characters/**"``
                     ``["**/*.pak", "**/*.uasset"]``
        languages : list[str] | None
            Language filter.
        workers : int
            Parallel download threads.
        retries : int
            Retry attempts per failed chunk.
        download : bool
            When ``False``, return the plan without downloading.

        Returns
        -------
        DownloadProgress | list[FilePlan]
        """
        src, _ = self._resolve_manifest_src(manifest)
        if not src:
            log.error("extract: could not resolve manifest source")
            return DownloadProgress() if download else []

        plan = ManifestBuilder(src, self.cfg.cdn).build(languages, glob_filter=pattern_filter)
        if not plan:
            return DownloadProgress() if download else []

        if download:
            return self._start_download(plan, output_dir=output_dir,
                                        workers=workers, retries=retries, style=style)
        return plan

    def calculate_download_size(
        self,
        manifest: Optional[str] = None,
        languages: Optional[list[str]] = None,
        game_dir: Optional[str] = None,
        old_manifest: Optional[str] = None,
    ) -> DownloadStatus:
        """
        pre-flight download size estimate without downloading anything

        Parameters
        ----------
        manifest : str, optional
            Target manifest (local path, CDN URL, or ID).
            Defaults to latest from API.
        languages : list[str] | None
            Language filter (``None`` = all languages).
        game_dir : str, optional
            Game folder for on-disk verification.
        old_manifest : str, optional
            Previous manifest for diff-based size reduction.

        Returns
        -------
        DownloadStatus
        """
        src, old_src = self._resolve_manifest_src(manifest, old_manifest)
        if not src:
            return DownloadStatus()

        new_plan = ManifestBuilder(src, self.cfg.cdn).build(languages)
        old_plan: list[FilePlan] = []
        if old_manifest and old_src:
            old_plan = ManifestBuilder(old_src, self.cfg.cdn).build(languages)

        all_chunks = [(fp, c) for fp in new_plan for c in fp.chunks]
        skip_ids = {c.chunk_id for fp in old_plan for c in fp.chunks}

        unchanged_chunks: list[tuple[FilePlan, PlanChunk]] = []
        to_check_chunks: list[tuple[FilePlan, PlanChunk]] = []

        for fp, c in all_chunks:
            (unchanged_chunks if c.chunk_id in skip_ids else to_check_chunks).append((fp, c))

        on_disk_chunks: list[tuple[FilePlan, PlanChunk]] = []
        to_dl_chunks: list[tuple[FilePlan, PlanChunk]] = []

        if game_dir and to_check_chunks:
            by_file: dict[str, list[tuple[FilePlan, PlanChunk]]] = defaultdict(list)
            for fp, c in to_check_chunks:
                by_file[fp.path].append((fp, c))

            for path, items in by_file.items():
                out_path = os.path.join(game_dir, path)
                if not os.path.exists(out_path):
                    to_dl_chunks.extend(items)
                    continue
                min_required = max(
                    (c.uncompressed_offset + c.uncompressed_size for _, c in items),
                    default=0,
                )
                if os.path.getsize(out_path) < min_required:
                    to_dl_chunks.extend(items)
                else:
                    on_disk_chunks.extend(items)
        else:
            to_dl_chunks = to_check_chunks

        return DownloadStatus(
            total_files=len(new_plan),
            total_chunks=len(all_chunks),
            total_size=sum(fp.size for fp in new_plan),
            compressed_total=sum(c.compressed_size for _, c in all_chunks),
            compressed_to_dl=sum(c.compressed_size for _, c in to_dl_chunks),
            compressed_on_disk=sum(c.compressed_size for _, c in on_disk_chunks),
            compressed_unchanged=sum(c.compressed_size for _, c in unchanged_chunks),
            chunks_to_dl=len(to_dl_chunks),
            chunks_on_disk=len(on_disk_chunks),
            chunks_unchanged=len(unchanged_chunks),
        )

    def language_sizes(
        self,
        manifest: Optional[str] = None,
        languages: Optional[list[str]] = None,
    ) -> list[LanguageSize]:
        """
        return per-language download size information

        Parameters
        ----------
        manifest : str, optional
            Local ``.manifest`` path, URL, or ID (defaults to latest from API).
        languages : list[str] | None
            Restrict output to these language names.
            ``None`` returns all available languages.

        Returns
        -------
        list[LanguageSize]
            Sorted by total bytes descending.
        """
        src, _ = self._resolve_manifest_src(manifest)
        if not src:
            return []

        mb = ManifestBuilder(src, cdn=self.cfg.cdn)
        full_plan = mb.build(languages=None)
        available_langs = mb.languages

        lang_files: dict[str, int] = {l: 0 for l in available_langs}
        lang_bytes: dict[str, int] = {l: 0 for l in available_langs}

        for fp in full_plan:
            if fp.locale_flags == 0:
                continue
            for lang in mb.manifest.languages:
                if lang.lang_id >= 1 and (fp.locale_flags & (1 << (lang.lang_id - 1))):
                    lang_files[lang.name] += 1
                    lang_bytes[lang.name] += fp.size

        filter_set = set(languages) if languages else None
        results = [
            LanguageSize(name, lang_files[name], lang_bytes[name])
            for name in available_langs
            if not filter_set or name in filter_set
        ]
        results.sort(key=lambda x: x.total_bytes, reverse=True)
        return results

    def history(
        self,
        limit: int = 20,
        include_hotfixes: bool = True,
        patch_filter: Optional[str] = None,
    ) -> list[ManifestVersion]:
        """
        fetch patch version history from the Morilli/riot-manifests archive.

        Credit: https://github.com/Morilli/riot-manifests

        Parameters
        ----------
        limit : int
            Maximum versions to return, newest first (default ``20``).
        include_hotfixes : bool
            Include hotfix releases (default ``True``).
        patch_filter : str, optional
            Restrict to a single patch cycle, e.g. ``"10.04"``.

        Returns
        -------
        list[ManifestVersion]
        """
        return self.version_control.history(
            limit=limit,
            include_hotfixes=include_hotfixes,
            patch_filter=patch_filter,
        )

    def history_regions(self) -> list[str]:
        """
        List available region subfolders for this game in the history archive.

        Returns
        -------
        list[str]
        """
        return self.version_control.regions()

    def dump(
        self,
        manifest: Optional[str] = None,
        languages: list[str] | None = None,
        json_path: Optional[str] = None,
        txt_path: Optional[str] = None,
        urls_path: Optional[str] = None,
        mac_os: bool = False,
    ) -> list[FilePlan]:
        """
        parse a manifest and optionally save its contents to disk

        Useful for datamining tools that need the full file/chunk list without
        downloading anything.

        Parameters
        ----------
        manifest : str, optional
            Local path, CDN URL, or manifest ID (``None`` = fetch latest).
        languages : list[str] | None
            Language filter.
        json_path : str, optional
            Save full plan to this JSON path.
        txt_path : str, optional
            Save human-readable summary to this path.
        urls_path : str, optional
            Save unique bundle URLs (one per line) to this path.
        mac_os : bool
            Fetch the macOS manifest.

        Returns
        -------
        list[FilePlan]
        """
        src, _ = self._resolve_manifest_src(manifest, mac_os=mac_os)
        if not src:
            log.error("dump: could not resolve manifest source")
            return []

        mb = ManifestBuilder(src, cdn=self.cfg.cdn)
        plan = mb.build(languages=languages)

        if json_path:
            mb.save_json(plan, json_path)
        if txt_path:
            mb.save_txt(plan, txt_path)
        if urls_path:
            mb.save_urls(plan, urls_path)

        return plan

    def _start_download(
        self,
        plan: list[FilePlan],
        output_dir: Optional[str],
        workers: int,
        retries: int,
        style: Optional[BarStyle],
        old_plan: Optional[list[FilePlan]] = None,
    ) -> DownloadProgress:
        """Shared helper that constructs a ``GameDownloader`` and starts it."""
        return GameDownloader(
            plan,
            old_plan=old_plan,
            game_dir=output_dir,
        ).start_download(
            output_dir or ".",
            workers=workers,
            retries=retries,
            style=style,
        )

    def _resolve_manifest_src(
        self,
        new_src: Optional[str] = None,
        old_src: Optional[str] = None,
        mac_os: bool = False,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        resolve one or two manifest references into CDN URLs (or file paths)

        Parameters
        ----------
        new_src : str, optional
            The newer / target manifest reference.
        old_src : str, optional
            The older / baseline manifest reference.
        mac_os : bool
            Fetch macOS manifest when ``new_src`` is ``None``.

        Returns
        -------
        tuple[new_url, old_url]
            Both values may be ``None`` on failure.
        """
        def _normalise(src: Optional[str]) -> Optional[str]:
            if not src:
                return None
            if os.path.isfile(src):
                return src
            manifest_id = extract_id(src)
            return self.cfg.manifest_url(manifest_id) if manifest_id else None

        resolved_old = _normalise(old_src)
        resolved_new = _normalise(new_src) if new_src else self.latest_manifest_url(mac_os=mac_os)

        log.debug("Resolved manifests — new=%s  old=%s", resolved_new, resolved_old)
        return resolved_new, resolved_old

"""
Client for the Morilli/riot-manifests GitHub archive.

This module is completely independent of the rest of PyRiotDL.
It only needs a ``GameConfig`` to know which folder/region to look in.

All history data comes from the community-maintained archive:
https://github.com/Morilli/riot-manifests
"""

from __future__ import annotations

import json
import logging
import os
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PyRiotDL.game import GameConfig
from PyRiotDL.helper import encode_path, extract_id

log = logging.getLogger(__name__)


@dataclass
class ManifestVersion:
    """
    One archived manifest entry from the Morilli/riot-manifests repo.

    Attributes
    ----------
    manifest_id : 16-char uppercase hex ID
    version     : full version string from the filename, e.g. ``"10.04.01.2352000"``
    date        : commit/archive date (``None`` — not available via Contents API)
    url         : CDN manifest URL ready to pass to ``ManifestBuilder``
    game        : game name string, e.g. ``"VALORANT"``

    Properties
    ----------
    is_hotfix    : ``True`` when the HOTFIX segment of the version > 0
    is_patch     : ``True`` when this is a full patch release (not a hotfix)
    patch_number : ``"MAJOR.PATCH"`` label, e.g. ``"10.04"`` — useful for grouping
    kind         : ``"patch"`` | ``"hotfix"``
    """

    manifest_id: str
    version: str
    date: Optional[datetime]
    url: str
    game: str

    @property
    def _parts(self) -> list[int]:
        try:
            return [int(x) for x in self.version.split(".")]
        except ValueError:
            return []

    @property
    def is_hotfix(self) -> bool:
        """``True`` if this release has a non-zero hotfix segment."""
        parts = self._parts
        return len(parts) >= 4 and parts[2] != 0

    @property
    def is_patch(self) -> bool:
        """``True`` if this is a full patch release (hotfix segment == 00 or absent)."""
        return not self.is_hotfix

    @property
    def patch_number(self) -> Optional[str]:
        """
        Short patch label: ``MAJOR.PATCH``, e.g. ``"10.04"``.
        Returns ``None`` if the version string is not parseable.
        """
        parts = self._parts
        return f"{parts[0]}.{parts[1]:02d}" if len(parts) >= 2 else None

    @property
    def kind(self) -> str:
        """``"hotfix"`` or ``"patch"``."""
        return "hotfix" if self.is_hotfix else "patch"

    def __str__(self) -> str:
        date_str = self.date.strftime("%Y-%m-%d %H:%M") if self.date else "unknown date"
        tag = "  [hotfix]" if self.is_hotfix else ""
        return (
            f"  {date_str}  {self.version:<30}  "
            f"{self.manifest_id}  {self.url}{tag}"
        )


class RiotManifestHistory:
    """
    Read-only client for the Morilli/riot-manifests GitHub archive.

    Credit: https://github.com/Morilli/riot-manifests

    Parameters
    ----------
    cfg : GameConfig
        Config for the game you want history for.
        Must have ``cfg.repo_folder`` set (all standard games do).
    """

    REPO   = "Morilli/riot-manifests"
    CREDIT = "https://github.com/Morilli/riot-manifests"

    _CONTENTS_URL = "https://api.github.com/repos/{repo}/contents/{path}"
    _RAW_URL      = "https://raw.githubusercontent.com/{repo}/master/{path}"
    _HEADERS = {
        "User-Agent": "PyRiotDL/1.0",
        "Accept":     "application/vnd.github+json",
    }

    def __init__(self, cfg: GameConfig) -> None:
        self.cfg = cfg

    def history(
        self,
        limit: int = 20,
        include_hotfixes: bool = True,
        patch_filter: Optional[str] = None,
    ) -> list[ManifestVersion]:
        """
        Fetch version history for this game from the community archive.

        The archive stores one file per version whose name is the version string
        and whose content is a CDN manifest URL (or JSON for Riot Client).
        Files are fetched in parallel so even large limits are fast.

        Parameters
        ----------
        limit : int
            Maximum versions to return, newest first (default ``20``).
        include_hotfixes : bool
            Include hotfix releases (default ``True``).
            Pass ``False`` to get only full patch releases.
        patch_filter : str, optional
            Restrict to one patch cycle, e.g. ``"10.04"``.
            Returns the patch itself plus all its hotfixes
            (or only the patch if *include_hotfixes* is ``False``).

        Returns
        -------
        list[ManifestVersion]
        """
        repo_path = self.repo_path()
        if not repo_path:
            log.warning("[%s] No history path configured for this game", self.cfg.name)
            return []

        log.info("[%s] Fetching version history from GitHub — path: %s", self.cfg.name, repo_path)

        entries = self._list(repo_path)
        if entries is None:
            return []

        files = [e for e in entries if e.get("type") == "file"]
        if not files:
            log.warning("[%s] No version files found in '%s'", self.cfg.name, repo_path)
            subdirs = [e["name"] for e in entries if e.get("type") == "dir"]
            if subdirs:
                log.info(
                    "[%s] Folder contains subdirectories: %s  (try a more specific region)",
                    self.cfg.name, subdirs,
                )
            return []

        is_json    = self.cfg.namespace == "keystone.self_update"
        json_field = "keystone.self_update.manifest_url"

        files.sort(key=lambda e: e["name"], reverse=True)
        files = files[:limit]

        if not files:
            return []

        def fetch(entry: dict) -> tuple[str, Optional[str]]:
            version_str  = os.path.splitext(entry["name"])[0]
            manifest_url = self._read_url(entry["path"], is_json, json_field)
            return version_str, manifest_url

        ordered: list[Optional[ManifestVersion]] = [None] * len(files)
        with ThreadPoolExecutor(max_workers=min(10, len(files))) as pool:
            future_map = {pool.submit(fetch, e): i for i, e in enumerate(files)}
            for fut in as_completed(future_map):
                idx = future_map[fut]
                try:
                    version_str, manifest_url = fut.result()
                except Exception as exc:
                    log.warning("Failed to fetch a version entry: %s", exc)
                    continue
                if not manifest_url:
                    continue
                manifest_id = extract_id(manifest_url) or version_str
                ordered[idx] = ManifestVersion(
                    manifest_id=manifest_id,
                    version=version_str,
                    date=None,
                    url=manifest_url,
                    game=self.cfg.name,
                )

        versions = [v for v in ordered if v is not None]

        if not include_hotfixes:
            versions = [v for v in versions if v.is_patch]
        if patch_filter:
            versions = [v for v in versions if v.patch_number == patch_filter]

        log.info("[%s] Found %d versions", self.cfg.name, len(versions))
        return versions

    def regions(self) -> list[str]:
        """
        List available region subfolders for this game in the archive.

        Returns
        -------
        list[str]
            Region/subfolder names, or an empty list for flat layouts.
        """
        folder = self.cfg.repo_folder
        if not folder:
            return []
        entries = self._list(folder)
        if not entries:
            return []
        return sorted(e["name"] for e in entries if e.get("type") == "dir")

    def repo_path(self) -> Optional[str]:
        """
        Return the exact path inside the archive repo for this game + region.

        This is the folder that contains the ``.txt`` (or ``.json``) version
        files.  Returns ``None`` if the game has no configured archive path.

        Returns
        -------
        str | None
        """
        folder = self.cfg.repo_folder
        if not folder:
            return None

        region = self.cfg.region or ""

        if folder == "VALORANT":
            r = region.lower() or "eu"
            return f"{folder}/{r}"

        if folder == "LoL":
            r = region.upper() or "EUW1"
            return f"{folder}/{r}/windows/lol-game-client"

        if folder == "TFT":
            # BUG FIX: Windows/macOS TFT manifests live under LoL/ in the archive, not TFT/.
            # The TFT/ root is only used for mobile (android) builds.
            # Source: Morilli/riot-manifests LoL + TFT.py:
            #   path = f'{"LoL" if OS in {"macos","windows"} else "TFT"}/{region}/{OS}/{artifact_type_id}'
            r = region.upper() or "EUW1"
            return f"LoL/{r}/windows/lol-standalone-client"

        if folder == "Riot Client":
            patchline = getattr(self.cfg, "patchline", "KeystoneFoundationLiveWin")
            if patchline == "live":
                patchline = "KeystoneFoundationLiveWin"
            return f"{folder}/{patchline}"

        if folder == "LoR":
            return folder
        if region:
            return f"{folder}/{region}"
        return folder

    def _list(self, repo_path: str) -> Optional[list[dict]]:
        """
        List the contents of *repo_path* in the archive via GitHub Contents API.

        Returns
        -------
        list[dict] | None
            Raw GitHub API entries, or ``None`` on error.
        """
        encoded = encode_path(repo_path)
        url = self._CONTENTS_URL.format(repo=self.REPO, path=encoded)
        try:
            resp = requests.get(url, headers=self._HEADERS, timeout=(10, 60), stream=True)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                log.error("Path not found in archive: '%s'  (check region/folder name)", repo_path)
            else:
                log.error("GitHub API error listing '%s': %s", repo_path, exc)
            return None
        except Exception as exc:
            log.error("Could not list '%s': %s", repo_path, exc)
            return None

    def _read_url(
        self,
        repo_path: str,
        is_json: bool,
        json_field: str,
    ) -> Optional[str]:
        """
        Fetch one version file from GitHub raw and return its manifest URL.

        Parameters
        ----------
        repo_path  : relative path inside the repo, e.g. ``"LoL/EUW1/windows/lol-game-client/14.01.txt"``
        is_json    : ``True`` for Riot Client entries whose content is a JSON object
        json_field : JSON key to extract when *is_json* is ``True``

        Returns
        -------
        str | None
            Manifest CDN URL, or ``None`` if the file cannot be read/parsed.
        """
        encoded = encode_path(repo_path)
        url = self._RAW_URL.format(repo=self.REPO, path=encoded)
        try:
            resp = requests.get(url, headers=self._HEADERS, timeout=10)
            resp.raise_for_status()
            content = resp.text.strip()

            if is_json:
                return json.loads(content).get(json_field)

            if content.startswith("http"):
                return content

            if re.fullmatch(r"[0-9A-Fa-f]{16}", content):
                return self.cfg.manifest_url(content.upper())

            log.warning("Unrecognised content format in '%s'", repo_path)
            return None
        except Exception as exc:
            log.warning("Could not read '%s': %s", repo_path, exc)
            return None
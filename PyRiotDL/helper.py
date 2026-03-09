from __future__ import annotations

import logging
import os
import re
import struct
from typing import Any, Optional
from urllib.parse import quote

import requests
import zstandard as zstd

log = logging.getLogger(__name__)


class BinaryReader:
    """
    wraps a ``bytes`` object and provides typed random-access reads

    Parameters
    ----------
    data : bytes
        The raw bytes to wrap.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.length = len(data)

    def _check(self, offset: int, size: int) -> None:
        if offset < 0 or offset + size > self.length:
            raise IndexError(
                f"BinaryReader read out of bounds: offset={offset}, size={size}, buffer={self.length}"
            )

    def u8(self, offset: int) -> int:
        """Read an unsigned 8-bit integer at *offset*."""
        try:
            self._check(offset, 1)
            return struct.unpack_from("<B", self.data, offset)[0]
        except struct.error as exc:
            raise IndexError(f"u8 read failed at offset {offset}: {exc}") from exc

    def u16(self, offset: int) -> int:
        """Read an unsigned 16-bit integer at *offset*."""
        try:
            self._check(offset, 2)
            return struct.unpack_from("<H", self.data, offset)[0]
        except struct.error as exc:
            raise IndexError(f"u16 read failed at offset {offset}: {exc}") from exc

    def u32(self, offset: int) -> int:
        """Read an unsigned 32-bit integer at *offset*."""
        try:
            self._check(offset, 4)
            return struct.unpack_from("<I", self.data, offset)[0]
        except struct.error as exc:
            raise IndexError(f"u32 read failed at offset {offset}: {exc}") from exc

    def u64(self, offset: int) -> int:
        """Read an unsigned 64-bit integer at *offset*."""
        try:
            self._check(offset, 8)
            return struct.unpack_from("<Q", self.data, offset)[0]
        except struct.error as exc:
            raise IndexError(f"u64 read failed at offset {offset}: {exc}") from exc

    def i16(self, offset: int) -> int:
        """Read a signed 16-bit integer at *offset*."""
        try:
            self._check(offset, 2)
            return struct.unpack_from("<h", self.data, offset)[0]
        except struct.error as exc:
            raise IndexError(f"i16 read failed at offset {offset}: {exc}") from exc

    def i32(self, offset: int) -> int:
        """Read a signed 32-bit integer at *offset*."""
        try:
            self._check(offset, 4)
            return struct.unpack_from("<i", self.data, offset)[0]
        except struct.error as exc:
            raise IndexError(f"i32 read failed at offset {offset}: {exc}") from exc

    def string(self, offset: int, length: int) -> str:
        """Read *length* bytes as an ASCII string starting at *offset*."""
        try:
            self._check(offset, length)
            return self.data[offset: offset + length].decode("ascii", errors="replace")
        except Exception as exc:
            raise IndexError(
                f"string read failed at offset={offset} length={length}: {exc}"
            ) from exc

    def bytes_at(self, offset: int, length: int) -> bytes:
        """Return a raw bytes slice starting at *offset*."""
        try:
            self._check(offset, length)
            return self.data[offset: offset + length]
        except Exception as exc:
            raise IndexError(
                f"bytes_at read failed at offset={offset} length={length}: {exc}"
            ) from exc

    def save(self, save_path: str) -> None:
        """Write the entire buffer to *save_path*."""
        try:
            with open(save_path, "wb") as f:
                f.write(self.data)
            log.debug("BinaryReader saved %d bytes → %s", self.length, save_path)
        except OSError as exc:
            raise OSError(f"BinaryReader.save failed for '{save_path}': {exc}") from exc


def raw_handler(raw: str | bytes | BinaryReader) -> Optional[BinaryReader]:
    """
    Convert a variety of input types into a :class:`BinaryReader`.

    Accepted inputs
    ---------------
    * :class:`BinaryReader` — returned as-is
    * ``bytes``             — wrapped in a new ``BinaryReader``
    * ``str`` (file path)   — file is read from disk
    * ``str`` (HTTP/S URL)  — file is fetched over the network

    Parameters
    ----------
    raw : str | bytes | BinaryReader
        Input to convert.

    Returns
    -------
    BinaryReader | None
        ``None`` if the type is not supported or the request fails.
    """
    if isinstance(raw, BinaryReader):
        return raw
    if isinstance(raw, bytes):
        return BinaryReader(raw)
    if isinstance(raw, str):
        if os.path.isfile(raw):
            log.debug("raw_handler: reading file %s", raw)
            try:
                with open(raw, "rb") as fh:
                    return BinaryReader(fh.read())
            except OSError as exc:
                log.error("raw_handler: could not read file '%s': %s", raw, exc)
                return None
        if raw.startswith("http://") or raw.startswith("https://"):
            log.debug("raw_handler: fetching URL %s", raw)
            try:
                response = requests.get(
                    raw,
                    headers={"User-Agent": "RiotClient/99.0.0.9999999 riot-client"},
                    timeout=30,
                )
                response.raise_for_status()
                return BinaryReader(response.content)
            except requests.exceptions.Timeout:
                log.error("raw_handler: request timed out for '%s'", raw)
                return None
            except requests.exceptions.ConnectionError as exc:
                log.error("raw_handler: connection error for '%s': %s", raw, exc)
                return None
            except requests.HTTPError as exc:
                log.error(
                    "raw_handler: HTTP %s for '%s'",
                    exc.response.status_code if exc.response is not None else "?",
                    raw,
                )
                return None
            except Exception as exc:
                log.error("raw_handler: unexpected error fetching '%s': %s", raw, exc)
                return None
    log.warning("raw_handler: unsupported input type %s", type(raw).__name__)
    return None


def fetch_data_from_url(
    url: Optional[str],
    json: bool = False,
) -> Any:
    """
    Perform a simple GET request and return the response body.

    Parameters
    ----------
    url : str | None
        Target URL.  Returns ``None`` immediately when ``None``.
    json : bool
        When ``True``, parse and return the JSON body.
        When ``False``, return raw ``bytes``.

    Returns
    -------
    dict | bytes | None
        ``None`` on any error (including HTTP errors).
    """
    if not url:
        return None
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "RiotClient/99.0.0.9999999 riot-client"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json() if json else response.content
    except Exception as exc:
        log.warning("fetch_data_from_url failed for %s: %s", url, exc)
        return None


def save_file(data: BinaryReader | str | bytes, save_path: str) -> str:
    """
    Write *data* to *save_path*, creating parent directories as needed.

    Parameters
    ----------
    data : BinaryReader | str | bytes
        Content to write.
    save_path : str
        Destination path.

    Returns
    -------
    str
        The *save_path* argument (for chaining).
    """
    if isinstance(data, BinaryReader):
        data = data.data
    try:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        mode = "w" if isinstance(data, str) else "wb"
        with open(save_path, mode) as f:
            f.write(data)
        log.debug("Saved file → %s", save_path)
    except OSError as exc:
        raise OSError(f"save_file failed for '{save_path}': {exc}") from exc
    return save_path


def save_manifest_file(url: str, save_path: str) -> Optional[str]:
    """
    Fetch a manifest from *url* and write it to *save_path*.

    Parameters
    ----------
    url : str
        CDN manifest URL.
    save_path : str
        Destination path.

    Returns
    -------
    str | None
        The *save_path* on success, ``None`` on failure.
    """
    data = fetch_data_from_url(url)
    if data:
        try:
            return save_file(data, save_path)
        except OSError as exc:
            log.error("save_manifest_file: could not write to '%s': %s", save_path, exc)
            return None
    log.warning("save_manifest_file: nothing fetched from %s", url)
    return None


def fmt_size(n: float) -> str:
    """
    Format a byte count as a human-readable string.

    Examples
    --------
    >>> fmt_size(1536)
    '1.5 KB'
    >>> fmt_size(1073741824)
    '1.0 GB'
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_speed(bps: float) -> str:
    """
    Format a bytes-per-second value as ``"X.X MB/s"``.

    Returns ``"-- MB/s"`` when *bps* is zero or negative.
    """
    if bps <= 0:
        return "-- MB/s"
    return f"{fmt_size(int(bps))}/s"


def fmt_eta(seconds: float | None) -> str:
    """
    Format an ETA in seconds as ``"MM:SS"`` or ``"H:MM:SS"``.

    Returns ``"--:--"`` when *seconds* is ``None``.
    """
    if seconds is None:
        return "--:--"
    if seconds < 0:
        return "00:00"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def decompress_zstd(compressed: bytes) -> bytes:
    """
    Decompress *compressed* using the zstd algorithm.

    Parameters
    ----------
    compressed : bytes
        Raw zstd-compressed bytes.

    Returns
    -------
    bytes
        Decompressed output.
    """
    try:
        ctx = zstd.ZstdDecompressor()
        return ctx.stream_reader(compressed).read()
    except zstd.ZstdError as exc:
        raise ValueError(f"zstd decompression failed: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"decompress_zstd unexpected error: {exc}") from exc


def encode_path(path: str) -> str:
    """
    URL-encode each segment of *path* while preserving ``/`` separators.

    Parameters
    ----------
    path : str
        A slash-separated path string, e.g. ``"Riot Client/KeystoneFoundationLiveWin"``.

    Returns
    -------
    str
        URL-encoded path safe for use in GitHub Contents API requests.
    """
    return "/".join(quote(seg, safe="") for seg in path.split("/"))


def extract_id(url: Optional[str]) -> Optional[str]:
    """
    Extract a 16-character manifest ID from a CDN URL, file path, or bare ID.

    Parameters
    ----------
    url : str | None
        CDN URL (``…/releases/ABCDEF0123456789.manifest``),
        local file path, or a bare 16-hex-char string.

    Returns
    -------
    str | None
        Uppercase 16-char hex ID, or ``None`` if not found.
    """
    if not url:
        return None
    if url.startswith("http") or os.path.isfile(url):
        url = url.split("/")[-1].replace(".manifest", "").upper()
    return url.upper() if re.fullmatch(r"[0-9A-Fa-f]{16}", url) else None


def deep_getter(data: dict, keys: list[str | int] | str, default: Any = None) -> Any:
    """
    Safely traverse a nested dict/list using a key path.

    Parameters
    ----------
    data : dict
        Root container to traverse.
    keys : str | list[str | int]
        Single key or ordered list of keys/indices.
    default : Any
        Value returned when any key is missing or a type error occurs.

    Returns
    -------
    Any
        The resolved value, or *default* on any failure.

    Examples
    --------
    >>> deep_getter({"a": {"b": 42}}, ["a", "b"])
    42
    >>> deep_getter({}, ["x", "y"], default="fallback")
    'fallback'
    """
    if isinstance(keys, str):
        keys = [keys]
    target = data
    for key in keys:
        if target is None:
            return default
        try:
            target = target[key] if isinstance(key, int) else target.get(key)
        except (IndexError, TypeError, AttributeError):
            return default
    return target if target is not None else default


def resolve_platform(platform: Optional[str], default: str = "win") -> str:
    """
    Normalise a platform string to Riot's short form.

    Parameters
    ----------
    platform : str | None
        ``"windows"`` → ``"win"``  |  ``"macos"`` → ``"mac"``  |  anything else → *default*
    default : str
        Value returned when *platform* is unknown.

    Returns
    -------
    str
    """
    if platform == "windows":
        return "win"
    if platform == "macos":
        return "mac"
    return default
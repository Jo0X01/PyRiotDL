"""
PyRiotDL — modern CLI

    python -m PyRiotDL <command> [options]
"""

from __future__ import annotations

import logging
import sys
from typing import Annotated, Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn
)
from rich.table import Table
from rich.text import Text

out = Console()
err = Console(stderr=True)

app = typer.Typer(
    name="PyRiotDL",
    help="[bold cyan]PyRiotDL[/] — download and inspect Riot Games files",
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False
)

GameArg = Annotated[str, typer.Argument(help="Game key: [cyan]lol[/] · val · tft · lor · 2xko · wildrift · rc")]
RegionOpt = Annotated[Optional[str], typer.Option("--region", "-r", help="Region code, e.g. [cyan]NA1[/] (LoL) or [cyan]eu[/] (VALORANT)")]
VerboseOpt = Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")]

def _setup_log(verbose: bool) -> None:
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)-8s %(name)s — %(message)s",
            stream=sys.stderr
        )

def _get_game(key: str):
    from PyRiotDL.config import RiotConfig
    cfg = RiotConfig.get(key)
    if cfg is None:
        all_keys = [k for g in RiotConfig.all() for k in g.key]
        err.print(f"[red][ERROR][/] Unknown game [bold]{key!r}[/]. Valid keys: {', '.join(all_keys)}")
        raise typer.Exit(1)
    return cfg


def _parse_langs(raw: Optional[list[str]]) -> Optional[list[str]]:
    """
    Converts CLI --lang values to the list[str] | None convention:
      (omitted)        → [] — neutral/base files only
      --lang all       → None — every language
      --lang en_US ... → ["en_US", …]
    """
    if not raw:
        return []
    if len(raw) == 1 and raw[0].lower() == "all":
        return None
    return list(raw)


def _fmt(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _kv_grid(*rows: tuple[str, str]) -> Table:
    """Build a simple key → value grid (no borders)."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column(style="bold")
    for k, v in rows:
        grid.add_row(k, v)
    return grid

@app.command("games", help="List every supported game with its key aliases and regions.")
def cmd_games() -> None:
    from PyRiotDL.config import RiotConfig

    t = Table(box=box.ROUNDED, highlight=True)
    t.add_column("Game",           style="bold cyan",   no_wrap=True)
    t.add_column("Key aliases",    style="yellow")
    t.add_column("Default region", style="green",       width=16)
    t.add_column("Platform",       style="dim",         width=10)

    for g in RiotConfig.all():
        t.add_row(
            g.name,
            " · ".join(g.key),
            g.region or "[dim]global[/]",
            g.platform or "windows",
        )

    out.print(Panel(t, title="[bold]Supported Games", border_style="cyan"))

@app.command("regions", help="List valid region codes for a game.")
def cmd_regions(game: GameArg) -> None:
    cfg = _get_game(game)

    if not cfg.regions:
        out.print(f"[yellow]⚠[/]  [bold]{cfg.name}[/] has no region selection (global).")
        raise typer.Exit(0)

    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("Code", style="bold cyan", width=10)
    t.add_column("Name", style="white")
    t.add_column("Default", width=9)

    for code, name in cfg.regions.items():
        t.add_row(code, name, "[green]✓[/]" if code == cfg.region else "")

    out.print(Panel(t, title=f"[bold]{cfg.name}[/] Regions", border_style="cyan"))

@app.command("history", help="Show version history from the [link=https://github.com/Morilli/riot-manifests]Morilli/riot-manifests[/link] archive.")
def cmd_history(
    game:         GameArg,
    region:       RegionOpt = None,
    limit:        Annotated[int,  typer.Option("--limit", "-n", help="Max versions to show")] = 20,
    no_hotfixes:  Annotated[bool, typer.Option("--no-hotfixes", help="Skip hotfix releases")] = False,
    patch_filter: Annotated[Optional[str], typer.Option("--patch", help="Restrict to one patch cycle, e.g. [cyan]15.04[/]")] = None,
    verbose:      VerboseOpt = False,
) -> None:
    _setup_log(verbose)
    from PyRiotDL.history import RiotManifestHistory

    cfg = _get_game(game)
    if region:
        try:
            cfg = cfg.copy_with(region=region)
        except ValueError as exc:
            err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    with out.status(f"[cyan]Fetching history for [bold]{cfg.name}[/] …"):
        versions = RiotManifestHistory(cfg).history(
            limit=limit,
            include_hotfixes=not no_hotfixes,
            patch_filter=patch_filter,
        )

    if not versions:
        out.print(f"[yellow]⚠[/]  No versions found for [bold]{cfg.name}[/] region=[cyan]{cfg.region or 'global'}[/]")
        raise typer.Exit(0)

    t = Table(box=box.SIMPLE_HEAD, highlight=True)
    t.add_column("#",            style="dim",          width=4)
    t.add_column("Version",      style="bold yellow",  min_width=22)
    t.add_column("Patch",        style="cyan",         width=8)
    t.add_column("Kind",         width=8)
    t.add_column("Manifest ID",  style="dim green",    width=18)
    t.add_column("URL",          style="dim",          overflow="fold")

    for i, v in enumerate(versions, 1):
        kind = "[red]hotfix[/]" if v.is_hotfix else "[green]patch[/]"
        t.add_row(str(i), v.version, v.patch_number or "—", kind, v.manifest_id, v.url)

    out.print(Panel(
        t,
        title=f"[bold]{cfg.name}[/] history · region=[cyan]{cfg.region or 'global'}[/]  ({len(versions)} entries)",
        border_style="cyan",
    ))
    out.print(f"[dim]Archive: {RiotManifestHistory.CREDIT}[/]")

@app.command("latest", help="Print the latest live manifest CDN URL for a game.")
def cmd_latest(
    game:    GameArg,
    region:  RegionOpt = None,
    macos:   Annotated[bool, typer.Option("--macos", help="Request macOS manifest")] = False,
    verbose: VerboseOpt = False,
) -> None:
    _setup_log(verbose)
    cfg = _get_game(game)
    if region:
        try:
            cfg = cfg.copy_with(region=region)
        except ValueError as exc:
            err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    with out.status("[cyan]Fetching latest manifest URL …"):
        try:
            url = cfg.dispatch_manifest_url(support_macos=macos)
        except Exception as exc:
            err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    if not url:
        err.print(f"[red]✗[/] No manifest URL returned for [bold]{cfg.name}[/]")
        raise typer.Exit(1)

    out.print(Panel(
        f"[bold green]{url}[/]",
        title=f"[bold]{cfg.name}[/] · [cyan]{cfg.region or 'global'}[/] · {'macOS' if macos else 'Windows'}",
        border_style="green",
    ))

@app.command("check-update", help="Check if a newer version is available (no download).")
def cmd_check_update(
    game:    GameArg,
    current: Annotated[str, typer.Argument(help="Installed .manifest path, URL, or 16-hex ID")],
    region:  RegionOpt = None,
    macos:   Annotated[bool, typer.Option("--macos")] = False,
    verbose: VerboseOpt = False,
) -> None:
    _setup_log(verbose)
    from PyRiotDL import PyRiotDL

    try:
        dl = PyRiotDL(game, region=region)
    except ValueError as exc:
        err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    with out.status("[cyan]Checking for updates …"):
        try:
            status = dl.check_for_update(current, mac_os=macos)
        except Exception as exc:
            err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    rows = [
        ("Game",    dl.cfg.name),
        ("Region",  dl.cfg.region or "global"),
        ("Current", f"[cyan]{status.current_id or '—'}[/]"),
        ("Latest",  f"[green]{status.latest_id or '—'}[/]"),
    ]

    if not status.latest_url:
        rows.append(("Status", "[red]Could not fetch latest version[/]"))
        out.print(Panel(_kv_grid(*rows), title="Update Check", border_style="red"))
        raise typer.Exit(1)
    elif status.has_update:
        rows.append(("Status", "[yellow bold]⬆  Update available[/]"))
        out.print(Panel(_kv_grid(*rows), title="Update Check", border_style="yellow"))
    else:
        rows.append(("Status", "[green bold]✓  Up to date[/]"))
        out.print(Panel(_kv_grid(*rows), title="Update Check", border_style="green"))

@app.command("info", help="Show metadata decoded from a local or remote manifest.")
def cmd_info(
    manifest: Annotated[str, typer.Argument(help="Local file path, CDN URL, or 16-hex manifest ID")],
    verbose:  VerboseOpt = False,
) -> None:
    _setup_log(verbose)
    from PyRiotDL.decoder import ManifestDecoder

    with out.status("[cyan]Loading manifest …"):
        try:
            m = ManifestDecoder(manifest).manifest
        except ValueError as exc:
            err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)
        except Exception as exc:
            err.print(f"[red]✗[/] Could not read manifest: {exc}"); raise typer.Exit(1)

    total_size   = sum(f.size for f in m.files)
    total_chunks = sum(len(b.chunks) for b in m.bundles)

    grid = _kv_grid(
        ("Manifest ID", f"[green]{m.manifest_id}[/]"),
        ("Version",     m.version),
        ("Files",       f"{len(m.files):,}"),
        ("Bundles",     f"{len(m.bundles):,}"),
        ("Chunks",      f"{total_chunks:,}"),
        ("Total size",  _fmt(total_size)),
        ("Languages",   str(len(m.languages))),
    )
    out.print(Panel(grid, title="[bold]Manifest Info", border_style="cyan"))

    if m.languages:
        lang_t = Table(box=box.SIMPLE, show_header=True)
        lang_t.add_column("Bit",      style="dim",    width=5)
        lang_t.add_column("Language", style="yellow")
        for lang in m.languages:
            lang_t.add_row(str(lang.lang_id), lang.name)
        out.print(lang_t)

@app.command("lang-sizes", help="Show per-language download size breakdown for a game.")
def cmd_lang_sizes(
    game:     GameArg,
    region:   RegionOpt = None,
    manifest: Annotated[Optional[str], typer.Option("--manifest", help="Specific manifest (default: fetch latest)")] = None,
    verbose:  VerboseOpt = False,
) -> None:
    _setup_log(verbose)
    from PyRiotDL import PyRiotDL

    try:
        dl = PyRiotDL(game, region=region)
    except ValueError as exc:
        err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    with out.status("[cyan]Calculating language sizes …"):
        sizes = dl.language_sizes(manifest=manifest)

    if not sizes:
        out.print("[yellow]⚠[/]  No language data available.")
        raise typer.Exit(0)

    max_bytes = max(ls.total_bytes for ls in sizes) or 1

    t = Table(box=box.ROUNDED, highlight=True)
    t.add_column("Language", style="bold yellow", width=14)
    t.add_column("Files",    justify="right",     width=8)
    t.add_column("Size",     justify="right",     width=12)
    t.add_column("",         min_width=24)

    for ls in sizes:
        bar_len = int(ls.total_bytes / max_bytes * 24)
        bar     = Text("█" * bar_len + "░" * (24 - bar_len), style="cyan")
        t.add_row(ls.name, f"{ls.file_count:,}", _fmt(ls.total_bytes), bar)

    out.print(Panel(t, title=f"[bold]{dl.cfg.name}[/] Language Sizes", border_style="cyan"))

@app.command("build", help="Parse a manifest and export its file plan (JSON / TXT / URLs) without downloading.")
def cmd_build(
    manifest: Annotated[str,  typer.Argument(help="Local file path or CDN URL")],
    game:     Annotated[Optional[str], typer.Option("--game", "-g", help="Game key — auto-resolves CDN")] = None,
    cdn:      Annotated[Optional[str], typer.Option("--cdn",        help="CDN hostname override")] = None,
    lang:     Annotated[Optional[list[str]], typer.Option("--lang", help="Languages. [cyan]all[/] = every locale.")] = None,
    platform: Annotated[Optional[str], typer.Option("--platform",   help="Platform pseudo-language (windows/mac)")] = None,
    filter_:  Annotated[Optional[list[str]], typer.Option("--filter", help="Include-only glob filters")] = None,
    json_out: Annotated[Optional[str], typer.Option("--json",        help="Save full plan as JSON")] = None,
    txt_out:  Annotated[Optional[str], typer.Option("--txt",         help="Save human-readable summary")] = None,
    urls_out: Annotated[Optional[str], typer.Option("--urls",        help="Save unique bundle URLs")] = None,
    verbose:  VerboseOpt = False,
) -> None:
    _setup_log(verbose)
    from PyRiotDL.builder import ManifestBuilder

    if not any([json_out, txt_out, urls_out]):
        err.print("[red]✗[/] Specify at least one output: [cyan]--json[/], [cyan]--txt[/], or [cyan]--urls[/]")
        raise typer.Exit(1)

    resolved_cdn = cdn or (_get_game(game).cdn if game else None)
    languages    = _parse_langs(lang)

    with out.status("[cyan]Loading manifest …"):
        try:
            mb = ManifestBuilder(manifest, cdn=resolved_cdn)
        except (ValueError, Exception) as exc:
            err.print(f"[red]✗[/] Could not load manifest: {exc}"); raise typer.Exit(1)

    with out.status("[cyan]Building file plan …"):
        try:
            plan = mb.build(
                languages=languages,
                platform=platform,
                json_path=json_out,
                txt_path=txt_out,
                urls_path=urls_out,
                glob_filter=filter_ or None,
            )
        except (OSError, ValueError) as exc:
            err.print(f"[red]✗[/] Build failed: {exc}"); raise typer.Exit(1)

    chunks  = sum(len(f.chunks) for f in plan)
    bundles = len({c.bundle_id for f in plan for c in f.chunks})

    rows: list[tuple[str, str]] = [
        ("Files",   f"[green]{len(plan):,}[/]"),
        ("Chunks",  f"[green]{chunks:,}[/]"),
        ("Bundles", f"[green]{bundles:,}[/]"),
        ("Size",    f"[green]{_fmt(sum(f.size for f in plan))}[/]"),
    ]
    if json_out: rows.append(("JSON →", json_out))
    if txt_out:  rows.append(("TXT →",  txt_out))
    if urls_out: rows.append(("URLs →", urls_out))

    out.print(Panel(_kv_grid(*rows), title="[bold]Plan Built", border_style="green"))

@app.command("diff", help="Compare two manifests — show what was added, removed, or modified.")
def cmd_diff(
    old_manifest: Annotated[str, typer.Argument(help="Old manifest (file path or URL)")],
    new_manifest: Annotated[str, typer.Argument(help="New manifest (file path or URL)")],
    game:   Annotated[Optional[str], typer.Option("--game", "-g", help="Game key — resolves CDN")] = None,
    cdn:    Annotated[Optional[str], typer.Option("--cdn",        help="CDN hostname override")] = None,
    lang:   Annotated[Optional[list[str]], typer.Option("--lang", help="Languages")] = None,
    detail: Annotated[bool, typer.Option("--detail", "-d",        help="Print individual file paths")] = False,
    verbose: VerboseOpt = False,
) -> None:
    _setup_log(verbose)
    from PyRiotDL.builder import ManifestBuilder
    from PyRiotDL.models import DiffResult

    resolved_cdn = cdn or (_get_game(game).cdn if game else None)
    languages    = _parse_langs(lang)

    with out.status("[cyan]Loading manifests …"):
        try:
            old_plan = ManifestBuilder(old_manifest, cdn=resolved_cdn).build(languages=languages)
            new_plan = ManifestBuilder(new_manifest, cdn=resolved_cdn).build(languages=languages)
        except Exception as exc:
            err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    diff = DiffResult(old_plan=old_plan, new_plan=new_plan)
    delta_sign = "+" if diff.size_delta >= 0 else ""

    summary = _kv_grid(
        ("[green]+[/] Added",    f"{len(diff.added):,}  files  +{_fmt(sum(d.size for d in diff.added))}"),
        ("[red]−[/] Removed",    f"{len(diff.removed):,}  files  −{_fmt(sum(d.old_size for d in diff.removed))}"),
        ("[yellow]~[/] Modified", f"{len(diff.modified):,}  files  {_fmt(sum(abs(d.size_delta) for d in diff.modified))} changed"),
        ("[dim]=[/] Unchanged",  f"{len(diff.unchanged):,}  files"),
        ("[bold]Net delta[/]",   f"{delta_sign}{_fmt(diff.size_delta)}"),
    )
    out.print(Panel(summary, title="[bold]Manifest Diff", border_style="cyan"))

    if not detail:
        return

    def _show_section(title: str, entries, color: str, show_delta: bool = False) -> None:
        if not entries:
            return
        t = Table(box=box.SIMPLE, show_header=True)
        t.add_column("Path",  style="white",  overflow="fold")
        t.add_column("Size",  style=color,    justify="right", width=12)
        if show_delta:
            t.add_column("Delta", style="dim", justify="right", width=12)
        for d in entries:
            size = _fmt(d.size if d.size else d.old_size)
            if show_delta:
                sign = "+" if d.size_delta >= 0 else ""
                t.add_row(d.path, size, f"{sign}{_fmt(d.size_delta)}")
            else:
                t.add_row(d.path, size)
        out.print(Panel(t, title=f"[bold]{title}[/]", border_style=color))

    _show_section("Added",    diff.added,    "green")
    _show_section("Removed",  diff.removed,  "red")
    _show_section("Modified", diff.modified, "yellow", show_delta=True)

@app.command("download", help="Fresh install — download all game files from the latest manifest.")
def cmd_download(
    game:          GameArg,
    output:        Annotated[str, typer.Option("--output", "-o", help="Destination directory")],
    region:        RegionOpt = None,
    lang:          Annotated[Optional[list[str]], typer.Option("--lang", help="Languages. [cyan]all[/] = every locale. Default = neutral only.")] = None,
    platform:      Annotated[Optional[str], typer.Option("--platform", help="Platform override (windows/macos)")] = None,
    workers:       Annotated[int,  typer.Option("--workers",  "-w", help="Download threads")] = 8,
    retries:       Annotated[int,  typer.Option("--retries",       help="Retry attempts per chunk")] = 3,
    macos:         Annotated[bool, typer.Option("--macos",         help="Download macOS build")] = False,
    save_manifest: Annotated[Optional[str], typer.Option("--save-manifest", help="Save the fetched .manifest file")] = None,
    verbose:       VerboseOpt = False,
) -> None:
    _setup_log(verbose)
    from PyRiotDL import PyRiotDL
    from PyRiotDL.builder import ManifestBuilder
    from PyRiotDL.downloader import GameDownloader
    from PyRiotDL.helper import save_manifest_file

    try:
        dl = PyRiotDL(game, region=region, platform=platform)
    except ValueError as exc:
        err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    languages = _parse_langs(lang)

    with out.status(f"[cyan]Resolving latest manifest for [bold]{dl.cfg.name}[/] …"):
        url = dl.latest_manifest_url(mac_os=macos)
        if not url:
            err.print(f"[red]✗[/] Could not resolve manifest URL for {dl.cfg.name}")
            raise typer.Exit(1)

    with out.status("[cyan]Building file plan …"):
        try:
            plan = ManifestBuilder(url, dl.cfg.cdn).build(languages)
        except Exception as exc:
            err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    if save_manifest:
        save_manifest_file(url, save_manifest)
        out.print(f"[dim]Manifest saved → {save_manifest}[/]")

    if not plan:
        out.print("[yellow]⚠[/]  Empty plan — nothing to download.")
        raise typer.Exit(0)

    total_bytes = sum(c.compressed_size for fp in plan for c in fp.chunks)
    out.print(Panel(
        _kv_grid(
            ("Game",    dl.cfg.name),
            ("Region",  dl.cfg.region or "global"),
            ("Files",   f"{len(plan):,}"),
            ("Size",    _fmt(total_bytes) + " compressed"),
        ),
        title="[bold]Starting Download",
        border_style="cyan",
    ))

    _run_rich_download(GameDownloader(plan), output, workers, retries)

@app.command("update", help="Patch an existing installation — only downloads changed chunks.")
def cmd_update(
    game:    GameArg,
    current: Annotated[str, typer.Option("--current", "-c", help="Currently installed .manifest path or URL")],
    output:  Annotated[str, typer.Option("--output",  "-o", help="Game directory to patch")],
    region:  RegionOpt = None,
    lang:    Annotated[Optional[list[str]], typer.Option("--lang", help="Languages. Default = neutral only.")] = None,
    workers: Annotated[int,  typer.Option("--workers", "-w")] = 8,
    retries: Annotated[int,  typer.Option("--retries")] = 3,
    macos:   Annotated[bool, typer.Option("--macos")] = False,
    verbose: VerboseOpt = False,
) -> None:
    _setup_log(verbose)
    from PyRiotDL import PyRiotDL
    from PyRiotDL.builder import ManifestBuilder
    from PyRiotDL.downloader import GameDownloader

    languages = _parse_langs(lang)

    try:
        dl = PyRiotDL(game, region=region)
    except ValueError as exc:
        err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    with out.status("[cyan]Loading manifests …"):
        try:
            old_plan = ManifestBuilder(current, dl.cfg.cdn).build(languages)
            new_url  = dl.latest_manifest_url(mac_os=macos)
            if not new_url:
                err.print("[red]✗[/] Could not fetch latest manifest URL"); raise typer.Exit(1)
            new_plan = ManifestBuilder(new_url, dl.cfg.cdn).build(languages)
        except Exception as exc:
            err.print(f"[red]✗[/] {exc}"); raise typer.Exit(1)

    downloader = GameDownloader(new_plan, old_plan=old_plan, game_dir=output)

    out.print(Panel(
        _kv_grid(
            ("[green]Skip[/]",     f"{downloader.chunks_to_skip:,} chunks (unchanged)"),
            ("[cyan]Resume[/]",    f"{downloader.chunks_to_resume:,} chunks (verified on disk)"),
            ("[yellow]Download[/]",f"{downloader.chunks_to_dl:,} chunks  ({_fmt(downloader.bytes_to_dl)} compressed)"),
        ),
        title=f"[bold]{dl.cfg.name}[/] Update Diff",
        border_style="cyan",
    ))

    if downloader.chunks_to_dl == 0:
        out.print("[bold green]✓[/]  Already up to date — nothing to download.")
        raise typer.Exit(0)

    _run_rich_download(downloader, output, workers, retries)

def _run_rich_download(downloader, output_dir: str, workers: int, retries: int) -> None:
    """
    Drive GameDownloader with a Rich live progress bar instead of the
    built-in BarStyle renderer.
    """
    import queue
    import threading
    import time
    from collections import defaultdict

    import requests
    import zstandard as zstd

    from PyRiotDL.models import FilePlan, PlanChunk

    work = downloader._to_download
    if not work:
        out.print("[bold green]✓[/]  Nothing to download — all chunks already up to date.")
        return

    downloader._allocate_files(downloader.new_plan, output_dir)

    done_bytes = 0
    done_count = 0
    fail_count = 0
    lock       = threading.Lock()
    file_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    q: queue.Queue[tuple[FilePlan, PlanChunk]] = queue.Queue()
    for item in work:
        q.put(item)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=32),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=out,
        transient=False,
    ) as rich_progress:
        task = rich_progress.add_task(
            f"Downloading {len(work):,} chunks",
            total=downloader.bytes_to_dl,
        )

        def worker() -> None:
            nonlocal done_bytes, done_count, fail_count
            session      = requests.Session()
            session.headers["User-Agent"] = "RiotClient/99.0.0.9999999 riot-client"
            decompressor = zstd.ZstdDecompressor()

            while True:
                try:
                    fp, chunk = q.get_nowait()
                except queue.Empty:
                    return

                data = None
                for attempt in range(1, retries + 1):
                    try:
                        data = downloader._fetch_chunk(chunk, session, decompressor)
                        break
                    except Exception as exc:
                        logging.getLogger(__name__).warning(
                            "Chunk %s attempt %d/%d: %s", chunk.chunk_id, attempt, retries, exc
                        )
                        if attempt < retries:
                            time.sleep(0.4 * attempt)

                wrote_ok = False
                if data is not None:
                    try:
                        with file_locks[fp.path]:
                            downloader._write_chunk(data, fp, chunk, output_dir)
                        wrote_ok = True
                    except Exception as exc:
                        logging.getLogger(__name__).error(
                            "Write failed chunk %s: %s", chunk.chunk_id, exc
                        )

                with lock:
                    if wrote_ok:
                        done_count += 1
                        done_bytes += chunk.compressed_size
                        rich_progress.advance(task, chunk.compressed_size)
                    else:
                        fail_count += 1

                q.task_done()

        threads = [
            threading.Thread(target=worker, daemon=True)
            for _ in range(min(workers, len(work)))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # ── completion panel ──
    border = "red" if fail_count else "green"
    icon   = "✗" if fail_count else "✓"
    rows: list[tuple[str, str]] = [
        ("Downloaded", f"[green]{done_count:,}[/] chunks  ({_fmt(done_bytes)})"),
        ("Skipped",    f"[cyan]{downloader.chunks_to_skip:,}[/] chunks"),
        ("Resumed",    f"[cyan]{downloader.chunks_to_resume:,}[/] chunks"),
    ]
    if fail_count:
        rows.append(("Failed", f"[red bold]{fail_count:,}[/] chunks"))

    out.print(Panel(_kv_grid(*rows), title=f"[bold]{icon}  Download Complete[/]", border_style=border))

    if fail_count:
        raise typer.Exit(1)

def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        err.print("\n[yellow]Interrupted.[/]")
        raise typer.Exit(130)

if __name__ == "__main__":
    main()
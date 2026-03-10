<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=D0021B&height=200&section=header&text=PyRiotDL&fontSize=80&fontColor=fff&animation=fadeIn&fontAlignY=38&desc=Riot%20Games%20Files%20Downloader&descAlignY=60&descAlign=50" width="100%"/>

<br/>

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-GPLv3-D0021B?style=for-the-badge)](LICENSE)
[![PyPI](https://img.shields.io/badge/PyPI-PyRiotDL-yellow?style=for-the-badge&logo=pypi&logoColor=white)](https://pypi.org/project/PyRiotDL)

<br/>

*A Python library & CLI for downloading, inspecting, and patching Riot Games files using RMAN manifests.*

<br/>

[**Getting Started**](#-installation) · [**Python API**](#-python-api) · [**CLI**](#%EF%B8%8F-cli) · [**Examples**](#-examples)

</div>

---

## 🎮 Supported Games

| Game | Keys | CDN |
|:---|:---|:---|
| **League of Legends** | `lol` `league` | `lol.secure.dyn.riotcdn.net` |
| **Teamfight Tactics** | `tft` | shares LoL CDN |
| **VALORANT** | `val` `valorant` | `valorant.secure.dyn.riotcdn.net` |
| **Legends of Runeterra** | `lor` `runeterra` `bacon` | `bacon.secure.dyn.riotcdn.net` |
| **2XKO** | `2xko` `ko2` | `lion.secure.dyn.riotcdn.net` |
| **Wild Rift** | `wildrift` `wr` | `wildrift.secure.dyn.riotcdn.net` |
| **Riot Client** | `rc` `riotclient` | `ks-foundation.secure.dyn.riotcdn.net` |

---

## ✨ What It Does

- **Manifest decoding** — parse Riot's binary RMAN format via a pure-Python FlatBuffer reader, no external schema needed
- **Multi-threaded downloads** — parallel HTTP Range requests + zstd decompression, writing chunks directly to pre-allocated files
- **Smart diffing** — compare old vs. new manifests and download only what changed
- **On-disk resume** — verify existing files and skip chunks already fully written
- **Version history** — browse every past patch via the [Morilli/riot-manifests](https://github.com/Morilli/riot-manifests) community archive
- **Glob extraction** — pull specific files with pattern filters like `ShooterGame/Content/**`
- **Language-aware** — bitmask-based locale filtering; download just the voice packs you need
- **Rich CLI** — beautiful terminal output with live progress bars, tables, and panels

---

## 📦 Installation

```bash
git clone https://github.com/Jo0x01/PyRiotDL.git
cd PyRiotDL
pip install .
```

> Requires **Python 3.10+**

**Dependencies:** `requests` · `zstandard` · `xxhash` · `typer` · `rich` · `certifi`

---

## 🐍 Python API

### Initialize

```python
from pyriotdl import PyRiotDL

dl = PyRiotDL("lol", region="NA1")
dl = PyRiotDL("val", region="eu")
dl = PyRiotDL("tft", region="EUW1")

# Using a GameConfig directly
dl = PyRiotDL(PyRiotDL.VALORANT.copy_with(region="na"))
```

Enable logging:

```python
import logging
PyRiotDL.setup_logging(level=logging.INFO)  # or logging.DEBUG
```

---

### `install()` — Fresh Install

Download a full game from scratch.

```python
progress = dl.install(
    output_dir    = "./LeagueOfLegends",
    languages     = ["en_US"],   # see Language Filtering below
    workers       = 16,          # parallel threads
    retries       = 3,
    save_manifest = "./lol.manifest",  # save for future updates
)
```

---

### `update()` — Patch Existing Install

Only downloads chunks that changed since the installed version.

```python
progress = dl.update(
    current            = "./lol.manifest",   # path or CDN URL
    output_dir         = "./LeagueOfLegends",
    languages          = ["en_US"],
    save_manifest_path = "./lol.manifest",   # overwrite with new version
)
```

---

### `repair()` — Verify & Fix Corrupt Files

Checks what's on disk and re-downloads anything missing or incomplete.

```python
progress = dl.repair(
    output_dir   = "./LeagueOfLegends",
    manifest_src = "./lol.manifest",   # omit to use latest from API
    languages    = ["en_US"],
    workers      = 8,
)
```

---

### `diff()` — Compare Two Versions

```python
result = dl.diff(old="v1.manifest", new="v2.manifest")

print(f"Added    {len(result.added):>5} files")
print(f"Removed  {len(result.removed):>5} files")
print(f"Modified {len(result.modified):>5} files")
print(f"Same     {len(result.unchanged):>5} files")

# Inspect individual changes
for f in result.modified:
    print(f"  ~ {f.path}  ({f.size_delta:+} bytes)")
```

---

### `extract()` — Download Specific Files

Pull only the files you care about using glob patterns.

```python
# Single pattern
progress = dl.extract(
    output_dir     = "./Assets",
    pattern_filter = "ShooterGame/Content/Characters/**",
    languages      = ["en_US"],
)

# Multiple patterns
progress = dl.extract(
    output_dir     = "./Assets",
    pattern_filter = ["**/*.pak", "**/*.uasset"],
)
```

---

### `history()` — Version History

Browse past releases from the community archive.

```python
versions = dl.history(
    limit            = 20,
    include_hotfixes = False,
    patch_filter     = "15.04",   # restrict to one patch cycle
)

for v in versions:
    print(f"[{v.kind}]  {v.version:<28}  {v.manifest_id}  {v.url}")
```

Each `ManifestVersion` has:

| Property | Type | Description |
|:---|:---|:---|
| `manifest_id` | `str` | 16-char hex ID |
| `version` | `str` | Full version string e.g. `15.04.01.2352000` |
| `url` | `str` | CDN manifest URL |
| `is_hotfix` | `bool` | True if hotfix segment > 0 |
| `patch_number` | `str` | Short label e.g. `"15.04"` |
| `kind` | `str` | `"patch"` or `"hotfix"` |

---

### `check_for_update()` — Update Check

```python
status = dl.check_for_update(current="./lol.manifest")

if status.has_update:
    print(f"Update available: {status.current_id} → {status.latest_id}")
else:
    print("Already up to date.")
```

---

### `calculate_download_size()` — Pre-flight Estimate

Get size info before committing to a download.

```python
info = dl.calculate_download_size(
    languages    = ["en_US"],
    game_dir     = "./LeagueOfLegends",
    old_manifest = "./lol.manifest",
)

print(f"Files:        {info.total_files:,}")
print(f"To download:  {info.compressed_to_dl / 1e9:.2f} GB")
print(f"Skipped:      {info.chunks_unchanged:,} chunks  (unchanged)")
print(f"On disk:      {info.chunks_on_disk:,} chunks  (already present)")
```

---

### `language_sizes()` — Per-Language Breakdown

```python
for lang in dl.language_sizes():
    print(f"{lang.name:<14}  {lang.file_count:>5} files  {lang.total_bytes / 1e9:.2f} GB")
```

---

### `dump()` — Export Manifest Data

Inspect a manifest without downloading anything.

```python
plan = dl.dump(
    manifest  = "./lol.manifest",   # omit to fetch latest
    languages = ["en_US"],
    json_path = "plan.json",
    txt_path  = "summary.txt",
    urls_path = "bundle_urls.txt",
)

print(f"{len(plan)} files in plan")
```

---

## 🌍 Language Filtering

| Value | What gets downloaded |
|:---|:---|
| `[]` *(default)* | Language-neutral base files only — no voice packs |
| `None` | Everything — all locales, largest possible download |
| `["en_US"]` | Base files + English voice/text |
| `["en_US", "ar_AE"]` | Base files + English + Arabic |


---

## 🖥️ CLI

```
pyriotdl <command> [options]
```

| Command | Description |
|:---|:---|
| `games` | List every supported game and its key aliases |
| `regions <game>` | Show valid region codes for a game |
| `latest <game>` | Print the latest live manifest CDN URL |
| `history <game>` | Browse version history from the community archive |
| `check-update <game> <manifest>` | Check if an update is available |
| `info <manifest>` | Show metadata from a local or remote manifest |
| `lang-sizes <game>` | Per-language download size breakdown |
| `build <manifest>` | Parse a manifest and export JSON / TXT / URLs |
| `diff <old> <new>` | Compare two manifests |
| `download <game>` | Fresh install |
| `update <game>` | Incremental patch |

### Examples

```bash
# List all supported games
pyriotdl games

# Valid regions for LoL
pyriotdl regions lol

# Latest VALORANT manifest URL
pyriotdl latest val --region eu

# Last 10 LoL patches, no hotfixes
pyriotdl history lol --region EUW1 --limit 10 --no-hotfixes

# Check if an update is available
pyriotdl check-update lol ./lol.manifest --region NA1

# Decode manifest metadata
pyriotdl info ./lol.manifest

# Language pack sizes
pyriotdl lang-sizes val --region eu

# Export file plan without downloading
pyriotdl build ./lol.manifest --game lol --lang en_US --json plan.json --urls urls.txt

# Compare two patch versions
pyriotdl diff v1.manifest v2.manifest --game lol --detail

# Download LoL (English, 16 threads)
pyriotdl download lol --output ./LoL --region EUW1 --lang en_US --workers 16

# Patch an existing install
pyriotdl update lol --current ./lol.manifest --output ./LoL --region EUW1
```

> Every command supports `--verbose` / `-v` for debug output and `--help` for full options.

---

## 💡 Examples

<details>
<summary><b>Download VALORANT (English only)</b></summary>

```python
from pyriotdl import PyRiotDL

dl = PyRiotDL("val", region="eu")
dl.install(output_dir="./VALORANT", languages=["en_US"], workers=16)
```
</details>

<details>
<summary><b>Get a specific historical patch</b></summary>

```python
from pyriotdl import PyRiotDL
from pyriotdl.builder import ManifestBuilder

dl = PyRiotDL("lol", region="EUW1")

versions = dl.history(patch_filter="15.04", include_hotfixes=False)
target = versions[0]
print(f"Patch {target}")
```
</details>

<details>
<summary><b>Check download size before committing</b></summary>

```python
from pyriotdl import PyRiotDL

dl   = PyRiotDL("lol", region="EUW1")
info = dl.calculate_download_size(languages=["en_US"])

print(f"Install size: {info.total_size / 1e9:.1f} GB")
print(f"To download:  {info.compressed_to_dl / 1e9:.1f} GB compressed")
```
</details>

<details>
<summary><b>Extract only VALORANT character assets</b></summary>

```python
from pyriotdl import PyRiotDL

dl = PyRiotDL("val", region="eu")
dl.extract(
    output_dir     = "./Characters",
    pattern_filter = "ShooterGame/Content/Characters/**",
    languages      = ["en_US"],
    workers        = 8,
)
```
</details>

<details>
<summary><b>Export full file list for datamining</b></summary>

```python
from pyriotdl import PyRiotDL

dl = PyRiotDL("lol")
dl.dump(
    languages = None,           # all locales
    json_path = "lol_all.json",
    urls_path = "bundles.txt",
)
```
</details>

---

## 🙏 Credits

Version history powered by the community-maintained [**Morilli/riot-manifests**](https://github.com/Morilli/riot-manifests) archive.

---

<div align="center">

**PyRiotDL is not affiliated with or endorsed by Riot Games.**
All game assets and manifest data belong to their respective owners.

<img src="https://capsule-render.vercel.app/api?type=waving&color=D0021B&height=100&section=footer" width="100%"/>

</div>

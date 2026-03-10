from setuptools import setup

__author__ = "Jo0x01"
__pkg_name__ = "PyRiotDL"
__version__ = "1.0.0"
__desc__ = "PyRiotDL is Python library and CLI tool for downloading and inspecting Riot Games files using RMAN manifest-based patching. Supports League of Legends, VALORANT, TFT, Legends of Runeterra, 2XKO, Wild Rift, and the Riot Client."

with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

setup(
    name=__pkg_name__,
    version=__version__,
    packages=[__pkg_name__],
    license='GNU',
    description=__desc__,
    author=__author__,
    long_description=long_description,
    long_description_content_type='text/markdown',
    url="https://github.com/Jo0X01/PyRiotDL",
    py_modules=["PyRiotDL"],
    install_requires=[
        "xxhash==3.6.0",
        "requests==2.32.5",
        "zstandard==0.25.0",
        "certifi==2026.2.25",
        "typer==0.24.1"
    ],
    entry_points={
        "console_scripts": [
            "pyriotdl=PyRiotDL.__main__:main",
            "riotdl=PyRiotDL.__main__:main",
            "pyr-dl=PyRiotDL.__main__:main",
        ]
    },
    keywords="anime, downloader, cli, Anime3rb, video, download, logging, scraper, automation, command-line, python, episodes, series, entertainment, media, streaming, batch-download, high-quality, fast, reliable, color-output, multi-resolution, anime-collection, media-downloader, web-scraper, terminal-tool, open-source",
    classifiers=[
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
        "Topic :: Games/Entertainment",
        "Topic :: Software Development :: Libraries :: Application Frameworks"
    ],
    python_requires=">=3.10",
)
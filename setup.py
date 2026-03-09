from setuptools import setup, find_packages

__author__ = "Jo0x01"
__pkg_name__ = "PyRiotDL"
__version__ = "1.0.0"
__desc__ = (
    "PyRiotDL is a Python library and CLI tool for downloading and inspecting "
    "Riot Games files using RMAN manifest-based patching. Supports League of Legends, "
    "VALORANT, TFT, Legends of Runeterra, 2XKO, Wild Rift, and the Riot Client."
)

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name=__pkg_name__,
    version=__version__,
    packages=find_packages(),
    license="GPL-3.0-only",
    description=__desc__,
    author=__author__,
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Jo0x01/PyRiotDL",
    project_urls={
        "Bug Tracker": "https://github.com/Jo0x01/PyRiotDL/issues",
        "Source Code": "https://github.com/Jo0x01/PyRiotDL",
    },
    install_requires=[
        "xxhash>=3.4.0",
        "requests>=2.31.0",
        "zstandard>=0.21.0",
        "certifi>=2024.1.1",
        "typer>=0.9.0",
        "rich>=13.0.0",
    ],
    extras_require={
        "gui": [
            "customtkinter>=5.2.0",
        ],
        "dev": [
            "pytest>=7.0",
            "twine>=4.0",
            "build>=1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "pyriotdl=PyRiotDL.__main__:main",
            "riotdl=PyRiotDL.__main__:main",
            "pyr-dl=PyRiotDL.__main__:main",
        ]
    },
    keywords=[
        "riot-games", "manifest", "rman", "downloader", "cli",
        "league-of-legends", "valorant", "tft", "wild-rift",
        "legends-of-runeterra", "2xko", "riot-client",
        "patching", "cdn", "flatbuffer",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Topic :: Games/Entertainment",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Utilities",
    ],
    python_requires=">=3.10",
)
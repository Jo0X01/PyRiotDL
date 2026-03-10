"""
Riot Games metadata , all games, regions, and API endpoints.
"""

from __future__ import annotations
import dataclasses
from typing import Optional
from pyriotdl.helper import deep_getter, fetch_data_from_url

@dataclasses.dataclass
class GameConfig:
    """
    Configuration for one Riot game

    Fields
    ------
    key       : list of lookup aliases (case-insensitive)
    name      : human readable display name
    cdn       : CDN hostname used for bundle/manifest downloads
    region    : default region code  "NA1" | "na" | None (global)
    regions   : all valid regions as {code: description}
                empty dict = no region selection (Riot Client)
    platform  : API platform override
    namespace : clientconfig keystone namespace
    patchline : clientconfig patchline key
    sieve_id  : product ID used in Sieve API URL
    want_type : artifact type filter for Sieve responses
    """

    key: list[str]
    name: str
    cdn: str
    region: Optional[str]
    regions: dict[str, str]
    repo_folder: Optional[str] = None
    platform: Optional[str] = None
    namespace: Optional[str] = None
    patchline: str= "live"
    sieve_id: Optional[str] = None
    want_type: Optional[str] = None

    @property
    def has_sieve(self) -> bool:
        """True if this game supports the Sieve API"""
        return self.sieve_id is not None

    @property
    def has_clientconfig(self) -> bool:
        """True if this game supports the clientconfig API"""
        return self.namespace is not None

    @property
    def is_global(self) -> bool:
        """True if this game has no region selection (e.g. Riot Client)."""
        return not self.regions

    @property
    def is_mobile(self) -> bool:
        """True if this is a mobile game (platform = android/ios)."""
        return self.platform in ("android", "ios")

    @property
    def bundle_base_url(self) -> str:
        """Base CDN URL for downloading .bundle files."""
        return f"https://{self.cdn}/channels/public/bundles"

    @property
    def release_base_url(self) -> str:
        """Base CDN URL for downloading .manifest files."""
        return f"https://{self.cdn}/channels/public/releases"

    def manifest_url(self, manifest_id: str) -> str:
        """Build the download URL for a specific manifest file."""
        return f"{self.release_base_url}/{manifest_id}.manifest"

    def bundle_url(self, bundle_id: str) -> str:
        """Build the download URL for a specific bundle file."""
        return f"{self.bundle_base_url}/{bundle_id}.bundle"

    def get_json_url(self, mac_os: bool = False) -> tuple[Optional[str], Optional[str]]:
        """
        Build the API request URLs for both Sieve and clientconfig.

        Args:
            mac_os: request the macOS manifest instead of Windows

        Returns:
            (sieve_url, clientconfig_url)
            Either value is None if that API is not supported for this game.

        Raises:
            ValueError if the current region is not valid for this game.
        """
        if self.regions and self.region not in self.regions:
            raise ValueError(
                f"Invalid region '{self.region}' for {self.name}. "
                f"Valid: {', '.join(self.regions.keys())}"
            )

        platform = self.platform if self.platform else ("macos" if mac_os else "windows")

        sieve_url = (
            f"https://sieve.services.riotcdn.net/api/v1/products/{self.sieve_id}"
            f"/version-sets/{self.region}"
            f"?q[platform]={platform}"
        ) if self.has_sieve else None

        clientconfig_url = None
        if self.has_clientconfig:
            if self.namespace == "keystone.self_update":
                clientconfig_url = (
                    f"https://clientconfig.rpg.riotgames.com/api/v1/config/public"
                    f"?version=99.0.0.9999999"
                    f"&patchline={self.patchline}"
                    f"&app=Riot+Client"
                    f"&namespace={self.namespace}"
                )
            else:
                clientconfig_url = f"https://clientconfig.rpg.riotgames.com/api/v1/config/public?namespace={self.namespace}"
        return sieve_url, clientconfig_url

    def get_content_from_json(self, mac_os: bool = False) -> dict:
        """
        Fetch JSON from the best available API for this game.

        Args:
            mac_os: request the macOS manifest instead of Windows

        Raises:
            ValueError if neither API returns a valid response.
        """
        sieve_url, clientconfig_url = self.get_json_url(mac_os)
        last_err = None
        for url in filter(None, [sieve_url, clientconfig_url]):
            try:
                return fetch_data_from_url(url, json=True)  # type: ignore
            except Exception as e:
                last_err = e
                continue
        raise ValueError(
            f"No valid API found for {self.name} in region {self.region}: {last_err}"
        )

    def is_valid_region(self, region: str) -> bool:
        """Check if a region code is valid for this game."""
        return region in self.regions

    def region_name(self, region: Optional[str] = None) -> Optional[str]:
        """
        Get the human readable name for a region code.

        Args:
            region: region code to look up. Uses current region if None.

        Returns:
            "North America" | None if not found.
        """
        r = region or self.region
        if r is None:
            return None
        return self.regions.get(r)

    def copy_with(self, region: Optional[str] = None, platform: Optional[str] = None) -> "GameConfig":
        """
        Return a copy of this config with a different region/platform.
        Does NOT mutate the original.

        Args:
            region  : region code  e.g. "EUW1" for LoL, "eu" for VALORANT
            platform: "windows" | "macos" | "android" | "ios"

        Returns:
            New GameConfig with the updated fields.
        """
        if region is None and platform is None:
            return self
        if region and self.regions and region not in self.regions:
            raise ValueError(
                f"Invalid region '{region}' for {self.name}. "
                f"Valid: {', '.join(self.regions.keys())}"
            )
        if region is None:
            region = self.region
        if platform is None:
            platform = self.platform
        return dataclasses.replace(self, region=region, platform=platform)

    def dispatch_manifest_url(self,data:Optional[dict]=None,support_macos:bool=False) -> Optional[str]:
        """
        Extract manifest URL from raw API JSON.
        Handles Riot Client, Sieve, and clientconfig response formats.
        """
        if not data:
            data = self.get_content_from_json(support_macos)
        
        if self.namespace == "keystone.self_update":
            return self._dispatch_riot_client(data)
        if self.has_sieve and "releases" in data:
            return self._dispatch_sieve_api(data)
        if self.has_clientconfig:
            return self._dispatch_clientconfig_api(data)
        raise ValueError("UnKnown Error API Response")

    def _dispatch_riot_client(self,data: dict):
        return data.get("keystone.self_update.manifest_url")

    def _dispatch_sieve_api(self,data:dict):
        for item in data.get("releases",[]):
            required_auth = deep_getter(item,["download","scd_required"],False)
            cpu_arch = deep_getter(item, ["release","labels","riot:cpu_arch","values",0],"?")
            artifact = deep_getter(item, ["release","labels","riot:artifact_type_id", "values", 0], "?")
            if required_auth or cpu_arch == "x86" or (self.want_type and artifact != self.want_type):
                continue
            return deep_getter(item,["download","url"])
        return None

    def _dispatch_clientconfig_api(self,data:dict):
        platform = self.platform[:3] if self.platform else "win"
        for top_key, top_value in data.items():
            if not top_key.startswith("keystone.") or not isinstance(top_value, dict):
                continue
            list_data = deep_getter(top_value,["platforms",platform,"configurations"],[])
            for config in list_data:
                url = deep_getter(config,"patch_url", "")
                shards = deep_getter(config,["valid_shards","live"], [])
                config_id = deep_getter(config,"id", "default")
                region = config_id
                if config_id == "default":
                    region = shards[0] if shards else "?"
                if self.is_global or region == self.region or self.region in shards:
                    return url
        return None


    def __str__(self):
        return f"GameConfig(name={self.name}, region={self.region}, cdn={self.cdn})"

    def __repr__(self):
        return self.__str__()
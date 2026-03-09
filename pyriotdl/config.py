from typing import Optional
from PyRiotDL.game import GameConfig

class RiotConfig:
    """
    Registry of all Riot game configurations.
    """

    LOL = GameConfig(
        key       = ["lol", "league", "leagueoflegends", "league_of_legends"],
        repo_folder = "LoL",
        name      = "League of Legends",
        cdn       = "lol.secure.dyn.riotcdn.net",
        region    = "EUW1",
        regions   = {
            "NA1":   "North America",
            "EUW1":  "Europe West",
            "EUNE1": "Europe Nordic & East",
            "KR":    "Korea",
            "BR1":   "Brazil",
            "LA1":   "Latin America North",
            "LA2":   "Latin America South",
            "OC1":   "Oceania",
            "RU":    "Russia",
            "TR1":   "Turkey",
            "JP1":   "Japan",
            "PH2":   "Philippines",
            "SG2":   "Singapore / Malaysia / Indonesia",
            "TH2":   "Thailand",
            "TW2":   "Taiwan / Hong Kong / Macao",
            "VN2":   "Vietnam",
        },
        sieve_id  = "lol",
        want_type = "lol-standalone-client-content",
        namespace = "keystone.products.league_of_legends.patchlines",
    )

    TFT = GameConfig(
        key       = ["tft", "teamfighttactics", "teamfight_tactics"],
        repo_folder= "TFT",
        name      = "Teamfight Tactics",
        cdn       = LOL.cdn,
        region    = LOL.region,
        regions   = LOL.regions,
        sieve_id  = LOL.sieve_id,
        want_type = LOL.want_type,
        namespace = LOL.namespace,
    )

    VALORANT = GameConfig(
        key       = ["val", "valorant"],
        repo_folder = "VALORANT",
        name      = "VALORANT",
        cdn       = "valorant.secure.dyn.riotcdn.net",
        region    = "eu",
        regions   = {
            "na":    "North America",
            "eu":    "Europe",
            "ap":    "Asia Pacific",
            "kr":    "Korea",
            "br":    "Brazil",
            "latam": "Latin America",
        },
        sieve_id  = None,
        want_type = None,
        namespace = "keystone.products.valorant.patchlines",
    )

    RUNETERRA = GameConfig(
        key       = ["lor", "runeterra", "legends_of_runeterra", "bacon"],
        repo_folder = "LoR",
        name      = "Legends of Runeterra",
        cdn       = "bacon.secure.dyn.riotcdn.net",
        region    = "eu",
        regions   = {
            "na":  "Americas",
            "eu":  "Europe",
            "ap":  "Asia Pacific",
            "sea": "Southeast Asia",
        },
        sieve_id  = None,
        want_type = None,
        namespace = "keystone.products.bacon.patchlines",
    )

    KO2 = GameConfig(
        key       = ["2xko", "ko2", "lion"],
        repo_folder = "2XKO",
        name      = "2XKO",
        cdn       = "lion.secure.dyn.riotcdn.net",
        region    = "eu",
        regions   = {
            "na": "North America",
            "eu": "Europe",
            "ap": "Asia Pacific",
        },
        sieve_id  = None,
        want_type = None,
        namespace = "keystone.products.lion.patchlines",
    )

    WILDRIFT = GameConfig(
        key       = ["wildrift", "wr", "wild_rift"],
        repo_folder = None,
        name      = "Wild Rift",
        cdn       = "wildrift.secure.dyn.riotcdn.net",
        region    = "eu",
        regions   = {
            "na":    "North America",
            "eu":    "Europe",
            "ap":    "Asia Pacific",
            "br":    "Brazil",
            "latam": "Latin America",
            "kr":    "Korea",
        },
        platform  = "android",
        sieve_id  = None,
        want_type = None,
        namespace = "keystone.products.wild_rift.patchlines",
    )

    RC = GameConfig(
        key       = ["rc", "riotclient", "riot_client"],
        repo_folder = "Riot Client",
        name      = "Riot Client",
        cdn       = "ks-foundation.secure.dyn.riotcdn.net",
        region    = None,
        regions   = {},
        sieve_id  = None,
        want_type = None,
        namespace = "keystone.self_update",
        patchline = "KeystoneFoundationLiveWin",
    )

    @classmethod
    def get(cls, key: str) -> Optional[GameConfig]:
        """
        Get a game config by any of its key aliases.

        Returns None if not found.
        """
        k = key.lower()
        for game in cls.all():
            if k in game.key:
                return game
        return None

    @classmethod
    def find_by_cdn(cls, cdn: str) -> Optional[GameConfig]:
        """
        Find a game config by its CDN hostname.
        """
        for game in cls.all():
            if game.cdn == cdn.lower():
                return game
        return None

    @classmethod
    def find_by_namespace(cls, namespace: str) -> Optional[GameConfig]:
        """
        Find a game config by its clientconfig namespace.
        """
        for game in cls.all():
            if game.namespace and game.namespace in namespace:
                return game
        return None

    @classmethod
    def all(cls) -> list[GameConfig]:
        """Return all games"""
        return [
            cls.LOL,
            cls.TFT,
            cls.VALORANT,
            cls.RUNETERRA,
            cls.KO2,
            cls.WILDRIFT,
            cls.RC,
        ]

    @classmethod
    def pc_games(cls) -> list[GameConfig]:
        """Return only PC games (excludes mobile platforms)."""
        return [g for g in cls.all() if not g.is_mobile]

    @classmethod
    def mobile_games(cls) -> list[GameConfig]:
        """Return only mobile games (android/ios platform)."""
        return [g for g in cls.all() if g.is_mobile]

    @classmethod
    def games_with_region(cls, region: str) -> list[GameConfig]:
        """
        Return all games that support a specific region code.
        """
        return [g for g in cls.all() if region in g.regions]

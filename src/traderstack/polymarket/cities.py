"""Warm/stable-climate city allowlist for weather-market research.

Continental / high-variance cities are intentionally absent from the default
set. An operator can add slugs that exist in ``CITY_CATALOG``, but unknown
slugs are refused (fail closed) rather than silently researched.
"""

from __future__ import annotations

from traderstack.polymarket.models import City

CITY_CATALOG: dict[str, City] = {
    "honolulu": City(
        slug="honolulu",
        name="Honolulu",
        aliases=("honolulu, hi", "oahu"),
        latitude=21.3069,
        longitude=-157.8583,
        timezone="Pacific/Honolulu",
        climate="tropical",
        station_icao="PHNL",
        iem_station="PHNL",
        iem_network="HI_ASOS",
        ghcn_id="USW00022521",
        resolution_station_name="Honolulu Daniel K. Inouye Intl Airport",
        market_unit="F",
    ),
    "san_diego": City(
        slug="san_diego",
        name="San Diego",
        aliases=("san diego",),
        latitude=32.7157,
        longitude=-117.1611,
        timezone="America/Los_Angeles",
        climate="mediterranean",
        station_icao="KSAN",
        iem_station="SAN",
        iem_network="CA_ASOS",
        ghcn_id="USW00023188",
        resolution_station_name="San Diego Intl Airport",
        market_unit="F",
    ),
    "miami": City(
        slug="miami",
        name="Miami",
        aliases=("miami, fl", "miami beach"),
        latitude=25.7617,
        longitude=-80.1918,
        timezone="America/New_York",
        climate="tropical",
        station_icao="KMIA",
        iem_station="MIA",
        iem_network="FL_ASOS",
        ghcn_id="USW00012839",
        resolution_station_name="Miami Intl Airport",
        market_unit="F",
    ),
    "phoenix": City(
        slug="phoenix",
        name="Phoenix",
        aliases=("phoenix, az",),
        latitude=33.4484,
        longitude=-112.0740,
        timezone="America/Phoenix",
        climate="arid",
        station_icao="KPHX",
        iem_station="PHX",
        iem_network="AZ_ASOS",
        ghcn_id="USW00023183",
        resolution_station_name="Phoenix Sky Harbor Intl Airport",
        market_unit="F",
    ),
    "singapore": City(
        slug="singapore",
        name="Singapore",
        aliases=(),
        latitude=1.3521,
        longitude=103.8198,
        timezone="Asia/Singapore",
        climate="equatorial",
        station_icao="WSSS",
        iem_station="WSSS",
        iem_network="SG__ASOS",
        ghcn_id="",
        resolution_station_name="Singapore Changi Airport",
        market_unit="C",
    ),
    "lisbon": City(
        slug="lisbon",
        name="Lisbon",
        aliases=("lisboa",),
        latitude=38.7223,
        longitude=-9.1393,
        timezone="Europe/Lisbon",
        climate="mediterranean",
        station_icao="LPPT",
        iem_station="LPPT",
        iem_network="PT__ASOS",
        ghcn_id="",
        resolution_station_name="Lisbon Humberto Delgado Airport",
        market_unit="C",
    ),
    "san_juan": City(
        slug="san_juan",
        name="San Juan",
        aliases=("san juan", "san juan, pr"),
        latitude=18.4655,
        longitude=-66.1057,
        timezone="America/Puerto_Rico",
        climate="tropical",
        station_icao="TJSJ",
        iem_station="TJSJ",
        iem_network="PR_ASOS",
        ghcn_id="",
        resolution_station_name="San Juan Luis Munoz Marin Intl Airport",
        market_unit="F",
    ),
    # Catalogued for operators who opt in; omitted from DEFAULT_CITY_SLUGS
    # because daily highs are high-variance relative to the research default.
    "new_york": City(
        slug="new_york",
        name="New York City",
        aliases=("new york", "nyc", "new york city"),
        latitude=40.7128,
        longitude=-74.0060,
        timezone="America/New_York",
        climate="humid_continental",
        station_icao="KLGA",
        iem_station="LGA",
        iem_network="NY_ASOS",
        ghcn_id="USW00014732",
        resolution_station_name="LaGuardia Airport",
        market_unit="F",
    ),
    "chicago": City(
        slug="chicago",
        name="Chicago",
        aliases=(),
        latitude=41.8781,
        longitude=-87.6298,
        timezone="America/Chicago",
        climate="humid_continental",
        station_icao="KORD",
        iem_station="ORD",
        iem_network="IL_ASOS",
        ghcn_id="USW00094846",
        resolution_station_name="Chicago O'Hare Intl Airport",
        market_unit="F",
    ),
    # --- polymarket weather PIT tape (#141) ---
    # Cities Polymarket lists today, catalogued so an operator can opt in and
    # so the collector can name the reason it skipped one. Station ids and
    # units come from each market's own resolution text (verified against the
    # live Gamma payload and one IEM/NCEI GET each, 2026-09-15); an empty
    # ``iem_network``/``ghcn_id`` means "not verified" and fails closed.
    # None of these are in DEFAULT_CITY_SLUGS: the frozen #44 allowlist and the
    # committed evaluation artifact must not move.
    "los_angeles": City(
        slug="los_angeles",
        name="Los Angeles",
        aliases=("los angeles", "la, ca"),
        latitude=33.9425,
        longitude=-118.4081,
        timezone="America/Los_Angeles",
        climate="mediterranean",
        station_icao="KLAX",
        iem_station="LAX",
        iem_network="CA_ASOS",
        ghcn_id="USW00023174",
        resolution_station_name="Los Angeles International Airport",
        market_unit="F",
    ),
    "san_francisco": City(
        slug="san_francisco",
        name="San Francisco",
        aliases=("san francisco",),
        latitude=37.6188,
        longitude=-122.3750,
        timezone="America/Los_Angeles",
        climate="mediterranean",
        station_icao="KSFO",
        iem_station="SFO",
        iem_network="CA_ASOS",
        ghcn_id="USW00023234",
        resolution_station_name="San Francisco International Airport",
        market_unit="F",
    ),
    "seattle": City(
        slug="seattle",
        name="Seattle",
        aliases=("seattle",),
        latitude=47.4444,
        longitude=-122.3139,
        timezone="America/Los_Angeles",
        climate="oceanic",
        station_icao="KSEA",
        iem_station="SEA",
        iem_network="WA_ASOS",
        ghcn_id="USW00024233",
        resolution_station_name="Seattle-Tacoma International Airport",
        market_unit="F",
    ),
    "houston": City(
        slug="houston",
        name="Houston",
        aliases=("houston",),
        latitude=29.6454,
        longitude=-95.2789,
        timezone="America/Chicago",
        climate="humid_subtropical",
        station_icao="KHOU",
        iem_station="HOU",
        iem_network="TX_ASOS",
        ghcn_id="USW00012918",
        resolution_station_name="William P. Hobby Airport",
        market_unit="F",
    ),
    "dallas": City(
        slug="dallas",
        name="Dallas",
        aliases=("dallas",),
        latitude=32.8471,
        longitude=-96.8518,
        timezone="America/Chicago",
        climate="humid_subtropical",
        station_icao="KDAL",
        iem_station="DAL",
        iem_network="TX_ASOS",
        ghcn_id="USW00013960",
        resolution_station_name="Dallas Love Field",
        market_unit="F",
    ),
    "austin": City(
        slug="austin",
        name="Austin",
        aliases=("austin",),
        latitude=30.1975,
        longitude=-97.6664,
        timezone="America/Chicago",
        climate="humid_subtropical",
        station_icao="KAUS",
        iem_station="AUS",
        iem_network="TX_ASOS",
        ghcn_id="USW00013904",
        resolution_station_name="Austin-Bergstrom International Airport",
        market_unit="F",
    ),
    "atlanta": City(
        slug="atlanta",
        name="Atlanta",
        aliases=("atlanta",),
        latitude=33.6407,
        longitude=-84.4277,
        timezone="America/New_York",
        climate="humid_subtropical",
        station_icao="KATL",
        iem_station="ATL",
        iem_network="GA_ASOS",
        ghcn_id="USW00013874",
        resolution_station_name="Hartsfield-Jackson International Airport",
        market_unit="F",
    ),
    "denver": City(
        slug="denver",
        name="Denver",
        aliases=("denver",),
        latitude=39.7017,
        longitude=-104.7517,
        timezone="America/Denver",
        climate="semi_arid",
        station_icao="KBKF",
        iem_station="BKF",
        iem_network="CO_ASOS",
        # Buckley Space Force Base has no verified GHCN-Daily id; the
        # cross-check is therefore unavailable and rows fail closed.
        ghcn_id="",
        resolution_station_name="Buckley Space Force Base",
        market_unit="F",
    ),
    # Celsius-resolved cities. Catalogued so the collector reports
    # ``unit_unsupported`` for a named city instead of silently dropping an
    # unknown one. Single-degree °C buckets need a unit-aware bucket model
    # (edge.py) and unit-aware ``yes_won`` (eval.py); both are out of scope
    # for this slice, so nothing here is ever scored.
    "london": City(
        slug="london",
        name="London",
        aliases=("london",),
        latitude=51.5053,
        longitude=0.0553,
        timezone="Europe/London",
        climate="oceanic",
        station_icao="EGLC",
        iem_station="EGLC",
        iem_network="GB__ASOS",
        ghcn_id="",
        resolution_station_name="London City Airport",
        market_unit="C",
    ),
    "seoul": City(
        slug="seoul",
        name="Seoul",
        aliases=("seoul (incheon)", "incheon"),
        latitude=37.4602,
        longitude=126.4407,
        timezone="Asia/Seoul",
        climate="humid_continental",
        station_icao="RKSI",
        iem_station="RKSI",
        iem_network="KR__ASOS",
        ghcn_id="",
        resolution_station_name="Incheon Intl Airport",
        market_unit="C",
    ),
    "toronto": City(
        slug="toronto",
        name="Toronto",
        aliases=("toronto",),
        latitude=43.6777,
        longitude=-79.6248,
        timezone="America/Toronto",
        climate="humid_continental",
        station_icao="CYYZ",
        iem_station="CYYZ",
        iem_network="CA_ON_ASOS",
        ghcn_id="",
        resolution_station_name="Toronto Pearson Intl Airport",
        market_unit="C",
    ),
    "zhengzhou": City(
        slug="zhengzhou",
        name="Zhengzhou",
        aliases=("zhengzhou",),
        latitude=34.5197,
        longitude=113.8408,
        timezone="Asia/Shanghai",
        climate="humid_continental",
        station_icao="ZHCC",
        iem_station="ZHCC",
        iem_network="CN__ASOS",
        ghcn_id="",
        resolution_station_name="Zhengzhou Xinzheng International Airport",
        market_unit="C",
    ),
}

DEFAULT_CITY_SLUGS: tuple[str, ...] = (
    "honolulu",
    "san_diego",
    "miami",
    "phoenix",
    "singapore",
    "lisbon",
)


def normalize_slug(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def resolve_allowlist(raw: str) -> tuple[City, ...]:
    """Parse a comma-separated allowlist. Unknown slugs raise."""

    slugs = [normalize_slug(part) for part in raw.split(",") if part.strip()]
    if not slugs:
        raise ValueError("POLYMARKET_WEATHER_CITIES allowlist is empty")
    cities: list[City] = []
    unknown: list[str] = []
    for slug in slugs:
        city = CITY_CATALOG.get(slug)
        if city is None:
            unknown.append(slug)
            continue
        cities.append(city)
    if unknown:
        raise ValueError(
            "unknown POLYMARKET_WEATHER_CITIES slug(s): "
            + ", ".join(unknown)
            + f" (catalog: {', '.join(sorted(CITY_CATALOG))})"
        )
    return tuple(cities)


def match_city(text: str, allowlist: tuple[City, ...]) -> City | None:
    """Return the allowlisted city named in ``text``, or None.

    Longer names win so "San Diego" is not shadowed by a hypothetical "San".
    """

    haystack = " ".join(text.lower().split())
    ranked = sorted(
        allowlist,
        key=lambda city: max((len(city.name), *(len(a) for a in city.aliases))),
        reverse=True,
    )
    for city in ranked:
        needles = (city.name.lower(), *(alias.lower() for alias in city.aliases))
        if any(needle and needle in haystack for needle in needles):
            return city
    return None


# --- polymarket weather PIT tape (#141) ---
# Cities whose daily high is high-variance relative to the warm/stable #44
# default. Reported as a separate group in the tape status table so a thin,
# easy-to-model universe is never averaged together with a thick, hard one.
HIGH_VARIANCE_CITY_SLUGS: tuple[str, ...] = (
    "new_york",
    "chicago",
    "denver",
    "dallas",
    "austin",
    "atlanta",
    "seattle",
    "san_francisco",
)


def resolvable_cities(allowlist: tuple[City, ...]) -> tuple[City, ...]:
    """Cities that can actually be resolved from an official station today.

    Fahrenheit buckets only (the °C bucket model is not implemented) and a
    verified IEM network/station pair. Everything else is skipped with a
    named reason rather than researched on a guessed station.
    """

    return tuple(
        city
        for city in allowlist
        if city.market_unit == "F" and city.iem_network and city.iem_station
    )

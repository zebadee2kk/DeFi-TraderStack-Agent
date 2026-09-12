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
    ),
    "san_diego": City(
        slug="san_diego",
        name="San Diego",
        aliases=("san diego",),
        latitude=32.7157,
        longitude=-117.1611,
        timezone="America/Los_Angeles",
        climate="mediterranean",
    ),
    "miami": City(
        slug="miami",
        name="Miami",
        aliases=("miami, fl", "miami beach"),
        latitude=25.7617,
        longitude=-80.1918,
        timezone="America/New_York",
        climate="tropical",
    ),
    "phoenix": City(
        slug="phoenix",
        name="Phoenix",
        aliases=("phoenix, az",),
        latitude=33.4484,
        longitude=-112.0740,
        timezone="America/Phoenix",
        climate="arid",
    ),
    "singapore": City(
        slug="singapore",
        name="Singapore",
        aliases=(),
        latitude=1.3521,
        longitude=103.8198,
        timezone="Asia/Singapore",
        climate="equatorial",
    ),
    "lisbon": City(
        slug="lisbon",
        name="Lisbon",
        aliases=("lisboa",),
        latitude=38.7223,
        longitude=-9.1393,
        timezone="Europe/Lisbon",
        climate="mediterranean",
    ),
    "san_juan": City(
        slug="san_juan",
        name="San Juan",
        aliases=("san juan", "san juan, pr"),
        latitude=18.4655,
        longitude=-66.1057,
        timezone="America/Puerto_Rico",
        climate="tropical",
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
    ),
    "chicago": City(
        slug="chicago",
        name="Chicago",
        aliases=(),
        latitude=41.8781,
        longitude=-87.6298,
        timezone="America/Chicago",
        climate="humid_continental",
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

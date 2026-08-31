#!/usr/bin/env python3
"""Build the curated KL place set the day planner's FakeMaps serves.

Run once, by hand, when the demo set needs refreshing:

    python3 scripts/fetch-kl-places.py

It writes apps/api/kira/adapters/data/kl_places.json. Nothing at runtime and
nothing in the test suite calls Overpass -- a volunteer-run service must not
become a build dependency, and the demo must work with no network at all.

Names and coordinates come from OpenStreetMap. Prices do not: OSM has no menu
prices, and neither does any Places API, so the estimate is banded from the
kind of place it is and shipped with the confidence that deserves.
"""

from __future__ import annotations

import json
import math
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

OVERPASS = "https://overpass-api.de/api/interpreter"
OUT = Path(__file__).resolve().parents[1] / "apps/api/kira/adapters/data/kl_places.json"

# Kuala Lumpur, loosely. Deliberately stops short of Selangor: the "nothing
# within range" state is a real one the UI must still be able to reach, and a
# test pins Penang returning nothing.
BBOX = (3.02, 101.61, 3.25, 101.76)

TARGET_TOTAL = 200

# OSM's halal tagging skews hard to fast-food chains: of 111 tagged places in
# KL, 33 are McDonald's. Taking them all buries the 51 independents -- the
# nasi kandar shops and kopitiams that are the point of the screen -- under a
# list that reads "McDonald's, McDonald's, McDonald's", all at the same price,
# so the ranking says nothing either. A brand earns a couple of slots, no more.
NAME_CAP_TOTAL = 6
NAME_CAP_DISTRICT = 1

# ...but variety must not cost a district its whole list. The Halal chip is on
# by default, and in outer KL the only halal-tagged places OSM knows are the
# very chains the cap throttles: within 5 km of Cheras it knows two McDonald's
# and three Marrybrown, and nothing else. Better a repeated brand there than a
# screen reading "nothing within range" in a suburb full of food.
HALAL_FLOOR_PER_DISTRICT = 2
FLOOR_RADIUS_KM = 5.0

# Each district gets its own share of the total so the set covers the city
# rather than piling up wherever OSM mappers were most active.
DISTRICTS: dict[str, tuple[float, float]] = {
    "KLCC": (3.1577, 101.7120),
    "Bukit Bintang": (3.1466, 101.7106),
    "Chow Kit": (3.1650, 101.6980),
    "Bangsar": (3.1285, 101.6709),
    "Mid Valley": (3.1177, 101.6770),
    "Mont Kiara": (3.1725, 101.6500),
    "Sri Hartamas": (3.1650, 101.6520),
    "Cheras": (3.0833, 101.7500),
    "Ampang": (3.1500, 101.7600),
    "Setapak": (3.2000, 101.7200),
    "Wangsa Maju": (3.2050, 101.7350),
    "Sentul": (3.1850, 101.6900),
    "Kepong": (3.2100, 101.6350),
    "Segambut": (3.1900, 101.6650),
    "Old Klang Road": (3.0950, 101.6750),
    "Sri Petaling": (3.0650, 101.6900),
    "Bukit Jalil": (3.0580, 101.6900),
    "Titiwangsa": (3.1750, 101.7050),
}

# (label, estimate in sen, confidence). A band, not a price: the app says so on
# every row. Confidence tracks how standardised the pricing actually is, so a
# chain reads "high" and a place we know nothing about reads "low".
CUISINE_BANDS: dict[str, tuple[str, int, str]] = {
    "mamak": ("Mamak", 1200, "high"),
    "malaysian": ("Malaysian", 1400, "medium"),
    "malay": ("Malay", 1200, "high"),
    "indian": ("Indian", 1300, "high"),
    "pakistani": ("Pakistani", 1500, "medium"),
    "arab": ("Middle Eastern", 2600, "low"),
    "chinese": ("Chinese", 1800, "medium"),
    "cantonese": ("Chinese", 2000, "medium"),
    "noodle": ("Noodles", 1400, "medium"),
    "ramen": ("Ramen", 2800, "medium"),
    "japanese": ("Japanese", 4200, "low"),
    "sushi": ("Japanese", 4600, "low"),
    "korean": ("Korean", 4000, "low"),
    "thai": ("Thai", 2200, "medium"),
    "vietnamese": ("Vietnamese", 2000, "medium"),
    "indonesian": ("Indonesian", 1600, "medium"),
    "western": ("Western", 3500, "low"),
    "american": ("Western", 3500, "low"),
    "burger": ("Burgers", 1800, "high"),
    "pizza": ("Pizza", 2800, "medium"),
    "italian": ("Italian", 4200, "low"),
    "seafood": ("Seafood", 4500, "low"),
    "steak_house": ("Steakhouse", 8000, "low"),
    "chicken": ("Chicken", 1600, "high"),
    "coffee_shop": ("Cafe", 1500, "high"),
    "cafe": ("Cafe", 1500, "high"),
    "breakfast": ("Breakfast", 1400, "medium"),
    "dessert": ("Dessert", 1200, "medium"),
    "ice_cream": ("Dessert", 1000, "high"),
    "bakery": ("Bakery", 1100, "high"),
    "sandwich": ("Sandwiches", 1600, "high"),
}

AMENITY_FALLBACK: dict[str, tuple[str, int, str]] = {
    "fast_food": ("Fast food", 1500, "high"),
    "food_court": ("Food court", 1400, "medium"),
    "cafe": ("Cafe", 1600, "medium"),
    "restaurant": ("Restaurant", 2200, "low"),
}


def fetch() -> list[dict]:
    query = f"""
    [out:json][timeout:180];
    (
      node["amenity"~"^(restaurant|fast_food|cafe|food_court)$"]["name"]
        ({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
    );
    out body;
    """
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(
        OVERPASS,
        data=body,
        headers={"User-Agent": "kira-demo-seed/1.0 (one-off curated demo fixture)"},
    )
    with urllib.request.urlopen(request, timeout=200) as response:
        return json.load(response)["elements"]


def cuisine_hits(tags: dict) -> list[tuple[str, int, str]]:
    """Every band the cuisine tag resolves to, in the order OSM states them.

    OSM lets one place carry several cuisines separated by semicolons, and 532
    of the 2,564 tagged places in the KL box do -- Nando's is
    ``chicken;portuguese``, Jake's Charbroil is ``steak_house;seafood``. Two
    spellings of one band (``cantonese;chinese``) collapse to one entry, since
    the point of the list is what the place can be found by.
    """
    hits: list[tuple[str, int, str]] = []
    labels: set[str] = set()
    for raw in (tags.get("cuisine") or "").split(";"):
        hit = CUISINE_BANDS.get(raw.strip().lower())
        if hit and hit[0] not in labels:
            labels.add(hit[0])
            hits.append(hit)
    return hits


def band(tags: dict) -> tuple[str, int, str]:
    """Label, estimate and confidence for a place, from what OSM knows of it.

    The FIRST cuisine that resolves, exactly as it always was. Recording the
    rest widens what a place can be found by and must not move what it costs:
    a place has not become dearer because OSM also calls it a seafood place.
    """
    hits = cuisine_hits(tags)
    if hits:
        label, sen, confidence = hits[0]
        # A recognisable chain prices predictably; an unbranded shop does not.
        if tags.get("brand") and confidence != "high":
            confidence = "high" if sen < 3000 else "medium"
        return label, sen, confidence
    return AMENITY_FALLBACK.get(tags.get("amenity", ""), ("Restaurant", 2200, "low"))


def kinds_of(tags: dict, primary: str) -> list[str]:
    """Every kind the place can be searched by, the display label first.

    A place whose cuisine tag resolved to nothing was banded off its amenity
    instead, so the one label ``band`` produced is all it can be found by.
    """
    return [hit[0] for hit in cuisine_hits(tags)] or [primary]


def is_halal(tags: dict) -> bool:
    """Only what OpenStreetMap actually states.

    Nothing is inferred from cuisine. Marking a halal place non-halal costs it
    custom; marking a non-halal place halal misleads someone about something
    that matters, and those two errors are not worth trading against each
    other. The UI never renders "not halal" -- the filter simply omits what is
    unverified -- so silence here stays honest.
    """
    return (tags.get("diet:halal") or "").lower() in {"yes", "only"}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius, rad = 6371.0, math.pi / 180
    d_lat, d_lng = (lat2 - lat1) * rad, (lng2 - lng1) * rad
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(h))


def district_of(lat: float, lng: float) -> str:
    return min(
        DISTRICTS,
        key=lambda name: (DISTRICTS[name][0] - lat) ** 2 + (DISTRICTS[name][1] - lng) ** 2,
    )


def signal(tags: dict) -> int:
    """Better-mapped entries are likelier to still be standing."""
    return sum(
        bool(tags.get(key))
        for key in ("cuisine", "brand", "website", "opening_hours", "addr:street")
    )


def address_of(tags: dict, district: str) -> str:
    """A street address where OSM has one, the locality where it does not.

    Only 23% of KL's food POIs carry addr:street, so most of these are the
    district rather than a doorstep. Never fabricate the rest of a line from a
    house number with no street to hang it on -- the row already carries a Maps
    link built from the coordinates, which finds the place regardless.
    """
    street = (tags.get("addr:street") or "").strip()
    if not street:
        return f"{district}, Kuala Lumpur"
    number = (tags.get("addr:housenumber") or "").strip()
    city = (tags.get("addr:city") or "Kuala Lumpur").strip()
    line = f"{number} {street}".strip()
    postcode = (tags.get("addr:postcode") or "").strip()
    tail = f"{postcode} {city}".strip()
    return f"{line}, {tail}"


def main() -> int:
    print("fetching from Overpass (one query, whole city)…", file=sys.stderr)
    elements = fetch()
    print(f"  {len(elements)} named food POIs in the KL box", file=sys.stderr)

    by_district: dict[str, list[dict]] = defaultdict(list)
    halal_pool: list[dict] = []
    for element in elements:
        tags = element.get("tags", {})
        name = (tags.get("name") or "").strip()
        if not name or len(name) > 80:
            continue
        record = {
            "lat": element["lat"],
            "lng": element["lon"],
            "tags": tags,
            "name": name,
            "osm_id": element["id"],
        }
        record["district"] = district_of(record["lat"], record["lng"])
        if is_halal(tags):
            halal_pool.append(record)
        else:
            by_district[record["district"]].append(record)

    print(f"  {len(halal_pool)} carry a diet:halal tag", file=sys.stderr)

    total_seen: dict[str, int] = defaultdict(int)
    district_seen: dict[tuple[str, str], int] = defaultdict(int)

    def take(
        record: dict, *, district_cap: int = NAME_CAP_DISTRICT, honour_total: bool = True
    ) -> bool:
        """Admit a place unless its name is already carrying the list.

        The floor pass sets ``honour_total=False``: a brand that has spent its
        global slots on richer districts must not thereby leave a thin one with
        nothing. Variety is a preference, coverage is the requirement -- and
        getting this the wrong way round is what emptied Cheras twice.
        """
        name = record["name"]
        here = (name, record["district"])
        if honour_total and total_seen[name] >= NAME_CAP_TOTAL:
            return False
        if district_seen[here] >= district_cap:
            return False
        total_seen[name] += 1
        district_seen[here] += 1
        return True

    # Independents before chains, and better-mapped before worse: an unbranded
    # shop is both likelier to be interesting and the thing the caps protect.
    def order(pool: list[dict]) -> list[dict]:
        return sorted(pool, key=lambda r: (bool(r["tags"].get("brand")), -signal(r["tags"]), r["name"]))

    # Halal places are the scarce resource -- the chip is on by default -- so
    # they get first refusal on the slots.
    chosen = [record for record in order(halal_pool) if take(record)]

    # No district may be left with an empty list under the default filter. Where
    # variety has starved one, admit the nearest halal places it actually has,
    # repeated brand and all.
    picked_ids = {id(record) for record in chosen}
    for name, (lat, lng) in DISTRICTS.items():
        def within(pool: list[dict]) -> int:
            return sum(
                1 for r in pool if haversine_km(lat, lng, r["lat"], r["lng"]) <= FLOOR_RADIUS_KM
            )

        shortfall = HALAL_FLOOR_PER_DISTRICT - within(chosen)
        if shortfall <= 0:
            continue
        nearby = sorted(
            (r for r in halal_pool if id(r) not in picked_ids),
            key=lambda r: haversine_km(lat, lng, r["lat"], r["lng"]),
        )
        for record in nearby:
            if shortfall <= 0:
                break
            if haversine_km(lat, lng, record["lat"], record["lng"]) > FLOOR_RADIUS_KM:
                break
            if take(record, district_cap=HALAL_FLOOR_PER_DISTRICT, honour_total=False):
                chosen.append(record)
                picked_ids.add(id(record))
                shortfall -= 1

    # Fill the rest evenly by district so no corner of the city comes back empty.
    remaining = TARGET_TOTAL - len(chosen)
    per_district = max(1, remaining // len(DISTRICTS))
    for name in DISTRICTS:
        picked = 0
        for record in order(by_district.get(name, [])):
            if picked >= per_district:
                break
            if take(record):
                chosen.append(record)
                picked += 1

    records = []
    seen: set[str] = set()
    for index, record in enumerate(sorted(chosen, key=lambda r: (r["district"], r["name"]))):
        label, sen, confidence = band(record["tags"])
        key = f"{record['name'].lower()}|{round(record['lat'], 4)}"
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "id": f"kl{index:03d}",
                "name": record["name"],
                "kind": label,
                # The label is the first of these, always. The rest are the
                # other cuisines OSM states, kept so a search for seafood can
                # reach a steakhouse that serves it.
                "kinds": kinds_of(record["tags"], label),
                "lat": round(record["lat"], 6),
                "lng": round(record["lng"], 6),
                "estimate_sen": sen,
                "confidence": confidence,
                "halal": is_halal(record["tags"]),
                "address": address_of(record["tags"], record["district"]),
                "note": f"{label} in {record['district']}. Estimate, not a quoted price.",
            }
        )

    payload = {
        "_comment": (
            "Curated demo set for the day planner. Names and coordinates from "
            "OpenStreetMap, (c) OpenStreetMap contributors, ODbL "
            "(https://www.openstreetmap.org/copyright). Prices are NOT from OSM: "
            "no Places API exposes menu prices, so each estimate is banded from "
            "the kind of place it is and carries its own confidence. 'kind' is "
            "the label a row is shown under and the one the estimate came from; "
            "'kinds' is every cuisine OSM states for the place, that label "
            "first, and is what a search matches against. 'halal' is "
            "true only where OSM states it; unverified is false, and the UI "
            "filters on it rather than labelling anything 'not halal'. "
            "Regenerate with scripts/fetch-kl-places.py."
        ),
        "places": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    halal_count = sum(r["halal"] for r in records)
    multi_kind = sum(len(r["kinds"]) > 1 for r in records)
    districts = defaultdict(int)
    for record in chosen[: len(records)]:
        districts[record["district"]] += 1
    print(f"wrote {len(records)} places to {OUT}", file=sys.stderr)
    print(f"  halal: {halal_count}  districts: {len(districts)}", file=sys.stderr)
    print(f"  carrying more than one kind: {multi_kind}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

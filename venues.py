"""
Tier 1 -- venue geography, and the air density it implies.

    python3 venues.py            coverage report
    python3 venues.py Madrid     one venue

Elevation is the cheapest real edge in data_plan.md and needs nothing but a
lookup table.  Temperature and humidity come from Open-Meteo (free, no key)
and are cached to disk; see weather.py.

The three are NOT separate features.  They are three inputs to one physical
quantity -- air density -- and entering them separately buys collinearity
and nothing else.  Less dense air means less drag, a faster ball, harder
returns, more holds.

Elevations are approximate (+/- 20 m), which is irrelevant: sea level to
Madrid is 667 m and to Bogota 2,640 m.  What matters is getting the
high-altitude venues right, not Rotterdam to the metre.

Tournament names in the source data are inconsistent ("US Open" vs
"Us Open"), so lookup normalises before matching -- without that, a third
of US Open matches silently miss the join.
"""

import math
import re
import sys

# name -> (lat, lon, elevation_m, indoor)
VENUES = {
    # --- slams
    "australian open": (-37.8214, 144.9784, 31, False),   # roofs on 3 courts
    "roland garros": (48.8470, 2.2530, 35, False),        # roof on Chatrier
    "wimbledon": (51.4340, -0.2140, 45, False),           # roofs Centre / No.1
    "us open": (40.7498, -73.8448, 5, False),             # roofs Ashe / Armstrong
    # --- masters
    "indian wells masters": (33.7175, -116.3050, 43, False),
    "miami masters": (25.9580, -80.2389, 3, False),
    "monte carlo masters": (43.7600, 7.4300, 10, False),
    "madrid masters": (40.4370, -3.5990, 667, False),     # the altitude one
    "rome masters": (41.9328, 12.4547, 21, False),
    "canada masters": (44.5800, -76.4800, 56, False),     # alternates TOR/MTL
    "cincinnati masters": (39.3560, -84.2700, 265, False),
    "shanghai masters": (31.2304, 121.4737, 4, False),
    "paris masters": (48.8386, 2.3785, 35, True),         # indoor
    # --- 500 / 250, outdoor
    "barcelona": (41.3874, 2.1686, 12, False),
    "washington": (38.9072, -77.0369, 12, False),
    "winston-salem": (36.0999, -80.2442, 297, False),
    "hamburg": (53.5511, 9.9937, 6, False),
    "queen's club": (51.4840, -0.2130, 10, False),
    "dubai": (25.2048, 55.2708, 5, False),
    "acapulco": (16.8531, -99.8237, 5, False),
    "doha": (25.2854, 51.5310, 10, False),
    "delray beach": (26.4615, -80.0728, 3, False),
    "buenos aires": (-34.6037, -58.3816, 25, False),
    "halle": (52.0600, 8.3600, 100, False),
    "munich": (48.1351, 11.5820, 520, False),
    "gstaad": (46.4750, 7.2860, 1050, False),             # altitude
    "stuttgart": (48.7758, 9.1829, 245, False),
    "kitzbuhel": (47.4470, 12.3920, 760, False),          # altitude
    "houston": (29.7604, -95.3698, 12, False),
    "umag": (45.4300, 13.5200, 5, False),
    "auckland": (-36.8485, 174.7633, 20, False),
    "bastad": (56.4200, 12.8500, 10, False),
    "newport": (41.4901, -71.3128, 10, False),
    "beijing": (39.9042, 116.4074, 44, False),
    "s hertogenbosch": (51.6900, 5.3000, 5, False),
    "estoril": (38.7050, -9.3970, 20, False),
    "eastbourne": (50.7687, 0.2844, 10, False),
    "mallorca": (39.5696, 2.6502, 13, False),
    "atlanta": (33.7490, -84.3880, 320, False),
    "los cabos": (22.8905, -109.9167, 10, False),
    "adelaide": (-34.9285, 138.6007, 50, False),
    "brisbane": (-27.4698, 153.0251, 27, False),
    "sydney": (-33.8688, 151.2093, 20, False),
    "marrakech": (31.6295, -7.9811, 470, False),
    "belgrade": (44.7866, 20.4489, 117, False),
    "geneva": (46.2044, 6.1432, 375, False),
    "rio de janeiro": (-22.9068, -43.1729, 10, False),
    "sao paulo": (-23.5505, -46.6333, 760, False),        # altitude
    "santiago": (-33.4489, -70.6693, 570, False),
    "cordoba": (-31.4201, -64.1888, 390, False),
    "quito": (-0.1807, -78.4678, 2850, False),            # extreme altitude
    "bogota": (4.7110, -74.0721, 2640, False),            # extreme altitude
    "kuala lumpur": (3.1390, 101.6869, 22, False),
    "chengdu": (30.5728, 104.0668, 500, False),
    "zhuhai": (22.2707, 113.5767, 10, False),
    "hangzhou": (30.2741, 120.1551, 10, False),
    "seoul": (37.5665, 126.9780, 38, False),
    "tel aviv": (32.0853, 34.7818, 30, False),
    "naples": (40.8518, 14.2681, 17, False),
    "gijon": (43.5322, -5.6611, 10, False),
    "bucharest": (44.4268, 26.1025, 85, False),
    "budapest": (47.4979, 19.0402, 105, False),
    "istanbul": (41.0082, 28.9784, 40, False),
    "nottingham": (52.9548, -1.1581, 60, False),
    "antalya": (36.8969, 30.7133, 30, False),
    "cagliari": (39.2238, 9.1217, 10, False),
    "almaty": (43.2220, 76.8512, 790, False),
    "banja luka": (44.7722, 17.1910, 163, False),
    "mahrain": (26.0667, 50.5577, 10, False),
    "chennai": (13.0827, 80.2707, 6, False),
    "nice": (43.7102, 7.2620, 10, False),
    "casablanca": (33.5731, -7.5898, 50, False),
    "shenzhen": (22.5431, 114.0579, 10, False),
    "pune": (18.5204, 73.8567, 560, False),
    "dusseldorf": (51.2277, 6.7735, 38, False),
    "los angeles": (34.0522, -118.2437, 90, False),
    "hong kong": (22.3193, 114.1694, 10, False),
    "atp cup": (-33.8688, 151.2093, 20, False),
    "united cup": (-33.8688, 151.2093, 20, False),
    # --- indoor
    "rotterdam": (51.9244, 4.4777, 0, True),
    "vienna": (48.2082, 16.3738, 170, True),
    "basel": (47.5596, 7.5886, 260, True),
    "marseille": (43.2965, 5.3698, 12, True),
    "montpellier": (43.6108, 3.8767, 27, True),
    "stockholm": (59.3293, 18.0686, 28, True),
    "metz": (49.1193, 6.1757, 180, True),
    "tokyo": (35.6762, 139.6503, 40, False),
    "moscow": (55.7558, 37.6173, 156, True),
    "st petersburg": (59.9311, 30.3609, 3, True),
    "sofia": (42.6977, 23.3219, 550, True),
    "zagreb": (45.8150, 15.9819, 122, True),
    "astana": (51.1694, 71.4491, 350, True),
    "nur-sultan": (51.1694, 71.4491, 350, True),
    "dallas": (32.7767, -96.7970, 130, True),
    "lyon": (45.7640, 4.8357, 170, False),
    "antwerp": (51.2194, 4.4025, 7, True),
    "cologne": (50.9375, 6.9603, 53, True),
    "singapore": (1.3521, 103.8198, 15, True),
    "milan": (45.4642, 9.1900, 120, True),
    "turin": (45.0703, 7.6869, 239, True),
    "london": (51.5074, -0.1278, 11, True),               # Tour Finals era
    "nitto atp finals": (45.0703, 7.6869, 239, True),
    "masters cup": (45.0703, 7.6869, 239, True),
    "tour finals": (45.0703, 7.6869, 239, True),
    "memphis": (35.1495, -90.0490, 80, True),
    "valencia": (39.4699, -0.3763, 15, True),
    "san jose": (37.3382, -121.8863, 25, True),
    "bangkok": (13.7563, 100.5018, 5, True),
    "new york": (40.7128, -74.0060, 10, True),
    "nextgen finals": (21.4858, 39.1925, 12, True),
}

# keys normalised the same way lookups are, or 'winston-salem' never matches
VENUES = {re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", k)).strip(): v
          for k, v in VENUES.items()}


def norm(name):
    """Normalise a tournament name for lookup.

    The source data carries 'US Open' and 'Us Open' as distinct strings --
    together a third of that event's matches.  Casefolding and stripping
    punctuation makes the join whole again.
    """
    n = name.lower().strip()
    n = re.sub(r"[^a-z0-9' ]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    for suffix in (" open", " atp", " championships"):
        if n.endswith(suffix) and n[: -len(suffix)] in VENUES:
            return n[: -len(suffix)]
    return n


def lookup_key(name):
    """Which VENUES key this tournament name resolves to, or None.

    Split out of lookup() so that everything keyed by venue -- geography and
    now the host country -- resolves through ONE matcher.  Two matchers
    would eventually disagree, and a tournament whose weather came from
    Madrid while its country came from Munich is a bug nobody would spot.
    """
    n = norm(name)
    if n in VENUES:
        return n
    for key in VENUES:                      # 'Rome Masters' -> 'rome'
        if n.startswith(key) or key.startswith(n):
            if abs(len(n) - len(key)) <= 9:
                return key
    return None


def lookup(name):
    """(lat, lon, elevation_m, indoor) or None."""
    k = lookup_key(name)
    return VENUES[k] if k else None


# venue key -> IOC code of the host nation, for the home-advantage term.
#
# Deliberately NOT derived from lat/lon: that needs a country-boundary table
# this project does not have, and a venue table already exists.  The
# season-ending finals are None on purpose -- they rotate between countries
# and the coordinates above pin only the most recent host, which is fine for
# elevation and wrong for nationality.  A missing country is a row the
# feature skips; a wrong one is a row it lies about.
COUNTRY = {
    # slams and masters
    "australian open": "AUS", "roland garros": "FRA", "wimbledon": "GBR",
    "us open": "USA", "indian wells masters": "USA", "miami masters": "USA",
    "monte carlo masters": "MON", "madrid masters": "ESP",
    "rome masters": "ITA", "canada masters": "CAN",
    "cincinnati masters": "USA", "shanghai masters": "CHN",
    "paris masters": "FRA",
    # the rest, by city
    "acapulco": "MEX", "adelaide": "AUS", "almaty": "KAZ", "antalya": "TUR",
    "antwerp": "BEL", "astana": "KAZ", "atlanta": "USA", "atp cup": "AUS",
    "auckland": "NZL", "bangkok": "THA", "banja luka": "BIH",
    "barcelona": "ESP", "basel": "SUI", "bastad": "SWE", "beijing": "CHN",
    "belgrade": "SRB", "bogota": "COL", "brisbane": "AUS",
    "bucharest": "ROU", "budapest": "HUN", "buenos aires": "ARG",
    "cagliari": "ITA", "casablanca": "MAR", "chengdu": "CHN",
    "chennai": "IND", "cologne": "GER", "cordoba": "ARG", "dallas": "USA",
    "delray beach": "USA", "doha": "QAT", "dubai": "UAE",
    "dusseldorf": "GER", "eastbourne": "GBR", "estoril": "POR",
    "geneva": "SUI", "gijon": "ESP", "gstaad": "SUI", "halle": "GER",
    "hamburg": "GER", "hangzhou": "CHN", "hong kong": "HKG",
    "houston": "USA", "istanbul": "TUR", "kitzbuhel": "AUT",
    "kuala lumpur": "MAS", "london": "GBR", "los angeles": "USA",
    "los cabos": "MEX", "lyon": "FRA", "mahrain": "BRN", "mallorca": "ESP",
    "marrakech": "MAR", "marseille": "FRA", "memphis": "USA", "metz": "FRA",
    "milan": "ITA", "montpellier": "FRA", "moscow": "RUS", "munich": "GER",
    "naples": "ITA", "new york": "USA", "newport": "USA", "nice": "FRA",
    "nottingham": "GBR", "nur sultan": "KAZ", "pune": "IND",
    "queen's club": "GBR", "quito": "ECU", "rio de janeiro": "BRA",
    "rotterdam": "NED", "s hertogenbosch": "NED", "san jose": "USA",
    "santiago": "CHI", "sao paulo": "BRA", "seoul": "KOR",
    "shenzhen": "CHN", "singapore": "SGP", "sofia": "BUL",
    "st petersburg": "RUS", "stockholm": "SWE", "stuttgart": "GER",
    "sydney": "AUS", "tel aviv": "ISR", "tokyo": "JPN", "turin": "ITA",
    "umag": "CRO", "united cup": "AUS", "valencia": "ESP", "vienna": "AUT",
    "washington": "USA", "winston salem": "USA", "zagreb": "CRO",
    "zhuhai": "CHN",
    # rotating neutral sites -- no host nation that means anything
    "masters cup": None, "tour finals": None, "nitto atp finals": None,
    "nextgen finals": None,
}


def country(name):
    """IOC code of the tournament's host nation, or None if not established."""
    k = lookup_key(name)
    return COUNTRY.get(k) if k else None


# IOC code -> approximate country centroid, for "how far from home is this
# player playing".  Covers the codes that carry 98% of tour matches; anything
# missing returns None rather than a guess.
#
# Precision does not matter and cannot: a country is not a point, and a
# Spaniard is not uniformly distributed over Spain.  What the table has to
# get right is the ORDER -- Buenos Aires is nearer home for a Uruguayan than
# for a Spaniard, and Monte Carlo is nearly home for a Frenchman.  Validated
# against the venue table below: every hosting country's centroid must come
# out nearest, or nearly nearest, to its own venues.
HOME = {
    "USA": (39.8, -98.6), "FRA": (46.6, 2.4), "ESP": (40.2, -3.6),
    "ITA": (42.8, 12.6), "ARG": (-35.4, -65.2), "AUS": (-25.7, 134.5),
    "GER": (51.1, 10.4), "RUS": (57.0, 40.0), "SRB": (44.2, 20.9),
    "GBR": (54.0, -2.5), "CAN": (56.1, -106.3), "CRO": (45.1, 15.2),
    "CZE": (49.8, 15.5), "JPN": (36.2, 138.3), "SUI": (46.8, 8.2),
    "AUT": (47.5, 14.6), "BEL": (50.5, 4.5), "NED": (52.1, 5.3),
    "KAZ": (48.0, 66.9), "CHI": (-35.7, -71.5), "BRA": (-14.2, -51.9),
    "POR": (39.4, -8.2), "BUL": (42.7, 25.5), "SVK": (48.7, 19.7),
    "GRE": (39.1, 21.8), "POL": (51.9, 19.1), "HUN": (47.2, 19.5),
    "NOR": (60.5, 8.5), "RSA": (-30.6, 22.9), "CHN": (35.9, 104.2),
    "BIH": (43.9, 17.7), "UKR": (48.4, 31.2), "GEO": (42.3, 43.4),
    "DEN": (56.3, 9.5), "SLO": (46.2, 15.0), "KOR": (35.9, 127.8),
    "SWE": (60.1, 18.6), "URU": (-32.5, -55.8), "FIN": (61.9, 25.7),
    "COL": (4.6, -74.3), "BLR": (53.7, 27.9), "LTU": (55.2, 23.9),
    "MDA": (47.4, 28.4), "TUN": (33.9, 9.5), "LUX": (49.8, 6.1),
    "TPE": (23.7, 121.0), "IND": (20.6, 79.0), "UZB": (41.4, 64.6),
    "CYP": (35.1, 33.4), "ROU": (45.9, 25.0), "LAT": (56.9, 24.6),
    "MEX": (23.6, -102.6), "PER": (-9.2, -75.0), "ISR": (31.0, 34.9),
    "DOM": (18.7, -70.2), "BOL": (-16.3, -63.6), "TUR": (39.0, 35.2),
    "JAM": (18.1, -77.3), "ECU": (-1.8, -78.2), "MON": (43.7, 7.4),
    "NZL": (-41.0, 174.9), "THA": (15.9, 101.0), "QAT": (25.4, 51.2),
    "UAE": (23.4, 53.8), "MAR": (31.8, -7.1), "EGY": (26.8, 30.8),
    "SGP": (1.35, 103.8), "MAS": (4.2, 101.98), "HKG": (22.3, 114.2),
    "BRN": (26.1, 50.6), "EST": (58.6, 25.0), "IRL": (53.4, -8.2),
    "SRI": (7.9, 80.8), "PAK": (30.4, 69.3), "KUW": (29.3, 47.5),
    "VEN": (6.4, -66.6), "PAR": (-23.4, -58.4), "CUB": (21.5, -77.8),
    "PHI": (12.9, 121.8), "INA": (-0.8, 113.9), "VIE": (14.1, 108.3),
    "ARM": (40.1, 45.0), "AZE": (40.1, 47.6), "KGZ": (41.2, 74.8),
    "ALG": (28.0, 1.7), "BAR": (13.2, -59.5), "ZIM": (-19.0, 29.9),
    "MKD": (41.6, 21.7), "MNE": (42.7, 19.4), "ALB": (41.2, 20.2),
    "ISL": (65.0, -18.6), "SYR": (34.8, 39.0), "LBN": (33.9, 35.9),
    "TJK": (38.9, 71.3), "NGR": (9.1, 8.7),
}


def home_distance_km(ioc, tname):
    """Great-circle km from the player's country to this venue, or None.

    A player in their OWN country is 0 km by definition, whatever the
    centroid says.  This is not a fudge, it is the whole reason the centroid
    cannot be used raw: a country is a region, not a point, and the error is
    proportional to its size.  Measured against the venue table, an American
    at the US Open sits 2,096 km from the centroid of the USA -- further
    than a Luxembourger at Metz, at 76 km.  Left alone, the feature would
    rank players by how large their country is.

    Everyone else gets the centroid distance, which is what this is for:
    a Frenchman at Monte Carlo is nearly home, a Uruguayan in Buenos Aires
    is close, a Spaniard there is not.

    None when either end is unknown -- a missing country must never become a
    zero, which is the value that means "at home".
    """
    if not ioc or ioc not in HOME:
        return None
    host = country(tname)
    if host and ioc == host:
        return 0.0
    v = lookup(tname)
    if not v:
        return None
    return distance_km(HOME[ioc], (v[0], v[1]))


def distance_km(a, b):
    """Great-circle km between two (lat, lon) pairs.

    The venue table already carries coordinates for air density; the same
    numbers give travel burden between consecutive tournaments for free.
    """
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def air_density(temp_c, elev_m, rh=0.5):
    """kg/m^3.  Sea level, 20C, 50% RH is about 1.204."""
    P = 101325.0 * math.exp(-elev_m / 8400.0)
    T = temp_c + 273.15
    es = 610.94 * math.exp(17.625 * temp_c / (temp_c + 243.04))
    pv = rh * es
    return (P - pv) / (287.058 * T) + pv / (461.495 * T)


def density_index(temp_c, elev_m, rh=0.5):
    """Air density relative to the 20C sea-level reference, as a deviation.

    THIS is the feature -- one number, not three.  Negative means thinner
    air: faster ball, more serve dominance, shorter rallies.
    """
    return air_density(temp_c, elev_m, rh) / 1.204 - 1.0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        v = lookup(q)
        if not v:
            sys.exit(f"no venue for {q!r}")
        lat, lon, el, ind = v
        print(f"{q}\n  {lat:.4f}, {lon:.4f}   {el} m   "
              f"{'indoor' if ind else 'outdoor'}")
        print(f"\n  air density index at this elevation:")
        for t in (10, 20, 30, 35):
            print(f"    {t:>2}C   {density_index(t, el):+.4f}   "
                  f"(vs {density_index(t, 0):+.4f} at sea level)")
        raise SystemExit(0)

    from collections import defaultdict
    from load import load
    c, hit = defaultdict(int), defaultdict(int)
    for m in load(2010, 2026)[0]:
        if not m.has_stats:
            continue
        c[m.tname] += 1
        if lookup(m.tname):
            hit[m.tname] += 1
    tot = sum(c.values()); got = sum(hit.values())
    print(f"venue coverage: {got:,}/{tot:,} matches ({100*got/tot:.1f}%)")
    print(f"                {len(VENUES)} venues in table, "
          f"{len(c)} tournament names in data\n")
    miss = sorted(((n, k) for n, k in c.items() if not hit[n]),
                  key=lambda x: -x[1])
    print("biggest unmatched tournaments:")
    for n, k in miss[:18]:
        print(f"  {k:>5}  {n}")

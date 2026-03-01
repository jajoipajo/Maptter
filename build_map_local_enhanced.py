from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path
from math import hypot
from urllib.parse import quote_plus

import folium
import geonamescache
from branca.element import Element
from yt_dlp import YoutubeDL


ROOT = Path("output")
COMBINED = ROOT / "combined"
WORLD_GEOJSON = Path("data") / "countries_detailed.geo.json"

ARTISTS = [
    {"slug": "matter", "name": "Matter", "color": "#c0392b"},
    {"slug": "tunja", "name": "Tunja", "color": "#1f77b4"},
]

TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿČčŠšŽžĆćĐđ]{2,}")
LOCATION_PREPOSITIONS = {
    "v",
    "na",
    "iz",
    "od",
    "do",
    "pri",
    "u",
    "po",
    "pod",
    "nad",
    "med",
    "za",
}

# Manual disambiguation/exclusion rules to keep output aligned with curated expectations.
EXCLUDED_MENTIONS = {
    ("matter", "ab raylight", "timbuktu"),
    ("matter", "polna pluca", "amerika"),
}


@dataclass(frozen=True)
class Toponym:
    key: str
    display: str
    kind: str  # "country" | "city" | "continent" | "river"
    lat: float
    lon: float
    country_geo_name: str | None = None
    line_coords: list[tuple[float, float]] | None = None


def normalize(text: str) -> str:
    text = text.replace("-", " ").replace("’", "'")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.casefold().split())


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_feature_index(world_geojson: dict) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for feat in world_geojson.get("features", []):
        props = feat.get("properties", {}) or {}
        candidates = [
            props.get("name"),
            props.get("NAME"),
            props.get("ADMIN"),
            props.get("NAME_EN"),
            props.get("SOVEREIGNT"),
            props.get("BRK_NAME"),
            props.get("formal_en"),
        ]
        for c in candidates:
            if c:
                idx[c] = feat
    return idx


def build_toponyms() -> tuple[dict[str, Toponym], dict[str, str]]:
    base = {
        "ljubljana": Toponym("ljubljana", "Ljubljana", "city", 46.0569, 14.5058),
        "kamnik": Toponym("kamnik", "Kamnik", "city", 46.2259, 14.6121),
        "duplica": Toponym("duplica", "Duplica", "city", 46.2065, 14.6008),
        "krsko": Toponym("krsko", "Krško", "city", 45.9592, 15.4917),
        "bled": Toponym("bled", "Bled", "city", 46.3683, 14.1146),
        "koper": Toponym("koper", "Koper", "city", 45.5481, 13.7302),
        "milano": Toponym("milano", "Milano", "city", 45.4642, 9.19),
        "rim": Toponym("rim", "Rim", "city", 41.9028, 12.4964),
        "berlin": Toponym("berlin", "Berlin", "city", 52.52, 13.405),
        "bejrut": Toponym("bejrut", "Bejrut", "city", 33.8938, 35.5018),
        "tokio": Toponym("tokio", "Tokio", "city", 35.6762, 139.6503),
        "honolulu": Toponym("honolulu", "Honolulu", "city", 21.3069, -157.8583),
        "timbuktu": Toponym("timbuktu", "Timbuktu", "city", 16.7666, -3.0026),
        "saint_tropez": Toponym("saint_tropez", "Saint-Tropez", "city", 43.267, 6.64),
        "san_francisco": Toponym("san_francisco", "San Francisco", "city", 37.7749, -122.4194),
        "el_paso": Toponym("el_paso", "El Paso", "city", 31.7619, -106.485),
        "antwerpen": Toponym("antwerpen", "Antwerpen", "city", 51.2194, 4.4025),
        "odesa": Toponym("odesa", "Odesa", "city", 46.4825, 30.7233),
        "cernobil": Toponym("cernobil", "Černobil", "city", 51.2768, 30.2219),
        "dubai": Toponym("dubai", "Dubai", "city", 25.2048, 55.2708),
        "zanzibar": Toponym("zanzibar", "Zanzibar", "city", -6.1659, 39.2026),
        "sumatra": Toponym("sumatra", "Sumatra", "city", 0.5897, 101.3431),
        "chicago": Toponym("chicago", "Chicago", "city", 41.8781, -87.6298),
        "arizona": Toponym("arizona", "Arizona", "city", 34.0489, -111.0937),
        "texas": Toponym("texas", "Texas", "city", 31.9686, -99.9018),
        "babilon": Toponym("babilon", "Babilon", "city", 32.5422, 44.42),
        "tigris": Toponym(
            "tigris",
            "Tigris",
            "river",
            33.4,
            43.9,
            line_coords=[
                # Simplified from Natural Earth river centerlines (Tigris), north -> south.
                (37.06253, 42.37656),
                (36.97309, 42.50750),
                (36.84337, 42.51474),
                (36.70616, 42.89210),
                (36.50544, 42.75107),
                (36.39773, 43.12395),
                (36.14138, 43.30299),
                (35.88068, 43.36085),
                (35.64464, 43.24130),
                (35.41157, 43.26946),
                (35.03063, 43.58391),
                (34.93272, 43.52206),
                (34.52973, 43.76979),
                (34.23554, 43.82276),
                (34.10578, 43.92864),
                (34.04169, 44.29143),
                (33.93549, 44.44768),
                (33.72468, 44.42579),
                (33.55012, 44.30860),
                (33.29474, 44.37965),
                (33.02582, 44.64641),
                (32.89484, 45.06007),
                (32.79275, 45.09075),
                (32.77428, 45.26734),
                (32.69343, 45.25579),
                (32.53437, 45.52630),
                (32.50222, 45.80909),
                (32.65457, 46.10434),
                (32.47936, 46.66318),
                (32.35822, 46.74952),
                (32.12877, 46.71949),
                (32.06208, 46.86280),
                (31.86925, 46.96559),
                (31.86384, 47.13478),
                (31.71137, 47.14983),
                (31.37511, 47.43401),
                (31.01883, 47.43401),
            ],
        ),
        "afrika": Toponym("afrika", "Afrika", "continent", 1.6508, 17.6791),
        "evropa": Toponym("evropa", "Evropa", "continent", 54.5260, 15.2551),
        "azija": Toponym("azija", "Azija", "continent", 34.0479, 100.6197),
        "severna_amerika": Toponym("severna_amerika", "Severna Amerika", "continent", 54.5260, -105.2551),
        "juzna_amerika": Toponym("juzna_amerika", "Južna Amerika", "continent", -8.7832, -55.4915),
        "oceanija": Toponym("oceanija", "Oceanija", "continent", -22.7359, 140.0188),
        "antarktika": Toponym("antarktika", "Antarktika", "continent", -82.8628, 135.0),
        "amerika": Toponym("amerika", "Amerika", "country", 39.8283, -98.5795, "United States of America"),
        "mehika": Toponym("mehika", "Mehika", "country", 23.6345, -102.5528, "Mexico"),
        "italija": Toponym("italija", "Italija", "country", 41.8719, 12.5674, "Italy"),
        "bosna": Toponym("bosna", "Bosna", "country", 43.9159, 17.6791, "Bosnia and Herzegovina"),
        "slovenija": Toponym("slovenija", "Slovenija", "country", 46.1512, 14.9955, "Slovenia"),
        "nemcija": Toponym("nemcija", "Nemčija", "country", 51.1657, 10.4515, "Germany"),
        "avstrija": Toponym("avstrija", "Avstrija", "country", 47.5162, 14.5501, "Austria"),
        "hrvaska": Toponym("hrvaska", "Hrvaška", "country", 45.1, 15.2, "Croatia"),
        "francija": Toponym("francija", "Francija", "country", 46.2276, 2.2137, "France"),
        "srbija": Toponym("srbija", "Srbija", "country", 44.0165, 21.0059, "Republic of Serbia"),
        "srilanka": Toponym("srilanka", "Šrilanka", "country", 7.8731, 80.7718, "Sri Lanka"),
        "maldivi": Toponym("maldivi", "Maldivi", "country", 3.2028, 73.2207, "Maldives"),
        "vietnam": Toponym("vietnam", "Vietnam", "country", 14.0583, 108.2772, "Vietnam"),
    }

    aliases = {
        "nemčija": "nemcija",
        "hrvaška": "hrvaska",
        "krško": "krsko",
        "krškem": "krsko",
        "krškemu": "krsko",
        "krsku": "krsko",
        "antwerpnu": "antwerpen",
        "antwerpa": "antwerpen",
        "antwerpu": "antwerpen",
        "tokijo": "tokio",
        "tokia": "tokio",
        "tigirs": "tigris",
        "tigrisu": "tigris",
        "tigrisa": "tigris",
        "duplici": "duplica",
        "bledu": "bled",
        "bleda": "bled",
        "kamnku": "kamnik",
        "kamnk": "kamnik",
        "odesse": "odesa",
        "odesi": "odesa",
        "odeso": "odesa",
        "černobil": "cernobil",
        "chernobyl": "cernobil",
        "dubaju": "dubai",
        "srilanki": "srilanka",
        "sri lanki": "srilanka",
        "maldivih": "maldivi",
        "maldivov": "maldivi",
        "vietnamu": "vietnam",
        "vietnama": "vietnam",
        "timbuktuju": "timbuktu",
        "timbuktuja": "timbuktu",
        "honoluluju": "honolulu",
        "honolulua": "honolulu",
        "afriki": "afrika",
        "afriko": "afrika",
        "evropi": "evropa",
        "evropo": "evropa",
        "aziji": "azija",
        "azijo": "azija",
    }
    return base, {normalize(k): v for k, v in aliases.items()}


def inflect_word_sl(base_norm: str) -> set[str]:
    w = base_norm
    forms = {w}
    if len(w) < 3:
        return forms
    if w.endswith("ija"):
        stem = w[:-1]
        forms.update({stem + "a", stem + "e", stem + "i", stem + "o", stem + "ama"})
    elif w.endswith("a"):
        stem = w[:-1]
        forms.update({stem + "e", stem + "i", stem + "o", stem + "u", stem + "ama", stem + "ah"})
    elif w.endswith("o") or w.endswith("e"):
        stem = w[:-1]
        forms.update({stem + "a", stem + "u", stem + "om", stem + "em", stem + "i", stem + "ih"})
    elif w.endswith("en"):
        stem = w[:-2]
        forms.update({w, w + "a", w + "u", stem + "nu"})
    else:
        forms.update({w + "a", w + "u", w + "om", w + "em", w + "i", w + "ih"})
    return forms


def build_variant_index(toponyms: dict[str, Toponym], aliases: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    variant_to_key: dict[str, str] = {}
    for key, topo in toponyms.items():
        parts = [p for p in normalize(topo.display).split() if p]
        if not parts:
            continue
        if len(parts) == 1:
            for form in inflect_word_sl(parts[0]):
                variant_to_key.setdefault(form, key)
        else:
            prefix = " ".join(parts[:-1])
            for tail in inflect_word_sl(parts[-1]):
                variant_to_key.setdefault(f"{prefix} {tail}", key)
            variant_to_key.setdefault(" ".join(parts), key)
    for alias_norm, key in aliases.items():
        variant_to_key[alias_norm] = key
    return variant_to_key, sorted(variant_to_key.keys())


def build_geonames_index() -> tuple[
    dict[str, tuple[str, float, float]],
    dict[str, tuple[str, float, float, str]],
    dict[str, tuple[str, float, float]],
]:
    gc = geonamescache.GeonamesCache()
    city_index: dict[str, tuple[str, float, float]] = {}
    country_index: dict[str, tuple[str, float, float, str]] = {}
    phrase_city_index: dict[str, tuple[str, float, float]] = {}

    for city in gc.get_cities().values():
        try:
            pop = int(city.get("population") or 0)
        except Exception:
            pop = 0
        # Keep only larger cities to limit false positives.
        if pop < 450_000:
            continue
        name = city.get("name")
        if not name:
            continue
        key = normalize(name)
        if key in city_index:
            continue
        try:
            lat = float(city["latitude"])
            lon = float(city["longitude"])
        except Exception:
            continue
        city_index[key] = (name, lat, lon)
        if " " in key and pop >= 300_000:
            phrase_city_index[key] = (name, lat, lon)

    for c in gc.get_countries().values():
        name = c.get("name")
        if not name:
            continue
        key = normalize(name)
        try:
            lat = float(c.get("latitude") or 0.0)
            lon = float(c.get("longitude") or 0.0)
        except Exception:
            lat, lon = 0.0, 0.0
        country_index[key] = (name, lat, lon, name)

    return city_index, country_index, phrase_city_index


def candidate_lemmas(token_norm: str) -> set[str]:
    out = {token_norm}
    suffixes = ["ju", "jem", "jo", "om", "em", "ih", "ah", "am", "a", "u", "i", "o"]
    for s in suffixes:
        if token_norm.endswith(s) and len(token_norm) - len(s) >= 4:
            out.add(token_norm[: -len(s)])
    return out


def song_norm(text: str) -> str:
    return normalize(text).replace("č", "c").replace("š", "s").replace("ž", "z")


def mention_is_excluded(artist: str, song: str, toponim_key: str) -> bool:
    return (artist.strip().lower(), song_norm(song), toponim_key.strip().lower()) in EXCLUDED_MENTIONS


def song_is_excluded(song: str) -> bool:
    return song_norm(song) == "ab raylight"


def polyline_midpoint(coords: list[tuple[float, float]]) -> tuple[float, float]:
    if not coords:
        return (0.0, 0.0)
    if len(coords) == 1:
        return coords[0]

    lengths = []
    total = 0.0
    for i in range(len(coords) - 1):
        (lat1, lon1), (lat2, lon2) = coords[i], coords[i + 1]
        seg = hypot(lat2 - lat1, lon2 - lon1)
        lengths.append(seg)
        total += seg
    if total <= 0.0:
        return coords[len(coords) // 2]

    target = total / 2.0
    acc = 0.0
    for i, seg in enumerate(lengths):
        if acc + seg >= target and seg > 0.0:
            ratio = (target - acc) / seg
            lat1, lon1 = coords[i]
            lat2, lon2 = coords[i + 1]
            return (lat1 + (lat2 - lat1) * ratio, lon1 + (lon2 - lon1) * ratio)
        acc += seg
    return coords[-1]


def extract_mentions(
    text: str,
    variant_to_key: dict[str, str],
    variant_vocab: list[str],
    artist: str,
    song: str,
    city_index: dict[str, tuple[str, float, float]],
    country_index: dict[str, tuple[str, float, float, str]],
    phrase_city_index: dict[str, tuple[str, float, float]],
    dynamic_toponyms: dict[str, Toponym],
) -> tuple[list[dict], list[dict]]:
    words = [(m.group(0), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
    mentions = []
    ambiguities = []
    i = 0
    while i < len(words):
        w1, s1, e1 = words[i]
        chosen = None
        if i + 1 < len(words):
            w2, s2, e2 = words[i + 1]
            if s2 <= e1 + 2:
                two = normalize(f"{w1} {w2}")
                key = variant_to_key.get(two)
                if key:
                    chosen = (s1, e2, text[s1:e2], key, two, "exact_bigram", 1.0)
                elif two in phrase_city_index and w1[:1].isupper() and w2[:1].isupper():
                    n, lat, lon = phrase_city_index[two]
                    dkey = two.replace(" ", "_")
                    if dkey not in dynamic_toponyms:
                        dynamic_toponyms[dkey] = Toponym(
                            key=dkey,
                            display=n,
                            kind="city",
                            lat=lat,
                            lon=lon,
                        )
                    chosen = (s1, e2, text[s1:e2], dkey, two, "geo_bigram", 1.0)
        if chosen is None:
            one = normalize(w1)
            key = variant_to_key.get(one)
            if key:
                chosen = (s1, e1, w1, key, one, "exact", 1.0)
            else:
                prev_word = normalize(words[i - 1][0]) if i > 0 else ""
                if prev_word in LOCATION_PREPOSITIONS and len(one) >= 4:
                    lemmas = candidate_lemmas(one)
                    geo = None
                    geo_kind = None
                    for lm in lemmas:
                        if lm in city_index:
                            n, lat, lon = city_index[lm]
                            geo = (lm, n, lat, lon, None)
                            geo_kind = "city"
                            break
                        if lm in country_index:
                            n, lat, lon, geo_name = country_index[lm]
                            if abs(lat) < 1e-9 and abs(lon) < 1e-9:
                                continue
                            geo = (lm, n, lat, lon, geo_name)
                            geo_kind = "country"
                            break
                    if geo is not None:
                        gkey, gname, glat, glon, geo_name = geo
                        if gkey not in dynamic_toponyms:
                            dynamic_toponyms[gkey] = Toponym(
                                key=gkey,
                                display=gname,
                                kind="country" if geo_kind == "country" else "city",
                                lat=glat,
                                lon=glon,
                                country_geo_name=geo_name,
                            )
                        chosen = (s1, e1, w1, gkey, one, "context_geo", 1.0)
                    else:
                        chosen = None
        if chosen is not None:
            s, e, surface, key, matched, method, score = chosen
            mentions.append(
                {
                    "start": s,
                    "end": e,
                    "surface": surface,
                    "toponym_key": key,
                    "matched_variant": matched,
                    "method": method,
                    "score": score,
                }
            )
            i += 2 if chosen[1] > e1 else 1
        else:
            i += 1
    return mentions, ambiguities


def resolve_yt_url(artist: str, title: str, cache: dict[str, str]) -> str:
    key = f"{artist}::{title}"
    if key in cache and cache[key] and "watch?v=" in cache[key]:
        return cache[key]
    queries = [
        f"{artist} {title} official video",
        f"{artist} {title}",
    ]
    url = ""
    for query in queries:
        try:
            with YoutubeDL({"quiet": True, "skip_download": True, "extract_flat": True, "no_warnings": True}) as ydl:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
                entries = info.get("entries") or []
                if entries:
                    e = entries[0]
                    vid = e.get("id")
                    if vid:
                        url = f"https://www.youtube.com/watch?v={vid}"
                    else:
                        url = e.get("url") or e.get("webpage_url") or ""
        except Exception:
            url = ""
        if "watch?v=" in url:
            break
    if not url:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    cache[key] = url
    return url


def popup_html(title: str, subtitle: str, artist: str, color: str, lines: list[str]) -> str:
    return (
        "<div style='min-width:360px; font-family:Arial,sans-serif; color:#111;'>"
        f"<div style='font-weight:700; font-size:16px; color:{color};'>{escape(title)}</div>"
        f"<div style='font-size:12px; margin:4px 0 8px 0; color:#222'>{escape(subtitle)}</div>"
        f"<div style='font-size:12px; margin:0 0 6px 0; color:#222'><b>Izvajalec:</b> {escape(artist)}</div>"
        f"<ul style='margin:0; padding-left:16px; font-size:12px; color:#111'>{''.join(f'<li>{line}</li>' for line in lines)}</ul>"
        "</div>"
    )


def split_div_icon(color_left: str, color_right: str, size: int, ring: bool = False) -> folium.DivIcon:
    outer = (
        f"width:{size}px;height:{size}px;border-radius:50%;"
        f"background:conic-gradient({color_left} 0 50%, {color_right} 50% 100%);"
        "border:2px solid rgba(255,255,255,0.9);position:relative;"
    )
    if ring:
        inner = max(10, size - 8)
        hole = (
            f"<div style='position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);"
            f"width:{inner}px;height:{inner}px;border-radius:50%;background:rgba(20,20,20,0.9);'></div>"
        )
    else:
        hole = ""
    html = f"<div style=\"{outer}\">{hole}</div>"
    return folium.DivIcon(html=html, icon_size=(size, size), icon_anchor=(size // 2, size // 2))


def main() -> None:
    toponyms, aliases = build_toponyms()
    variant_to_key, variant_vocab = build_variant_index(toponyms, aliases)
    city_index, country_index, phrase_city_index = build_geonames_index()
    dynamic_toponyms: dict[str, Toponym] = {}

    world = load_json(WORLD_GEOJSON, {"type": "FeatureCollection", "features": []})
    if not world.get("features"):
        world = load_json(Path("data") / "countries.geo.json", {"type": "FeatureCollection", "features": []})
    features_by_name = build_feature_index(world)

    yt_cache_path = COMBINED / "youtube_cache.json"
    yt_cache = load_json(yt_cache_path, {})

    all_rows = []
    ambiguity_rows = []
    unknown_location_candidates = Counter()

    for artist_cfg in ARTISTS:
        slug = artist_cfg["slug"]
        artist_name = artist_cfg["name"]
        db_dir = ROOT / slug / "db"
        songs_path = db_dir / "songs.csv"
        if not songs_path.exists():
            continue

        songs = list(csv.DictReader(songs_path.open(encoding="utf-8")))
        mention_rows = []
        for s in songs:
            lyrics_file = s.get("lyrics_file", "")
            if not lyrics_file:
                continue
            lp = Path(lyrics_file)
            if not lp.exists():
                continue
            text = lp.read_text(encoding="utf-8", errors="ignore")
            mentions, ambiguities = extract_mentions(
                text,
                variant_to_key,
                variant_vocab,
                slug,
                s.get("title", ""),
                city_index,
                country_index,
                phrase_city_index,
                dynamic_toponyms,
            )
            ambiguity_rows.extend(ambiguities)
            # Candidate mining: words in location context not currently recognized.
            words = [m.group(0) for m in TOKEN_RE.finditer(text)]
            recognized = {normalize(m["surface"]) for m in mentions}
            for idx in range(1, len(words)):
                prev = normalize(words[idx - 1])
                cur = normalize(words[idx])
                if prev in LOCATION_PREPOSITIONS and cur not in recognized and len(cur) >= 4:
                    unknown_location_candidates[cur] += 1
            yt_url = resolve_yt_url(artist_name, s.get("title", ""), yt_cache)
            counts = Counter(m["toponym_key"] for m in mentions)
            for key, c in counts.items():
                topo = toponyms.get(key) or dynamic_toponyms.get(key)
                if topo is None:
                    continue
                if mention_is_excluded(slug, s.get("title", ""), key):
                    continue
                mention_rows.append(
                    {
                        "artist": slug,
                        "toponim": topo.display,
                        "toponim_key": key,
                        "tip_lokacije": (
                            "država"
                            if topo.kind == "country"
                            else ("celina" if topo.kind == "continent" else ("reka" if topo.kind == "river" else "mesto/kraj"))
                        ),
                        "skladba": s.get("title", ""),
                        "album": s.get("album", "Unknown") or "Unknown",
                        "besedilo_url": s.get("genius_url", ""),
                        "yt_url": yt_url,
                        "stevilo_pojavljanj": int(c),
                        "lat": topo.lat,
                        "lon": topo.lon,
                        "country_geo_name": topo.country_geo_name or "",
                    }
                )
        # Disambiguation: "Bled" as toponym only in the song "Bejrut".
        mention_rows = [r for r in mention_rows if not (r["toponim_key"] == "bled" and r["skladba"] != "Bejrut")]
        # User curation: remove all mentions from song "AB Raylight".
        mention_rows = [r for r in mention_rows if not song_is_excluded(r.get("skladba", ""))]

        write_csv(
            db_dir / "toponym_mentions.csv",
            [
                "artist",
                "toponim",
                "toponim_key",
                "tip_lokacije",
                "skladba",
                "album",
                "besedilo_url",
                "yt_url",
                "stevilo_pojavljanj",
                "lat",
                "lon",
                "country_geo_name",
            ],
            sorted(mention_rows, key=lambda r: (r["toponim_key"], r["skladba"])),
        )
        write_csv(
            db_dir / "country_mentions.csv",
            [
                "artist",
                "toponim",
                "toponim_key",
                "tip_lokacije",
                "skladba",
                "album",
                "besedilo_url",
                "yt_url",
                "stevilo_pojavljanj",
                "lat",
                "lon",
                "country_geo_name",
            ],
            sorted((r for r in mention_rows if r["tip_lokacije"] == "država"), key=lambda r: (r["toponim_key"], r["skladba"])),
        )
        write_csv(
            db_dir / "continent_mentions.csv",
            [
                "artist",
                "toponim",
                "toponim_key",
                "tip_lokacije",
                "skladba",
                "album",
                "besedilo_url",
                "yt_url",
                "stevilo_pojavljanj",
                "lat",
                "lon",
                "country_geo_name",
            ],
            sorted((r for r in mention_rows if r["tip_lokacije"] == "celina"), key=lambda r: (r["toponim_key"], r["skladba"])),
        )
        all_rows.extend(mention_rows)

    save_json(yt_cache_path, yt_cache)

    write_csv(
        COMBINED / "toponym_mentions_all_artists.csv",
        [
            "artist",
            "toponim",
            "toponim_key",
            "tip_lokacije",
            "skladba",
            "album",
            "besedilo_url",
            "yt_url",
            "stevilo_pojavljanj",
            "lat",
            "lon",
            "country_geo_name",
        ],
        sorted(all_rows, key=lambda r: (r["artist"], r["toponim_key"], r["skladba"])),
    )
    write_csv(
        COMBINED / "ambiguities.csv",
        ["artist", "song", "token", "matched_variant", "score", "alternatives"],
        sorted(ambiguity_rows, key=lambda r: (r["artist"], r["song"], r["token"])),
    )
    write_csv(
        COMBINED / "unknown_location_candidates.csv",
        ["candidate", "count"],
        [{"candidate": c, "count": n} for c, n in unknown_location_candidates.most_common(300)],
    )

    # Build map.
    m = folium.Map(location=[46.15, 14.99], zoom_start=4, tiles="CartoDB dark_matter")
    merged_toponyms = dict(toponyms)
    merged_toponyms.update(dynamic_toponyms)
    by_topo = defaultdict(list)
    for r in all_rows:
        by_topo[r["toponim_key"]].append(r)

    matter_cfg = next(x for x in ARTISTS if x["slug"] == "matter")
    tunja_cfg = next(x for x in ARTISTS if x["slug"] == "tunja")

    for topo_key, rows in sorted(by_topo.items()):
        topo = merged_toponyms[topo_key]
        artists_here = sorted({r["artist"] for r in rows})
        is_shared = len(artists_here) > 1
        total = sum(r["stevilo_pojavljanj"] for r in rows)
        location_type = (
            "država" if topo.kind == "country" else ("celina" if topo.kind == "continent" else ("reka" if topo.kind == "river" else "mesto/kraj"))
        )
        line_items = []
        for r in sorted(rows, key=lambda x: (x["artist"], -x["stevilo_pojavljanj"], x["skladba"])):
            artist_name = next(a["name"] for a in ARTISTS if a["slug"] == r["artist"])
            line_items.append(
                f"<b>{escape(artist_name)}</b> - {escape(r['skladba'])} ({escape(r['album'])}) - "
                f"<b>število pojavljanj: {r['stevilo_pojavljanj']}</b> - "
                f"<a href='{escape(r['besedilo_url'])}' target='_blank'>besedilo</a> | "
                f"<a href='{escape(r['yt_url'])}' target='_blank'>yt</a>"
            )
        artist_label = ", ".join(next(a["name"] for a in ARTISTS if a["slug"] == s) for s in artists_here)
        if is_shared:
            pop_color = "#9b59b6"
        else:
            pop_color = matter_cfg["color"] if artists_here[0] == "matter" else tunja_cfg["color"]
        details_html = popup_html(
            title=topo.display,
            subtitle=f"{location_type} | skupno pojavljanj: {total}",
            artist=artist_label,
            color=pop_color,
            lines=line_items,
        )

        if is_shared:
            color = "#9b59b6"
            tooltip_artist = "Matter + Tunja"
        else:
            single = artists_here[0]
            color = matter_cfg["color"] if single == "matter" else tunja_cfg["color"]
            tooltip_artist = "Matter" if single == "matter" else "Tunja"

        popup = folium.Popup(details_html, max_width=500)

        if topo.kind == "country" and topo.country_geo_name and topo.country_geo_name in features_by_name:
            feature = features_by_name[topo.country_geo_name]
            gj = folium.GeoJson(
                {"type": "FeatureCollection", "features": [feature]},
                style_function=lambda _f, c=color, shared=is_shared: {
                    "fillColor": c,
                    "color": c,
                    "weight": 2.5 if not shared else 3.0,
                    "fillOpacity": 0.18 if not shared else 0.12,
                },
                highlight_function=lambda _f: {"weight": 4, "fillOpacity": 0.28},
            )
            gj.add_child(popup)
            gj.add_to(m)

        marker_lat, marker_lon = topo.lat, topo.lon
        if topo.kind == "river" and topo.line_coords:
            line_coords = list(topo.line_coords)
            center = polyline_midpoint(line_coords)
            marker_lat, marker_lon = center
            if center not in line_coords:
                mid = len(line_coords) // 2
                line_coords.insert(mid, center)
            pl = folium.PolyLine(
                locations=line_coords,
                color=color,
                weight=4.5,
                opacity=0.95,
            )
            pl.add_child(folium.Popup(details_html, max_width=500))
            pl.add_to(m)

        if is_shared:
            size = 30 if topo.kind == "continent" else min(28, 14 + int(total**0.5 * 2))
            icon = split_div_icon(matter_cfg["color"], tunja_cfg["color"], size=size, ring=(topo.kind == "continent"))
            mk = folium.Marker(
                location=[marker_lat, marker_lon],
                icon=icon,
            )
            mk.add_child(folium.Popup(details_html, max_width=500))
            mk.add_to(m)
        else:
            radius = 18 if topo.kind == "continent" else min(16, 5 + total**0.5)
            cm = folium.CircleMarker(
                location=[marker_lat, marker_lon],
                radius=radius,
                color=color,
                fill=False if topo.kind == "continent" else True,
                fill_color=color,
                fill_opacity=0.85,
                weight=3 if topo.kind == "continent" else 2,
            )
            cm.add_child(folium.Popup(details_html, max_width=500))
            cm.add_to(m)

    # Simple legend.
    legend_html = f"""
    <div style="position: fixed; bottom: 24px; left: 24px; z-index: 9999; background: rgba(20,20,20,0.92);
         color: #f2f2f2; border:1px solid #666; border-radius:8px; padding:10px 12px; font:13px Arial;">
      <div style='font-weight:700; margin-bottom:6px;'>Legenda</div>
      <label style='display:block; margin-bottom:4px;'>
        <span style='display:inline-block;width:10px;height:10px;background:#c0392b;border-radius:50%;margin:0 6px;'></span>Matter
      </label>
      <label style='display:block; margin-bottom:4px;'>
        <span style='display:inline-block;width:10px;height:10px;background:#1f77b4;border-radius:50%;margin:0 6px;'></span>Tunja
      </label>
    </div>
    """
    m.get_root().html.add_child(Element(legend_html))

    out_map = COMBINED / "toponym_map_all_artists.html"
    out_map.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_map))

    print(f"Map: {out_map.resolve()}")
    print(f"Rows: {len(all_rows)}")
    print(f"Ambiguities: {len(ambiguity_rows)}")
    print(f"Unknown candidates: {(COMBINED / 'unknown_location_candidates.csv').resolve()}")


if __name__ == "__main__":
    main()

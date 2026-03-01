from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import escape
from pathlib import Path
from typing import Iterable

import folium
import lyricsgenius
import requests
from branca.element import Element
from folium.plugins import MarkerCluster


ARTISTS = [
    {"name": "Matter", "slug": "matter", "color": "#c0392b"},
    {"name": "Tunja", "slug": "tunja", "color": "#1f77b4"},
]

MAX_SONGS_PER_ARTIST = 300
ROOT_OUTPUT = Path("output")
WORLD_GEOJSON_PATH = Path("data") / "countries.geo.json"
COMBINED_DIR = ROOT_OUTPUT / "combined"
LRCLIB_BASE = "https://lrclib.net/api"


@dataclass(frozen=True)
class Toponym:
    canonical: str
    kind: str  # "country" | "city"
    lat: float
    lon: float
    country_geo_name: str | None = None  # Country name in world geojson


TOPONYMS: dict[str, Toponym] = {
    "ljubljana": Toponym("ljubljana", "city", 46.0569, 14.5058),
    "kamnik": Toponym("kamnik", "city", 46.2259, 14.6121),
    "duplica": Toponym("duplica", "city", 46.2065, 14.6008),
    "koper": Toponym("koper", "city", 45.5481, 13.7302),
    "milano": Toponym("milano", "city", 45.4642, 9.19),
    "rim": Toponym("rim", "city", 41.9028, 12.4964),
    "berlin": Toponym("berlin", "city", 52.52, 13.405),
    "bejrut": Toponym("bejrut", "city", 33.8938, 35.5018),
    "tokio": Toponym("tokio", "city", 35.6762, 139.6503),
    "honolulu": Toponym("honolulu", "city", 21.3069, -157.8583),
    "timbuktu": Toponym("timbuktu", "city", 16.7666, -3.0026),
    "sumatra": Toponym("sumatra", "city", 0.5897, 101.3431),
    "chicago": Toponym("chicago", "city", 41.8781, -87.6298),
    "amerika": Toponym("amerika", "country", 39.8283, -98.5795, "United States of America"),
    "arizona": Toponym("arizona", "city", 34.0489, -111.0937),
    "texas": Toponym("texas", "city", 31.9686, -99.9018),
    "mehika": Toponym("mehika", "country", 23.6345, -102.5528, "Mexico"),
    "italija": Toponym("italija", "country", 41.8719, 12.5674, "Italy"),
    "bosna": Toponym("bosna", "country", 43.9159, 17.6791, "Bosnia and Herzegovina"),
    "slovenija": Toponym("slovenija", "country", 46.1512, 14.9955, "Slovenia"),
    "nemcija": Toponym("nemcija", "country", 51.1657, 10.4515, "Germany"),
    "avstrija": Toponym("avstrija", "country", 47.5162, 14.5501, "Austria"),
    "hrvaska": Toponym("hrvaska", "country", 45.1, 15.2, "Croatia"),
    "francija": Toponym("francija", "country", 46.2276, 2.2137, "France"),
    "srbija": Toponym("srbija", "country", 44.0165, 21.0059, "Republic of Serbia"),
    "babilon": Toponym("babilon", "city", 32.5422, 44.42),
}


ALIASES = {
    "tokijo": "tokio",
    "tokia": "tokio",
    "kamnk": "kamnik",
    "duplici": "duplica",
    "mehike": "mehika",
    "berlina": "berlin",
    "timbuktuju": "timbuktu",
    "timbuktuja": "timbuktu",
    "timbuktujem": "timbuktu",
    "honolulua": "honolulu",
    "honoluluju": "honolulu",
}


TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿČčŠšŽžĆćĐđ]{3,}")
LRC_LINE_RE = re.compile(r"^\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)$")


def load_token_from_env_file(env_path: Path) -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("GENIUS_ACCESS_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.casefold()


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name)
    cleaned = cleaned.strip().rstrip(".")
    return cleaned or "untitled"


def inflect_word_sl(word: str) -> set[str]:
    w = normalize(word)
    forms = {w}
    if len(w) < 3:
        return forms
    if w.endswith("ija"):
        stem = w[:-1]
        forms.update({stem + "a", stem + "e", stem + "i", stem + "o", stem + "ama"})
    elif w.endswith("a"):
        stem = w[:-1]
        forms.update({stem + "e", stem + "i", stem + "o", stem + "u", stem + "ama", stem + "ah"})
    elif w.endswith("o"):
        stem = w[:-1]
        forms.update({w, stem + "a", stem + "u", stem + "om", stem + "o", stem + "ju", stem + "jem", stem + "jo"})
    elif w.endswith("u"):
        stem = w[:-1]
        forms.update({w, stem + "uja", stem + "uju", stem + "ujem", stem + "uju", stem + "u"})
    else:
        forms.update({w + "a", w + "u", w + "om", w + "em", w + "i", w + "ih"})
    return forms


def generate_variants(base: str) -> set[str]:
    parts = [p for p in normalize(base).split() if p]
    if not parts:
        return set()
    if len(parts) == 1:
        return inflect_word_sl(parts[0])
    prefix = " ".join(parts[:-1])
    return {prefix + " " + last for last in inflect_word_sl(parts[-1])}


def build_variant_index() -> tuple[dict[str, str], list[str]]:
    variant_to_canonical: dict[str, str] = {}
    for canonical in TOPONYMS:
        for variant in generate_variants(canonical):
            variant_to_canonical.setdefault(variant, canonical)
    for alias, canonical in ALIASES.items():
        variant_to_canonical[normalize(alias)] = canonical
    variant_vocab = sorted(variant_to_canonical.keys())
    return variant_to_canonical, variant_vocab


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_match(token_norm: str, variant_vocab: list[str]) -> tuple[str | None, list[str], float]:
    best_variant = None
    best_score = 0.0
    near: list[tuple[str, float]] = []
    for variant in variant_vocab:
        if abs(len(variant) - len(token_norm)) > 3:
            continue
        score = similarity(token_norm, variant)
        if score >= 0.84:
            near.append((variant, score))
        if score > best_score:
            best_score = score
            best_variant = variant
    near.sort(key=lambda x: x[1], reverse=True)
    near_variants = [v for v, s in near if best_score - s <= 0.03 and s >= 0.84]
    return best_variant, near_variants, best_score


def extract_mentions(
    text: str,
    variant_to_canonical: dict[str, str],
    variant_vocab: list[str],
    artist: str,
    song_title: str,
) -> tuple[list[dict], list[dict]]:
    words = [(m.group(0), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
    mentions: list[dict] = []
    ambiguities: list[dict] = []
    i = 0
    while i < len(words):
        w1, s1, e1 = words[i]
        chosen = None
        if i + 1 < len(words):
            w2, s2, e2 = words[i + 1]
            if s2 <= e1 + 2:
                two_norm = normalize(w1 + " " + w2)
                canonical = variant_to_canonical.get(two_norm)
                if canonical:
                    chosen = (s1, e2, text[s1:e2], canonical, two_norm, 1.0, "exact_bigram")
        if chosen is None:
            one_norm = normalize(w1)
            canonical = variant_to_canonical.get(one_norm)
            if canonical:
                chosen = (s1, e1, w1, canonical, one_norm, 1.0, "exact")
            else:
                best_variant, near_variants, score = fuzzy_match(one_norm, variant_vocab)
                if best_variant and score >= 0.89 and len(one_norm) >= 5:
                    canonical = variant_to_canonical[best_variant]
                    chosen = (s1, e1, w1, canonical, best_variant, score, "fuzzy")
                    if len(near_variants) > 1:
                        ambiguities.append(
                            {
                                "artist": artist,
                                "song": song_title,
                                "token": w1,
                                "matched_variant": best_variant,
                                "score": f"{score:.3f}",
                                "alternatives": "|".join(near_variants[:6]),
                            }
                        )
        if chosen is not None:
            s, e, surface, canonical, matched, score, method = chosen
            mentions.append(
                {
                    "start": s,
                    "end": e,
                    "surface": surface,
                    "canonical": canonical,
                    "matched_variant": matched,
                    "score": score,
                    "method": method,
                }
            )
            i += 2 if chosen[1] > e1 else 1
        else:
            i += 1
    return mentions, ambiguities


def annotate_text(text: str, mentions: Iterable[dict]) -> str:
    spans = sorted(mentions, key=lambda m: m["start"])
    out = []
    cur = 0
    for m in spans:
        s = m["start"]
        e = m["end"]
        if s < cur:
            continue
        out.append(text[cur:s])
        out.append(f"[[TOPONYM:{m['surface']}|{m['canonical']}|{m['method']}]]")
        cur = e
    out.append(text[cur:])
    return "".join(out)


def ensure_world_geojson() -> None:
    if WORLD_GEOJSON_PATH.exists():
        return
    WORLD_GEOJSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    import urllib.request

    url = "https://raw.githubusercontent.com/johan/world.geo.json/master/countries.geo.json"
    urllib.request.urlretrieve(url, WORLD_GEOJSON_PATH)


def parse_lrc(lrc_text: str) -> list[dict]:
    lines: list[dict] = []
    for raw in lrc_text.splitlines():
        m = LRC_LINE_RE.match(raw.strip())
        if not m:
            continue
        mm = int(m.group(1))
        ss = int(m.group(2))
        frac = m.group(3) or "0"
        ms = int(frac.ljust(3, "0")[:3])
        t = mm * 60 + ss + ms / 1000.0
        text = m.group(4).strip()
        if not text:
            continue
        lines.append({"time": t, "text": text})
    return lines


def load_lrc_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_lrc_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_lrclib_synced(song_title: str, artist_name: str, album_name: str | None, cache: dict) -> str | None:
    cache_key = f"{artist_name}::{song_title}::{album_name or ''}"
    if cache_key in cache and cache[cache_key]:
        return cache[cache_key]

    params = {"track_name": song_title, "artist_name": artist_name}
    if album_name and album_name != "Unknown":
        params["album_name"] = album_name
    synced = None
    try:
        resp = requests.get(f"{LRCLIB_BASE}/get", params=params, timeout=20)
        if resp.ok:
            body = resp.json()
            synced = body.get("syncedLyrics")
    except Exception:
        synced = None
    if not synced:
        # Fallback search for approximate title/artist matches.
        try:
            sr = requests.get(
                f"{LRCLIB_BASE}/search",
                params={"track_name": song_title, "artist_name": artist_name},
                timeout=20,
            )
            if sr.ok:
                candidates = sr.json() or []
                best = None
                best_score = 0.0
                for c in candidates:
                    lyr = c.get("syncedLyrics")
                    if not lyr:
                        continue
                    t_score = similarity(normalize(song_title), normalize(c.get("trackName", "")))
                    a_score = similarity(normalize(artist_name), normalize(c.get("artistName", "")))
                    score = 0.65 * t_score + 0.35 * a_score
                    if score > best_score:
                        best_score = score
                        best = lyr
                if best_score >= 0.72:
                    synced = best
        except Exception:
            synced = synced
    cache[cache_key] = synced
    return synced


def youtube_search_url(artist: str, title: str) -> str:
    query = f"{artist} {title} official video"
    from urllib.parse import quote_plus

    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"


def fetch_artist_songs(genius: lyricsgenius.Genius, artist_name: str) -> list[dict]:
    artist = genius.search_artist(artist_name, max_songs=MAX_SONGS_PER_ARTIST, sort="title")
    songs: list[dict] = []
    seen = set()
    if artist is not None:
        for song in artist.songs:
            song_dict = song.to_dict()
            key = song_dict.get("id") or song_dict.get("url") or song_dict.get("title")
            if key in seen:
                continue
            seen.add(key)
            album_obj = song_dict.get("album") or {}
            album_name = album_obj.get("name") if isinstance(album_obj, dict) else None
            songs.append(
                {
                    "song_id": song_dict.get("id"),
                    "title": song_dict.get("title", song.title),
                    "artist": artist.name,
                    "full_title": song_dict.get("full_title", ""),
                    "album": album_name or "Unknown",
                    "url": song_dict.get("url", getattr(song, "url", "")),
                    "yt_url": youtube_search_url(artist.name, song_dict.get("title", song.title)),
                    "lyrics": song.lyrics or "",
                }
            )
        return songs

    # Fallback for ambiguous artist naming on Genius (e.g. Dacho/DaChoyce).
    try:
        search_blob = genius.search_all(artist_name, per_page=5)
    except Exception:
        return []
    artist_norm = normalize(artist_name)
    candidates = []
    for section in search_blob.get("sections", []):
        if section.get("type") != "song":
            continue
        for hit in section.get("hits", []):
            result = hit.get("result", {})
            primary = normalize((result.get("primary_artist") or {}).get("name", ""))
            if artist_norm and artist_norm in primary:
                candidates.append(result)

    for result in candidates:
        title = result.get("title")
        primary_artist_name = (result.get("primary_artist") or {}).get("name")
        if not title or not primary_artist_name:
            continue
        try:
            song = genius.search_song(title, primary_artist_name)
        except Exception:
            song = None
        if song is None:
            continue
        song_dict = song.to_dict()
        key = song_dict.get("id") or song_dict.get("url") or song_dict.get("title")
        if key in seen:
            continue
        seen.add(key)
        album_obj = song_dict.get("album") or {}
        album_name = album_obj.get("name") if isinstance(album_obj, dict) else None
        songs.append(
            {
                "song_id": song_dict.get("id"),
                "title": song_dict.get("title", song.title),
                "artist": primary_artist_name,
                "full_title": song_dict.get("full_title", ""),
                "album": album_name or "Unknown",
                "url": song_dict.get("url", getattr(song, "url", "")),
                "yt_url": youtube_search_url(primary_artist_name, song_dict.get("title", song.title)),
                "lyrics": song.lyrics or "",
            }
        )
    return songs


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_popup_html(title: str, subtitle: str, artist: str, color: str, lines: list[str]) -> str:
    rendered = "".join(f"<li>{line}</li>" for line in lines)
    return (
        "<div style='min-width:340px; font-family:Arial,sans-serif;'>"
        f"<div style='font-weight:700; font-size:16px; color:{color};'>{escape(title)}</div>"
        f"<div style='font-size:12px; margin:4px 0 8px 0; color:#333'>{escape(subtitle)}</div>"
        f"<div style='font-size:12px; margin:0 0 6px 0;'><b>Artist:</b> {escape(artist)}</div>"
        f"<ul style='margin:0; padding-left:16px; font-size:12px;'>{rendered}</ul>"
        "</div>"
    )


def main() -> None:
    token = load_token_from_env_file(Path(".env"))
    if not token:
        raise SystemExit("Missing GENIUS_ACCESS_TOKEN in .env")

    ensure_world_geojson()
    world_geo = json.loads(WORLD_GEOJSON_PATH.read_text(encoding="utf-8"))

    genius = lyricsgenius.Genius(token)
    genius.verbose = False
    genius.remove_section_headers = True
    genius.skip_non_songs = True
    genius.excluded_terms = ["(Remix)", "(Live)"]

    variant_to_canonical, variant_vocab = build_variant_index()

    combined_mentions_rows: list[dict] = []
    combined_country_rows: list[dict] = []
    combined_timed_rows: list[dict] = []
    ambiguity_rows: list[dict] = []
    all_song_rows: list[dict] = []

    for artist_cfg in ARTISTS:
        artist_name = artist_cfg["name"]
        artist_slug = artist_cfg["slug"]
        artist_dir = ROOT_OUTPUT / artist_slug
        lyrics_dir = artist_dir / "lyrics"
        annotated_dir = artist_dir / "annotated_toponyms"
        db_dir = artist_dir / "db"
        lyrics_dir.mkdir(parents=True, exist_ok=True)
        annotated_dir.mkdir(parents=True, exist_ok=True)
        db_dir.mkdir(parents=True, exist_ok=True)

        songs = fetch_artist_songs(genius, artist_name)
        all_song_rows.extend(
            [
                {
                    "artist": artist_slug,
                    "song_id": s["song_id"],
                    "title": s["title"],
                    "album": s["album"],
                    "url": s["url"],
                    "yt_url": s["yt_url"],
                }
                for s in songs
            ]
        )

        name_counts: dict[str, int] = defaultdict(int)
        song_rows: list[dict] = []
        mention_rows: list[dict] = []
        country_rows: list[dict] = []
        timed_rows: list[dict] = []
        lrc_cache_path = db_dir / "lrc_cache.json"
        lrc_cache = load_lrc_cache(lrc_cache_path)

        for song in songs:
            base_name = sanitize_filename(song["title"])
            name_counts[base_name] += 1
            suffix = f" ({name_counts[base_name]})" if name_counts[base_name] > 1 else ""
            filename = f"{base_name}{suffix}.txt"

            lyrics_path = lyrics_dir / filename
            lyrics_path.write_text(song["lyrics"], encoding="utf-8")

            mentions, ambiguities = extract_mentions(
                song["lyrics"], variant_to_canonical, variant_vocab, artist_slug, song["title"]
            )
            ambiguity_rows.extend(ambiguities)

            synced_lrc = fetch_lrclib_synced(song["title"], song["artist"], song["album"], lrc_cache)
            timed_lines = parse_lrc(synced_lrc) if synced_lrc else []

            annotated_text = annotate_text(song["lyrics"], mentions)
            (annotated_dir / filename).write_text(annotated_text, encoding="utf-8")

            counts = Counter(m["canonical"] for m in mentions)
            for canonical, count in counts.items():
                topo = TOPONYMS[canonical]
                row = {
                    "artist": artist_slug,
                    "beseda": canonical,
                    "tip_lokacije": topo.kind,
                    "skladba": song["title"],
                    "album": song["album"],
                    "genius_url": song["url"],
                    "yt_url": song["yt_url"],
                    "pojavnost": count,
                    "lat": topo.lat,
                    "lon": topo.lon,
                    "country_geo_name": topo.country_geo_name or "",
                }
                mention_rows.append(row)
                if topo.kind == "country":
                    country_rows.append(row)

            # Timestamp detection per toponym mention in synced lyric lines.
            for line in timed_lines:
                line_mentions, line_ambiguities = extract_mentions(
                    line["text"], variant_to_canonical, variant_vocab, artist_slug, song["title"]
                )
                ambiguity_rows.extend(line_ambiguities)
                if not line_mentions:
                    continue
                for lm in line_mentions:
                    canonical = lm["canonical"]
                    topo = TOPONYMS[canonical]
                    timed_rows.append(
                        {
                            "artist": artist_slug,
                            "beseda": canonical,
                            "tip_lokacije": topo.kind,
                            "skladba": song["title"],
                            "album": song["album"],
                            "genius_url": song["url"],
                            "yt_url": song["yt_url"],
                            "line_text": line["text"],
                            "timestamp_s": round(float(line["time"]), 3),
                            "lat": topo.lat,
                            "lon": topo.lon,
                        }
                    )

            song_rows.append(
                {
                    "artist": artist_slug,
                    "title": song["title"],
                    "album": song["album"],
                    "genius_url": song["url"],
                    "lyrics_file": str(lyrics_path),
                    "mentions_total": sum(counts.values()),
                    "has_synced_lrc": bool(timed_lines),
                }
            )

        save_lrc_cache(lrc_cache_path, lrc_cache)

        write_csv(
            db_dir / "songs.csv",
            ["artist", "title", "album", "genius_url", "yt_url", "lyrics_file", "mentions_total", "has_synced_lrc"],
            song_rows,
        )
        write_csv(
            db_dir / "toponym_mentions.csv",
            [
                "artist",
                "beseda",
                "tip_lokacije",
                "skladba",
                "album",
                "genius_url",
                "yt_url",
                "pojavnost",
                "lat",
                "lon",
                "country_geo_name",
            ],
            sorted(mention_rows, key=lambda r: (r["beseda"], r["skladba"])),
        )
        write_csv(
            db_dir / "country_mentions.csv",
            [
                "artist",
                "beseda",
                "tip_lokacije",
                "skladba",
                "album",
                "genius_url",
                "yt_url",
                "pojavnost",
                "lat",
                "lon",
                "country_geo_name",
            ],
            sorted(country_rows, key=lambda r: (r["beseda"], r["skladba"])),
        )
        write_csv(
            db_dir / "toponym_timestamps.csv",
            [
                "artist",
                "beseda",
                "tip_lokacije",
                "skladba",
                "album",
                "genius_url",
                "yt_url",
                "line_text",
                "timestamp_s",
                "lat",
                "lon",
            ],
            sorted(timed_rows, key=lambda r: (r["beseda"], r["skladba"], r["timestamp_s"])),
        )

        combined_mentions_rows.extend(mention_rows)
        combined_country_rows.extend(country_rows)
        combined_timed_rows.extend(timed_rows)

    write_csv(
        COMBINED_DIR / "toponym_mentions_all_artists.csv",
        [
            "artist",
            "beseda",
            "tip_lokacije",
            "skladba",
            "album",
            "genius_url",
            "yt_url",
            "pojavnost",
            "lat",
            "lon",
            "country_geo_name",
        ],
        sorted(combined_mentions_rows, key=lambda r: (r["artist"], r["beseda"], r["skladba"])),
    )
    write_csv(
        COMBINED_DIR / "ambiguities.csv",
        ["artist", "song", "token", "matched_variant", "score", "alternatives"],
        sorted(ambiguity_rows, key=lambda r: (r["artist"], r["song"], r["token"])),
    )
    write_csv(
        COMBINED_DIR / "toponym_timestamps_all_artists.csv",
        [
            "artist",
            "beseda",
            "tip_lokacije",
            "skladba",
            "album",
            "genius_url",
            "yt_url",
            "line_text",
            "timestamp_s",
            "lat",
            "lon",
        ],
        sorted(combined_timed_rows, key=lambda r: (r["artist"], r["beseda"], r["skladba"], r["timestamp_s"])),
    )

    # Build one combined map with exactly 3 artist layers.
    artist_color = {a["slug"]: a["color"] for a in ARTISTS}
    m = folium.Map(location=[46.15, 14.99], zoom_start=4, tiles="CartoDB dark_matter")

    features_by_country_name = {f["properties"]["name"]: f for f in world_geo["features"]}

    # Map (artist, toponym, song) -> first synced timestamp and line.
    timed_index: dict[tuple[str, str, str], dict] = {}
    for row in combined_timed_rows:
        key = (row["artist"], row["beseda"], row["skladba"])
        existing = timed_index.get(key)
        if existing is None or float(row["timestamp_s"]) < float(existing["timestamp_s"]):
            timed_index[key] = row

    country_rows_by_artist_topo: dict[tuple[str, str], list[dict]] = defaultdict(list)
    city_rows_by_artist_topo: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in combined_mentions_rows:
        key = (row["artist"], row["beseda"])
        if row["tip_lokacije"] == "country":
            country_rows_by_artist_topo[key].append(row)
        else:
            city_rows_by_artist_topo[key].append(row)

    for artist_cfg in ARTISTS:
        artist = artist_cfg["slug"]
        color = artist_cfg["color"]
        layer = folium.FeatureGroup(name=artist_cfg["name"].upper(), show=True)
        m.add_child(layer)
        city_cluster = MarkerCluster(name=f"{artist}_cluster", control=False).add_to(layer)

        # Countries as polygons.
        for (a, topo_name), rows in sorted(country_rows_by_artist_topo.items()):
            if a != artist:
                continue
            topo = TOPONYMS[topo_name]
            geo_name = topo.country_geo_name
            if not geo_name:
                continue
            feature = features_by_country_name.get(geo_name)
            if not feature:
                continue
            total_mentions = sum(r["pojavnost"] for r in rows)
            lines = []
            for r in sorted(rows, key=lambda x: (-x["pojavnost"], x["skladba"])):
                timed = timed_index.get((artist, topo_name, r["skladba"]))
                line = (
                    f"{escape(r['skladba'])} ({escape(r['album'])}) - {r['pojavnost']}x - "
                    f"<a href='{escape(r['genius_url'])}' target='_blank'>besedilo</a> | "
                    f"<a href='{escape(r['yt_url'])}' target='_blank'>yt</a>"
                )
                if timed:
                    line += f"<div style='color:#555'>[{float(timed['timestamp_s']):.1f}s] {escape(timed['line_text'])}</div>"
                lines.append(line)

            popup = folium.Popup(
                make_popup_html(
                    title=topo_name,
                    subtitle=f"Drzava | Skupna pojavnost: {total_mentions}",
                    artist=artist.upper(),
                    color=color,
                    lines=lines,
                ),
                max_width=520,
            )
            folium.GeoJson(
                data={"type": "FeatureCollection", "features": [feature]},
                style_function=lambda _f, c=color: {"fillColor": c, "color": c, "weight": 1.5, "fillOpacity": 0.26},
                highlight_function=lambda _f: {"weight": 3, "fillOpacity": 0.38},
                tooltip=f"{artist.upper()}: {topo_name} ({total_mentions})",
                popup=popup,
            ).add_to(layer)

        # Cities/smaller places as points.
        for (a, topo_name), rows in sorted(city_rows_by_artist_topo.items()):
            if a != artist:
                continue
            topo = TOPONYMS[topo_name]
            total_mentions = sum(r["pojavnost"] for r in rows)
            lines = []
            for r in sorted(rows, key=lambda x: (-x["pojavnost"], x["skladba"])):
                timed = timed_index.get((artist, topo_name, r["skladba"]))
                line = (
                    f"{escape(r['skladba'])} ({escape(r['album'])}) - {r['pojavnost']}x - "
                    f"<a href='{escape(r['genius_url'])}' target='_blank'>besedilo</a> | "
                    f"<a href='{escape(r['yt_url'])}' target='_blank'>yt</a>"
                )
                if timed:
                    line += f"<div style='color:#555'>[{float(timed['timestamp_s']):.1f}s] {escape(timed['line_text'])}</div>"
                lines.append(line)

            popup = folium.Popup(
                make_popup_html(
                    title=topo_name,
                    subtitle=f"Mesto/kraj | Skupna pojavnost: {total_mentions}",
                    artist=artist.upper(),
                    color=color,
                    lines=lines,
                ),
                max_width=520,
            )
            folium.CircleMarker(
                location=[topo.lat, topo.lon],
                radius=min(16, 5 + total_mentions ** 0.5),
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.78,
                weight=2,
                tooltip=f"{artist.upper()}: {topo_name} ({total_mentions})",
                popup=popup,
            ).add_to(city_cluster)

    folium.LayerControl(collapsed=False).add_to(m)

    legend_html = (
        "<div style=\"position: fixed; bottom: 24px; left: 24px; z-index: 9999; "
        "background: rgba(255,255,255,0.95); border:1px solid #bbb; border-radius:8px; "
        "padding:10px 12px; font:13px Arial;\">"
        "<div style='font-weight:700; margin-bottom:6px;'>Legenda artistov</div>"
        "<div><span style='display:inline-block;width:10px;height:10px;background:#c0392b;border-radius:50%;margin-right:6px;'></span>Matter</div>"
        "<div><span style='display:inline-block;width:10px;height:10px;background:#1f77b4;border-radius:50%;margin-right:6px;'></span>Tunja</div>"
        "<div style='margin-top:6px;color:#555;'>Drzave = poligoni, mesta = tocke</div>"
        "</div>"
    )
    m.get_root().html.add_child(Element(legend_html))
    map_out = COMBINED_DIR / "toponym_map_all_artists.html"
    map_out.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(map_out))

    # Album stats for Matter (user mentioned 4 albums).
    matter_rows = [r for r in combined_mentions_rows if r["artist"] == "matter"]
    album_counts = Counter(r["album"] for r in matter_rows)
    album_stats_rows = [{"album": album, "mentions": n} for album, n in sorted(album_counts.items(), key=lambda x: (-x[1], x[0]))]
    write_csv(COMBINED_DIR / "matter_album_counts.csv", ["album", "mentions"], album_stats_rows)

    print(f"Combined map: {map_out.resolve()}")
    print(f"Combined table: {(COMBINED_DIR / 'toponym_mentions_all_artists.csv').resolve()}")
    print(f"Ambiguities: {(COMBINED_DIR / 'ambiguities.csv').resolve()}")
    print(f"Matter album stats: {(COMBINED_DIR / 'matter_album_counts.csv').resolve()}")
    print(f"Ambiguous matches found: {len(ambiguity_rows)}")


if __name__ == "__main__":
    main()

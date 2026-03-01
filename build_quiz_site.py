from __future__ import annotations

import csv
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
import shutil
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path('output') / 'combined'
SITE = ROOT / 'site'
ASSETS = SITE / 'assets'
COVERS = ASSETS / 'covers'

RED = '#e01515'
BLUE = '#1123ff'
GRAY = '#d9d9d9'
SLOVENIA_KEYS = {"ljubljana", "kamnik", "duplica", "krsko", "bled", "koper", "slovenija"}
ALBUM_RELEASE_YEAR = {
    ("matter", "Troglav I"): 2015,
    ("matter", "Troglav II"): 2016,
    ("matter", "Troglav III"): 2017,
    ("matter", "Amphibios"): 2017,
    ("matter", "Mrk"): 2018,
    ("matter", "Haos"): 2019,
    ("matter", "Predjed"): 2020,
    ("tunja", "Kolajna"): 2023,
}


def slugify(text: str) -> str:
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower()
    return text or 'unknown'


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def fetch_text(url: str) -> str:
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=20) as resp:
        return resp.read().decode('utf-8', errors='ignore')


def fetch_bytes(url: str) -> bytes:
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=25) as resp:
        return resp.read()


def localize_map_assets(map_html: Path) -> None:
    vendor_dir = ASSETS / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    assets_map = {
        "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js": "leaflet.js",
        "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css": "leaflet.css",
        "https://code.jquery.com/jquery-3.7.1.min.js": "jquery.min.js",
        "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js": "bootstrap.bundle.min.js",
        "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/css/bootstrap.min.css": "bootstrap.min.css",
        "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.js": "leaflet.awesome-markers.js",
        "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.css": "leaflet.awesome-markers.css",
        "https://cdn.jsdelivr.net/gh/python-visualization/folium/folium/templates/leaflet.awesome.rotate.min.css": "leaflet.awesome.rotate.min.css",
        "https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap-glyphicons.css": "bootstrap-glyphicons.css",
        "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.2.0/css/all.min.css": "all.min.css",
    }
    html = map_html.read_text(encoding="utf-8")
    for url, fname in assets_map.items():
        dst = vendor_dir / fname
        if not dst.exists():
            try:
                dst.write_bytes(fetch_bytes(url))
            except Exception:
                continue
        if dst.exists():
            html = html.replace(url, f"assets/vendor/{fname}")
    map_html.write_text(html, encoding="utf-8")


def genius_og_image(genius_url: str) -> str:
    try:
        html = fetch_text(genius_url)
    except Exception:
        return ''
    m = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']', html, flags=re.I)
    return m.group(1) if m else ''


def save_placeholder(path: Path, title: str) -> None:
    safe = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600">
  <rect width="300" height="300" x="0" y="0" fill="{RED}"/>
  <rect width="300" height="300" x="300" y="0" fill="{BLUE}"/>
  <rect width="300" height="300" x="0" y="300" fill="{GRAY}"/>
  <rect width="300" height="300" x="300" y="300" fill="{RED}"/>
  <polygon points="0,600 60,420 120,600" fill="{BLUE}"/>
  <polygon points="100,600 200,380 300,600" fill="{BLUE}"/>
  <polygon points="240,600 290,420 340,600" fill="{BLUE}"/>
  <rect x="24" y="24" width="552" height="90" fill="rgba(0,0,0,0.45)"/>
  <text x="300" y="80" text-anchor="middle" font-family="Arial" font-size="34" fill="#fff">{safe}</text>
</svg>'''
    path.write_text(svg, encoding='utf-8')


def yt_thumb_from_url(yt_url: str) -> str:
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{6,})", yt_url or "")
    if not m:
        return ""
    vid = m.group(1)
    return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"


def build_album_covers(mentions: list[dict], matter_songs: list[dict], tunja_songs: list[dict]) -> dict[tuple[str, str], str]:
    COVERS.mkdir(parents=True, exist_ok=True)

    album_sources_genius: dict[tuple[str, str], str] = {}
    for row in matter_songs + tunja_songs:
        artist = row.get('artist', '').strip().lower()
        album = (row.get('album') or 'Unknown').strip() or 'Unknown'
        url = row.get('genius_url', '').strip()
        key = (artist, album)
        if key not in album_sources_genius and url:
            album_sources_genius[key] = url

    album_sources_yt: dict[tuple[str, str], str] = {}
    for row in mentions:
        artist = row.get('artist', '').strip().lower()
        album = (row.get('album') or 'Unknown').strip() or 'Unknown'
        yt_url = row.get('yt_url', '').strip()
        key = (artist, album)
        if key not in album_sources_yt and yt_url:
            album_sources_yt[key] = yt_url

    output_map: dict[tuple[str, str], str] = {
        ("matter", "Troglav I"): "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Matter_album_troglav.jpg/500px-Matter_album_troglav.jpg",
        ("matter", "Troglav II"): "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Matter_album_troglav.jpg/500px-Matter_album_troglav.jpg",
        ("matter", "Troglav III"): "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Matter_album_troglav.jpg/500px-Matter_album_troglav.jpg",
        ("matter", "Amphibios"): "https://upload.wikimedia.org/wikipedia/sl/thumb/6/6b/Matter_album_amphibios.jpg/500px-Matter_album_amphibios.jpg",
        ("matter", "Mrk"): "https://upload.wikimedia.org/wikipedia/commons/9/93/Matter_album_mrk.jpg",
        ("matter", "Predjed"): "https://upload.wikimedia.org/wikipedia/sl/d/d6/Matter_album_predjed.jpg",
        ("tunja", "Kolajna"): "https://f4.bcbits.com/img/a3346174976_10.jpg",
    }
    keys = sorted(set(album_sources_genius.keys()) | set(album_sources_yt.keys()))
    for key in keys:
        if key in output_map:
            continue
        song_url = album_sources_genius.get(key, "")
        yt_url = album_sources_yt.get(key, "")
        artist, album = key
        fname_base = f"{slugify(artist)}_{slugify(album)}"
        target_jpg = COVERS / f"{fname_base}.jpg"
        target_svg = COVERS / f"{fname_base}.svg"

        img_url = genius_og_image(song_url)
        saved = False
        if img_url:
            try:
                data = fetch_bytes(img_url)
                target_jpg.write_bytes(data)
                output_map[key] = f"assets/covers/{target_jpg.name}"
                saved = True
            except Exception:
                saved = False
        if not saved and yt_url:
            thumb = yt_thumb_from_url(yt_url)
            if thumb:
                try:
                    data = fetch_bytes(thumb)
                    target_jpg.write_bytes(data)
                    output_map[key] = f"assets/covers/{target_jpg.name}"
                    saved = True
                except Exception:
                    saved = False
        if not saved:
            save_placeholder(target_svg, f"{key[0].title()} - {album}")
            output_map[key] = f"assets/covers/{target_svg.name}"

    return output_map


def build_quiz_data(mentions: list[dict], cover_map: dict[tuple[str, str], str]) -> dict:
    by_topo: dict[str, list[dict]] = {}
    songs_all: dict[str, dict] = {}

    for r in mentions:
        toponim_key = r.get('toponim_key', '')
        by_topo.setdefault(toponim_key, []).append(r)
        artist = r.get('artist', '')
        album = r.get('album', 'Unknown') or 'Unknown'
        skladba = r.get('skladba', '')
        sid = f"{artist}|{album}|{skladba}"
        songs_all[sid] = {
            'id': sid,
            'artist': artist,
            'album': album,
            'song': skladba,
            'label': f"{skladba} - {album} ({artist.title()})",
            'cover': cover_map.get((artist, album), ''),
        }

    all_song_ids = sorted(songs_all.keys())
    rng = random.Random(42)
    questions = []

    for topo_key, rows in sorted(by_topo.items()):
        sample = rows[0]
        correct = sorted({f"{r['artist']}|{r['album']}|{r['skladba']}" for r in rows})
        if not correct:
            continue

        pool_wrong = [sid for sid in all_song_ids if sid not in correct]
        rng.shuffle(pool_wrong)
        max_options = 6
        wrong_needed = max(2, min(max_options - len(correct), 4))
        wrong = pool_wrong[:wrong_needed]

        option_ids = correct + wrong
        rng.shuffle(option_ids)
        options = []
        for sid in option_ids:
            item = dict(songs_all[sid])
            item['correct'] = sid in correct
            options.append(item)

        questions.append(
            {
                'toponim_key': topo_key,
                'toponim': sample.get('toponim', topo_key),
                'lat': float(sample.get('lat') or 0.0),
                'lon': float(sample.get('lon') or 0.0),
                'correct_ids': correct,
                'options': options,
            }
        )

    rng.shuffle(questions)
    return {'questions': questions}


def to_int(v: str) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


def norm_song(v: str) -> str:
    t = unicodedata.normalize("NFKD", (v or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def album_sort_key(album_label: str) -> tuple[int, str, str]:
    parts = album_label.split(" - ", 1)
    artist = (parts[0] or "").strip().lower() if parts else ""
    album = (parts[1] or "").strip() if len(parts) > 1 else ""
    year = ALBUM_RELEASE_YEAR.get((artist, album))
    if album.lower() == "unknown":
        return (9999, artist, album)
    return (year if year is not None else 9000, artist, album)


def continent_for_toponym(row: dict) -> str:
    key = (row.get("toponim_key") or "").strip().lower()
    tip = (row.get("tip_lokacije") or "").strip().lower()
    if tip == "celina":
        return (row.get("toponim") or "").strip() or "Neznano"
    mapping = {
        "ljubljana": "Evropa", "kamnik": "Evropa", "duplica": "Evropa", "krsko": "Evropa", "bled": "Evropa", "koper": "Evropa",
        "milano": "Evropa", "rim": "Evropa", "berlin": "Evropa", "bejrut": "Azija", "tokio": "Azija", "honolulu": "Severna Amerika",
        "timbuktu": "Afrika", "saint_tropez": "Evropa", "san_francisco": "Severna Amerika", "el_paso": "Severna Amerika",
        "antwerpen": "Evropa", "odesa": "Evropa", "cernobil": "Evropa", "dubai": "Azija", "zanzibar": "Afrika",
        "sumatra": "Azija", "chicago": "Severna Amerika", "arizona": "Severna Amerika", "texas": "Severna Amerika",
        "babilon": "Azija", "amerika": "Severna Amerika", "mehika": "Severna Amerika", "italija": "Evropa",
        "bosna": "Evropa", "slovenija": "Evropa", "nemcija": "Evropa", "avstrija": "Evropa", "hrvaska": "Evropa",
        "francija": "Evropa", "srbija": "Evropa", "srilanka": "Azija", "maldivi": "Azija", "belem": "Južna Amerika",
        "las_vegas": "Severna Amerika", "vietnam": "Azija", "boston": "Severna Amerika", "tigris": "Azija",
    }
    return mapping.get(key, "Neznano")


def build_stats_payload(mentions: list[dict]) -> dict:
    by_album: dict[str, list[dict]] = defaultdict(list)
    toponym_songsets: dict[str, set[str]] = defaultdict(set)
    toponym_album_songsets: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    toponym_display: dict[str, str] = {}

    for r in mentions:
        artist = (r.get("artist") or "").strip().title()
        album = (r.get("album") or "Unknown").strip() or "Unknown"
        album_label = f"{artist} - {album}"
        by_album[album_label].append(r)
        key = (r.get("toponim_key") or "").strip().lower()
        if key:
            song_id = f"{r.get('artist','')}|{r.get('album','')}|{r.get('skladba','')}"
            toponym_songsets[key].add(song_id)
            toponym_album_songsets[key][album_label].add(song_id)
            toponym_display[key] = (r.get("toponim") or key).strip()

    albums = sorted(by_album.keys(), key=album_sort_key)
    rows = []
    cat_celine = []
    cat_drzave = []
    cat_kraji = []
    cat_slovenija = []
    continent_counts: dict[str, Counter] = {}
    global_unique = set()
    total_mentions_all = 0

    for alb in albums:
        rr = by_album[alb]
        total_mentions = len(rr)
        total_mentions_all += total_mentions
        uniq = {x.get("toponim_key", "") for x in rr}
        global_unique.update(uniq)
        uniq_countries = {x.get("toponim_key", "") for x in rr if x.get("tip_lokacije") == "država"}
        uniq_cities = {x.get("toponim_key", "") for x in rr if x.get("tip_lokacije") == "mesto/kraj"}
        uniq_cont = {x.get("toponim_key", "") for x in rr if x.get("tip_lokacije") == "celina"}

        cel = drz = kraj = slo = 0
        for x in rr:
            # Graphs 1/2 count a toponym once per song row, not raw repeats within lyrics.
            n = 1
            tip = (x.get("tip_lokacije") or "").strip().lower()
            key = (x.get("toponim_key") or "").strip().lower()
            if key in SLOVENIA_KEYS:
                slo += n
            elif tip == "celina":
                cel += n
            elif tip == "država":
                drz += n
            else:
                kraj += n
        cat_celine.append(cel)
        cat_drzave.append(drz)
        cat_kraji.append(kraj)
        cat_slovenija.append(slo)

        rows.append(
            {
                "album": alb,
                "mentions_total": total_mentions,
                "unique_toponyms": len(uniq),
                "unique_countries": len(uniq_countries),
                "unique_cities": len(uniq_cities),
                "unique_continents": len(uniq_cont),
            }
        )
        cc = Counter()
        for x in rr:
            c = continent_for_toponym(x)
            cc[c] += 1
        continent_counts[alb] = cc

    continents = sorted({c for cc in continent_counts.values() for c in cc.keys()})
    continent_matrix = {c: [continent_counts[a].get(c, 0) for a in albums] for c in continents}

    top5_keys = sorted(
        toponym_songsets.keys(),
        key=lambda k: (-len(toponym_songsets[k]), toponym_display.get(k, k)),
    )[:5]
    top5_words = [toponym_display.get(k, k) for k in top5_keys]
    top5_totals = [len(toponym_songsets[k]) for k in top5_keys]
    top5_album_matrix: dict[str, list[int]] = {}
    for alb in albums:
        top5_album_matrix[alb] = [len(toponym_album_songsets[k].get(alb, set())) for k in top5_keys]

    top_album = max(rows, key=lambda r: r["mentions_total"]) if rows else None
    summary = {
        "total_mentions_all": total_mentions_all,
        "total_unique_toponyms": len(global_unique),
        "total_unique_countries": len({r.get("toponim_key") for r in mentions if r.get("tip_lokacije") == "država"}),
        "total_unique_cities": len({r.get("toponim_key") for r in mentions if r.get("tip_lokacije") == "mesto/kraj"}),
        "albums_count": len(albums),
        "top_album": top_album["album"] if top_album else "",
        "top_album_mentions": top_album["mentions_total"] if top_album else 0,
    }
    return {
        "albums": albums,
        "rows": rows,
        "cat_mentions": {
            "celine": cat_celine,
            "drzave": cat_drzave,
            "kraji": cat_kraji,
            "slovenija": cat_slovenija,
        },
        "continents": continents,
        "continent_matrix": continent_matrix,
        "top5_words": top5_words,
        "top5_totals": top5_totals,
        "top5_album_matrix": top5_album_matrix,
        "summary": summary,
    }


def write_index() -> None:
    html = f'''<!doctype html>
<html lang="sl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MAPTTER</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Anton&display=swap" rel="stylesheet">
  <style>
    :root {{ --red:#c54444; --blue:#3555cc; --gray:#d3d7df; --ink:#0a0a0a; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; font-family:Arial, sans-serif; color:#111;
      background:
      radial-gradient(circle at 18% 18%, rgba(197,68,68,.22), transparent 45%),
      radial-gradient(circle at 82% 12%, rgba(53,85,204,.22), transparent 40%),
      linear-gradient(180deg,#17191d 0%, #111318 100%); }}
    .title {{ text-align:center; color:#f3f5fb; font-family:'Anton', Arial, sans-serif; font-size:92px; line-height:0.95; letter-spacing:1.5px; margin:4px 0 20px; text-transform:uppercase; text-shadow:0 10px 30px rgba(0,0,0,.45); }}
    .grid {{ display:grid; grid-template-columns:repeat(3, minmax(220px, 360px)); gap:24px;
      justify-content:center; align-content:center; min-height:100vh; padding:24px; }}
    .card {{ text-decoration:none; color:#111; border:2px solid #6b7691; border-radius:18px; overflow:hidden;
      box-shadow:0 10px 24px rgba(0,0,0,.30); background:#f2f4f8; }}
    .art {{ height:220px; position:relative; background: conic-gradient(from 90deg at 50% 50%, var(--red) 0 25%, var(--blue) 25% 50%, #ca4a4a 50% 75%, var(--gray) 75% 100%); }}
    .art::after {{ content:''; position:absolute; left:0; right:0; bottom:0; height:46%;
      background:linear-gradient(135deg, transparent 0 22%, var(--blue) 22% 33%, transparent 33% 44%, var(--blue) 44% 62%, transparent 62% 73%, var(--blue) 73% 83%, transparent 83% 100%); }}
    .txt {{ padding:16px; background:#f2f4f8; }}
    .t {{ font-size:28px; font-weight:900; margin:0 0 6px; text-transform:uppercase; letter-spacing:.5px; }}
    .s {{ margin:0; color:#333; font-size:14px; }}
    @media (max-width: 700px) {{ .grid {{ grid-template-columns:1fr; }} .art {{ height:200px; }} }}
  </style>
</head>
<body>
  <main>
    <h1 class="title">MAPTTER</h1>
    <section class="grid">
    <a class="card" href="zemljevid.html">
      <div class="art"></div>
      <div class="txt"><p class="t">Zemljevid</p><p class="s">Interaktivni prikaz toponimov</p></div>
    </a>
    <a class="card" href="quiz.html">
      <div class="art"></div>
      <div class="txt"><p class="t">Kviz</p><p class="s">Ugani skladbo po toponimu</p></div>
    </a>
    <a class="card" href="stats.html">
      <div class="art"></div>
      <div class="txt"><p class="t">Statistika</p><p class="s">Toponimi po albumih in celinah</p></div>
    </a>
    </section>
  </main>
</body>
</html>'''
    (SITE / 'index.html').write_text(html, encoding='utf-8')


def write_quiz(quiz_payload: dict) -> None:
    quiz_json = json.dumps(quiz_payload, ensure_ascii=False)
    html = f'''<!doctype html>
<html lang="sl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Toponim Kviz</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin=""/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
  <style>
    :root {{ --red:#c54444; --blue:#3555cc; --gray:#c9c9c9; --dark:#111; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Arial,sans-serif; color:#f1f1f1;
      background:
      radial-gradient(circle at 20% 20%, rgba(197,68,68,.23), transparent 42%),
      radial-gradient(circle at 80% 15%, rgba(53,85,204,.23), transparent 38%),
      linear-gradient(180deg,#17191d 0%, #111318 100%);
    }}
    .wrap {{ max-width:1200px; margin:0 auto; padding:20px; }}
    .top {{ display:flex; gap:12px; align-items:center; justify-content:space-between; margin-bottom:16px; }}
    .back {{ color:#fff; text-decoration:none; border:2px solid #7f8aa5; padding:8px 12px; border-radius:10px; font-weight:700; background:#1b1f28; }}
    .score {{ background:#1b1f28; border:1px solid #4a5369; padding:8px 12px; border-radius:10px; font-weight:700; }}
    .panel {{ display:grid; grid-template-columns: 420px 1fr; gap:18px; }}
    #map {{ height:420px; border:2px solid #5e6a86; border-radius:14px; overflow:hidden; }}
    .qbox {{ background:#171b24; border:2px solid #5e6a86; border-radius:14px; padding:14px; }}
    .qtitle {{ font-size:26px; margin:0 0 8px; font-weight:900; text-transform:uppercase; }}
    .qsub {{ margin:0 0 12px; color:#cad1df; font-weight:700; }}
    .opts {{ display:grid; grid-template-columns:repeat(2,minmax(240px,1fr)); gap:10px; }}
    .opt {{ display:flex; gap:10px; background:#f3f5f9; color:#111; border-radius:12px; padding:8px; border:2px solid transparent; }}
    .opt.correct{{ border-color:#22aa44; }}
    .opt.wrong{{ border-color:#cc2233; }}
    .opt img{{ width:64px; height:64px; object-fit:cover; border-radius:8px; background:#ddd; }}
    .opt label{{ display:block; font-size:13px; font-weight:700; }}
    .controls{{ margin-top:12px; display:flex; gap:10px; }}
    .result{{ margin-top:12px; padding:10px 12px; border-radius:10px; border:1px solid #4a5369; background:#121722; color:#d9e0ef; font-size:13px; }}
    .result.ok{{ border-color:#22aa44; color:#c9ffd8; }}
    .result.bad{{ border-color:#cc2233; color:#ffd3d8; }}
    button{{ border:0; border-radius:10px; padding:10px 14px; font-weight:800; cursor:pointer; }}
    .check{{ background:#cad1df; color:#111; }}
    .next{{ background:#3555cc; color:#fff; }}
    @media (max-width: 980px) {{ .panel {{ grid-template-columns:1fr; }} #map {{ height:320px; }} .opts {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <a class="back" href="index.html">Nazaj</a>
    <div class="score" id="score">0 / 0</div>
  </div>
  <div class="panel">
    <div id="map"></div>
    <div class="qbox">
      <h1 class="qtitle" id="toponim">Toponim</h1>
      <p class="qsub" id="hint">Izberi pravilno skladbo ali več skladb.</p>
      <div class="opts" id="options"></div>
      <div class="controls">
        <button class="check" id="checkBtn">Preveri</button>
        <button class="next" id="nextBtn">Naprej</button>
      </div>
      <div class="result" id="resultBox">Odgovori in klikni Preveri.</div>
    </div>
  </div>
</div>
<script>
const ALL_QUESTIONS = {quiz_json}.questions || [];
let data=[]; let idx=0; let solved=0; let score=0; let marker=null; let answeredCurrent=false;
const map=L.map('map',{{zoomControl:true}}).setView([46.15,14.99],3);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{attribution:'&copy; OpenStreetMap'}}).addTo(map);

function updateScore(){{document.getElementById('score').textContent=`${{score}} / ${{solved}}`;}}
function byId(id){{return document.getElementById(id);}}

function renderQuestion(){{
  const q=data[idx];
  answeredCurrent=false;
  byId('toponim').textContent=q.toponim;
  byId('hint').textContent='Izberi pravilno skladbo ali več skladb.';
  byId('resultBox').className='result';
  byId('resultBox').textContent='Odgovori in klikni Preveri.';
  const wrap=byId('options'); wrap.innerHTML='';
  q.options.forEach((o,i)=>{{
    const el=document.createElement('div'); el.className='opt'; el.dataset.correct=o.correct?'1':'0';
    el.innerHTML=`<input type="checkbox" id="o${{i}}" style="margin-top:6px" />
      <img src="${{o.cover || ''}}" alt="album" />
      <label for="o${{i}}">${{o.label}}</label>`;
    wrap.appendChild(el);
  }});
  if(marker) map.removeLayer(marker);
  marker=L.circleMarker([q.lat,q.lon],{{radius:12,color:'#fff',weight:3,fillColor:'#e01515',fillOpacity:0.8}}).addTo(map);
  marker.bindTooltip(q.toponim,{{permanent:true,direction:'top'}}).openTooltip();
  map.setView([q.lat,q.lon],4);
}}

function checkAnswer(){{
  if (answeredCurrent) return;
  const boxes=[...document.querySelectorAll('#options .opt')];
  const correctLabels=[];
  boxes.forEach((b,ix)=>{{
    const c=b.querySelector('input').checked;
    const isC=b.dataset.correct==='1';
    const label=b.querySelector('label')?.textContent || '';
    if(isC) correctLabels.push(label);
    b.classList.remove('correct','wrong');
    if(isC) b.classList.add('correct');
    if(c && !isC) b.classList.add('wrong');
  }});
  const ok = boxes.every((b)=>{{
    const c=b.querySelector('input').checked;
    const isC=b.dataset.correct==='1';
    return c===isC;
  }});
  answeredCurrent = true;
  solved += 1; if(ok) score += 1; updateScore();
  const rb = byId('resultBox');
  rb.className = ok ? 'result ok' : 'result bad';
  rb.innerHTML = (ok ? 'Pravilno.' : 'Napačno.') + '<br><b>Pravilni odgovori:</b><br>' + correctLabels.map(x => '• ' + x).join('<br>');
}}

function nextQuestion(){{
  idx += 1;
  if (idx >= data.length) {{
    idx = 0;
    data = shuffle([...ALL_QUESTIONS]).slice(0, Math.min(10, ALL_QUESTIONS.length));
  }}
  renderQuestion();
}}

function shuffle(arr){{
  for(let i=arr.length-1;i>0;i--){{const j=Math.floor(Math.random()*(i+1)); [arr[i],arr[j]]=[arr[j],arr[i]];}}
  return arr;
}}
data = shuffle([...ALL_QUESTIONS]).slice(0, Math.min(10, ALL_QUESTIONS.length));
if(!data.length){{ byId('hint').textContent='Ni vprašanj.'; }}
else {{ renderQuestion(); updateScore(); }}
byId('checkBtn').addEventListener('click',checkAnswer);
byId('nextBtn').addEventListener('click',nextQuestion);
</script>
</body>
</html>'''
    (SITE / 'quiz.html').write_text(html, encoding='utf-8')


def write_stats(stats_payload: dict) -> None:
    payload = json.dumps(stats_payload, ensure_ascii=False)
    html = f'''<!doctype html>
<html lang="sl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Statistika Toponimov</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    body {{
      margin:0;
      font-family: Arial, sans-serif;
      color:#eaf0ff;
      background:
        radial-gradient(circle at 16% 14%, rgba(197,68,68,.18), transparent 38%),
        radial-gradient(circle at 85% 18%, rgba(53,85,204,.18), transparent 36%),
        linear-gradient(180deg,#17191d 0%, #101219 100%);
    }}
    .wrap {{ width:min(96vw, 1700px); margin:0 auto; padding:18px 0 36px; }}
    .top {{ display:flex; justify-content:space-between; align-items:center; margin:0 1.4vw 16px; }}
    .back {{ color:#fff; text-decoration:none; border:2px solid #7f8aa5; padding:8px 12px; border-radius:10px; background:#1b1f28; font-weight:700; }}
    .title {{ font-size:34px; margin:0; font-weight:900; }}
    .intro {{ margin:0 1.4vw 14px; background:#171c28; border:1px solid #4a5369; border-radius:12px; padding:14px; line-height:1.45; }}
    .panel {{ min-height:100vh; display:flex; flex-direction:column; justify-content:center; padding:20px 1.4vw; }}
    .panel h2 {{ margin:0 0 8px; font-size:24px; }}
    .panel p {{ margin:0 0 12px; color:#c9d2e8; }}
    .plot {{ width:100%; height:72vh; background:#171c28; border:1px solid #4a5369; border-radius:12px; }}
    @media (max-width: 980px) {{ .plot {{ height:62vh; }} .panel {{ min-height:auto; padding-bottom:28px; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <h1 class="title">Statistika</h1>
      <a class="back" href="index.html">Nazaj</a>
    </div>
    <div class="intro" id="intro"></div>
    <section class="panel">
      <h2>1. Št. toponimov po albumih (po kategorijah)</h2>
      <p>Stacked prikaz pojavitev: celine, države, kraji in Slovenija (slovenski kraji).</p>
      <div id="chart-1" class="plot"></div>
    </section>
    <section class="panel">
      <h2>2. Celinske razporeditve po albumih</h2>
      <p>Primerjava pojavitev po celinah za vsak album.</p>
      <div id="chart-2" class="plot"></div>
    </section>
    <section class="panel">
      <h2>3. Top 5 toponimov po številu različnih pesmi</h2>
      <p>Na osi x so besede; y prikazuje število različnih pesmi, razdeljeno po albumih.</p>
      <div id="chart-3" class="plot"></div>
    </section>
  </div>
<script>
const STATS = {payload};
const rows = STATS.rows || [];
const albums = STATS.albums || [];
const s = STATS.summary || {{}};
const modeCfg = {{responsive:true, displayModeBar:false}};

document.getElementById('intro').innerHTML =
  `Skupaj smo zaznali <b>${{s.total_unique_toponyms || 0}}</b> unikatnih toponimov in <b>${{s.total_mentions_all || 0}}</b> vseh pojavitev. ` +
  `Od tega je <b>${{s.total_unique_countries || 0}}</b> držav in <b>${{s.total_unique_cities || 0}}</b> mest/krajev. ` +
  `V analizi je <b>${{s.albums_count || 0}}</b> albumov. Največ pojavitev ima album <b>${{s.top_album || '-'}}</b> (${{s.top_album_mentions || 0}}).`;

const commonLayout = {{
  paper_bgcolor:'#171c28',
  plot_bgcolor:'#171c28',
  font:{{color:'#eaf0ff'}},
  margin:{{l:65,r:20,t:18,b:95}},
  xaxis:{{tickangle:-28, automargin:true}},
  hoverlabel:{{namelength:-1}}
}};

const cat = STATS.cat_mentions || {{}};
Plotly.newPlot('chart-1', [
  {{x: albums, y: cat.celine || [], type:'bar', name:'Celine', marker:{{color:'#6C8EAD'}}, customdata: albums, hovertemplate:'Album: %{{customdata}}<br>Kategorija: Celine<br>Št. pojavnosti: %{{y}}<extra></extra>'}},
  {{x: albums, y: cat.drzave || [], type:'bar', name:'Države', marker:{{color:'#5B8A72'}}, customdata: albums, hovertemplate:'Album: %{{customdata}}<br>Kategorija: Države<br>Št. pojavnosti: %{{y}}<extra></extra>'}},
  {{x: albums, y: cat.kraji || [], type:'bar', name:'Kraji', marker:{{color:'#C98C5A'}}, customdata: albums, hovertemplate:'Album: %{{customdata}}<br>Kategorija: Kraji<br>Št. pojavnosti: %{{y}}<extra></extra>'}},
  {{x: albums, y: cat.slovenija || [], type:'bar', name:'Slovenija', marker:{{color:'#3F6FA6'}}, customdata: albums, hovertemplate:'Album: %{{customdata}}<br>Kategorija: Slovenija<br>Št. pojavnosti: %{{y}}<extra></extra>'}}
], {{
  ...commonLayout,
  barmode:'stack',
  yaxis:{{title:'Št. pojavnosti'}}
}}, modeCfg);

const contNames = STATS.continents || [];
const contMatrix = STATS.continent_matrix || {{}};
const contColors = ['#5E81AC','#A3BE8C','#EBCB8B','#D08770','#B48EAD','#88C0D0','#81A1C1','#8FBCBB'];
const tracesCont = contNames.map((c, i) => ({{
  x: albums,
  y: contMatrix[c] || albums.map(()=>0),
  type:'bar',
  name:c,
  marker:{{color: contColors[i % contColors.length]}},
  customdata: albums,
  hovertemplate:'Album: %{{customdata}}<br>Celina: %{{fullData.name}}<br>Št. pojavnosti: %{{y}}<extra></extra>'
}}));
Plotly.newPlot('chart-2', tracesCont, {{
  ...commonLayout,
  barmode:'stack',
  yaxis:{{title:'Št. pojavnosti'}}
}}, modeCfg);

const words = STATS.top5_words || [];
const topAlbumMatrix = STATS.top5_album_matrix || {{}};
const albumColors = ['#5E81AC','#BF616A','#A3BE8C','#D08770','#B48EAD','#88C0D0','#EBCB8B','#81A1C1','#8FBCBB','#C0C6CF'];
const tracesTop = albums.map((alb, i) => ({{
  x: words,
  y: topAlbumMatrix[alb] || words.map(() => 0),
  type:'bar',
  name: alb,
  marker: {{color: albumColors[i % albumColors.length]}},
  customdata: Array(words.length).fill(alb),
  hovertemplate: 'Album: %{{customdata}}<br>Toponim: %{{x}}<br>Št. različnih pesmi: %{{y}}<extra></extra>'
}}));
Plotly.newPlot('chart-3', tracesTop, {{
  ...commonLayout,
  barmode:'stack',
  xaxis:{{tickangle:-18}},
  yaxis:{{title:'Št. različnih pesmi'}}
}}, modeCfg);
</script>
</body>
</html>'''
    (SITE / 'stats.html').write_text(html, encoding='utf-8')


def main() -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)

    mentions = read_csv(ROOT / 'toponym_mentions_all_artists.csv')
    mentions = [r for r in mentions if norm_song(r.get("skladba", "")) != "ab raylight"]
    matter_songs = read_csv(Path('output') / 'matter' / 'db' / 'songs.csv')
    tunja_songs = read_csv(Path('output') / 'tunja' / 'db' / 'songs.csv')

    cover_map = build_album_covers(mentions, matter_songs, tunja_songs)
    quiz = build_quiz_data(mentions, cover_map)
    stats = build_stats_payload(mentions)
    (SITE / 'quiz_data.json').write_text(json.dumps(quiz, ensure_ascii=False, indent=2), encoding='utf-8')

    src_map = ROOT / "toponym_map_all_artists.html"
    dst_map = SITE / "zemljevid.html"
    if src_map.exists():
        shutil.copyfile(src_map, dst_map)
        localize_map_assets(dst_map)
    else:
        dst_map.write_text(
            "<!doctype html><meta charset='utf-8'><title>Zemljevid</title>"
            "<body style='font-family:Arial;padding:20px'>"
            "Zemljevid še ni generiran. Najprej zaženi build_map_local_enhanced.py"
            "</body>",
            encoding="utf-8",
        )

    write_index()
    write_quiz(quiz)
    write_stats(stats)

    print(f'Site: {(SITE / "index.html").resolve()}')
    print(f'Map: {(SITE / "zemljevid.html").resolve()}')
    print(f'Quiz: {(SITE / "quiz.html").resolve()}')
    print(f'Stats: {(SITE / "stats.html").resolve()}')
    print(f'Questions: {len(quiz.get("questions", []))}')


if __name__ == '__main__':
    main()

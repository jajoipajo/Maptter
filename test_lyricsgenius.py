import argparse
import os
import sys
from pathlib import Path

import lyricsgenius


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal test script for lyricsgenius.")
    parser.add_argument("--title", required=True, help="Song title")
    parser.add_argument("--artist", required=True, help="Artist name")
    parser.add_argument(
        "--outdir",
        default="output",
        help="Directory where song files will be saved (default: output)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.getenv("GENIUS_ACCESS_TOKEN")
    if not token:
        token = load_token_from_env_file(Path(".env"))
    if not token:
        print(
            "Missing GENIUS_ACCESS_TOKEN (set env var or put it in .env).",
            file=sys.stderr,
        )
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    genius = lyricsgenius.Genius(token)
    genius.verbose = True
    genius.remove_section_headers = True
    genius.skip_non_songs = True
    genius.excluded_terms = ["(Remix)", "(Live)"]

    song = genius.search_song(args.title, args.artist)
    if song is None:
        print(f"Song not found: {args.artist} - {args.title}", file=sys.stderr)
        return 2

    txt_path = outdir / f"{song.artist} - {song.title}.txt"
    json_path = outdir / f"{song.artist} - {song.title}.json"

    txt_path.write_text(song.lyrics, encoding="utf-8")
    song.save_lyrics(filename=str(json_path), overwrite=True)

    print(f"Saved TXT:  {txt_path}")
    print(f"Saved JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Post the latest KVCU spin from Spinitron to Mastodon, with dedupe state."""

from __future__ import annotations

import argparse
import html
import json
import logging
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_SPINITRON_URL = (
    "https://widgets.spinitron.com/widget/now-playing-v2?station=kvcu&num=1&meta=1"
)
DEFAULT_FALLBACK_URL = "https://spinitron.com/KVCU/"
DEFAULT_STATE_FILE = "last_spin_id.txt"
DEFAULT_TIMEOUT = 20


@dataclass
class Spin:
    unique_id: str
    played_time: str
    dj: str
    song: str
    artist: str
    album: str
    album_art_url: Optional[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch current spin data from Spinitron and post to Mastodon, "
            "skipping duplicates based on a saved spin ID."
        )
    )
    parser.add_argument("--spinitron-url", default=DEFAULT_SPINITRON_URL)
    parser.add_argument("--fallback-url", default=DEFAULT_FALLBACK_URL)
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    parser.add_argument(
        "--env-file",
        default="",
        help="Optional path to a .env file (default: .env next to this script if present).",
    )
    parser.add_argument("--visibility", default="public")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def load_dotenv_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "kvcu-mastodon-bot/1.0"})
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def strip_tags(raw: str) -> str:
    no_tags = re.sub(r"<[^>]+>", "", raw, flags=re.DOTALL)
    return html.unescape(" ".join(no_tags.split())).strip()


def extract_attr(open_tag: str, attr_name: str) -> str:
    m = re.search(rf'{re.escape(attr_name)}="([^"]*)"', open_tag)
    return html.unescape(m.group(1)).strip() if m else ""


def normalize_album_art_url(url: str) -> str:
    updated = url.replace("200x200", "800x800")
    updated = re.sub(r"/\d+x\d+(bb)?(?=\.)", r"/800x800\1", updated, count=1)
    return updated


def parse_spin(html_text: str) -> Spin:
    row_match = re.search(
        r"(<tr[^>]*class=\"[^\"]*\bspin-item\b[^\"]*\"[^>]*>)(.*?)</tr>",
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not row_match:
        raise ValueError("No spin row found (selector: tr.spin-item)")

    row_open = row_match.group(1)
    row_inner = row_match.group(2)

    spin_key = extract_attr(row_open, "data-key")
    data_spin_raw = extract_attr(row_open, "data-spin")
    spin_i = ""
    if data_spin_raw:
        try:
            spin_i = str(json.loads(data_spin_raw).get("i", "")).strip()
        except json.JSONDecodeError:
            spin_i = ""

    row_id = extract_attr(row_open, "id")
    unique_id = spin_key or spin_i or row_id
    if not unique_id:
        raise ValueError("Could not find a stable unique ID for the current spin")

    def field(pattern: str, default: str = "") -> str:
        m = re.search(pattern, row_inner, flags=re.DOTALL | re.IGNORECASE)
        return strip_tags(m.group(1)) if m else default

    played_time = field(r'<td[^>]*class="[^"]*\bspin-time\b[^"]*"[^>]*>(.*?)</td>', "Unknown time")
    song = field(r'<span[^>]*class="[^"]*\bsong\b[^"]*"[^>]*>(.*?)</span>', "Unknown song")
    artist = field(r'<span[^>]*class="[^"]*\bartist\b[^"]*"[^>]*>(.*?)</span>', "Unknown artist")
    album = field(r'<span[^>]*class="[^"]*\brelease\b[^"]*"[^>]*>(.*?)</span>', "Unknown album")

    dj_match = re.search(
        r'<div[^>]*class="[^"]*\bpl\b[^"]*\bdescription\b[^"]*"[^>]*>.*?<p[^>]*>\s*<strong[^>]*>(.*?)</strong>',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not dj_match:
        dj_match = re.search(
            r'<div[^>]*class="[^"]*\bdescription\b[^"]*"[^>]*>.*?<p[^>]*>\s*<strong[^>]*>(.*?)</strong>',
            html_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
    dj = strip_tags(dj_match.group(1)) if dj_match else "Unknown DJ"

    art_match = re.search(
        r'<td[^>]*class="[^"]*\bspin-art\b[^"]*"[^>]*>.*?<img[^>]*src="([^"]+)"',
        row_inner,
        flags=re.DOTALL | re.IGNORECASE,
    )
    album_art_url = html.unescape(art_match.group(1)).strip() if art_match else ""
    if "placeholders/loudspeaker.svg" in album_art_url:
        album_art_url = ""
    elif album_art_url:
        album_art_url = normalize_album_art_url(album_art_url)

    return Spin(
        unique_id=unique_id,
        played_time=played_time,
        dj=dj,
        song=song,
        artist=artist,
        album=album,
        album_art_url=album_art_url or None,
    )


def load_last_spin_id(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def save_last_spin_id(path: Path, spin_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{spin_id}\n", encoding="utf-8")


def format_played_time(raw_time: str) -> str:
    text = raw_time.strip()
    match = re.search(r"(\d{1,2}:\d{2})\s*([APMapm]{2})", text)
    if match:
        return f"{match.group(1)}{match.group(2).lower()}"
    return text.replace(" ", "").lower()


def to_hashtag(value: str) -> str:
    """Convert free-form text into a Mastodon-friendly hashtag token."""
    # Keep letters/numbers/underscore, remove punctuation, and collapse spaces.
    cleaned = re.sub(r"#", "", value, flags=re.UNICODE)
    cleaned = re.sub(r"[^\w\s]", "", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "", cleaned, flags=re.UNICODE).strip("_")
    return f"#{cleaned}" if cleaned else ""


def build_status(spin: Spin) -> str:
    played_time = format_played_time(spin.played_time)
    status = (
        f"🎶 {played_time} {spin.song} "
        f"by {spin.artist} from {spin.album}.\n{spin.dj}"
    )
    hashtags: list[str] = []
    for source in (spin.artist, spin.dj):
        tag = to_hashtag(source)
        if tag and tag not in hashtags:
            hashtags.append(tag)
    if hashtags:
        status = f"{status}\n{' '.join(hashtags)}"
    return status


def fetch_binary(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "kvcu-mastodon-bot/1.0"})
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
        content = resp.read()
        content_type = resp.headers.get_content_type() or "application/octet-stream"
    return content, content_type


def build_multipart_form(fields: dict[str, str], file_field: str, filename: str, data: bytes, mime: str) -> tuple[bytes, str]:
    boundary = f"----kvcu{uuid.uuid4().hex}"
    crlf = b"\r\n"
    body = bytearray()

    for key, value in fields.items():
        body.extend(f"--{boundary}".encode("utf-8"))
        body.extend(crlf)
        body.extend(f'Content-Disposition: form-data; name="{key}"'.encode("utf-8"))
        body.extend(crlf)
        body.extend(crlf)
        body.extend(value.encode("utf-8"))
        body.extend(crlf)

    body.extend(f"--{boundary}".encode("utf-8"))
    body.extend(crlf)
    body.extend(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"'.encode("utf-8")
    )
    body.extend(crlf)
    body.extend(f"Content-Type: {mime}".encode("utf-8"))
    body.extend(crlf)
    body.extend(crlf)
    body.extend(data)
    body.extend(crlf)

    body.extend(f"--{boundary}--".encode("utf-8"))
    body.extend(crlf)
    return bytes(body), boundary


def api_post_json(base_url: str, token: str, api_path: str, payload: bytes, content_type: str) -> dict:
    url = f"{base_url.rstrip('/')}{api_path}"
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "User-Agent": "kvcu-mastodon-bot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
        raw = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
    return json.loads(raw)


def upload_album_art(base_url: str, token: str, art_url: str, alt_text: str) -> str:
    file_bytes, content_type = fetch_binary(art_url)
    ext = mimetypes.guess_extension(content_type) or ".img"
    filename = f"album_art{ext}"
    body, boundary = build_multipart_form(
        fields={"description": alt_text},
        file_field="file",
        filename=filename,
        data=file_bytes,
        mime=content_type,
    )
    result = api_post_json(
        base_url,
        token,
        "/api/v2/media",
        payload=body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    media_id = str(result.get("id", "")).strip()
    if not media_id:
        raise ValueError("Mastodon media upload succeeded but no media ID was returned")
    return media_id


def post_status(base_url: str, token: str, status_text: str, visibility: str, media_id: Optional[str]) -> str:
    params: dict[str, object] = {
        "status": status_text,
        "visibility": visibility,
    }
    if media_id:
        params["media_ids[]"] = [media_id]

    encoded = urllib.parse.urlencode(params, doseq=True).encode("utf-8")
    result = api_post_json(
        base_url,
        token,
        "/api/v1/statuses",
        payload=encoded,
        content_type="application/x-www-form-urlencoded",
    )
    return str(result.get("url") or result.get("uri") or "")


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    script_dir = Path(__file__).resolve().parent
    env_path = Path(args.env_file).expanduser() if args.env_file else script_dir / ".env"
    load_dotenv_file(env_path)

    mastodon_base_url = os.getenv("MASTODON_BASE_URL", "").strip()
    mastodon_token = os.getenv("MASTODON_ACCESS_TOKEN", "").strip()
    if not args.dry_run and (not mastodon_base_url or not mastodon_token):
        logging.error("Missing MASTODON_BASE_URL or MASTODON_ACCESS_TOKEN environment variable")
        return 2

    state_file = Path(args.state_file)

    html_text = ""
    source_url = args.spinitron_url
    try:
        html_text = fetch_html(args.spinitron_url)
    except urllib.error.URLError as err:
        logging.warning("Primary URL failed (%s): %s", args.spinitron_url, err)
        source_url = args.fallback_url
        try:
            html_text = fetch_html(args.fallback_url)
        except urllib.error.URLError as fallback_err:
            logging.error("Fallback URL failed (%s): %s", args.fallback_url, fallback_err)
            return 1

    try:
        spin = parse_spin(html_text)
    except ValueError as err:
        logging.error("Could not parse spin data from %s: %s", source_url, err)
        return 1

    logging.info("Current spin unique ID: %s", spin.unique_id)
    last_spin_id = load_last_spin_id(state_file)
    if spin.unique_id == last_spin_id:
        logging.info("Duplicate spin ID; skipping post")
        return 0

    status_text = build_status(spin)
    logging.info("Prepared status:\n%s", status_text)
    if spin.album_art_url:
        logging.info("Album art URL for post: %s", spin.album_art_url)
    else:
        logging.info("Album art URL for post: none (placeholder or unavailable)")

    if args.dry_run:
        logging.info("Dry run enabled; skipping Mastodon post")
        return 0

    media_id: Optional[str] = None
    if spin.album_art_url:
        alt_text = f"{status_text} This is the cover of {spin.album}."
        try:
            media_id = upload_album_art(
                base_url=mastodon_base_url,
                token=mastodon_token,
                art_url=spin.album_art_url,
                alt_text=alt_text,
            )
            logging.info("Uploaded album art; media ID: %s", media_id)
        except Exception as err:
            logging.warning("Album art upload failed; posting without media: %s", err)

    try:
        post_url = post_status(
            base_url=mastodon_base_url,
            token=mastodon_token,
            status_text=status_text,
            visibility=args.visibility,
            media_id=media_id,
        )
    except Exception as err:
        logging.error("Mastodon post failed: %s", err)
        return 1

    save_last_spin_id(state_file, spin.unique_id)
    logging.info("Posted successfully%s", f": {post_url}" if post_url else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import os
import random
import re
import time
import requests
import yt_dlp
from dataclasses import dataclass
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

load_dotenv()


@dataclass
class VideoData:
    transcript: str
    url: str
    title: str
    channel: str
    thumbnail: str
    duration: int  # seconds


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from any YouTube URL format."""
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11})",
        r"(?:youtu\.be\/)([0-9A-Za-z_-]{11})",
        r"(?:embed\/)([0-9A-Za-z_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from URL: {url}")


def _fetch_webshare_proxy_list() -> list[dict]:
    """Fetch (and cache) the current Direct-mode proxy list from Webshare's account API."""
    PROXY_LIST_TTL = 300
    proxy_list_cache = {"proxies": [], "fetched_at": 0.0}
    now = time.time()
    if proxy_list_cache["proxies"] and (now - proxy_list_cache["fetched_at"] < PROXY_LIST_TTL):
        return proxy_list_cache["proxies"]

    api_key = os.environ.get("WEBSHARE_API_KEY")
    if not api_key:
        return []

    response = requests.get(
        "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100",
        headers={"Authorization": f"Token {api_key}"},
        timeout=10,
    )
    response.raise_for_status()
    results = response.json().get("results", [])

    proxy_list_cache["proxies"] = results
    proxy_list_cache["fetched_at"] = now
    return results


def _get_webshare_proxy_url() -> str | None:
    proxies = _fetch_webshare_proxy_list()
    if not proxies:
        return None

    p = random.choice(proxies)
    return f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}/"


def _get_webshare_proxies() -> dict | None:
    proxy_url = _get_webshare_proxy_url()
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def _build_transcript_api() -> YouTubeTranscriptApi:
    proxy_url = _get_webshare_proxy_url()
    if proxy_url:
        return YouTubeTranscriptApi(
            proxy_config=GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)
        )
    return YouTubeTranscriptApi()


def _get_transcript_via_transcript_api(video_id: str) -> str:
    ytt_api = _build_transcript_api()
    fetched = ytt_api.fetch(video_id, languages=["en"])

    segments = []
    for entry in fetched:
        text = getattr(entry, "text", None)
        if text is None and isinstance(entry, dict):
            text = entry.get("text", "")
        if text and text.strip():
            segments.append(text)

    transcript = " ".join(segments).strip()
    if not transcript:
        raise ValueError("Empty transcript from youtube-transcript-api")
    return transcript


def _get_metadata_via_ytdlp(url: str, proxies: dict | None) -> dict:
    ydl_opts = {"quiet": True, "skip_download": True}
    if proxies:
        ydl_opts["proxy"] = proxies["https"]
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return {
        "title": info.get("title", "Untitled"),
        "channel": info.get("uploader", "Unknown"),
        "thumbnail": info.get("thumbnail", ""),
        "duration": info.get("duration", 0),
    }


def _get_transcript_via_ytdlp(url: str, proxies: dict | None) -> str:
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "json3",
    }
    if proxies:
        ydl_opts["proxy"] = proxies["https"]
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    subs = info.get("subtitles") or info.get("automatic_captions")
    if not subs or "en" not in subs:
        raise ValueError("No English subtitles found via yt-dlp")

    subtitle_url = subs["en"][0]["url"]
    print(f"Fetching transcript from: {subtitle_url}")
    data = requests.get(subtitle_url, proxies=proxies, timeout=15).json()

    segments = []
    for event in data.get("events", []):
        for seg in event.get("segs", []):
            text = seg.get("utf8", "")
            if text.strip():
                segments.append(text)

    transcript = " ".join(segments).strip()
    if not transcript:
        raise ValueError("Transcript is empty after parsing")
    return transcript


def get_video_data(url: str) -> VideoData:
    """
    Fetch video metadata and transcript.

    Metadata always comes from yt-dlp.
    Transcript: tries youtube-transcript-api first (fast, works locally
    with no config, and on servers once WEBSHARE_API_KEY is set in .env),
    then falls back to yt-dlp.
    """
    video_id = extract_video_id(url)
    proxies = _get_webshare_proxies()

    metadata = _get_metadata_via_ytdlp(url, proxies)

    try:
        print("Fetching transcript via youtube-transcript-api...")
        transcript = _get_transcript_via_transcript_api(video_id)
        print("youtube-transcript-api success")
    except Exception as e:
        print(f"youtube-transcript-api failed: {e} — trying yt-dlp fallback")
        transcript = _get_transcript_via_ytdlp(url, proxies)

    return VideoData(
        transcript=transcript,
        url=url,
        title=metadata["title"],
        channel=metadata["channel"],
        thumbnail=metadata["thumbnail"],
        duration=metadata["duration"],
    )


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    video = get_video_data(url)

    print(f"\nTitle:      {video.title}")
    print(f"Channel:    {video.channel}")
    print(f"Duration:   {video.duration}s")
    print(f"Thumbnail:  {video.thumbnail}")
    print(f"Transcript: {len(video.transcript.split())} words")
    print(f"Preview:    {video.transcript[:200]}...")
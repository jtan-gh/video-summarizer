import os
import re
import requests
import yt_dlp
from dataclasses import dataclass
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

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


def _get_webshare_credentials() -> tuple[str, str]:
    username = os.environ.get("WEBSHARE_PROXY_USERNAME")
    password = os.environ.get("WEBSHARE_PROXY_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD not set. "
            "Get these from https://dashboard.webshare.io/proxy/settings "
            "(the residential rotating pair, not the Direct-mode list)."
        )
    return username, password


def _get_webshare_proxies() -> dict:
    """requests/yt-dlp style proxies dict, routed through the residential
    rotating gateway."""
    username, password = _get_webshare_credentials()
    # The "-rotate" suffix tells Webshare's gateway to hand back a random
    # IP from the pool each connection, instead of a fixed identity.
    if not username.endswith("-rotate"):
        username = f"{username}-rotate"
    proxy_url = f"http://{username}:{password}@p.webshare.io:80/"
    print(f"[proxy] routing through residential gateway p.webshare.io:80 (user={username})")
    return {"http": proxy_url, "https": proxy_url}


def _build_transcript_api() -> YouTubeTranscriptApi:
    """
    Build a YouTubeTranscriptApi client routed through Webshare's
    residential rotating proxy.
    """
    username, password = _get_webshare_credentials()
    return YouTubeTranscriptApi(
        proxy_config=WebshareProxyConfig(
            proxy_username=username,
            proxy_password=password,
        )
    )
    # return YouTubeTranscriptApi()  # local/no-proxy fallback — disabled for now


def _get_transcript_via_transcript_api(video_id: str) -> str:
    """
    Fetch the transcript using the youtube-transcript-api library, routed
    through the Webshare residential proxy.
    """
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


def _get_metadata_via_ytdlp(url: str, proxies: dict) -> dict:
    """Fetch title/channel/thumbnail/duration using yt-dlp."""
    ydl_opts = {"quiet": True, "skip_download": True, "proxy": proxies["https"]}
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


def _get_transcript_via_ytdlp(url: str, proxies: dict) -> str:
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "json3",
        "proxy": proxies["https"],
    }
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    subs = info.get("subtitles") or info.get("automatic_captions")
    if not subs or "en" not in subs:
        raise ValueError("No English subtitles found via yt-dlp")

    subtitle_url = subs["en"][0]["url"]
    print(f"Fetching transcript from: {subtitle_url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(subtitle_url, proxies=proxies, headers=headers, timeout=15)
    print(f"[proxy] subtitle fetch status={resp.status_code} bytes={len(resp.content)}")

    if resp.status_code != 200 or not resp.content:
        raise ValueError(
            f"Subtitle fetch failed or empty "
            f"(status={resp.status_code}, body preview={resp.text[:200]!r})"
        )

    data = resp.json()

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
    Transcript: tries youtube-transcript-api first, then falls back to
    yt-dlp's own subtitle extraction if that fails.

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
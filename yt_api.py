import os
import re
import requests
import yt_dlp
from dataclasses import dataclass
from dotenv import load_dotenv

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


# ── YouTube Data API v3 ────────────────────────────────────────────────────────


def _get_metadata_via_api(video_id: str) -> dict:
    """Fetch video metadata using YouTube Data API v3."""
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY not set")

    response = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={
            "key": api_key,
            "id": video_id,
            "part": "snippet,contentDetails",
        },
    )
    response.raise_for_status()
    data = response.json()

    if not data.get("items"):
        raise ValueError(f"Video not found: {video_id}")

    item = data["items"][0]
    snippet = item["snippet"]

    # Parse ISO 8601 duration (PT1H2M3S) to seconds
    duration_str = item["contentDetails"]["duration"]
    duration = _parse_duration(duration_str)

    return {
        "title": snippet["title"],
        "channel": snippet["channelTitle"],
        "thumbnail": snippet["thumbnails"]
        .get("maxres", snippet["thumbnails"].get("high", {}))
        .get("url", ""),
        "duration": duration,
    }


def _get_transcript_via_api(video_id: str) -> str:
    """Fetch captions using YouTube Data API v3."""
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY not set")

    # List available caption tracks
    response = requests.get(
        "https://www.googleapis.com/youtube/v3/captions",
        params={
            "key": api_key,
            "videoId": video_id,
            "part": "snippet",
        },
    )
    response.raise_for_status()
    captions = response.json()

    # Find English caption track
    caption_id = None
    for item in captions.get("items", []):
        lang = item["snippet"]["language"]
        if lang.startswith("en"):
            caption_id = item["id"]
            break

    if not caption_id:
        raise ValueError("No English captions found via API")

    # Download the caption track
    caption_response = requests.get(
        f"https://www.googleapis.com/youtube/v3/captions/{caption_id}",
        params={
            "key": api_key,
            "tfmt": "srt",
        },
    )
    caption_response.raise_for_status()

    return _parse_srt(caption_response.text)


def _parse_duration(iso_duration: str) -> int:
    """Convert ISO 8601 duration string to seconds."""
    pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
    match = re.match(pattern, iso_duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _parse_srt(srt_text: str) -> str:
    """Strip SRT timestamps and return clean transcript text."""
    # Remove sequence numbers, timestamps, and blank lines
    lines = srt_text.splitlines()
    output = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.isdigit():
            continue
        if "-->" in line:
            continue
        output.append(line)
    return " ".join(output)


# ── yt-dlp fallback ───────────────────────────────────────────────────────────


def _get_video_data_via_ytdlp(url: str) -> VideoData:
    """Fallback: fetch metadata and transcript using yt-dlp."""
    print("Falling back to yt-dlp...")

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "json3",
    }

    # Use cookies file if available (for production)
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    subs = info.get("subtitles") or info.get("automatic_captions")
    if not subs or "en" not in subs:
        raise ValueError("No English subtitles found via yt-dlp")

    subtitle_url = subs["en"][0]["url"]
    print(f"Fetching transcript from: {subtitle_url}")
    data = requests.get(subtitle_url).json()

    segments = []
    for event in data.get("events", []):
        for seg in event.get("segs", []):
            text = seg.get("utf8", "")
            if text.strip():
                segments.append(text)

    transcript = " ".join(segments).strip()
    if not transcript:
        raise ValueError("Transcript is empty after parsing")

    return VideoData(
        transcript=transcript,
        url=url,
        title=info.get("title", "Untitled"),
        channel=info.get("uploader", "Unknown"),
        thumbnail=info.get("thumbnail", ""),
        duration=info.get("duration", 0),
    )


# ── Public interface ──────────────────────────────────────────────────────────


def get_video_data(url: str) -> VideoData:
    """
    Fetch video metadata and transcript.
    Tries YouTube Data API v3 first, falls back to yt-dlp.
    """
    video_id = extract_video_id(url)

    # ── Try YouTube Data API first ─────────────────────────────
    if os.environ.get("YOUTUBE_API_KEY"):
        try:
            print("Fetching via YouTube Data API...")
            metadata = _get_metadata_via_api(video_id)
            transcript = _get_transcript_via_api(video_id)

            if not transcript.strip():
                raise ValueError("Empty transcript from API")

            print("YouTube API success")
            return VideoData(
                transcript=transcript,
                url=url,
                title=metadata["title"],
                channel=metadata["channel"],
                thumbnail=metadata["thumbnail"],
                duration=metadata["duration"],
            )

        except Exception as e:
            print(f"YouTube API failed: {e} — trying yt-dlp fallback")

    # ── Fall back to yt-dlp ────────────────────────────────────
    return _get_video_data_via_ytdlp(url)


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

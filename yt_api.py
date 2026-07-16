from dataclasses import dataclass
import yt_dlp
import requests

@dataclass
class VideoData:
    transcript:  str
    url:         str
    title:       str
    channel:     str
    thumbnail:   str
    duration:    int  # seconds

def get_video_data(url: str) -> VideoData:
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    subs = info.get("subtitles") or info.get("automatic_captions")

    if not subs or "en" not in subs:
        raise ValueError("No English subtitles found for this video.")

    subtitle_url = subs["en"][0]["url"]
    print(f"Fetching transcript from: {subtitle_url}")
    data = requests.get(subtitle_url).json()

    segments = []
    for event in data.get("events", []):
        for seg in event.get("segs", []):
            text = seg.get("utf8", "")
            if text.strip():
                segments.append(text)
    transcript = " ".join(segments).replace("\n", " ").strip()

    if not transcript:
        raise ValueError("Transcript is empty after parsing.")

    return VideoData(
        transcript=transcript,
        url=url,
        title=info.get("title", "Untitled"),
        channel=info.get("uploader", "Unknown"),
        thumbnail=info.get("thumbnail", ""),
        duration=info.get("duration", 0),
    )

if __name__ == "__main__":
    urls = [
        "https://www.youtube.com/watch?v=wdzmWO27Ubo&t=309s",
        # "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]
    videos = [get_video_data(url) for url in urls]
    print(videos)
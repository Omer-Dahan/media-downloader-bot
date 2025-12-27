#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - __init__.py.py

from urllib.parse import urlparse
from typing import Any, Callable

from engine.generic import YoutubeDownload
from engine.direct import DirectDownload
from engine.pixeldrain import pixeldrain_download
from engine.instagram import InstagramDownload
from engine.krakenfiles import krakenfiles_download
from engine.reddit import RedditDownload


def youtube_entrance(client, bot_message, url):
    youtube = YoutubeDownload(client, bot_message, url)
    youtube.start()


def youtube_entrance_with_quality(client, bot_message, url, quality: str):
    """Start YouTube download with specific quality selection.
    
    Args:
        quality: One of '1080', '720', '480', '360', 'audio'
    """
    youtube = YoutubeDownload(client, bot_message, url, selected_quality=quality)
    youtube.start()


def get_youtube_video_info(url: str) -> dict | None:
    """Extract video info without downloading.
    
    Returns dict with 'title' and 'duration' or None on error.
    """
    return YoutubeDownload.extract_info(url)


def direct_entrance(client, bot_message, url):
    dl = DirectDownload(client, bot_message, url)
    dl.start()


# --- Handler for the Instagram class, to make the interface consistent ---
def instagram_handler(client: Any, bot_message: Any, url: str) -> None:
    """A wrapper to handle the InstagramDownload class."""
    downloader = InstagramDownload(client, bot_message, url)
    downloader.start()


# --- Handler for Reddit ---
def reddit_handler(client: Any, bot_message: Any, url: str) -> None:
    """A wrapper to handle the RedditDownload class."""
    downloader = RedditDownload(client, bot_message, url)
    downloader.start()


DOWNLOADER_MAP: dict[str, Callable[[Any, Any, str], Any]] = {
    "pixeldrain.com": pixeldrain_download,
    "krakenfiles.com": krakenfiles_download,
    "instagram.com": instagram_handler,
    "reddit.com": reddit_handler,
    "redd.it": reddit_handler,
}

def special_download_entrance(client: Any, bot_message: Any, url: str) -> Any:
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            raise ValueError(f"לא ניתן לחלץ hostname של הקישור: {url}")
    except (ValueError, TypeError) as e:
        raise ValueError(f"פורמט קישור לא תקין: {url}") from e

    # Handle the special case for YouTube URLs first.
    if hostname.endswith("youtube.com") or hostname == "youtu.be":
        raise ValueError("לקישורי יוטיוב, פשוט שלח את הקישור ישירות.")

    # Iterate through the map to find a matching handler.
    for domain_suffix, handler_function in DOWNLOADER_MAP.items():
        if hostname.endswith(domain_suffix):
            return handler_function(client, bot_message, url)

    raise ValueError(f"לא נמצא מוריד מתאים עבור: {hostname}")

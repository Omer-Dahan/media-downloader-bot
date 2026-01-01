#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - tiktok.py
# TikTok downloader with yt-dlp primary and tiktokapipy fallback

import logging
import pathlib
import requests
from typing import Optional

import yt_dlp

from config import ARCHIVE_CHANNEL
from engine.base import BaseDownloader


def resolve_tiktok_url(url: str) -> str:
    """Resolve short TikTok URLs (vt.tiktok.com, vm.tiktok.com) to full URLs."""
    # Check if it's a short URL that needs resolving
    short_domains = ['vt.tiktok.com', 'vm.tiktok.com']
    
    if not any(domain in url for domain in short_domains):
        return url  # Already a full URL
    
    try:
        logging.info("TikTok: Resolving short URL: %s", url)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
        resolved_url = response.url
        
        # Clean up URL - remove query parameters for cleaner URL
        if "?" in resolved_url:
            resolved_url = resolved_url.split("?")[0]
        
        logging.info("TikTok: Resolved to: %s", resolved_url)
        return resolved_url
    except Exception as e:
        logging.warning("TikTok: Failed to resolve short URL, using original: %s", e)
        return url

# Try to import tiktokapipy, but make it optional
try:
    from tiktokapipy.api import TikTokAPI
    TIKTOKAPIPY_AVAILABLE = True
except Exception:
    TIKTOKAPIPY_AVAILABLE = False


class TikTokDownload(BaseDownloader):
    """Downloader for TikTok videos using yt-dlp with tiktokapipy fallback."""

    def _setup_formats(self) -> list | None:
        """TikTok doesn't need format setup like YouTube."""
        return [None]

    def _download_with_ytdlp_url(self, url: str) -> list:
        """Try downloading with yt-dlp first."""
        output = pathlib.Path(self._tempdir.name, "%(title).70s.%(ext)s").as_posix()
        ydl_opts = {
            "outtmpl": output,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "format": "best[ext=mp4]/best",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            "retries": 3,
            "fragment_retries": 3,
        }

        try:
            logging.info("TikTok: Trying yt-dlp with URL: %s", url)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            files = list(pathlib.Path(self._tempdir.name).glob("*"))
            if files:
                logging.info("TikTok: yt-dlp succeeded!")
                return [str(f) for f in files if f.is_file()]
        except Exception as e:
            logging.warning("TikTok: yt-dlp failed: %s", e)

        return []

    def _download_with_tiktokapipy_url(self, url: str) -> list:
        """Fallback download using tiktokapipy."""
        if not TIKTOKAPIPY_AVAILABLE:
            logging.warning("TikTok: tiktokapipy not available for fallback")
            return []

        try:
            logging.info("TikTok: Trying tiktokapipy fallback with URL: %s", url)
            
            # tiktokapipy has sync API
            with TikTokAPI() as api:
                video = api.video(url)
                
                if video is None:
                    logging.warning("TikTok: tiktokapipy could not get video info")
                    return []
                
                # Get video bytes
                video_bytes = video.video.download()
                
                if video_bytes:
                    # Save to temp file
                    title = getattr(video, 'desc', 'tiktok_video')[:70] or 'tiktok_video'
                    # Clean title for filename
                    title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                    if not title:
                        title = 'tiktok_video'
                    
                    output_path = pathlib.Path(self._tempdir.name) / f"{title}.mp4"
                    output_path.write_bytes(video_bytes)
                    
                    logging.info("TikTok: tiktokapipy succeeded!")
                    return [str(output_path)]
                    
        except Exception as e:
            logging.warning("TikTok: tiktokapipy fallback failed: %s", e)

        return []

    def _download(self, formats=None) -> list:
        """Download TikTok video, trying yt-dlp first then tiktokapipy."""
        # Store original URL for caption/display (user wants original link, not resolved redirect)
        original_url = self._url
        
        # Resolve short URLs to full URLs for download only
        download_url = resolve_tiktok_url(self._url)
        
        # Try yt-dlp first (usually more reliable and faster)
        files = self._download_with_ytdlp_url(download_url)
        
        if files:
            self._format = "video"
            return files
        
        # Fallback to tiktokapipy
        files = self._download_with_tiktokapipy_url(download_url)
        
        if files:
            self._format = "video"
            return files
        
        # Both failed - report to archive channel and show error to user
        error_msg = "הורדה מ-TikTok נכשלה!"
        self._bot_msg.edit_text(
            f"❌ {error_msg}\n\n"
            "TikTok חוסם הורדות לפעמים. נסה שוב מאוחר יותר."
        )
        
        # Send error report to archive channel
        if ARCHIVE_CHANNEL:
            try:
                from database.model import get_user_stats
                user_info = get_user_stats(self._from_user)
                if user_info:
                    name = user_info.get('first_name') or ""
                    if user_info.get('username'):
                        name = f"{name} @{user_info['username']}".strip()
                    user_display = name if name else str(self._from_user)
                else:
                    user_display = str(self._from_user)
                
                report = (
                    f"❌ **דיווח שגיאה**\n"
                    f"👤 משתמש: {user_display}\n"
                    f"🆔 {self._from_user}\n"
                    f"🔗 קישור: {self._url}\n"
                    f"⚠️ שגיאה: {error_msg}"
                )
                self._client.send_message(
                    chat_id=ARCHIVE_CHANNEL, 
                    text=report,
                    disable_web_page_preview=True
                )
            except Exception as e:
                logging.warning("Failed to send error to archive: %s", e)
        
        return []  # Return empty, error already reported

    def _start(self):
        """Start download and upload process."""
        downloaded_files = self._download()
        if downloaded_files:
            self._upload(files=downloaded_files)

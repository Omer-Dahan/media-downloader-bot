#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - generic.py

import logging
import os
import subprocess
import sys
from pathlib import Path

import yt_dlp

from config import AUDIO_FORMAT
from utils import is_youtube
from database.model import get_format_settings, get_quality_settings
from engine.base import BaseDownloader

# Get absolute path to cookies file (relative to src directory)
_SCRIPT_DIR = Path(__file__).parent.parent
COOKIES_PATH = _SCRIPT_DIR / "youtube-cookies.txt"

# Track if we've already tried updating yt-dlp in this session
_ytdlp_update_attempted = False


def try_update_ytdlp() -> bool:
    """Try to update yt-dlp to the latest version.
    
    Returns True if update was successful, False otherwise.
    Only attempts update once per session.
    """
    global _ytdlp_update_attempted
    
    if _ytdlp_update_attempted:
        logging.info("yt-dlp update already attempted this session, skipping")
        return False
    
    _ytdlp_update_attempted = True
    logging.info("Attempting to auto-update yt-dlp...")
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout
        )
        
        if result.returncode == 0:
            logging.info("yt-dlp updated successfully!")
            # Reload yt_dlp module to use new version
            import importlib
            importlib.reload(yt_dlp)
            return True
        else:
            logging.error("yt-dlp update failed: %s", result.stderr)
            return False
    except subprocess.TimeoutExpired:
        logging.error("yt-dlp update timed out")
        return False
    except Exception as e:
        logging.error("yt-dlp update failed with exception: %s", e)
        return False


def is_extraction_error(error_msg: str) -> bool:
    """Check if the error is an extraction error that might be fixed by updating."""
    extraction_errors = [
        "Unable to extract",
        "unable to extract",
        "Unsupported URL",
        "This video is not available",
        "Video unavailable",
        "ExtractorError",
    ]
    return any(err in str(error_msg) for err in extraction_errors)


def match_filter(info_dict):
    if info_dict.get("is_live"):
        raise NotImplementedError("לא ניתן להוריד שידור חי")
    return None  # Allow download for non-live videos


class YoutubeDownload(BaseDownloader):
    def __init__(self, client, bot_msg, url, selected_quality: str = None):
        """Initialize YoutubeDownload.
        
        Args:
            selected_quality: Optional quality selected by user ('1080', '720', '480', '360', 'audio')
        """
        super().__init__(client, bot_msg, url)
        self._selected_quality = selected_quality
        # Override format immediately if audio is selected (important for cache hits)
        if selected_quality == 'audio':
            self._format = 'audio'
        # Include selected quality in cache key to prevent returning wrong quality from cache
        if selected_quality:
            self._quality = f"{self._quality}:{selected_quality}"
    
    @staticmethod
    def extract_info(url: str) -> dict | None:
        """Extract video info without downloading.
        
        Returns dict with 'title' and 'duration' or None on error.
        """
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        # Setup cookies for youtube
        if COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 100:
            ydl_opts["cookiefile"] = str(COOKIES_PATH)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    duration_seconds = info.get('duration', 0)
                    minutes = duration_seconds // 60
                    seconds = duration_seconds % 60
                    duration_str = f"{minutes}:{seconds:02d}"
                    return {
                        'title': info.get('title', 'Unknown'),
                        'duration': duration_str,
                        'duration_seconds': duration_seconds,
                    }
        except Exception as e:
            logging.error("Failed to extract video info: %s", e)
        return None
    
    @staticmethod
    def get_format(m):
        return [
            f"bestvideo[ext=mp4][height={m}]+bestaudio[ext=m4a]",
            f"bestvideo[vcodec^=avc][height={m}]+bestaudio[acodec^=mp4a]/best[vcodec^=avc]/best",
        ]

    def _setup_formats(self) -> list | None:
        if not is_youtube(self._url):
            return [None]

        # If user selected a specific quality via buttons, use that
        if self._selected_quality:
            audio = AUDIO_FORMAT or "m4a"
            defaults = [
                "bestvideo[ext=mp4][vcodec!*=av01][vcodec!*=vp09]+bestaudio[ext=m4a]/bestvideo+bestaudio",
                "bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/best[vcodec^=avc]/best",
                None,
            ]
            # Use height<=X to allow fallback to lower resolutions if exact match not available
            quality_map = {
                '1080': [
                    "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best",
                ],
                '720': [
                    "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best",
                ],
                '480': [
                    "bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best",
                ],
                '360': [
                    "bestvideo[ext=mp4][height<=360]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best",
                ],
                'audio': [
                    f"bestaudio[ext={audio}]",
                    "bestaudio[ext=mp3]",
                    "bestaudio[ext=opus]",
                    "bestaudio[ext=webm]",
                    "bestaudio",
                    # Fallback to video+audio and extract audio
                    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
                ],
            }
            formats = quality_map.get(self._selected_quality, defaults)
            # Set format type for upload
            if self._selected_quality == 'audio':
                self._format = 'audio'
                # For audio, don't add video defaults - return only audio formats
                return formats
            else:
                self._format = 'video'
            return formats + defaults

        # Otherwise use user's default settings
        quality, format_ = get_quality_settings(self._chat_id), get_format_settings(self._chat_id)
        # quality: high, medium, low, custom
        # format: audio, video, document
        formats = []
        defaults = [
            # webm , vp9 and av01 are not streamable on telegram, so we'll extract only mp4
            "bestvideo[ext=mp4][vcodec!*=av01][vcodec!*=vp09]+bestaudio[ext=m4a]/bestvideo+bestaudio",
            "bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/best[vcodec^=avc]/best",
            None,
        ]
        audio = AUDIO_FORMAT or "m4a"
        maps = {
            "high-audio": [f"bestaudio[ext={audio}]"],
            "high-video": defaults,
            "high-document": defaults,
            "medium-audio": [f"bestaudio[ext={audio}]"],  # no mediumaudio :-(
            "medium-video": self.get_format(720),
            "medium-document": self.get_format(720),
            "low-audio": [f"bestaudio[ext={audio}]"],
            "low-video": self.get_format(480),
            "low-document": self.get_format(480),
            "custom-audio": "",
            "custom-video": "",
            "custom-document": "",
        }

        if quality == "custom":
            pass
            # TODO not supported yet

        formats.extend(maps[f"{quality}-{format_}"])
        # extend default formats if not high*
        if quality != "high":
            formats.extend(defaults)
        return formats

    def _download(self, formats, _retry_after_update: bool = False) -> list:
        output = Path(self._tempdir.name, "%(title).70s.%(ext)s").as_posix()
        ydl_opts = {
            "progress_hooks": [lambda d: self.download_hook(d)],
            "outtmpl": output,
            "restrictfilenames": False,
            "quiet": True,
            "match_filter": match_filter,
            "concurrent_fragments": 16,
            "buffersize": 4194304,
            "retries": 6,
            "fragment_retries": 6,
            "skip_unavailable_fragments": True,
            "embed_metadata": True,
            "embed_thumbnail": True,
            "writethumbnail": False,
            # Ensure MP4 output for Telegram inline streaming support
            "merge_output_format": "mp4",
        }
        
        # Add MP3 conversion for audio-only downloads
        if self._selected_quality == 'audio':
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        # setup cookies for youtube only
        if is_youtube(self._url):
            # use cookies from browser firstly
            if browsers := os.getenv("BROWSERS"):
                ydl_opts["cookiesfrombrowser"] = browsers.split(",")
            if COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 100:
                ydl_opts["cookiefile"] = str(COOKIES_PATH)
            # try add extract_args if present
            if potoken := os.getenv("POTOKEN"):
                ydl_opts["extractor_args"] = {"youtube": ["player-client=web,default", f"po_token=web+{potoken}"]}
                # for new version? https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
                # ydl_opts["extractor_args"] = {
                #     "youtube": [f"po_token=web.player+{potoken}", f"po_token=web.gvs+{potoken}"]
                # }

        if self._url.startswith("https://drive.google.com"):
            # Always use the `source` format for Google Drive URLs.
            formats = ["source"] + formats

        files = None
        extraction_error_encountered = False
        last_error = None
        
        for f in formats:
            try:
                ydl_opts["format"] = f
                logging.info("yt-dlp options: %s", ydl_opts)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([self._url])
                files = list(Path(self._tempdir.name).glob("*"))
                if files:  # Only break if we actually got files
                    break
            except Exception as e:
                last_error = str(e)
                logging.warning("Format %s failed: %s, trying next...", f, e)
                # Check if this is an extraction error
                if is_extraction_error(last_error):
                    extraction_error_encountered = True
                continue

        # If all formats failed due to extraction error, try auto-updating yt-dlp
        if not files and extraction_error_encountered and not _retry_after_update:
            logging.info("Extraction error detected, attempting yt-dlp auto-update...")
            if try_update_ytdlp():
                logging.info("Retrying download after yt-dlp update...")
                return self._download(formats, _retry_after_update=True)
            else:
                logging.warning("yt-dlp auto-update failed or already attempted")

        return files

    def _start(self, formats=None):
        # start download and upload, no cache hit
        # user can choose format by clicking on the button(custom config)
        default_formats = self._setup_formats()
        if formats is not None:
            # formats according to user choice
            default_formats = formats + self._setup_formats()
        files = self._download(default_formats)
        if not files:
            raise ValueError("ההורדה נכשלה - לא נמצאו פורמטים זמינים. נסה לעדכן את yt-dlp.")
        self._upload()

#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - types.py

import hashlib
import json
import logging
import re
import tempfile
import uuid
from abc import ABC, abstractmethod
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import final

import ffmpeg
import filetype
from pyrogram import enums, types
from tqdm import tqdm

from config import TG_NORMAL_MAX_SIZE, Types, ARCHIVE_CHANNEL
from database import Redis
from database.model import (
    add_bandwidth_used,
    check_quota,
    get_format_settings,
    get_free_quota,
    get_paid_quota,
    get_quality_settings,
    get_user_stats,
    use_quota,
)
from engine.helper import debounce, sizeof_fmt


def generate_input_media(file_paths: list, cap: str) -> list:
    input_media = []
    for path in file_paths:
        mime = filetype.guess_mime(path)
        if "video" in mime:
            input_media.append(types.InputMediaVideo(media=path, supports_streaming=True))
        elif "image" in mime:
            input_media.append(types.InputMediaPhoto(media=path))
        elif "audio" in mime:
            input_media.append(types.InputMediaAudio(media=path))
        else:
            input_media.append(types.InputMediaDocument(media=path))

    input_media[0].caption = cap
    return input_media


class BaseDownloader(ABC):
    def __init__(self, client: Types.Client, bot_msg: Types.Message, url: str):
        self._client = client
        self._url = url
        # chat id is the same for private chat
        self._chat_id = self._from_user = bot_msg.chat.id
        if bot_msg.chat.type == enums.ChatType.GROUP or bot_msg.chat.type == enums.ChatType.SUPERGROUP:
            # if in group, we need to find out who send the message
            self._from_user = bot_msg.reply_to_message.from_user.id
        self._id = bot_msg.id
        self._tempdir = tempfile.TemporaryDirectory(prefix="ytdl-")
        self._bot_msg: Types.Message = bot_msg
        self._redis = Redis()
        self._quality = get_quality_settings(self._chat_id)
        self._format = get_format_settings(self._chat_id)

    def __del__(self):
        self._tempdir.cleanup()

    def _record_usage(self, file_size: int = 0):
        free, paid = get_free_quota(self._from_user), get_paid_quota(self._from_user)
        logging.info("User %s has %s free and %s paid quota", self._from_user, free, paid)
        if free + paid < 0:
            raise Exception("חריגה ממכסת השימוש")

        use_quota(self._from_user)
        if file_size > 0:
            add_bandwidth_used(self._from_user, file_size)

    @staticmethod
    def __remove_bash_color(text):
        return re.sub(r"\u001b|\[0;94m|\u001b\[0m|\[0;32m|\[0m|\[0;33m", "", text)

    @staticmethod
    def __tqdm_progress(desc, total, finished, speed="", eta=""):
        def more(title, initial):
            if initial:
                return f"{title} {initial}"
            else:
                return ""

        f = StringIO()
        tqdm(
            total=total,
            initial=finished,
            file=f,
            ascii=False,
            unit_scale=True,
            ncols=30,
            bar_format="{l_bar}{bar} |{n_fmt}/{total_fmt} ",
        )
        raw_output = f.getvalue()
        tqdm_output = raw_output.split("|")
        progress = f"`[{tqdm_output[1]}]`"
        detail = tqdm_output[2].replace("[A", "")
        
        # Modern RTL style progress display
        text = f"""‏📥 **{desc}**
━━━━━━━━━━━━━━━━━━
{progress}
‏📊 {detail}
{more("‏⚡ מהירות:", speed)}
{more("‏⏱️ זמן משוער:", eta)}
━━━━━━━━━━━━━━━━━━"""
        f.close()
        return text

    def download_hook(self, d: dict):
        if d["status"] == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)

            if total > TG_NORMAL_MAX_SIZE:
                msg = f"גודל הקובץ {sizeof_fmt(total)} גדול מדי עבור טלגרם."
                raise Exception(msg)

            # percent = remove_bash_color(d.get("_percent_str", "N/A"))
            speed = self.__remove_bash_color(d.get("_speed_str", "N/A"))
            eta = self.__remove_bash_color(d.get("_eta_str", d.get("eta")))
            text = self.__tqdm_progress("מוריד...", total, downloaded, speed, eta)
            self.edit_text(text)

    def upload_hook(self, current, total):
        text = self.__tqdm_progress("מעלה...", total, current)
        self.edit_text(text)

    @debounce(5)
    def edit_text(self, text: str):
        self._bot_msg.edit_text(text)

    @abstractmethod
    def _setup_formats(self) -> list | None:
        pass

    @abstractmethod
    def _download(self, formats) -> list:
        # responsible for get format and download it
        pass

    @property
    def _methods(self):
        return {
            "document": self._client.send_document,
            "audio": self._client.send_audio,
            "video": self._client.send_video,
            "animation": self._client.send_animation,
            "photo": self._client.send_photo,
        }

    def send_something(self, *, chat_id, files, _type, caption=None, thumb=None, **kwargs):
        self._client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_DOCUMENT)
        is_cache = kwargs.pop("cache", False)
        if len(files) > 1 and is_cache == False:
            inputs = generate_input_media(files, caption)
            return self._client.send_media_group(chat_id, inputs)[0]
        else:
            file_arg_name = None
            if _type == "photo":
                file_arg_name = "photo"
            elif _type == "video":
                file_arg_name = "video"
            elif _type == "animation":
                file_arg_name = "animation"
            elif _type == "document":
                file_arg_name = "document"
            elif _type == "audio":
                file_arg_name = "audio"
            else:
                logging.error("Unknown _type encountered: %s", _type)
                return None

            send_args = {
                "chat_id": chat_id,
                file_arg_name: files[0],
                "caption": caption,
                "progress": self.upload_hook,
                **kwargs,
            }
            
            # Add supports_streaming for video to enable inline playback in Telegram
            if _type == "video":
                send_args["supports_streaming"] = True

            if _type in ["video", "animation", "document", "audio"] and thumb is not None:
                send_args["thumb"] = thumb

            return self._methods[_type](**send_args)

    def get_metadata(self):
        video_path = list(Path(self._tempdir.name).glob("*"))[0]
        filename = Path(video_path).name
        width = height = duration = 0
        try:
            video_streams = ffmpeg.probe(video_path, select_streams="v")
            for item in video_streams.get("streams", []):
                height = item["height"]
                width = item["width"]
            duration = int(float(video_streams["format"]["duration"]))
        except Exception as e:
            logging.error("Error while getting metadata: %s", e)
        try:
            thumb = Path(video_path).parent.joinpath(f"{uuid.uuid4().hex}-thunmnail.png").as_posix()
            # A thumbnail's width and height should not exceed 320 pixels.
            ffmpeg.input(video_path, ss=duration / 2).filter(
                "scale",
                "if(gt(iw,ih),300,-1)",  # If width > height, scale width to 320 and height auto
                "if(gt(iw,ih),-1,300)",
            ).output(thumb, vframes=1).run()
        except ffmpeg._run.Error:
            thumb = None

        # Format duration as minutes:seconds
        duration_minutes = duration // 60
        duration_seconds = duration % 60
        duration_str = f"{duration_minutes}:{duration_seconds:02d} דקות"
        
        caption = f"🔗 מקור:\n{self._url}\n📐 רזולוציה: {width}x{height}\n⏱️ אורך: {duration_str}\n⬇️ הקובץ מוכן לצפייה והורדה\nצפייה מהנה 👀✨"
        return dict(height=height, width=width, duration=duration, thumb=thumb, caption=caption)

    def _upload(self, files=None, meta=None):
        if files is None:
            files = list(Path(self._tempdir.name).glob("*"))
        if meta is None:
            meta = self.get_metadata()

        success = SimpleNamespace(document=None, video=None, audio=None, animation=None, photo=None)
        if self._format == "document":
            logging.info("Sending as document for %s", self._url)
            success = self.send_something(
                chat_id=self._chat_id,
                files=files,
                _type="document",
                thumb=meta.get("thumb"),
                force_document=True,
                caption=meta.get("caption"),
            )
        elif self._format == "photo":
            logging.info("Sending as photo for %s", self._url)
            success = self.send_something(
                chat_id=self._chat_id,
                files=files,
                _type="photo",
                caption=meta.get("caption"),
            )
        elif self._format == "audio":
            logging.info("Sending as audio for %s", self._url)
            try:
                success = self.send_something(
                    chat_id=self._chat_id,
                    files=files,
                    _type="audio",
                    caption=meta.get("caption"),
                )
            except ValueError as e:
                # Cache may have wrong file type, try sending as document
                logging.warning("Failed to send as audio (%s), trying as document", e)
                success = self.send_something(
                    chat_id=self._chat_id,
                    files=files,
                    _type="document",
                    caption=meta.get("caption"),
                )
        elif self._format == "video":
            logging.info("Sending as video for %s", self._url)
            attempt_methods = ["video", "animation", "audio", "photo"]
            video_meta = meta.copy()

            upload_successful = False  # Flag to track if any method succeeded
            for method in attempt_methods:
                current_meta = video_meta.copy()

                if method == "photo":
                    current_meta.pop("thumb", None)
                    current_meta.pop("duration", None)
                    current_meta.pop("height", None)
                    current_meta.pop("width", None)
                elif method == "audio":
                    current_meta.pop("height", None)
                    current_meta.pop("width", None)

                try:
                    success_obj = self.send_something(
                        chat_id=self._chat_id,
                        files=files,
                        _type=method,
                        **current_meta
                    )

                    if method == "video":
                        success = success_obj
                    elif method == "animation":
                        success = success_obj
                    elif method == "photo":
                        success = success_obj
                    elif method == "audio":
                        success = success_obj

                    upload_successful = True # Set flag to True on success
                    break
                except Exception as e:
                    logging.error("Retry to send as %s, error: %s", method, e)

            # Check the flag after the loop
            if not upload_successful:
                raise ValueError("שגיאה: לקישורים ישירים, נסה שוב עם `/direct`.")

        else:
            logging.error("Unknown upload format settings for %s", self._format)
            return

        video_key = self._calc_video_key()
        obj = success.document or success.video or success.audio or success.animation or success.photo
        mapping = {
            "file_id": json.dumps([getattr(obj, "file_id", None)]),
            "meta": json.dumps({k: v for k, v in meta.items() if k != "thumb"}, ensure_ascii=False),
        }

        self._redis.add_cache(video_key, mapping)
        
        # Forward to archive channel if configured
        logging.info("Archive channel check: ARCHIVE_CHANNEL=%s, success=%s", ARCHIVE_CHANNEL, type(success))
        if ARCHIVE_CHANNEL and success:
            try:
                msg_id = getattr(success, 'id', None)
                
                # Get user info for caption
                user_info = get_user_stats(self._from_user)
                if user_info:
                    name = user_info.get('first_name') or ""
                    if user_info.get('username'):
                        name = f"{name} @{user_info['username']}".strip()
                    user_display = name if name else str(self._from_user)
                else:
                    user_display = str(self._from_user)
                
                # Send to archive with user info
                archive_caption = f"📥 הורדה עבור: {user_display}\n🆔 {self._from_user}\n🔗 {self._url}"
                
                logging.info("Attempting to copy message %s to channel %s", msg_id, ARCHIVE_CHANNEL)
                self._client.send_message(
                    chat_id=ARCHIVE_CHANNEL,
                    text=archive_caption,
                )
                self._client.copy_message(
                    chat_id=ARCHIVE_CHANNEL,
                    from_chat_id=self._chat_id,
                    message_id=msg_id,
                )
                logging.info("Forwarded to archive channel: %s", ARCHIVE_CHANNEL)
            except Exception as e:
                logging.error("Failed to forward to archive channel: %s", e)
        
        # change progress bar to done
        self._bot_msg.edit_text("✅ הושלם בהצלחה")
        return success

    def _get_video_cache(self):
        return self._redis.get_cache(self._calc_video_key())

    def _calc_video_key(self):
        h = hashlib.md5()
        h.update((self._url + self._quality + self._format).encode())
        key = h.hexdigest()
        return key

    @final
    def start(self):
        check_quota(self._from_user)
        if cache := self._get_video_cache():
            logging.info("Cache hit for %s", self._url)
            meta, file_id = json.loads(cache["meta"]), json.loads(cache["file_id"])
            meta["cache"] = True
            self._upload(file_id, meta)
            # For cached files, we still count bandwidth (estimated from file_id)
            self._record_usage(0)  # Cache doesn't count towards bandwidth
        else:
            self._start()
            # Calculate total file size from downloaded files
            file_size = sum(f.stat().st_size for f in Path(self._tempdir.name).glob("*") if f.is_file())
            self._record_usage(file_size)

    @abstractmethod
    def _start(self):
        pass

# 📥 Media Downloader Bot

A **personal Telegram bot** for downloading media from popular platforms and delivering it directly to Telegram.

This project is designed for **private use** and as a solid, extensible base for further development.  
It focuses on reliability, modular architecture, and full in-bot management.

---

## 🚀 What This Bot Does

- Accepts links sent via Telegram
- Automatically detects the source platform
- Downloads **video or audio**
- Allows **quality selection** and **audio-only** downloads
- Sends the media directly back to the user on Telegram
- Manages users, credits, and limits **inside the bot**

The bot supports multiple users, enforces quotas, and provides full administrative control without external tools.

---

## 🌐 Supported Platforms

The bot reliably supports downloading from:

- ▶️ YouTube  
- 🎵 TikTok  
- 📸 Instagram  
- 👽 Reddit  
- 🔗 Direct download links  
- 🌍 Other websites supported by **yt-dlp**

⚠️ Maximum supported file size: **2 GB**

---

## 🎧 Supported Media Types

- 📹 Video downloads  
- 🎵 Audio-only downloads  
- 🎚️ Quality selection (when supported by the source)  
- 📁 Downloads are performed as-is (no forced re-encoding)

---

## ✨ Key Features

### Core Features
- 👥 Multi-user Telegram bot
- 🎥 Video and audio downloads
- 🤖 Automatic platform detection
- 📏 File size limit enforcement (2 GB)
- 🗃️ Database-backed cache and state handling
- 📝 Logging and error handling

### 🛠️ Admin and Management Features
- 🧩 Full admin panel inside Telegram
- 💳 User credit management via bot commands
- ⏱️ Rate limiting and quota enforcement
- 🔐 Credit-based download system
- ⚙️ Administrative control without server access

### 🆕 Enhancements Added in This Project
The following features were added and did not exist in the original upstream project:

- 🧑‍💼 Extended admin panel
- 💰 Credit management directly from the bot
- 🎚️ Quality selection and audio-only options
- 👽 Reddit platform support
- ✍️ Full rewrite and correction of all UI and user-facing texts
- 🧭 Improved menu structure and user interaction flow

---

## 🗂️ Project Structure

```
media-downloader-bot/
│
├─ src/
│  ├─ main.py              Bot entry point
│  ├─ admin.py             Admin commands and logic
│  ├─ engine/              Platform-specific download engines
│  ├─ database/            Cache and data handling
│  ├─ config/              Configuration management
│  └─ utils/               Utility helpers
│
├─ assets/                 Images and icons
├─ requirements.txt        Python dependencies
├─ run_bot.bat             Windows startup script
├─ LICENSE                 GPL-3.0 license
└─ README.md               This file
```

---

## 🧰 Requirements

- 🐍 Python 3.10 or newer
- 🤖 Telegram Bot Token
- 🌐 Internet connection
- ⚙️ yt-dlp available in the environment

---

## ▶️ Installation and Usage

1. Clone the repository:
```
git clone https://github.com/Omer-Dahan/media-downloader-bot.git
```

2. Install dependencies:
```
pip install -r requirements.txt
```

3. Create a `.env` file with the required configuration (Telegram token, admin IDs, etc).

4. Run the bot:
```
python src/main.py
```

On Windows:
```
run_bot.bat
```

---

## 🔐 Security Notes

- `.env`, cookies, session files, and databases are excluded from the repository
- Tokens and credentials must be stored securely
- The operator is responsible for complying with platform terms of service

---

## 📜 License

This project is licensed under the **GNU General Public License v3.0**.

Any redistribution or modification must comply with the terms of this license.

---

## 🙏 Credits

This project is based on the original work from:  
ytdlbot  
https://github.com/tgbot-collection/ytdlbot  

The codebase was modified, extended, and customized with additional features and structural changes.

---

## ⚠️ Disclaimer

This bot is intended for **lawful use only**.  
The responsibility for downloaded content and compliance with local laws and platform policies lies solely with the user.

---
title: Media Downloader Bot
emoji: 📥
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# 📥 Media Downloader Bot v3.0

Telegram bot for downloading media from YouTube, Instagram, TikTok, and other platforms without watermarks.

## Features 🌟
- **17+ Platforms Support**: YouTube, Instagram, TikTok, Pinterest, etc.
- **High Quality**: Downloads up to 1080p video and 320kbps audio.
- **Admin Panel**: Statistics, Broadcasting, User Management, and Settings.
- **Database**: SQLite based persistent storage.
- **Privacy**: No media storage, auto-cleanup.

## Deployment to Hugging Face Spaces 🚀

1.  **Create Space**:
    - Go to Hugging Face Spaces.
    - Click **Create new Space**.
    - Set the name (e.g., `media-downloader-bot`).
    - Choose **Docker** as the SDK.

2.  **Connect Repository**:
    - You can push this code directly or link your GitHub repository.

3.  **Environment Variables**:
    - Go to **Settings** -> **Variables and secrets**.
    - Add the following secrets:
        - `BOT_TOKEN`: Your Telegram Bot Token.
        - `ADMIN_IDS`: Your Telegram User ID (e.g., `6309900880`).
        - `MONGO_URI`: Your MongoDB connection string.

4.  **Database Persistence**:
    - Data is stored in MongoDB, so it persists across restarts.

## Local Development 💻
1.  Clone the repository.
2.  Install requirements: `pip install -r requirements.txt`
3.  Set up `.env` file.
4.  Run: `python bot.py`

## Commands 📝
- `/start` - Start the bot
- `/settings` - User settings
- `/help` - Help message
- `/admin` - Admin Panel (Admin only)

"""
Configuration management module for Bot Hoster.
Loads values from environment and optional `.env` file.
"""
from pathlib import Path
import os
from typing import Optional

from dotenv import load_dotenv

# Load .env from project root if present
BASE_DIR = Path(__file__).parent.absolute()
DOTENV_PATH = BASE_DIR / ".env"
if DOTENV_PATH.exists():
    load_dotenv(DOTENV_PATH)
else:
    # Try to load from environment automatically if present
    load_dotenv()

# Directories
USER_UPLOADS_DIR = BASE_DIR / "user_uploads"
HOST_FILES_DIR = BASE_DIR / "host_files"
USER_UPLOADS_DIR.mkdir(exist_ok=True)
HOST_FILES_DIR.mkdir(exist_ok=True)
# Multi-bot support
MAX_BOTS_PER_USER: int = int(os.getenv("MAX_BOTS_PER_USER", "2"))


# Core secrets and IDs (NO hardcoded secrets here - use environment or .env)
DISCORD_TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")
GUILD_ID: Optional[int] = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

# Bot settings
BOT_PREFIX: str = os.getenv("BOT_PREFIX", "!")
COMMAND_TIMEOUT: int = int(os.getenv("COMMAND_TIMEOUT", "300"))
SESSION_TIMEOUT: int = int(os.getenv("SESSION_TIMEOUT", "600"))

# File upload settings
MAX_ZIP_SIZE: int = int(os.getenv("MAX_ZIP_SIZE", str(50 * 1024 * 1024)))
MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(100 * 1024)))
ALLOWED_EXTENSIONS: list = ['.zip']

# Security settings
SECURITY_SCAN_TIMEOUT: int = int(os.getenv("SECURITY_SCAN_TIMEOUT", "30"))
SECURITY_BATCH_SIZE: int = int(os.getenv("SECURITY_BATCH_SIZE", "5"))
MAX_CONSOLE_LINES: int = int(os.getenv("MAX_CONSOLE_LINES", "50"))
MAX_CONSOLE_OUTPUT_LENGTH: int = int(os.getenv("MAX_CONSOLE_OUTPUT_LENGTH", "1900"))

# Process settings
PROCESS_TERMINATION_TIMEOUT: int = int(os.getenv("PROCESS_TERMINATION_TIMEOUT", "5"))
CONSOLE_UPDATE_INTERVAL: int = int(os.getenv("CONSOLE_UPDATE_INTERVAL", "3"))
CONSOLE_LINES_PER_UPDATE: int = int(os.getenv("CONSOLE_LINES_PER_UPDATE", "3"))

# Emojis for UI
EMOJIS = {
    "loading": "⏳",
    "safe": "✅",
    "danger": "⚠️",
    "robot": "🤖",
    "server": "🖥️",
    "trash": "🗑️",
    "help": "❓",
    "upload": "📤",
    "file": "📁",
    "play": "▶️",
    "stop": "⏹️",
    "cpu": "💻",
    "memory": "💾",
    "disk": "💿",
    "rocket": "🚀",
    "clipboard": "📋",
    "warning": "⚠️",
    "folder": "📁",
    "checkmark": "✅",
    "cross": "❌",
    "green_circle": "🟢",
    "red_circle": "🔴"
}

# Color codes for Discord embeds
EMBED_COLORS = {
    "success": 0x00FF00,  # Green
    "error": 0xFF0000,    # Red
    "warning": 0xFFA500,  # Orange
    "info": 0x5865F2,     # Discord blurple
    "danger": 0xFF0000    # Red
}

# Logging configuration
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "bot_hoster.log"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5


def validate_config() -> tuple[bool, Optional[str]]:
    """
    Validate configuration settings. Do not accept missing secrets.

    Returns:
        tuple: (is_valid, error_message)
    """
    if not DISCORD_TOKEN or DISCORD_TOKEN == "":
        return False, "DISCORD_TOKEN is not set (set via environment or .env)"

    return True, None


def get_user_project_dir(user_id: int, bot_slot: int = 1) -> Path:
    """
    Get or create user project directory for a specific bot slot.

    Args:
        user_id: Discord user ID
        bot_slot: Slot number for the user's bot (1-based)

    Returns:
        Path: Absolute path to user's project directory for the slot
    """
    # Ensure slot is within bounds
    if bot_slot < 1:
        bot_slot = 1
    user_root = USER_UPLOADS_DIR / str(user_id)
    slot_dir = user_root / f"bot_{bot_slot}"
    slot_dir.mkdir(parents=True, exist_ok=True)
    return slot_dir.absolute()


def get_user_root_dir(user_id: int) -> Path:
    """
    Return the root directory for all of a user's projects.
    """
    user_root = USER_UPLOADS_DIR / str(user_id)
    user_root.mkdir(parents=True, exist_ok=True)
    return user_root.absolute()


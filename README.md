# Discord Bot Hosting Service

A Discord bot that allows users to host and even **AI-generate** their own Discord bots on your server.

## Features

- 🚀 **Easy Hosting**: Upload bot code as `.zip` files
- 🤖 **Up to 2 Bots per User**: Each user can run **two bots in parallel**, tracked by numbered slots
- 🔒 **Security Scanning**: Automatic code analysis using AI to detect malicious code
- 🛰️ **Live File Monitoring**: While a bot is running, any **newly created files** in its project are auto-scanned; malicious ones are deleted and the user is DM’d
- 📦 **Dependency Management**: Automatic installation of `requirements.txt`
- 🎮 **Bot Control**: Start/stop bots with real-time console output
- 🧠 **AI Bot Development**: `/develop` command uses AI models to **generate a full Discord bot project** for you
- 📊 **System Monitoring**: Check server resources with `/status`
- 🗑️ **Project Management**: Clear all your projects with `/clear`

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure your bot token and API keys using a `.env` file or environment variables.
   - Copy `.env.example` to `.env` and fill the values:
     - `DISCORD_TOKEN`: Your Discord bot token
     - `OPENROUTER_API_KEY`: Your OpenRouter API key
     - `GUILD_ID`: Your Discord server ID (optional)
   - The app will also read values from environment variables if present.

3. Run the bot:
```bash
python3 bot.py
```

## Commands

- `/host` - Start hosting your Discord bot from a `.zip` upload (supports 2 concurrent bots per user)
- `/develop` - Let AI generate a complete Discord bot project from your prompt, then run it with auto-fix attempts
- `/status` - Check server system status (CPU, memory, disk)
- `/clear` - Delete all your hosted projects
- `/help` - Get help about the hosting service

## How It Works

1. User runs `/host` command
2. User uploads their bot code as a `.zip` file
3. Code is automatically scanned for security issues
4. If safe, dependencies are installed (if `requirements.txt` exists)
5. User selects main file from dropdown and the system assigns a **slot** (1 or 2) transparently
6. Bot runs and console output is streamed to Discord
7. While running, any **new files** created by the bot are auto-scanned; malicious ones are deleted and the user is DM’d
8. User can stop the bot anytime using the Stop button below the console output

### How `/develop` Works

1. User runs `/develop` with a natural language **prompt** describing the bot they want  
2. The bot calls AI models (`google/gemini-2.0-flash-exp:free` and `amazon/nova-2-lite-v1:free`) to generate a JSON payload of files:
   - `main.py` (entry point)
   - `requirements.txt`
   - `.env` for secrets (keys only, no real tokens)
   - Optional `README.md`, configs, helper modules, etc.
3. The service:
   - Writes each file into a **new project directory for that user/slot**
   - Shows a progress embed with **per-file loading → checkmark** animation
4. If a `.env` file is present:
   - A **“Fill .env”** button appears  
   - Clicking opens a form with one input per env key for the user to fill securely
5. `requirements.txt` is installed
6. `main.py` is run and console output is streamed into Discord
7. The **full console output** is then sent to AI to answer: *“Is this an error?”* (JSON yes/no)
8. If AI says **yes**:
   - Another AI pass receives *all files + console error* and returns updated files or a short “statement” if only config/.env needs fixing
   - Only the files returned are overwritten, requirements re-installed if needed, and the bot is **re-run**
   - This auto-fix loop runs up to **two attempts**

## Security

The bot uses AI-powered security scanning to detect:
- Linux command execution attempts
- File system access outside project directory
- Attempts to modify/delete host_files folder
- Shell command execution
- Other malicious patterns

Additional measures:

- While a bot is running, **newly created files** in its project are periodically:
  - Collected
  - Scanned by the AI security checker
  - Safe files are recorded, malicious ones are **deleted**
  - A DM is sent to the user summarizing which files were safe/removed
- Each user is isolated in `user_uploads/<user_id>/bot_<slot>/`

## File Structure (simplified)

```
.
├── bot.py               # Main bot file (slash commands, /develop flow, status server)
├── code_executor.py     # Process management and console streaming
├── file_handler.py      # Zip handling and file utilities
├── security.py          # AI-powered security scanning
├── session_manager.py   # Tracks sessions, slots, and running bots (multi-bot aware)
├── config.py            # Configuration, directories, constants
├── host_files/          # Legacy implementation (not used by main entry point)
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

## Notes

- Each user can host **up to 2 bots at a time**
- All hosted bots run in isolated directories under `user_uploads/<user_id>/bot_<slot>/`
- Console output is limited to prevent Discord message limits
- Security scanning (including new-file scanning) uses multiple AI models for accuracy

# working-bot-hoster

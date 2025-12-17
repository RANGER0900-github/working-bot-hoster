# Discord Bot Hosting Service

A Discord bot that allows users to host their own Discord bots on your server, with AI-powered bot generation using Bytez.

## Features

- 🚀 **Easy Hosting**: Upload bot code as `.zip` files (up to 2 bots per user)
- 🔒 **Security Scanning**: Automatic AI-powered code analysis to detect malicious code
- 📦 **Dependency Management**: Automatic installation of requirements.txt
- 🎮 **Bot Control**: Start/stop bots with real-time console output
- 📊 **System Monitoring**: Check server resources with `/status`
- 🗑️ **Project Management**: Clear all your projects with `/clear`
- 🛠️ **AI Bot Generation**: Create Discord bots from natural language with `/develop`
- 🔍 **Auto-Scan New Files**: Monitors running bots for new files and scans them automatically
- 🔧 **Manual Fix Errors**: Use the **Fix Error** button to repair generated bot errors as needed!

## Installation

1. Install dependencies:
```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

2. Configure your bot token using a `.env` file or environment variables:
   - Copy `.env.example` to `.env` and fill the values:
     - `DISCORD_TOKEN`: Your Discord bot token
     - `GUILD_ID`: Your Discord server ID (optional)

3. Run the bot:
```bash
./venv/bin/python bot.py
```

## API Key System

This bot uses **Bytez.com** for all AI features. Users need to provide their own Bytez API key (defaults provided for free):

- Get your API key from https://docs.bytez.com/model-api/docs/task/chat 
- Use the **Enter API Key** button when prompted in Discord

API keys are stored in `api_keys.json` with format:
```json
{
  "default": "fallback_key_here",
  "user_id": "their_api_key"
}
```

**Free tier limits:** see [Bytez docs](https://docs.bytez.com/model-api/docs/task/chat)

## Commands

- `/host` - Start hosting your Discord bot (upload as .zip)
- `/develop` - Generate a Discord bot using AI from a text prompt
- `/status` - Check server system status (CPU, memory, disk)
- `/clear` - Delete all your hosted projects
- `/help` - Get help about the hosting service

## How It Works

### /host Command
1. User runs `/host` command
2. If no API key, user is prompted to enter their Bytez API key
3. User uploads their bot code as a `.zip` file
4. Code is automatically scanned for security issues using Bytez AI
5. If safe, dependencies are installed (if requirements.txt exists)
6. User selects main file from dropdown
7. Bot runs and console output is streamed to Discord
8. New files created by the bot are auto-scanned
9. User can stop the bot anytime

### /develop Command
1. User runs `/develop prompt: <description>`
2. If no API key, user is prompted to enter their Bytez API key
3. AI generates complete bot files (main.py, requirements.txt, .env, README.md)
4. User can fill .env values via a form
5. Dependencies are installed automatically
6. User launches bot using **Run Bot** button in Discord
7. If errors occur, click **Fix Error** to attempt an auto-fix (as many times as you'd like)

## Security

The bot uses AI-powered security scanning to detect:
- Linux command execution attempts
- File system access outside project directory
- Attempts to modify/delete host_files folder
- Shell command execution
- Other malicious patterns

## File Structure

```
.
├── bot.py              # Main bot file
├── bytez_client.py     # Bytez API client
├── api_keys.json       # User API keys storage
├── security.py         # Legacy security module
├── config.py           # Configuration management
├── session_manager.py  # Session and bot process management
├── file_handler.py     # File operations
├── code_executor.py    # Process execution
├── logger_setup.py     # Logging configuration
├── requirements.txt    # Python dependencies
├── user_uploads/       # Directory for hosted bot files
└── README.md           # This file
```

## Multi-Bot Support

- Each user can host up to **2 bots** simultaneously
- Each bot runs in its own slot (`bot_1`, `bot_2`)
- Slots are managed automatically
- Users can stop individual bots or clear all projects

## Notes

- All hosted bots run in isolated directories under `user_uploads/<user_id>/bot_<slot>/`
- Console output is limited to prevent Discord message limits
- New files created by running bots are automatically scanned
- Malicious files are deleted automatically and user is notified via DM

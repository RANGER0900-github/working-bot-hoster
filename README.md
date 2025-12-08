# Discord Bot Hosting Service

A Discord bot that allows users to host their own Discord bots on your server.

## Features

- 🚀 **Easy Hosting**: Upload bot code as `.zip` files
- 🔒 **Security Scanning**: Automatic code analysis using AI to detect malicious code
- 📦 **Dependency Management**: Automatic installation of requirements.txt
- 🎮 **Bot Control**: Start/stop bots with real-time console output
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

- `/host` - Start hosting your Discord bot
- `/status` - Check server system status (CPU, memory, disk)
- `/clear` - Delete all your hosted projects
- `/help` - Get help about the hosting service

## How It Works

1. User runs `/host` command
2. User uploads their bot code as a `.zip` file
3. Code is automatically scanned for security issues
4. If safe, dependencies are installed (if requirements.txt exists)
5. User selects main file from dropdown
6. Bot runs and console output is streamed to Discord
7. User can stop the bot anytime

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
├── security.py         # Security checking module
├── requirements.txt    # Python dependencies
├── host_files/        # Directory for hosted bot files (created automatically)
└── README.md          # This file
```

## Notes

- Each user can host one bot at a time
- All hosted bots run in isolated directories under `host_files/`
- Console output is limited to prevent Discord message limits
- Security scanning uses multiple AI models for accuracy

# working-bot-hoster

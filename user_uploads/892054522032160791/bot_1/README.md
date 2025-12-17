# Random Discord Bot

A simple, modular Discord bot with slash commands using discord.py 2.0+.

## Features
- `/hello` - Greet the user
- `/roll` - Roll a random number between 1 and 100
- `/dice` - Roll a 6-sided die
- `/ping` - Check bot latency

## Setup
1. Create a bot on [Discord Developer Portal](https://discord.com/developers/applications)
2. Copy your bot token and save it in a `.env` file:
   ```env
   DISCORD_TOKEN=your_bot_token_here
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the bot:
   ```bash
   python main.py
   ```

## Notes
- Replace `your_bot_token_here` with your actual bot token.
- Ensure the bot has the necessary permissions to use slash commands.

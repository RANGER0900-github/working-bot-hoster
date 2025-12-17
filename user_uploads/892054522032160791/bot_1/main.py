import os
import discord
from discord import app_commands
from discord.ext import commands

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Slash command group
@bot.tree.command(name="hello", description="Says hello to the user")
def hello(interaction: discord.Interaction):
    """
    Responds with a greeting to the user.
    """
    await interaction.response.send_message(f"Hello, {interaction.user.mention}! Welcome to the random bot!")

@bot.tree.command(name="roll", description="Rolls a random number between 1 and 100")
def roll(interaction: discord.Interaction):
    """
    Rolls a random number between 1 and 100 and sends it to the user.
    """
    import random
    roll_result = random.randint(1, 100)
    await interaction.response.send_message(f"🎲 You rolled: {roll_result}")

@bot.tree.command(name="dice", description="Rolls a 6-sided die")
def dice(interaction: discord.Interaction):
    """
    Rolls a six-sided die and sends the result.
    """
    import random
    dice_result = random.randint(1, 6)
    await interaction.response.send_message(f"⚀⚁⚂⚃⚄⚅ You rolled: {dice_result}")

@bot.tree.command(name="ping", description="Checks the bot's latency")
def ping(interaction: discord.Interaction):
    """
    Returns the bot's latency in milliseconds.
    """
    latency = bot.latency * 1000
    await interaction.response.send_message(f"🏓 Pong! Latency: {latency:.2f}ms")

# Event: When the bot is ready
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

# Run the bot
if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print('Error: DISCORD_TOKEN not found in environment variables.')
        exit(1)
    bot.run(token)

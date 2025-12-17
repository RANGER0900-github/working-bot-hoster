"""
Discord Bot Hosting Service - Main Bot File
Refactored with modular architecture, robust error handling, and comprehensive logging.
"""
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime
import subprocess
import psutil
import sys
from pathlib import Path
from typing import Optional, List, Tuple, Dict
import aiohttp
from aiohttp import web
import json
import time

# Branding tagline used across embeds/presence
COOL_TAGLINE = "⚡ UnitedNodes • Instant Discord bot hosting with style"

# Import our modules
from config import (
    DISCORD_TOKEN, GUILD_ID, EMOJIS, EMBED_COLORS,
    get_user_root_dir, validate_config,
    SESSION_TIMEOUT, MAX_CONSOLE_OUTPUT_LENGTH, MAX_BOTS_PER_USER
)
from logger_setup import setup_logging, get_logger
from file_handler import FileHandler
from session_manager import SessionManager
from code_executor import CodeExecutor
from gemini_client import (
    get_user_api_key, set_user_api_key, has_user_api_key,
    generate_bot_files, check_for_error, fix_bot_errors, scan_code_for_security
)

# Set up logging
setup_logging()
logger = get_logger(__name__)

# region agent log helper
DEBUG_LOG_PATH = Path("/home/kali/Downloads/working-bot-hoster/.cursor/debug.log")


def _agent_debug_log(hypothesis_id: str, location: str, message: str, data: Dict):
    """Append a single NDJSON debug log line for debug-mode analysis."""
    try:
        payload = {
            "sessionId": "debug-session",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        # Never let debug logging break runtime behavior
        pass
# endregion

# Validate configuration
is_valid, error_msg = validate_config()
if not is_valid:
    logger.error(f"Configuration error: {error_msg}")
    sys.exit(1)

# Initialize modules
file_handler = FileHandler()
session_manager = SessionManager(session_timeout=SESSION_TIMEOUT)
code_executor = CodeExecutor()
http_client: Optional[aiohttp.ClientSession] = None

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

_presence_lock = asyncio.Lock()
_presence_task: Optional[asyncio.Task] = None
_presence_signature: Optional[str] = None

@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f"Bot logged in as {bot.user}")
    logger.info(f"Bot ID: {bot.user.id}")
    logger.info(f"Guilds: {len(bot.guilds)}")
    
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Error syncing commands: {str(e)}", exc_info=True)

    # Kick off presence loop to keep status fresh
    global _presence_task
    if not _presence_task or _presence_task.done():
        _presence_task = bot.loop.create_task(_presence_update_loop())
    await refresh_presence(force=True)


async def refresh_presence(force: bool = False) -> None:
    """Update the bot's Discord presence with current running bot count."""
    try:
        if not bot.is_ready():
            return
    except Exception:
        return

    count = session_manager.get_running_bots_count()
    noun = "bot" if count == 1 else "bots"
    activity_text = f"Hosting {count} {noun}"
    signature = activity_text

    async with _presence_lock:
        global _presence_signature
        if not force and _presence_signature == signature:
            return
        activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text)
        try:
            await bot.change_presence(status=discord.Status.online, activity=activity)
            _presence_signature = signature
        except Exception as e:
            logger.warning(f"Failed to update presence: {str(e)}", exc_info=True)


async def _presence_update_loop():
    """Background task to refresh presence periodically."""
    try:
        while not bot.is_closed():
            try:
                await refresh_presence()
            except Exception as e:
                logger.warning(f"Presence loop error: {str(e)}", exc_info=True)
            await asyncio.sleep(45)
    except asyncio.CancelledError:
        logger.info("Presence update loop cancelled.")
        raise
# ============ API Key Entry Classes ============ #

class GeminiApiKeyModal(discord.ui.Modal, title="🔑 Enter Gemini API Key"):
    """Modal for entering Gemini API key."""
    
    api_key_input = discord.ui.TextInput(
        label="Gemini API Key",
        placeholder="Enter your Google AI Studio API key here...",
        style=discord.TextStyle.short,
        required=True,
        min_length=10,
        max_length=100
    )
    
    def __init__(self, callback_command: str = "host"):
        super().__init__(timeout=300)
        self.callback_command = callback_command
    
    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        api_key = self.api_key_input.value.strip()
        
        # Save the API key
        if set_user_api_key(user_id, api_key):
            embed = discord.Embed(
                title=f"{EMOJIS['safe']} API Key Saved!",
                description=(
                    "Your Gemini API key has been saved successfully.\n\n"
                    f"You can now use `/{self.callback_command}` command!"
                ),
                color=EMBED_COLORS['success']
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Failed to Save",
                description="Could not save your API key. Please try again.",
                color=EMBED_COLORS['error']
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class ApiKeyRequiredView(discord.ui.View):
    """View shown when user needs to enter their API key."""
    
    def __init__(self, callback_command: str = "host"):
        super().__init__(timeout=300)
        self.callback_command = callback_command
        
        # Add link button to Google AI Studio
        self.add_item(discord.ui.Button(
            label="🔗 Get API Key",
            url="https://aistudio.google.com/apikey",
            style=discord.ButtonStyle.link
        ))
    
    @discord.ui.button(label="🔑 Enter API Key", style=discord.ButtonStyle.primary)
    async def enter_api_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GeminiApiKeyModal(self.callback_command)
        await interaction.response.send_modal(modal)


async def check_user_api_key(interaction: discord.Interaction, command_name: str = "host") -> Optional[str]:
    """
    Check if user has an API key. If not, show the API key entry prompt.
    Returns the API key if available, None otherwise.
    """
    user_id = interaction.user.id
    api_key = get_user_api_key(user_id)
    
    if api_key:
        return api_key
    
    # No API key - show prompt
    embed = discord.Embed(
        title=f"{EMOJIS['warning']} API Key Required",
        description=(
            "To use the Bot Hoster, you need to enter your **Google AI Studio API key**.\n\n"
            "**How to get your free API key:**\n"
            "1. Click the **Get API Key** button below\n"
            "2. Sign in with your Google account\n"
            "3. Create a new API key\n"
            "4. Copy the key and click **Enter API Key**\n\n"
            "Your key is stored securely and used only for AI features."
        ),
        color=EMBED_COLORS['warning']
    )
    embed.set_footer(text="Google AI Studio provides 60 requests/min for free!")
    
    view = ApiKeyRequiredView(command_name)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    return None


@bot.tree.command(name="host", description="🚀 Host your Discord bot on our server!")
async def host_command(interaction: discord.Interaction):
    """Command to start hosting a Discord bot."""
    try:
        logger.info(f"Host command invoked by user {interaction.user.id}")
        
        # Check for API key first
        api_key = await check_user_api_key(interaction, "host")
        if not api_key:
            return  # User was shown the API key prompt
        
        from datetime import datetime
        embed = discord.Embed(
            title=f"{EMOJIS['rocket']} Code Hosting Bot",
            description="Upload your Python project as a `.zip` file to get started!",
            color=EMBED_COLORS['info']
        )
        
        embed.add_field(
            name=f"{EMOJIS['clipboard']} Instructions",
            value=(
                "1. Prepare your Python project in a `.zip` file (max 50MB)\n"
                "2. Choose upload location using buttons below\n"
                "3. Upload your `.zip` file\n"
                "4. Select main Python file to execute\n"
                "5. Install dependencies (if needed)\n"
                "6. Run your code!"
            ),
            inline=False
        )
        
        embed.add_field(
            name=f"{EMOJIS['warning']} Security Notes",
            value=(
                "• Only Python files are supported\n"
                "• Malicious code scan is active\n"
                "• Code runs in an isolated environment"
            ),
            inline=False
        )
        
        # Set footer with user's avatar only
        try:
            avatar_url = interaction.user.display_avatar.url
        except Exception:
            avatar_url = None
        embed.set_footer(text="Choose an upload method below 👇", icon_url=avatar_url)
        
        view = UploadMethodView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        
    except discord.HTTPException as e:
        logger.error(f"HTTP error in host command: {str(e)}", exc_info=True)
        await interaction.response.send_message(
            "❌ An error occurred while processing your request. Please try again.",
            ephemeral=True
        )
    except Exception as e:
        logger.error(f"Unexpected error in host command: {str(e)}", exc_info=True)
        await interaction.response.send_message(
            "❌ An unexpected error occurred. Please contact an administrator.",
            ephemeral=True
        )

@bot.tree.command(name="status", description="📊 Check server system status and resources")
async def status_command(interaction: discord.Interaction):
    """Command to check server status."""
    try:
        logger.info(f"Status command invoked by user {interaction.user.id}")
        
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Determine color based on CPU usage
        status_color = EMBED_COLORS['success'] if cpu_percent < 80 else EMBED_COLORS['warning'] if cpu_percent < 95 else EMBED_COLORS['error']

        # Add a status headline with colored circle and [OK]/[WARN]/[CRITICAL]
        status_label = "[OK]" if cpu_percent < 80 else "[WARN]" if cpu_percent < 95 else "[CRITICAL]"
        status_circle = EMOJIS.get('green_circle') if cpu_percent < 80 else EMOJIS.get('red_circle')
        embed = discord.Embed(
            title=f"{EMOJIS['server']} Server Status {status_circle} {status_label}",
            color=status_color
        )
        
        embed.add_field(
            name=f"{EMOJIS['cpu']} CPU Usage",
            value=f"```\n{cpu_percent:.1f}%\n```",
            inline=True
        )
        
        embed.add_field(
            name=f"{EMOJIS['memory']} Memory Usage",
            value=(
                f"```\n{memory.percent:.1f}%\n"
                f"Used: {memory.used / (1024**3):.2f} GB\n"
                f"Total: {memory.total / (1024**3):.2f} GB\n```"
            ),
            inline=True
        )
        
        embed.add_field(
            name=f"{EMOJIS['disk']} Disk Usage",
            value=(
                f"```\n{disk.percent:.1f}%\n"
                f"Used: {disk.used / (1024**3):.2f} GB\n"
                f"Total: {disk.total / (1024**3):.2f} GB\n```"
            ),
            inline=True
        )
        
        # Count running bots
        running_count = session_manager.get_running_bots_count()
        embed.add_field(
            name=f"{EMOJIS['robot']} Running Bots",
            value=f"```\n{running_count} active bot(s)\n```",
            inline=False
        )
        
        # Footer: include user's avatar and a friendly timestamp like "Today at 01:17 PM"
        now = datetime.now()
        if now.date() == datetime.utcnow().date():
            time_str = now.strftime("Today at %I:%M %p")
        else:
            time_str = now.strftime("%Y-%m-%d at %I:%M %p")
        footer_text = f"Requested by {interaction.user.name} | {time_str}"
        try:
            avatar_url = interaction.user.display_avatar.url
        except Exception:
            avatar_url = None
        embed.set_footer(text=footer_text, icon_url=avatar_url)
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        logger.error(f"Error in status command: {str(e)}", exc_info=True)
        await interaction.response.send_message(
            "❌ An error occurred while checking server status.",
            ephemeral=True
        )



@bot.tree.command(name="clear", description="🗑️ Delete all your hosted projects (WARNING: This cannot be undone!)")
async def clear_command(interaction: discord.Interaction):
    """Command to clear all user projects."""
    try:
        user_id = interaction.user.id
        logger.info(f"Clear command invoked by user {user_id}")

        user_root = get_user_root_dir(user_id)

        if not user_root.exists() or not any(user_root.iterdir()):
            embed = discord.Embed(
                title=f"{EMOJIS['trash']} Clear Projects",
                description="You don't have any projects to delete!",
                color=EMBED_COLORS['warning']
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f"{EMOJIS['warning']} WARNING: Delete All Projects",
            description=(
                "This will **permanently delete** all your hosted projects!\n\n"
                "This action **cannot be undone**.\n\n"
                "Are you sure you want to proceed?"
            ),
            color=EMBED_COLORS['error']
        )
        embed.set_footer(text="Click the button below to confirm deletion")
        
        view = ConfirmClearView(user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
    except Exception as e:
        logger.error(f"Error in clear command: {str(e)}", exc_info=True)
        await interaction.response.send_message(
            "❌ An error occurred while processing your request.",
            ephemeral=True
        )

@bot.tree.command(name="help", description="❓ Get help about the bot hosting service")
async def help_command(interaction: discord.Interaction):
    """Command to show help information."""
    try:
        embed = discord.Embed(
            title=f"{EMOJIS['help']} Bot Hosting Service - Help",
            description="Here's everything you need to know about our hosting service!",
            color=EMBED_COLORS['info']
        )
        
        embed.add_field(
            name=f"{EMOJIS['upload']} `/host`",
            value="Start hosting your Discord bot. Upload your code as a `.zip` file.",
            inline=False
        )
        
        embed.add_field(
            name=f"{EMOJIS['server']} `/status`",
            value="Check server CPU, memory, and disk usage statistics.",
            inline=False
        )
        
        embed.add_field(
            name=f"{EMOJIS['trash']} `/clear`",
            value="Delete all your hosted projects. **Warning: This is permanent!**",
            inline=False
        )
        
        embed.add_field(
            name="📝 How It Works",
            value=(
                "1. Use `/host` to start\n"
                "2. Upload your `.zip` file\n"
                "3. Code is automatically scanned\n"
                "4. Install dependencies\n"
                "5. Select main file and run!"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🔒 Security",
            value=(
                "• All code is scanned for malicious content\n"
                "• Linux commands are not allowed\n"
                "• File system access is restricted\n"
                "• Only safe code will be executed"
            ),
            inline=False
        )
        
        embed.set_footer(text=f"{COOL_TAGLINE}\nNeed more help? Contact the server admins!")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"Error in help command: {str(e)}", exc_info=True)
        await interaction.response.send_message(
            "❌ An error occurred while displaying help.",
            ephemeral=True
        )

class ConfirmClearView(discord.ui.View):
    """View for confirming project deletion."""
    
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
    
    @discord.ui.button(label="✅ Confirm Delete", style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm deletion of projects."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your project!", ephemeral=True)
            return
        
        try:
            logger.info(f"User {self.user_id} confirmed project deletion")
            
            # Stop running bot(s) if any
            if session_manager.is_bot_running(self.user_id):
                success, error = session_manager.stop_bot(self.user_id, None)
                if not success:
                    logger.warning(f"Error stopping bots for user {self.user_id}: {error}")
                else:
                    await refresh_presence()
            
            # Delete root directory
            user_root = get_user_root_dir(self.user_id)
            success, error = file_handler.cleanup_directory(user_root)
            
            if success:
                embed = discord.Embed(
                    title=f"{EMOJIS['trash']} Projects Deleted",
                    description="All your projects have been permanently deleted!",
                    color=EMBED_COLORS['success']
                )
                logger.info(f"Successfully deleted projects for user {self.user_id}")
            else:
                embed = discord.Embed(
                    title=f"{EMOJIS['danger']} Error",
                    description=f"Error deleting projects: `{error}`",
                    color=EMBED_COLORS['error']
                )
                logger.error(f"Error deleting projects for user {self.user_id}: {error}")
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except Exception as e:
            logger.error(f"Error in confirm_delete: {str(e)}", exc_info=True)
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Error",
                description=f"An unexpected error occurred: `{str(e)}`",
                color=EMBED_COLORS['error']
            )
            await interaction.response.edit_message(embed=embed, view=None)
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel deletion."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your project!", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="✅ Deletion Cancelled",
            description="Your projects are safe!",
            color=EMBED_COLORS['success']
        )
        await interaction.response.edit_message(embed=embed, view=None)

class UploadMethodView(discord.ui.View):
    """View for selecting upload method."""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📤 Upload Here", style=discord.ButtonStyle.primary, custom_id="upload_here")
    async def upload_here(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Upload in channel."""
        try:
            logger.info(f"User {interaction.user.id} selected channel upload")
            success, error, slot, _ = session_manager.start_upload_session(interaction.user.id, "channel")
            if not success or slot is None:
                await interaction.response.send_message(
                    f"❌ {error or 'Cannot start upload right now.'}",
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title=f"{EMOJIS['upload']} Upload Your Bot Code",
                description=(
                    "Please upload your bot code as a **`.zip` file** in this channel.\n\n"
                    f"I'll be waiting for your `.zip` file for slot `{slot}`..."
                ),
                color=EMBED_COLORS['info']
            )
            embed.set_footer(text="Only .zip files will be accepted")
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in upload_here: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred. Please try again.",
                ephemeral=True
            )
    
    @discord.ui.button(label="📩 Upload in DM", style=discord.ButtonStyle.secondary, custom_id="upload_dm")
    async def upload_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Upload in DM."""
        try:
            logger.info(f"User {interaction.user.id} selected DM upload")
            success, error, slot, _ = session_manager.start_upload_session(interaction.user.id, "dm")
            if not success or slot is None:
                await interaction.response.send_message(
                    f"❌ {error or 'Cannot start upload right now.'}",
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title=f"{EMOJIS['upload']} Upload Your Bot Code",
                description=(
                    "Please upload your bot code as a **`.zip` file** in our DM.\n\n"
                    f"I'll be waiting for your `.zip` file in DMs... (slot `{slot}`)"
                ),
                color=EMBED_COLORS['info']
            )
            embed.set_footer(text="Only .zip files will be accepted")
            
            try:
                await interaction.user.send(embed=embed)
                await interaction.response.send_message(
                    f"{EMOJIS['upload']} Check your DMs! I've sent you instructions there.",
                    ephemeral=True
                )
            except discord.Forbidden:
                session_manager.end_upload_session(interaction.user.id)
                await interaction.response.send_message(
                    "❌ I cannot send you a DM! Please enable DMs from server members.",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error in upload_dm: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred. Please try again.",
                ephemeral=True
            )

@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages for file uploads."""
    if message.author == bot.user:
        return
    
    await bot.process_commands(message)
    
    user_id = message.author.id
    
    # Check if user is in upload process
    if not session_manager.is_user_uploading(user_id):
        return
    
    project_dir = session_manager.get_upload_project_dir(user_id)
    current_slot = session_manager.get_upload_slot(user_id)
    if not project_dir or current_slot is None:
        logger.warning(f"Upload session missing project dir/slot for user {user_id}")
        session_manager.end_upload_session(user_id)
        return
    
    upload_location = session_manager.get_upload_location(user_id)
    
    # Check if message is in correct location
    if upload_location == "channel":
        if isinstance(message.channel, discord.DMChannel):
            return
        if hasattr(message.channel, 'type') and message.channel.type != discord.ChannelType.text:
            return
    elif upload_location == "dm":
        if not isinstance(message.channel, discord.DMChannel):
            return
    
    # Check for zip file attachment
    if not message.attachments:
        return
    
    zip_attachment = None
    for attachment in message.attachments:
        if attachment.filename.endswith('.zip'):
            zip_attachment = attachment
            break
    
    if not zip_attachment:
        return
    
    # Process the zip file
    await process_zip_upload(message, zip_attachment, user_id, project_dir, current_slot)

async def process_zip_upload(message: discord.Message, attachment: discord.Attachment, user_id: int, user_dir: Path, slot: int):
    """Process uploaded zip file for a given user slot."""
    try:
        logger.info(f"Processing zip upload from user {user_id}: {attachment.filename}")
        
        # Ensure slot directory exists and is clean
        file_handler.cleanup_directory(user_dir)
        user_dir.mkdir(parents=True, exist_ok=True)
        
        # Download zip
        zip_path = user_dir / "uploaded.zip"
        success, error = await file_handler.download_attachment(attachment, zip_path)
        if not success:
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Upload Error",
                description=f"Error downloading file: `{error}`",
                color=EMBED_COLORS['error']
            )
            await message.channel.send(embed=embed)
            session_manager.end_upload_session(user_id)
            return
        
        # Extract zip
        success, error, all_files = file_handler.extract_zip(zip_path, user_dir)
        if not success:
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Extraction Error",
                description=f"Error extracting zip file: `{error}`",
                color=EMBED_COLORS['error']
            )
            await message.channel.send(embed=embed)
            session_manager.end_upload_session(user_id)
            return
        
        # Remove zip file
        try:
            zip_path.unlink()
        except Exception as e:
            logger.warning(f"Error removing zip file: {str(e)}")
        
        # Create file list embed with loading emojis
        file_list_text = "\n".join([f"{EMOJIS['loading']} `{f}`" for f in all_files[:30]])
        embed = discord.Embed(
            title=f"{EMOJIS['file']} Files Detected - Security Scan",
            description=f"Found `{len(all_files)}` file(s). Scanning for security...\n\n{file_list_text}",
            color=EMBED_COLORS['warning']
        )
        if len(all_files) > 30:
            embed.set_footer(text=f"... and {len(all_files) - 30} more files")
        
        status_msg = await message.channel.send(embed=embed)
        
        # Progress tracking
        file_status = {f: EMOJIS['loading'] for f in all_files}
        
        async def update_progress(batch_files, current_results):
            """Update embed with progress."""
            try:
                for file_path in batch_files:
                    if file_path in current_results:
                        result = current_results[file_path]
                        if result['type'] == 'malicious':
                            file_status[file_path] = EMOJIS['danger']
                        else:
                            file_status[file_path] = EMOJIS['safe']
                
                # Update embed
                updated_list = [f"{file_status.get(f, EMOJIS['loading'])} `{f}`" for f in all_files[:30]]
                embed.description = f"Found `{len(all_files)}` file(s). Scanning for security...\n\n" + "\n".join(updated_list)
                await status_msg.edit(embed=embed)
            except Exception as e:
                logger.warning(f"Error updating progress: {str(e)}")
        
        # Scan files with progress updates using Gemini
        api_key = get_user_api_key(user_id)
        scan_results = await scan_files_with_gemini(api_key, user_dir, all_files, update_progress)
        
        # Final update embed with results
        malicious_found = False
        malicious_statement = ""
        updated_file_list = []
        
        for file_path, result in scan_results.items():
            if result['type'] == 'malicious':
                malicious_found = True
                malicious_statement = result.get('statement', 'Malicious code detected')
                updated_file_list.append(f"{EMOJIS['danger']} `{file_path}`")
            else:
                updated_file_list.append(f"{EMOJIS['safe']} `{file_path}`")
        
        if malicious_found:
            # Delete user code
            file_handler.cleanup_directory(user_dir)
            session_manager.end_upload_session(user_id)
            
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Security Scan Failed",
                description=(
                    f"**Malicious code detected!**\n\n"
                    f"**Reason:** {malicious_statement}\n\n"
                    f"Your code has been deleted for security reasons."
                ),
                color=EMBED_COLORS['error']
            )
            await status_msg.edit(embed=embed)
            logger.warning(f"Malicious code detected for user {user_id}: {malicious_statement}")
            return
        
        # All files are safe
        embed = discord.Embed(
            title=f"{EMOJIS['safe']} Security Scan Passed",
            description=f"All `{len(all_files)}` file(s) scanned and verified safe!\n\n" + "\n".join(updated_file_list[:20]),
            color=EMBED_COLORS['success']
        )
        if len(all_files) > 20:
            embed.set_footer(text=f"... and {len(all_files) - 20} more files")
        await status_msg.edit(embed=embed)
        
        # Check for requirements.txt
        requirements_path = file_handler.find_requirements_file(user_dir)
        
        if requirements_path:
            # Install requirements
            embed = discord.Embed(
                title=f"{EMOJIS['loading']} Installing Dependencies",
                description="Found `requirements.txt`. Installing packages...",
                color=EMBED_COLORS['warning']
            )
            install_msg = await message.channel.send(embed=embed)
            
            try:
                result = subprocess.run(
                    ['pip', 'install', '-r', str(requirements_path)],
                    cwd=str(user_dir),
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode == 0:
                    # Try to parse installed package names from pip output
                    installed = []
                    stdout = result.stdout or ""
                    for line in stdout.splitlines():
                        line = line.strip()
                        if line.lower().startswith('successfully installed'):
                            parts = line.split()
                            # remove 'Successfully' and 'installed'
                            installed = parts[2:]
                            break
                    if not installed:
                        # Fallback: show contents of requirements.txt
                        try:
                            with open(requirements_path, 'r', encoding='utf-8') as f:
                                installed = [l.strip() for l in f.readlines() if l.strip() and not l.startswith('#')]
                        except Exception:
                            installed = []

                    desc = "All packages from `requirements.txt` have been installed successfully!"
                    if installed:
                        desc += "\n\nInstalled: `" + ", ".join(installed) + "`"
                    embed = discord.Embed(
                        title=f"{EMOJIS['safe']} Dependencies Installed",
                        description=desc,
                        color=EMBED_COLORS['success']
                    )
                    logger.info(f"Successfully installed dependencies for user {user_id}")
                else:
                    # Attempt to parse which packages failed
                    failed_list = []
                    stderr = result.stderr or ""
                    # If stderr lists specific packages, include a short excerpt
                    if stderr:
                        failed_list = stderr.splitlines()[:8]
                    embed = discord.Embed(
                        title=f"{EMOJIS['danger']} Installation Warning",
                        description=f"Some packages failed to install:\n```\n{stderr[:1000]}\n```",
                        color=EMBED_COLORS['warning']
                    )
                    logger.warning(f"Partial dependency installation failure for user {user_id}")
            except subprocess.TimeoutExpired:
                embed = discord.Embed(
                    title=f"{EMOJIS['danger']} Installation Timeout",
                    description="Dependency installation timed out after 5 minutes.",
                    color=EMBED_COLORS['error']
                )
                logger.error(f"Dependency installation timeout for user {user_id}")
            except Exception as e:
                embed = discord.Embed(
                    title=f"{EMOJIS['danger']} Installation Error",
                    description=f"Error installing dependencies: `{str(e)}`",
                    color=EMBED_COLORS['error']
                )
                logger.error(f"Error installing dependencies for user {user_id}: {str(e)}", exc_info=True)
            
            await install_msg.edit(embed=embed)
            # Continue to main file selector after requirements installation
            await show_main_file_selector(message.channel, user_id, user_dir, all_files, slot)
        else:
            # Ask if they want to install packages
            embed = discord.Embed(
                title=f"{EMOJIS['file']} No Requirements File",
                description=(
                    "No `requirements.txt` or `requirement.txt` detected.\n\n"
                    "Would you like to install any packages?"
                ),
                color=EMBED_COLORS['warning']
            )
            view = InstallPackagesView(user_id, user_dir, message.channel, slot)
            await message.channel.send(embed=embed, view=view)
        
    except Exception as e:
        logger.error(f"Error processing zip upload for user {user_id}: {str(e)}", exc_info=True)
        embed = discord.Embed(
            title=f"{EMOJIS['danger']} Error",
            description=f"An error occurred: `{str(e)}`",
            color=EMBED_COLORS['error']
        )
        await message.channel.send(embed=embed)
        session_manager.end_upload_session(user_id)


async def scan_files_with_gemini(api_key: str, project_dir: Path, file_paths: List[str], progress_callback=None) -> Dict[str, Dict]:
    """
    Scan multiple files for security using Gemini API.
    """
    code_extensions = ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb']
    code_files = [f for f in file_paths if any(f.endswith(ext) for ext in code_extensions)]
    
    if not code_files:
        return {f: {'type': 'normal', 'statement': 'Not a code file'} for f in file_paths}
    
    scan_results = {}
    batch_size = 3
    
    for batch_start in range(0, len(code_files), batch_size):
        batch_files = code_files[batch_start:batch_start + batch_size]
        
        for file_path in batch_files:
            try:
                full_path = project_dir / file_path
                if not full_path.is_file():
                    scan_results[file_path] = {'type': 'normal', 'statement': 'File not found'}
                    continue
                
                # Read file content
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()[:5000]  # Limit to 5KB
                except Exception:
                    scan_results[file_path] = {'type': 'normal', 'statement': 'Could not read file'}
                    continue
                
                # Scan with Gemini
                result = await scan_code_for_security(api_key, file_path, content)
                scan_results[file_path] = result
                
            except Exception as e:
                logger.warning(f"Error scanning {file_path}: {e}")
                scan_results[file_path] = {'type': 'normal', 'statement': f'Scan error: {str(e)[:50]}'}
        
        # Update progress
        if progress_callback:
            try:
                await progress_callback(batch_files, scan_results)
            except Exception:
                pass
    
    # Add non-code files as normal
    for file_path in file_paths:
        if file_path not in scan_results:
            scan_results[file_path] = {'type': 'normal', 'statement': 'Not a code file'}
    
    return scan_results


async def watch_new_files(user_id: int, slot: int, user_dir: Path, poll_interval: int = 12):
    """
    Monitor a user's project directory for new files and scan them.
    Sends a DM to the user with results; deletes malicious files automatically.
    """
    try:
        known_files = set(file_handler.get_all_files(user_dir))
        while session_manager.is_bot_running(user_id, slot):
            await asyncio.sleep(poll_interval)
            current_files = set(file_handler.get_all_files(user_dir))
            new_files = [f for f in current_files if f not in known_files]
            known_files = current_files
            if not new_files:
                continue

            # region agent log
            _agent_debug_log(
                "HYP_B",
                "bot.py:watch_new_files:new_files",
                "Detected new files for running bot",
                {"user_id": user_id, "slot": slot, "count": len(new_files)},
            )
            # endregion

            try:
                api_key = get_user_api_key(user_id)
                scan_results = await scan_files_with_gemini(api_key, user_dir, new_files)
            except Exception as e:
                logger.warning(f"New-file scan failed for user {user_id} slot {slot}: {str(e)}", exc_info=True)
                # region agent log
                _agent_debug_log(
                    "HYP_B",
                    "bot.py:watch_new_files:scan_failed",
                    "New-file scan raised exception",
                    {"user_id": user_id, "slot": slot, "error": str(e)},
                )
                # endregion
                continue

            malicious = [f for f, r in scan_results.items() if r.get('type') == 'malicious']
            safe = [f for f, r in scan_results.items() if r.get('type') != 'malicious']

            # region agent log
            _agent_debug_log(
                "HYP_B",
                "bot.py:watch_new_files:scan_results",
                "Completed new-file scan",
                {"user_id": user_id, "slot": slot, "malicious_count": len(malicious), "safe_count": len(safe)},
            )
            # endregion

            # Delete malicious files
            for mf in malicious:
                try:
                    target = (user_dir / mf).resolve()
                    # Only delete inside user_dir
                    target.relative_to(user_dir.resolve())
                    if target.exists():
                        target.unlink()
                        logger.warning(f"Deleted malicious file {mf} for user {user_id} slot {slot}")
                except Exception as e:
                    logger.error(f"Failed to delete malicious file {mf} for user {user_id}: {str(e)}", exc_info=True)

            # Notify user via DM
            try:
                user = await bot.fetch_user(user_id)
            except Exception as e:
                logger.warning(f"Unable to fetch user {user_id} for new file DM: {str(e)}")
                continue

            try:
                description_lines = []
                for f in safe:
                    description_lines.append(f"{EMOJIS['safe']} `{f}` — scanned safe")
                for f in malicious:
                    description_lines.append(f"{EMOJIS['danger']} `{f}` — flagged & removed")
                description = "\n".join(description_lines[:20])
                if len(description_lines) > 20:
                    description += f"\n...and {len(description_lines) - 20} more file(s)"

                embed = discord.Embed(
                    title=f"{EMOJIS['warning']} New File Detected (slot {slot})",
                    description=description,
                    color=EMBED_COLORS['warning'] if malicious else EMBED_COLORS['success']
                )
                await user.send(embed=embed)
            except Exception as e:
                logger.warning(f"Failed to DM user {user_id} about new files: {str(e)}")
                continue
    except Exception as e:
        logger.error(f"Fatal error in watch_new_files for user {user_id} slot {slot}: {str(e)}", exc_info=True)


async def call_openrouter(model: str, messages: list, timeout: int = 120) -> Optional[str]:
    """
    Call OpenRouter chat completion API and return the message content.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # Recommended by OpenRouter docs to identify your app
        "HTTP-Referer": "https://discord.com",
        "X-Title": "Working Bot Hoster"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.35
    }

    try:
        client = http_client or aiohttp.ClientSession()
        async with client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            if response.status != 200:
                text = await response.text()
                logger.warning(f"OpenRouter HTTP {response.status}: {text[:200]}")
                return None
            data = await response.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content")
    except Exception as e:
        logger.error(f"OpenRouter call failed: {str(e)}", exc_info=True)
        return None


def _parse_files_json(content: str) -> Tuple[bool, Optional[str], Optional[List[Dict[str, str]]]]:
    """
    Parse the JSON string returned by the AI into a list of files.
    """
    try:
        # Strip markdown fences if present
        if "```" in content:
            parts = content.split("```")
            if len(parts) > 1:
                content = parts[1]
                if content.startswith("json"):
                    content = content[4:]
        data = json.loads(content.strip())
        files = data.get("files")
        if not isinstance(files, list):
            return False, "Invalid response format: missing files array", None
        sanitized = []
        for f in files:
            name = f.get("file_name")
            body = f.get("content", "")
            if not name:
                continue
            path_obj = Path(name)
            if path_obj.is_absolute() or ".." in path_obj.parts:
                return False, f"Unsafe file path detected: {name}", None
            sanitized.append({"file_name": name, "content": body})
        return True, None, sanitized
    except Exception as e:
        logger.error(f"Failed to parse files JSON: {str(e)}", exc_info=True)
        return False, str(e), None


async def generate_files_from_prompt(user_prompt: str) -> Tuple[bool, Optional[str], Optional[List[Dict[str, str]]], Optional[str]]:
    """
    Generate bot files using prioritized models with robust fallback.
    Returns (success, error, files, model_used)
    """
    generation_prompt = (
        "You are an expert Discord bot developer with extensive experience in creating bots that are both "
        "functional and scalable. Your task is to generate a Python-based Discord bot based on the following user prompt. "
        "Your response should include multiple files that make up the bot's complete functionality. These files should be "
        "provided in a JSON format with the following structure:\n\n"
        "{\"files\": [{\"file_name\": \"main.py\", \"content\": \"...\"}, ...]}\n\n"
        "The generated files should include at least the main bot code (in a file called main.py), "
        "a requirements file (requirements.txt) listing necessary libraries, .env for sensitive data like the bot token, "
        "and any other necessary files (e.g., README.md, etc.).\n\n"
        "Important: Ensure that the bot is implemented in a modular way, the code should be efficient and well-commented for easy understanding. "
        "Ensure that external dependencies are listed clearly in the requirements.txt and all sensitive data is securely handled in the .env. "
        "Respond ONLY with valid JSON, no markdown fences, no explanation."
    )
    full_prompt = f"{generation_prompt}\n\nUser prompt:\n{user_prompt}"
    # Extended model list for better fallback coverage
    models = [
        "google/gemini-2.0-flash-exp:free",
        "amazon/nova-2-lite-v1:free",
        "qwen/qwen3-coder:free",
        "tngtech/deepseek-r1t-chimera:free",
        "mistralai/mistral-small-3.1-24b-instruct:free",
    ]
    last_error = None
    for model in models:
        logger.info(f"[generate_files] Trying model: {model}")
        content = await call_openrouter(model, [{"role": "user", "content": full_prompt}])
        if not content:
            logger.warning(f"[generate_files] Model {model} returned no content, trying next.")
            continue
        ok, err, files = _parse_files_json(content)
        # region agent log
        _agent_debug_log(
            "HYP_C",
            "bot.py:generate_files_from_prompt:model_result",
            "Model generation attempt",
            {"model": model, "ok": ok, "file_count": len(files) if files else 0, "err": err},
        )
        # endregion
        if ok and files:
            logger.info(f"[generate_files] Success with model {model}, {len(files)} files.")
            return True, None, files, model
        else:
            last_error = err
            logger.warning(f"[generate_files] Model {model} returned invalid/truncated JSON: {err}, trying next.")
    return False, last_error or "All models failed to generate valid files.", None, None


async def check_console_output_for_error(output_text: str) -> Optional[bool]:
    """
    Ask the model if console output indicates an error. Returns True/False/None.
    Uses multiple models with fallback.
    """
    prompt = (
        "Is this console output an error? Reply with JSON: {\"yes\":true} for error, {\"yes\":false} for no error. "
        "No explanation.\n\n"
        f"Console output:\n{output_text}"
    )
    models = [
        "google/gemini-2.0-flash-exp:free",
        "amazon/nova-2-lite-v1:free",
        "qwen/qwen3-coder:free",
        "tngtech/deepseek-r1t-chimera:free",
        "mistralai/mistral-small-3.1-24b-instruct:free",
    ]
    for model in models:
        content = await call_openrouter(model, [{"role": "user", "content": prompt}], timeout=60)
        if not content:
            logger.warning(f"[check_error] Model {model} returned no content, trying next.")
            continue
        try:
            if "```" in content:
                parts = content.split("```")
                if len(parts) > 1:
                    content = parts[1]
                    if content.startswith("json"):
                        content = content[4:]
            data = json.loads(content.strip())
            decision = bool(data.get("yes"))
            # region agent log
            _agent_debug_log(
                "HYP_D",
                "bot.py:check_console_output_for_error:decision",
                "Model classified console output",
                {"model": model, "is_error": decision},
            )
            # endregion
            return decision
        except Exception as e:
            logger.warning(f"[check_error] Model {model} returned unparseable response: {e}, trying next.")
            continue
    return None


async def request_error_fix(files: List[Dict[str, str]], console_output: str) -> Tuple[bool, Optional[str], Optional[List[Dict[str, str]]]]:
    """
    Ask AI to fix code based on console errors. Returns (success, error, updated_files).
    Uses multiple models with fallback.
    """
    files_json = json.dumps({"files": files, "console_output": console_output})
    prompt = (
        "You are expert discord bot error fixer. Below codes contain error. "
        "Please fix them. Provide full updated code for only necessary files, no placeholders. "
        "Respond strictly in JSON as {\"files\":[{\"file_name\":\"...\",\"content\":\"...\"}],\"statement\": \"...\"}. "
        "No markdown fences, just raw JSON.\n"
        "Here is the payload:\n"
        f"{files_json}"
    )
    models = [
        "google/gemini-2.0-flash-exp:free",
        "amazon/nova-2-lite-v1:free",
        "qwen/qwen3-coder:free",
        "tngtech/deepseek-r1t-chimera:free",
        "mistralai/mistral-small-3.1-24b-instruct:free",
    ]
    last_error = None
    for model in models:
        logger.info(f"[request_error_fix] Trying model: {model}")
        content = await call_openrouter(model, [{"role": "user", "content": prompt}], timeout=120)
        if not content:
            logger.warning(f"[request_error_fix] Model {model} returned no content, trying next.")
            continue
        ok, err, parsed = _parse_files_json(content)
        if ok and parsed is not None:
            logger.info(f"[request_error_fix] Success with model {model}, {len(parsed)} files.")
            return True, None, parsed
        # Even if parsing failed, try to parse statement
        try:
            raw = content
            if "```" in raw:
                parts = raw.split("```")
                if len(parts) > 1:
                    raw = parts[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
            data = json.loads(raw.strip())
            if "statement" in data:
                return True, data.get("statement"), []
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[request_error_fix] Model {model} returned unparseable response: {e}, trying next.")
            continue
    return False, last_error or "Unable to generate fixes from AI", None


def write_files_to_directory(base_dir: Path, files: List[Dict[str, str]]) -> Tuple[List[str], List[str]]:
    """
    Write generated files safely into the target directory.
    Returns (written_files, errors)
    """
    written = []
    errors = []
    for f in files:
        name = f.get("file_name")
        content = f.get("content", "")
        if not name:
            continue
        path_obj = Path(name)
        if path_obj.is_absolute() or ".." in path_obj.parts:
            errors.append(f"Unsafe path skipped: {name}")
            continue
        target = (base_dir / path_obj).resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fp:
                fp.write(content)
            written.append(str(path_obj))
        except Exception as e:
            errors.append(f"{name}: {str(e)}")
    return written, errors


def parse_env_keys(env_path: Path, limit: int = 5) -> List[str]:
    """Extract env variable keys from a .env file (best-effort)."""
    keys = []
    if not env_path.exists():
        return keys
    try:
        with open(env_path, "r", encoding="utf-8", errors="ignore") as fp:
            for line in fp:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip()
                if key:
                    keys.append(key)
                if len(keys) >= limit:
                    break
    except Exception:
        return []
    return keys


def find_requirements_path(project_dir: Path) -> Optional[Path]:
    """Locate requirements.txt inside the generated project."""
    candidates = [project_dir / "requirements.txt", project_dir / "requirement.txt"]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def install_requirements(req_path: Path, cwd: Path) -> Tuple[bool, str]:
    """Install requirements from a file."""
    try:
        result = subprocess.run(
            ['pip', 'install', '-r', str(req_path)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=360
        )
        if result.returncode == 0:
            return True, result.stdout
        return False, result.stderr or result.stdout
    except subprocess.TimeoutExpired:
        return False, "Dependency installation timed out."
    except Exception as e:
        return False, str(e)

class InstallPackagesView(discord.ui.View):
    """View for installing packages."""
    
    def __init__(self, user_id: int, user_dir: Path, channel, slot: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.user_dir = user_dir
        self.channel = channel
        self.slot = slot
    
    @discord.ui.button(label="✅ Yes", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Yes button to install packages."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your upload!", ephemeral=True)
            return
        
        modal = PackageInstallModal(self.user_dir, self.channel, self.slot)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="❌ No", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """No button to skip package installation."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your upload!", ephemeral=True)
            return
        
        # Get all files for main file selector
        all_files = file_handler.get_all_files(self.user_dir)
        await show_main_file_selector(self.channel, self.user_id, self.user_dir, all_files, self.slot)
        await interaction.response.defer()

class PackageInstallModal(discord.ui.Modal, title="📦 Install Packages"):
    """Modal for entering package names."""
    
    def __init__(self, user_dir: Path, channel, slot: int):
        super().__init__()
        self.user_dir = user_dir
        self.channel = channel
        self.slot = slot
    
    package_input = discord.ui.TextInput(
        label="Package Names",
        placeholder="discord.py\nrequests\nnumpy\n...",
        style=discord.TextStyle.paragraph,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle package installation."""
        try:
            packages = [p.strip() for p in self.package_input.value.split('\n') if p.strip()]
            logger.info(f"Installing packages for user {interaction.user.id}: {packages}")
            
            embed = discord.Embed(
                title=f"{EMOJIS['loading']} Installing Packages",
                description=f"Installing `{len(packages)}` package(s)...",
                color=EMBED_COLORS['warning']
            )
            await interaction.response.send_message(embed=embed)
            msg = await interaction.original_response()
            
            try:
                result = subprocess.run(
                    ['pip', 'install'] + packages,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode == 0:
                    # Compose installed package list (we have the package names)
                    desc = f"Successfully installed `{len(packages)}` package(s)!"
                    if packages:
                        desc += "\n\nInstalled: `" + ", ".join(packages) + "`"
                    embed = discord.Embed(
                        title=f"{EMOJIS['safe']} Packages Installed",
                        description=desc,
                        color=EMBED_COLORS['success']
                    )
                    logger.info(f"Successfully installed packages for user {interaction.user.id}")
                else:
                    embed = discord.Embed(
                        title=f"{EMOJIS['danger']} Installation Warning",
                        description=f"Some packages failed:\n```\n{result.stderr[:1000]}\n```",
                        color=EMBED_COLORS['warning']
                    )
                    logger.warning(f"Partial package installation failure for user {interaction.user.id}")
            except subprocess.TimeoutExpired:
                embed = discord.Embed(
                    title=f"{EMOJIS['danger']} Installation Timeout",
                    description="Package installation timed out after 5 minutes.",
                    color=EMBED_COLORS['error']
                )
                logger.error(f"Package installation timeout for user {interaction.user.id}")
            except Exception as e:
                embed = discord.Embed(
                    title=f"{EMOJIS['danger']} Installation Error",
                    description=f"Error: `{str(e)}`",
                    color=EMBED_COLORS['error']
                )
                logger.error(f"Error installing packages for user {interaction.user.id}: {str(e)}", exc_info=True)
            
            await msg.edit(embed=embed)
            
            # Get all files for main file selector
            all_files = file_handler.get_all_files(self.user_dir)
            await show_main_file_selector(self.channel, interaction.user.id, self.user_dir, all_files, self.slot)
            
        except Exception as e:
            logger.error(f"Error in package installation modal: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred during package installation.",
                ephemeral=True
            )

async def show_main_file_selector(channel, user_id: int, user_dir: Path, all_files: list, slot: int):
    """Show dropdown to select main file."""
    try:
        # Filter Python files
        python_files = file_handler.find_python_files(user_dir)
        
        if not python_files:
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} No Python Files",
                description="No Python files found in your code!",
                color=EMBED_COLORS['error']
            )
            await channel.send(embed=embed)
            session_manager.end_upload_session(user_id)
            return
        
        embed = discord.Embed(
            title=f"{EMOJIS['file']} Select Main File",
            description=f"Choose the main file to run your bot (slot {slot}):",
            color=EMBED_COLORS['info']
        )
        
        view = MainFileView(user_id, user_dir, python_files, slot)
        await channel.send(embed=embed, view=view)
        session_manager.end_upload_session(user_id)
        
    except Exception as e:
        logger.error(f"Error showing main file selector: {str(e)}", exc_info=True)
        embed = discord.Embed(
            title=f"{EMOJIS['danger']} Error",
            description=f"An error occurred: `{str(e)}`",
            color=EMBED_COLORS['error']
        )
        await channel.send(embed=embed)

class MainFileView(discord.ui.View):
    """View for selecting and running main file."""
    
    def __init__(self, user_id: int, user_dir: Path, files: list, slot: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.user_dir = user_dir
        self.selected_file = None
        self.files = files
        self.slot = slot
        self.add_item(MainFileSelect(files, self))
    
    @discord.ui.button(label=f"{EMOJIS['play']} Run Bot", style=discord.ButtonStyle.success, row=1)
    async def run_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Run the bot with selected file."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your upload!", ephemeral=True)
            return
        
        if not self.selected_file:
            await interaction.response.send_message("❌ Please select a main file first!", ephemeral=True)
            return
        
        # Enforce per-user max bots
        if session_manager.get_running_bots_count_for_user(self.user_id) >= MAX_BOTS_PER_USER:
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Bot Limit Reached",
                description=(
                    f"You can run up to `{MAX_BOTS_PER_USER}` bots. Stop an existing bot before starting a new one."
                ),
                color=EMBED_COLORS['error']
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Prevent double-use of same slot
        if session_manager.is_bot_running(self.user_id, self.slot):
            await interaction.response.send_message(
                f"❌ Slot {self.slot} is already running. Stop it first.",
                ephemeral=True
            )
            return
        
        try:
            main_file = self.user_dir / self.selected_file
            
            # Verify the file exists
            if not main_file.exists():
                await interaction.response.send_message("❌ Selected file not found!", ephemeral=True)
                return
            
            # Security check: ensure file is within user directory
            try:
                main_file.resolve().relative_to(self.user_dir.resolve())
            except ValueError:
                await interaction.response.send_message("❌ Invalid file path!", ephemeral=True)
                return
            
            # Start bot
            embed = discord.Embed(
                title=f"{EMOJIS['play']} Starting Bot",
                description=f"Starting bot with main file: `{self.selected_file}` (slot {self.slot})",
                color=EMBED_COLORS['success']
            )
            await interaction.response.send_message(embed=embed)
            msg = await interaction.original_response()
            
            # Start process
            process, error = code_executor.start_process(main_file, self.user_dir)
            if process is None:
                embed = discord.Embed(
                    title=f"{EMOJIS['danger']} Error Starting Bot",
                    description=f"Error: `{error}`",
                    color=EMBED_COLORS['error']
                )
                await msg.edit(embed=embed)
                return
            
            # Register running bot
            session_manager.register_running_bot(self.user_id, self.slot, process, self.user_dir, msg)
            await refresh_presence()
            
            # Start new-file watcher for auto-scanning newly created files
            bot.loop.create_task(watch_new_files(self.user_id, self.slot, self.user_dir))
            
            # Start console output monitoring
            async def output_callback(output_lines: list):
                """Callback for console output updates."""
                try:
                    output_text = "\n".join(output_lines)
                    if len(output_text) > MAX_CONSOLE_OUTPUT_LENGTH:
                        output_text = output_text[-MAX_CONSOLE_OUTPUT_LENGTH:]
                    
                    embed = discord.Embed(
                        title=f"{EMOJIS['play']} Console Output",
                        description=f"```\n{output_text}\n```",
                        color=EMBED_COLORS['info']
                    )
                    bot_info = session_manager.get_running_bot(self.user_id, self.slot)
                    if bot_info and bot_info.get('message'):
                        await bot_info['message'].edit(embed=embed)
                except Exception as e:
                    logger.warning(f"Error in output callback: {str(e)}")
            
            async def _monitor_and_deliver():
                try:
                    full_lines = await code_executor.monitor_console_output(process, output_callback)
                    full_text = "\n".join(full_lines)
                    # If not too large, edit the existing message to include final output
                    if len(full_text) <= MAX_CONSOLE_OUTPUT_LENGTH:
                        embed = discord.Embed(
                            title=f"{EMOJIS['play']} Console Output (Final)",
                            description=f"```\n{full_text}\n```",
                            color=EMBED_COLORS['info']
                        )
                        bot_info = session_manager.get_running_bot(self.user_id, self.slot)
                        if bot_info and bot_info.get('message'):
                            try:
                                await bot_info['message'].edit(embed=embed)
                            except Exception:
                                pass
                    else:
                        # Too large for embed - send as a file
                        try:
                            bot_info = session_manager.get_running_bot(self.user_id)
                            target_channel = None
                            if bot_info and bot_info.get('message'):
                                target_channel = bot_info['message'].channel
                            if not target_channel:
                                target_channel = msg.channel
                            # Split into a .txt file and send as attachment
                            from io import BytesIO
                            bio = BytesIO(full_text.encode('utf-8'))
                            bio.seek(0)
                            await target_channel.send(content=f"{EMOJIS['play']} Full console output for `{self.selected_file}`:", file=discord.File(fp=bio, filename=f"console_{self.user_id}.txt"))
                        except Exception:
                            logger.exception("Failed to deliver full console output file")
                except Exception as e:
                    logger.error(f"Error in monitor_and_deliver: {str(e)}", exc_info=True)

            bot.loop.create_task(_monitor_and_deliver())
            
            embed = discord.Embed(
                title=f"{EMOJIS['play']} Bot Running",
                description=(
                    f"Bot is now running!\n\n"
                    f"Main file: `{self.selected_file}`\n"
                    f"Slot: `{self.slot}`\n\n"
                    f"Console output will appear below:"
                ),
                color=EMBED_COLORS['success']
            )
            if status_server and status_server.display_url:
                embed.description += f"\n\nStatus page: `{status_server.display_url}`"
            view = BotControlView(self.user_id, self.slot)
            await msg.edit(embed=embed, view=view)
            logger.info(f"Bot started for user {self.user_id} with file {self.selected_file}")
            
        except Exception as e:
            logger.error(f"Error running bot for user {self.user_id}: {str(e)}", exc_info=True)
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Error Starting Bot",
                description=f"Error: `{str(e)}`",
                color=EMBED_COLORS['error']
            )
            try:
                await interaction.response.send_message(embed=embed)
            except:
                pass

class MainFileSelect(discord.ui.Select):
    """Select menu for choosing main file."""
    
    def __init__(self, files: list, parent_view):
        options = [discord.SelectOption(label=f, value=f, description=f"Select {f} as main file") for f in files[:25]]
        super().__init__(placeholder="Choose main file...", options=options)
        self.files = files
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        """Handle file selection."""
        self.parent_view.selected_file = self.values[0]
        
        embed = discord.Embed(
            title=f"{EMOJIS['file']} Main File Selected",
            description=f"Selected: `{self.values[0]}`\n\nClick 'Run Bot' to start!",
            color=EMBED_COLORS['info']
        )
        # Show the user's avatar as a square thumbnail on the right
        try:
            avatar_url = interaction.user.display_avatar.url
            embed.set_thumbnail(url=avatar_url)
        except Exception:
            pass
        await interaction.response.send_message(embed=embed, ephemeral=True)

class BotControlView(discord.ui.View):
    """View for controlling running bot."""
    
    def __init__(self, user_id: int, slot: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.slot = slot
    
    @discord.ui.button(label=f"{EMOJIS['stop']} Stop Bot", style=discord.ButtonStyle.danger)
    async def stop_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Stop the running bot."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your bot!", ephemeral=True)
            return
        
        if not session_manager.is_bot_running(self.user_id, self.slot):
            await interaction.response.send_message("❌ No bot is running!", ephemeral=True)
            return
        
        try:
            success, error = session_manager.stop_bot(self.user_id, self.slot)
            if success:
                embed = discord.Embed(
                    title=f"{EMOJIS['stop']} Bot Stopped",
                    description=f"Your bot in slot {self.slot} has been stopped.",
                    color=EMBED_COLORS['error']
                )
                logger.info(f"Bot stopped by user {self.user_id}")
                await refresh_presence()
            else:
                embed = discord.Embed(
                    title=f"{EMOJIS['danger']} Error",
                    description=f"Error stopping bot: `{error}`",
                    color=EMBED_COLORS['error']
                )
                logger.error(f"Error stopping bot for user {self.user_id}: {error}")
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except Exception as e:
            logger.error(f"Error in stop_bot: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while stopping the bot.",
                ephemeral=True
            )



class EnvFillModal(discord.ui.Modal, title="Fill .env values"):
    """Modal to capture .env values from the user."""
    
    def __init__(self, env_path: Path, keys: List[str]):
        super().__init__(timeout=300)
        self.env_path = env_path
        self.keys = keys
        # Dynamically create text inputs (up to 5)
        for key in keys:
            field = discord.ui.TextInput(
                label=key,
                placeholder=f"Enter value for {key}",
                required=True,
                style=discord.TextStyle.short
            )
            self.add_item(field)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            lines = []
            for item in self.children:
                if isinstance(item, discord.ui.TextInput):
                    lines.append(f"{item.label}={item.value}")
            self.env_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.env_path, "w", encoding="utf-8") as fp:
                fp.write("\n".join(lines))
            embed = discord.Embed(
                title=f"{EMOJIS['safe']} .env updated",
                description="Your environment values have been saved.",
                color=EMBED_COLORS['success']
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error saving .env values: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                "❌ Failed to save .env values.",
                ephemeral=True
            )


class EnvFillView(discord.ui.View):
    """View that provides a button to open the .env modal."""
    
    def __init__(self, env_path: Path, keys: List[str]):
        super().__init__(timeout=600)
        self.env_path = env_path
        self.keys = keys
    
    @discord.ui.button(label="Fill .env", style=discord.ButtonStyle.primary)
    async def fill_env(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EnvFillModal(self.env_path, self.keys)
        await interaction.response.send_modal(modal)


async def run_generated_bot(channel, user_id: int, slot: int, project_dir: Path, main_file: Path):
    """
    Start and monitor a generated bot project.
    Returns tuple (full_output_text, message_obj)
    """
    try:
        embed = discord.Embed(
            title=f"{EMOJIS['play']} Starting Generated Bot",
            description=f"Starting `main.py` in slot `{slot}`...",
            color=EMBED_COLORS['info']
        )
        msg = await channel.send(embed=embed)
        
        process, error = code_executor.start_process(main_file, project_dir)
        if process is None:
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Start Failed",
                description=f"Error: `{error}`",
                color=EMBED_COLORS['error']
            )
            await msg.edit(embed=embed)
            return "", msg
        
        session_manager.register_running_bot(user_id, slot, process, project_dir, msg)
        await refresh_presence()

        # Start new file watcher
        bot.loop.create_task(watch_new_files(user_id, slot, project_dir))

        async def output_callback(output_lines: list):
            try:
                output_text = "\n".join(output_lines)
                if len(output_text) > MAX_CONSOLE_OUTPUT_LENGTH:
                    output_text = output_text[-MAX_CONSOLE_OUTPUT_LENGTH:]
                embed = discord.Embed(
                    title=f"{EMOJIS['play']} Console Output (slot {slot})",
                    description=f"```\n{output_text}\n```",
                    color=EMBED_COLORS['info']
                )
                bot_info = session_manager.get_running_bot(user_id, slot)
                if bot_info and bot_info.get('message'):
                    await bot_info['message'].edit(embed=embed, view=BotControlView(user_id, slot))
            except Exception as e:
                logger.warning(f"Output callback error: {str(e)}")

        full_lines = await code_executor.monitor_console_output(process, output_callback)
        full_text = "\n".join(full_lines)

        final_embed = discord.Embed(
            title=f"{EMOJIS['stop']} Bot finished",
            description=f"```\n{full_text[-MAX_CONSOLE_OUTPUT_LENGTH:]}\n```",
            color=EMBED_COLORS['warning']
        )
        try:
            await msg.edit(embed=final_embed, view=None)
        except Exception:
            pass
        return full_text, msg
    except Exception as e:
        logger.error(f"Error running generated bot: {str(e)}", exc_info=True)
        return "", None


@bot.tree.command(name="develop", description="🛠️ Generate and run a Discord bot with AI")
@app_commands.describe(prompt="Describe the bot you want to build")
async def develop_command(interaction: discord.Interaction, prompt: str):
    """Generate bot code via AI, install, run, and auto-fix errors."""
    user_id = interaction.user.id
    
    # Check for API key first (can't defer before this check for modal to work)
    api_key = get_user_api_key(user_id)
    if not api_key:
        # Show API key prompt
        embed = discord.Embed(
            title=f"{EMOJIS['warning']} API Key Required",
            description=(
                "To use the Bot Hoster, you need to enter your **Google AI Studio API key**.\n\n"
                "**How to get your free API key:**\n"
                "1. Click the **Get API Key** button below\n"
                "2. Sign in with your Google account\n"
                "3. Create a new API key\n"
                "4. Copy the key and click **Enter API Key**\n\n"
                "Your key is stored securely and used only for AI features."
            ),
            color=EMBED_COLORS['warning']
        )
        embed.set_footer(text="Google AI Studio provides 60 requests/min for free!")
        view = ApiKeyRequiredView("develop")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return
    
    await interaction.response.defer(thinking=True, ephemeral=False)

    # Ensure capacity
    if session_manager.get_running_bots_count_for_user(user_id) >= MAX_BOTS_PER_USER:
        await interaction.followup.send(
            f"❌ You already have `{MAX_BOTS_PER_USER}` bots running. Stop one before using /develop.",
            ephemeral=True
        )
        return

    # Reserve slot and directory
    success, error, slot, project_dir = session_manager.start_upload_session(user_id, "develop")
    if not success or slot is None or project_dir is None:
        await interaction.followup.send(f"❌ {error or 'Cannot start a develop session right now.'}", ephemeral=True)
        return

    progress_embed = discord.Embed(
        title=f"{EMOJIS['rocket']} Creating your bot",
        description=f"Slot: `{slot}`\nPrompt: `{prompt}`\n\n{EMOJIS['loading']} Generating files...",
        color=EMBED_COLORS['info']
    )
    progress_msg = await interaction.followup.send(embed=progress_embed)

    # Generate files with Gemini AI
    gen_ok, gen_err, files, _ = await generate_bot_files(api_key, prompt)
    if not gen_ok or not files:
        err_embed = discord.Embed(
            title=f"{EMOJIS['danger']} Generation Failed",
            description=f"Error: `{gen_err}`",
            color=EMBED_COLORS['error']
        )
        await progress_msg.edit(embed=err_embed)
        session_manager.end_upload_session(user_id)
        return

    file_names = [f.get("file_name") for f in files if f.get("file_name")]
    status_lines = [f"{EMOJIS['loading']} `{name}`" for name in file_names]
    progress_embed.description = (
        f"Slot: `{slot}`\nModel: `Gemini 1.5 Flash`\n\n" +
        "\n".join(status_lines)
    )
    await progress_msg.edit(embed=progress_embed)

    # Write files
    written, write_errors = write_files_to_directory(project_dir, files)
    status_lines = [f"{EMOJIS['safe']} `{name}`" for name in written]
    if write_errors:
        status_lines += [f"{EMOJIS['danger']} {err}" for err in write_errors]
    progress_embed.description = "\n".join(status_lines) or "No files written."
    progress_embed.title = f"{EMOJIS['safe']} Files Generated"
    await progress_msg.edit(embed=progress_embed)

    # Offer .env fill if present
    env_path = project_dir / ".env"
    if env_path.exists():
        keys = parse_env_keys(env_path)
        env_embed = discord.Embed(
            title=f"{EMOJIS['warning']} Fill your .env",
            description="Please fill required environment values before running (optional).",
            color=EMBED_COLORS['warning']
        )
        env_view = EnvFillView(env_path, keys) if keys else EnvFillView(env_path, [])
        await interaction.followup.send(embed=env_embed, view=env_view, ephemeral=True)

    # Install requirements
    req_path = find_requirements_path(project_dir)
    if req_path:
        ok, pip_log = install_requirements(req_path, project_dir)
        req_embed = discord.Embed(
            title=f"{EMOJIS['safe'] if ok else EMOJIS['warning']} Dependencies",
            description="Installed requirements." if ok else f"Installation issues:\n```\n{pip_log[:900]}\n```",
            color=EMBED_COLORS['success'] if ok else EMBED_COLORS['warning']
        )
        await interaction.followup.send(embed=req_embed, ephemeral=True)
    else:
        await interaction.followup.send(
            f"{EMOJIS['warning']} No requirements.txt found. Skipping installation.",
            ephemeral=True
        )

    # End upload session so user can initiate another if needed
    session_manager.end_upload_session(user_id)

    # Run bot with auto-fix loop (max 2 attempts)
    main_file = project_dir / "main.py"
    attempts = 0
    files_state = files
    last_output = ""
    while attempts < 2:
        last_output, run_message = await run_generated_bot(interaction.channel, user_id, slot, project_dir, main_file)
        await refresh_presence()

        # Evaluate output using Gemini
        _, is_error, _ = await check_for_error(api_key, last_output)
        # region agent log
        _agent_debug_log(
            "HYP_D",
            "bot.py:develop_command:error_check",
            "Evaluated console output for error",
            {"attempt": attempts, "is_error": is_error},
        )
        # endregion
        if not is_error:
            break

        # Request fixes using Gemini
        fix_ok, fix_err, fixed_files = await fix_bot_errors(api_key, files_state, last_output)
        if not fix_ok:
            warn_embed = discord.Embed(
                title=f"{EMOJIS['danger']} Auto-fix failed",
                description=fix_err or "Could not generate fixes.",
                color=EMBED_COLORS['error']
            )
            await interaction.followup.send(embed=warn_embed, ephemeral=True)
            break

        if fixed_files:
            write_files_to_directory(project_dir, fixed_files)
            files_state = fixed_files
            # Reinstall requirements in case they changed
            req_path = find_requirements_path(project_dir)
            if req_path:
                install_requirements(req_path, project_dir)
            attempts += 1
            continue
        else:
            # Only statement provided
            info_embed = discord.Embed(
                title=f"{EMOJIS['warning']} Auto-fix hint",
                description=fix_err or "Check your configuration values.",
                color=EMBED_COLORS['warning']
            )
            await interaction.followup.send(embed=info_embed, ephemeral=True)
            break









class StatusServer:
    """Simple aiohttp server reporting bot status on a random free port."""
    
    def __init__(self, session_manager: SessionManager, host: str = "0.0.0.0"):
        self._session_manager = session_manager
        self._host = host
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self.port: Optional[int] = None
        self._app = web.Application(middlewares=[self._error_middleware])
        self._app.router.add_get("/", self._handle_root)
        self._app.router.add_get("/healthz", self._handle_health)
        self._app.router.add_get("/metrics", self._handle_metrics)
        self._start_lock = asyncio.Lock()
    
    @property
    def host(self) -> str:
        return self._host
    
    @property
    def display_url(self) -> Optional[str]:
        if not self.port:
            return None
        host = "127.0.0.1" if self._host in ("0.0.0.0", "::") else self._host
        return f"http://{host}:{self.port}"
    
    @web.middleware
    async def _error_middleware(self, request, handler):
        try:
            return await handler(request)
        except Exception as e:
            logger.error(f"StatusServer error handling {request.method} {request.path}: {str(e)}", exc_info=True)
            return web.json_response({"status": "error", "message": "internal server error"}, status=500)
    
    async def _handle_root(self, request: web.Request):
        running = self._session_manager.get_running_bots_count()
        body = f"Bot is running. Active bots: {running}\n{COOL_TAGLINE}"
        return web.Response(text=body)
    
    async def _handle_health(self, request: web.Request):
        return web.json_response({
            "status": "ok",
            "tagline": COOL_TAGLINE,
            "active_bots": self._session_manager.get_running_bots_count()
        })
    
    async def _handle_metrics(self, request: web.Request):
        # Basic Prometheus-like metrics
        active = self._session_manager.get_running_bots_count()
        lines = [
            "# HELP bot_active_bots Number of running hosted bots.",
            "# TYPE bot_active_bots gauge",
            f"bot_active_bots {active}",
            "# HELP bot_tagline Constant label describing the service.",
            "# TYPE bot_tagline gauge",
            "bot_tagline 1",
        ]
        return web.Response(text="\n".join(lines), content_type="text/plain")
    
    async def start(self) -> Optional[int]:
        """Start server on free port; returns selected port."""
        async with self._start_lock:
            if self._runner and self._site:
                return self.port
            self._runner = web.AppRunner(self._app, access_log=None)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, host=self._host, port=0)
            await self._site.start()
            sockets = getattr(self._site._server, "sockets", None)  # type: ignore[attr-defined]
            if sockets:
                self.port = sockets[0].getsockname()[1]
            logger.info(f"Status server listening on {self._host}:{self.port}")
            return self.port
    
    async def stop(self):
        async with self._start_lock:
            if self._site:
                await self._site.stop()
                self._site = None
            if self._runner:
                await self._runner.cleanup()
                self._runner = None
            self.port = None


status_server = StatusServer(session_manager)

async def main():
    """Entry point to start status server and Discord bot concurrently."""
    status_port = None
    try:
        global http_client
        http_client = aiohttp.ClientSession()
        status_port = await status_server.start()
        if status_server.display_url:
            logger.info(f"Status dashboard available at {status_server.display_url}")
        logger.info("Starting Discord bot...")
        await bot.start(DISCORD_TOKEN)
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        logger.info("Shutdown requested via KeyboardInterrupt.")
    except Exception as e:
        logger.error(f"Fatal error while running bot: {str(e)}", exc_info=True)
        raise
    finally:
        global _presence_task
        if _presence_task:
            _presence_task.cancel()
            try:
                await _presence_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Error awaiting presence task: {str(e)}", exc_info=True)
            _presence_task = None
        try:
            await status_server.stop()
        except Exception as e:
            logger.warning(f"Error stopping status server: {str(e)}", exc_info=True)
        try:
            if http_client:
                await http_client.close()
        except Exception as e:
            logger.warning(f"Error closing HTTP client: {str(e)}", exc_info=True)
        if not bot.is_closed():
            try:
                await bot.close()
            except Exception as e:
                logger.warning(f"Error closing bot: {str(e)}", exc_info=True)
        logger.info(f"Bot shutdown complete. Status server port was: {status_port}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)


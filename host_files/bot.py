import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import zipfile
import os
import json
import subprocess
import psutil
import threading
from datetime import datetime
import shutil
import sys
import io
import time

# Get the directory where this script is located (host_files folder)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# User uploads should be in parent directory, not inside host_files
PARENT_DIR = os.path.dirname(BASE_DIR)
USER_UPLOADS_DIR = os.path.join(PARENT_DIR, "user_uploads")
os.makedirs(USER_UPLOADS_DIR, exist_ok=True)

# Add host_files to path for imports
sys.path.insert(0, BASE_DIR)
from security import SecurityChecker

# Configuration - load from project config (use .env or environment variables)
try:
    from config import DISCORD_TOKEN, GUILD_ID, OPENROUTER_API_KEY
except Exception:
    DISCORD_TOKEN = None
    GUILD_ID = None
    OPENROUTER_API_KEY = None

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# Store running bots and user projects
running_bots = {}  # {user_id: {process, project_path, console_output}}
user_projects = {}  # {user_id: project_path}
security_checker = SecurityChecker(OPENROUTER_API_KEY)

# Emojis
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
    "disk": "💿"
}

def get_user_project_dir(user_id):
    """Get or create user project directory"""
    user_dir = os.path.join(USER_UPLOADS_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return os.path.abspath(user_dir)  # Always return absolute path

@bot.event
async def on_ready():
    print(f'🤖 {bot.user} has logged in!')
    # Sync commands on startup
    try:
        synced = await bot.tree.sync()
        print(f'✅ Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'❌ Error syncing commands: {e}')

@bot.tree.command(name="host", description="🚀 Host your Discord bot on our server!")
async def host_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"{EMOJIS['robot']} Bot Hosting Service",
        description="Welcome to our Discord bot hosting service! Follow these steps:",
        color=0x5865F2
    )
    embed.add_field(
        name="📋 Steps to Host Your Bot",
        value="1️⃣ Prepare your bot code in a `.zip` file\n"
              "2️⃣ Click one of the buttons below to upload\n"
              "3️⃣ We'll scan your code for security\n"
              "4️⃣ Install dependencies if needed\n"
              "5️⃣ Select your main file\n"
              "6️⃣ Run your bot!",
        inline=False
    )
    embed.add_field(
        name="⚠️ Important Notes",
        value="• Only `.zip` files are accepted\n"
              "• Your code will be security scanned\n"
              "• Malicious code will be rejected\n"
              "• Each user can host one bot at a time",
        inline=False
    )
    embed.set_footer(text="Choose an upload method below 👇")
    
    view = UploadMethodView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

@bot.tree.command(name="status", description="📊 Check server system status and resources")
async def status_command(interaction: discord.Interaction):
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    embed = discord.Embed(
        title=f"{EMOJIS['server']} Server Status",
        color=0x00FF00 if cpu_percent < 80 else 0xFF0000
    )
    embed.add_field(
        name=f"{EMOJIS['cpu']} CPU Usage",
        value=f"`{cpu_percent}%`",
        inline=True
    )
    embed.add_field(
        name=f"{EMOJIS['memory']} Memory Usage",
        value=f"`{memory.percent}%`\nUsed: `{memory.used / (1024**3):.2f} GB`\nTotal: `{memory.total / (1024**3):.2f} GB`",
        inline=True
    )
    embed.add_field(
        name=f"{EMOJIS['disk']} Disk Usage",
        value=f"`{disk.percent}%`\nUsed: `{disk.used / (1024**3):.2f} GB`\nTotal: `{disk.total / (1024**3):.2f} GB`",
        inline=True
    )
    
    # Count running bots
    running_count = len([b for b in running_bots.values() if b.get('process') and b['process'].poll() is None])
    embed.add_field(
        name=f"{EMOJIS['robot']} Running Bots",
        value=f"`{running_count}` active bot(s)",
        inline=False
    )
    
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="🗑️ Delete all your hosted projects (WARNING: This cannot be undone!)")
async def clear_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_dir = get_user_project_dir(user_id)
    
    if not os.path.exists(user_dir) or not os.listdir(user_dir):
        embed = discord.Embed(
            title=f"{EMOJIS['trash']} Clear Projects",
            description="You don't have any projects to delete!",
            color=0xFFA500
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    embed = discord.Embed(
        title=f"⚠️ WARNING: Delete All Projects",
        description=f"This will **permanently delete** all your hosted projects!\n\n"
                   f"This action **cannot be undone**.\n\n"
                   f"Are you sure you want to proceed?",
        color=0xFF0000
    )
    embed.set_footer(text="Click the button below to confirm deletion")
    
    view = ConfirmClearView(user_id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="help", description="❓ Get help about the bot hosting service")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"{EMOJIS['help']} Bot Hosting Service - Help",
        description="Here's everything you need to know about our hosting service!",
        color=0x5865F2
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
        value="1. Use `/host` to start\n"
              "2. Upload your `.zip` file\n"
              "3. Code is automatically scanned\n"
              "4. Install dependencies\n"
              "5. Select main file and run!",
        inline=False
    )
    embed.add_field(
        name="🔒 Security",
        value="• All code is scanned for malicious content\n"
              "• Linux commands are not allowed\n"
              "• File system access is restricted\n"
              "• Only safe code will be executed",
        inline=False
    )
    embed.set_footer(text="Need more help? Contact the server admins!")
    await interaction.response.send_message(embed=embed, ephemeral=True)

class ConfirmClearView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
    
    @discord.ui.button(label="✅ Confirm Delete", style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your project!", ephemeral=True)
            return
        
        user_dir = get_user_project_dir(self.user_id)
        
        # Stop running bot if any
        if self.user_id in running_bots:
            try:
                process = running_bots[self.user_id].get('process')
                if process:
                    if isinstance(process, asyncio.subprocess.Process):
                        process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(), timeout=2)
                        except:
                            process.kill()
                    else:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except:
                            process.kill()
                del running_bots[self.user_id]
            except:
                pass
        
        # Delete directory
        try:
            if os.path.exists(user_dir):
                shutil.rmtree(user_dir)
            
            embed = discord.Embed(
                title=f"{EMOJIS['trash']} Projects Deleted",
                description="All your projects have been permanently deleted!",
                color=0xFF0000
            )
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Error",
                description=f"Error deleting projects: `{str(e)}`",
                color=0xFF0000
            )
            await interaction.response.edit_message(embed=embed, view=None)
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your project!", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="✅ Deletion Cancelled",
            description="Your projects are safe!",
            color=0x00FF00
        )
        await interaction.response.edit_message(embed=embed, view=None)

class UploadMethodView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📤 Upload Here", style=discord.ButtonStyle.primary, custom_id="upload_here")
    async def upload_here(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title=f"{EMOJIS['upload']} Upload Your Bot Code",
            description="Please upload your bot code as a **`.zip` file** in this channel.\n\n"
                       "I'll be waiting for your `.zip` file...",
            color=0x5865F2
        )
        embed.set_footer(text="Only .zip files will be accepted")
        await interaction.response.send_message(embed=embed)
        user_projects[interaction.user.id] = "channel"
    
    @discord.ui.button(label="📩 Upload in DM", style=discord.ButtonStyle.secondary, custom_id="upload_dm")
    async def upload_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            embed = discord.Embed(
                title=f"{EMOJIS['upload']} Upload Your Bot Code",
                description="Please upload your bot code as a **`.zip` file** in our DM.\n\n"
                           "I'll be waiting for your `.zip` file in DMs...",
                color=0x5865F2
            )
            embed.set_footer(text="Only .zip files will be accepted")
            await interaction.user.send(embed=embed)
            await interaction.response.send_message(
                f"{EMOJIS['upload']} Check your DMs! I've sent you instructions there.",
                ephemeral=True
            )
            user_projects[interaction.user.id] = "dm"
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I cannot send you a DM! Please enable DMs from server members.",
                ephemeral=True
            )

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    
    user_id = message.author.id
    
    # Check if user is in upload process
    if user_id not in user_projects:
        await bot.process_commands(message)
        return
    
    upload_location = user_projects[user_id]
    
    # Check if message is in correct location
    if upload_location == "channel":
        if isinstance(message.channel, discord.DMChannel):
            return  # User chose channel but sent in DM
        if hasattr(message.channel, 'type') and message.channel.type != discord.ChannelType.text:
            return
    elif upload_location == "dm":
        if not isinstance(message.channel, discord.DMChannel):
            return  # User chose DM but sent in channel
    
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
    await process_zip_upload(message, zip_attachment, user_id)

async def process_zip_upload(message: discord.Message, attachment: discord.Attachment, user_id: int):
    """Process uploaded zip file"""
    try:
        # Create user directory
        user_dir = get_user_project_dir(user_id)
        
        # Clean previous uploads
        if os.path.exists(user_dir):
            shutil.rmtree(user_dir)
        os.makedirs(user_dir, exist_ok=True)
        
        # Download zip
        zip_data = await attachment.read()
        zip_path = os.path.join(user_dir, "uploaded.zip")
        with open(zip_path, 'wb') as f:
            f.write(zip_data)
        
        # Extract zip
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(user_dir)
        os.remove(zip_path)
        
        # Get all files
        all_files = []
        for root, dirs, files in os.walk(user_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), user_dir)
                all_files.append(rel_path)
        
        # Create file list embed with loading emojis
        file_list_text = "\n".join([f"{EMOJIS['loading']} `{f}`" for f in all_files[:30]])  # Limit to 30 files for display
        embed = discord.Embed(
            title=f"{EMOJIS['file']} Files Detected - Security Scan",
            description=f"Found `{len(all_files)}` file(s). Scanning for security...\n\n{file_list_text}",
            color=0xFFA500
        )
        if len(all_files) > 30:
            embed.set_footer(text=f"... and {len(all_files) - 30} more files")
        # Send to appropriate channel (DM or text channel)
        if isinstance(message.channel, discord.DMChannel):
            status_msg = await message.channel.send(embed=embed)
        else:
            status_msg = await message.channel.send(embed=embed)
        
        # Progress tracking
        file_status = {f: EMOJIS['loading'] for f in all_files}
        
        async def update_progress(batch_files, current_results):
            """Update embed with progress"""
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
            try:
                await status_msg.edit(embed=embed)
            except:
                pass
        
        # Scan files with progress updates
        scan_results = await security_checker.scan_files(user_dir, all_files, update_progress)
        
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
            shutil.rmtree(user_dir)
            del user_projects[user_id]
            
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Security Scan Failed",
                description=f"**Malicious code detected!**\n\n"
                           f"**Reason:** {malicious_statement}\n\n"
                           f"Your code has been deleted for security reasons.",
                color=0xFF0000
            )
            await status_msg.edit(embed=embed)
            return
        
        # All files are safe
        embed = discord.Embed(
            title=f"{EMOJIS['safe']} Security Scan Passed",
            description=f"All `{len(all_files)}` file(s) scanned and verified safe!\n\n" + "\n".join(updated_file_list[:20]),
            color=0x00FF00
        )
        if len(all_files) > 20:
            embed.set_footer(text=f"... and {len(all_files) - 20} more files")
        await status_msg.edit(embed=embed)
        
        # Check for requirements.txt
        requirements_path = None
        for req_file in ['requirements.txt', 'requirement.txt']:
            req_path = os.path.join(user_dir, req_file)
            if os.path.exists(req_path):
                requirements_path = req_path
                break
        
        if requirements_path:
            # Install requirements
            embed = discord.Embed(
                title=f"{EMOJIS['loading']} Installing Dependencies",
                description="Found `requirements.txt`. Installing packages...",
                color=0xFFA500
            )
            install_msg = await message.channel.send(embed=embed)
            
            try:
                result = subprocess.run(
                    ['pip', 'install', '-r', requirements_path],
                    cwd=user_dir,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode == 0:
                    embed = discord.Embed(
                        title=f"{EMOJIS['safe']} Dependencies Installed",
                        description="All packages from `requirements.txt` have been installed successfully!",
                        color=0x00FF00
                    )
                else:
                    embed = discord.Embed(
                        title=f"{EMOJIS['danger']} Installation Warning",
                        description=f"Some packages failed to install:\n```\n{result.stderr[:1000]}\n```",
                        color=0xFFA500
                    )
            except Exception as e:
                embed = discord.Embed(
                    title=f"{EMOJIS['danger']} Installation Error",
                    description=f"Error installing dependencies: `{str(e)}`",
                    color=0xFF0000
                )
            
            await install_msg.edit(embed=embed)
            # Continue to main file selector after requirements installation
            await show_main_file_selector(message.channel, user_id, user_dir, all_files)
        else:
            # Ask if they want to install packages
            embed = discord.Embed(
                title=f"{EMOJIS['file']} No Requirements File",
                description="No `requirements.txt` or `requirement.txt` detected.\n\n"
                           "Would you like to install any packages?",
                color=0xFFA500
            )
            view = InstallPackagesView(user_id, user_dir, message.channel)
            await message.channel.send(embed=embed, view=view)
            # Don't return - let the view handle continuation
        
    except Exception as e:
        embed = discord.Embed(
            title=f"{EMOJIS['danger']} Error",
            description=f"An error occurred: `{str(e)}`",
            color=0xFF0000
        )
        await message.channel.send(embed=embed)
        if user_id in user_projects:
            del user_projects[user_id]

class InstallPackagesView(discord.ui.View):
    def __init__(self, user_id: int, user_dir: str, channel):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.user_dir = user_dir
        self.channel = channel
    
    @discord.ui.button(label="✅ Yes", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your upload!", ephemeral=True)
            return
        
        modal = PackageInstallModal(self.user_dir, self.channel)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="❌ No", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your upload!", ephemeral=True)
            return
        
        # Get all files for main file selector
        all_files = []
        for root, dirs, files in os.walk(self.user_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.user_dir)
                all_files.append(rel_path)
        
        await show_main_file_selector(self.channel, self.user_id, self.user_dir, all_files)
        await interaction.response.defer()

class PackageInstallModal(discord.ui.Modal, title="📦 Install Packages"):
    def __init__(self, user_dir: str, channel):
        super().__init__()
        self.user_dir = user_dir
        self.channel = channel
    
    package_input = discord.ui.TextInput(
        label="Package Names",
        placeholder="discord.py\nrequests\nnumpy\n...",
        style=discord.TextStyle.paragraph,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        packages = [p.strip() for p in self.package_input.value.split('\n') if p.strip()]
        
        embed = discord.Embed(
            title=f"{EMOJIS['loading']} Installing Packages",
            description=f"Installing `{len(packages)}` package(s)...",
            color=0xFFA500
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
                embed = discord.Embed(
                    title=f"{EMOJIS['safe']} Packages Installed",
                    description=f"Successfully installed `{len(packages)}` package(s)!",
                    color=0x00FF00
                )
            else:
                embed = discord.Embed(
                    title=f"{EMOJIS['danger']} Installation Warning",
                    description=f"Some packages failed:\n```\n{result.stderr[:1000]}\n```",
                    color=0xFFA500
                )
        except Exception as e:
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Installation Error",
                description=f"Error: `{str(e)}`",
                color=0xFF0000
            )
        
        await msg.edit(embed=embed)
        
        # Get all files for main file selector
        all_files = []
        for root, dirs, files in os.walk(self.user_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.user_dir)
                all_files.append(rel_path)
        
        await show_main_file_selector(self.channel, interaction.user.id, self.user_dir, all_files)

async def show_main_file_selector(channel, user_id: int, user_dir: str, all_files: list):
    """Show dropdown to select main file"""
    # Filter Python files
    python_files = [f for f in all_files if f.endswith('.py')]
    
    if not python_files:
        embed = discord.Embed(
            title=f"{EMOJIS['danger']} No Python Files",
            description="No Python files found in your code!",
            color=0xFF0000
        )
        await channel.send(embed=embed)
        if user_id in user_projects:
            del user_projects[user_id]
        return
    
    embed = discord.Embed(
        title=f"{EMOJIS['file']} Select Main File",
        description="Choose the main file to run your bot:",
        color=0x5865F2
    )
    
    view = MainFileView(user_id, user_dir, python_files)
    await channel.send(embed=embed, view=view)
    # Clean up user_projects after showing file selector (user can start new upload if needed)
    if user_id in user_projects:
        del user_projects[user_id]

class MainFileView(discord.ui.View):
    def __init__(self, user_id: int, user_dir: str, files: list):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.user_dir = user_dir
        self.selected_file = None
        self.files = files
        self.add_item(MainFileSelect(files, self))
    
    @discord.ui.button(label=f"{EMOJIS['play']} Run Bot", style=discord.ButtonStyle.success, row=1)
    async def run_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your upload!", ephemeral=True)
            return
        
        # Get selected file from select menu
        if not self.selected_file:
            await interaction.response.send_message("❌ Please select a main file first!", ephemeral=True)
            return
        
        # Use absolute path to avoid duplication
        main_file = os.path.abspath(os.path.join(self.user_dir, self.selected_file))
        user_dir_abs = os.path.abspath(self.user_dir)
        
        # Verify the file exists and is within the user directory
        if not os.path.exists(main_file):
            await interaction.response.send_message("❌ Selected file not found!", ephemeral=True)
            return
        
        # Security check: ensure file is within user directory
        if not main_file.startswith(user_dir_abs):
            await interaction.response.send_message("❌ Invalid file path!", ephemeral=True)
            return
        
        # Stop existing bot if running
        if self.user_id in running_bots and running_bots[self.user_id].get('process'):
            old_process = running_bots[self.user_id]['process']
            try:
                if isinstance(old_process, asyncio.subprocess.Process):
                    old_process.terminate()
                    try:
                        await asyncio.wait_for(old_process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        old_process.kill()
                else:
                    old_process.terminate()
                    try:
                        old_process.wait(timeout=5)
                    except:
                        old_process.kill()
            except:
                try:
                    if isinstance(old_process, asyncio.subprocess.Process):
                        old_process.kill()
                    else:
                        old_process.kill()
                except:
                    pass
        
        # Start bot
        embed = discord.Embed(
            title=f"{EMOJIS['play']} Starting Bot",
            description=f"Starting bot with main file: `{self.selected_file}`",
            color=0x00FF00
        )
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        
        try:
            # Use asyncio subprocess for proper async support
            # Note: text mode is handled by decoding bytes manually
            process = await asyncio.create_subprocess_exec(
                'python3', main_file,
                cwd=user_dir_abs,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            running_bots[self.user_id] = {
                'process': process,
                'project_path': user_dir_abs,
                'console_output': [],
                'message': msg
            }
            
            # Start console output monitoring
            bot.loop.create_task(monitor_console_output(self.user_id, process))
            
            embed = discord.Embed(
                title=f"{EMOJIS['play']} Bot Running",
                description=f"Bot is now running!\n\nMain file: `{self.selected_file}`\n\nConsole output will appear below:",
                color=0x00FF00
            )
            view = BotControlView(self.user_id)
            await msg.edit(embed=embed, view=view)
            
        except Exception as e:
            embed = discord.Embed(
                title=f"{EMOJIS['danger']} Error Starting Bot",
                description=f"Error: `{str(e)}`",
                color=0xFF0000
            )
            await msg.edit(embed=embed)

class MainFileSelect(discord.ui.Select):
    def __init__(self, files: list, parent_view):
        options = [discord.SelectOption(label=f, value=f, description=f"Select {f} as main file") for f in files[:25]]
        super().__init__(placeholder="Choose main file...", options=options)
        self.files = files
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        # Store selected file in parent view
        self.parent_view.selected_file = self.values[0]
        
        embed = discord.Embed(
            title=f"{EMOJIS['file']} Main File Selected",
            description=f"Selected: `{self.values[0]}`\n\nClick 'Run Bot' to start!",
            color=0x5865F2
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class BotControlView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
    
    @discord.ui.button(label=f"{EMOJIS['stop']} Stop Bot", style=discord.ButtonStyle.danger)
    async def stop_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your bot!", ephemeral=True)
            return
        
        if self.user_id not in running_bots:
            await interaction.response.send_message("❌ No bot is running!", ephemeral=True)
            return
        
        process = running_bots[self.user_id].get('process')
        if process:
            try:
                if isinstance(process, asyncio.subprocess.Process):
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        process.kill()
                else:
                    # Legacy subprocess.Popen
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except:
                        process.kill()
            except:
                try:
                    if isinstance(process, asyncio.subprocess.Process):
                        process.kill()
                    else:
                        process.kill()
                except:
                    pass
        
        del running_bots[self.user_id]
        
        embed = discord.Embed(
            title=f"{EMOJIS['stop']} Bot Stopped",
            description="Your bot has been stopped.",
            color=0xFF0000
        )
        await interaction.response.edit_message(embed=embed, view=None)

async def monitor_console_output(user_id: int, process: asyncio.subprocess.Process):
    """Monitor and send console output to Discord (non-blocking async)"""
    if user_id not in running_bots:
        return
    
    output_lines = []
    max_lines = 50
    last_update = 0
    
    try:
        while True:
            if user_id not in running_bots:
                break
            
            # Check if process is still running
            if process.returncode is not None:
                # Process ended, read remaining output
                try:
                    if process.stdout:
                        remaining = await process.stdout.read()
                        if remaining:
                            # Decode bytes to string if needed
                            if isinstance(remaining, bytes):
                                remaining = remaining.decode('utf-8', errors='ignore')
                            for line in remaining.split('\n'):
                                if line.strip():
                                    output_lines.append(line.strip())
                                    if len(output_lines) > max_lines:
                                        output_lines.pop(0)
                except:
                    pass
                break
            
            # Read line with timeout (non-blocking)
            try:
                if process.stdout:
                    # Read with timeout to prevent blocking
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=0.5
                    )
                else:
                    await asyncio.sleep(0.5)
                    continue
            except asyncio.TimeoutError:
                # No data available, continue loop
                await asyncio.sleep(0.1)
                continue
            except Exception as e:
                # Process might have closed stdout
                if user_id in running_bots:
                    break
                await asyncio.sleep(0.5)
                continue
            
            if not line:
                # EOF or empty line
                if process.returncode is not None:
                    break
                await asyncio.sleep(0.5)
                continue
            
            # Decode bytes to string if needed
            if isinstance(line, bytes):
                line = line.decode('utf-8', errors='ignore')
            
            line = line.strip()
            if line:
                output_lines.append(line)
                if len(output_lines) > max_lines:
                    output_lines.pop(0)
                
                # Update message every 3 lines or every 3 seconds
                current_time = time.time()
                if len(output_lines) % 3 == 0 or (current_time - last_update) > 3:
                    output_text = "\n".join(output_lines[-20:])
                    if len(output_text) > 1900:
                        output_text = output_text[-1900:]
                    embed = discord.Embed(
                        title=f"{EMOJIS['play']} Console Output",
                        description=f"```\n{output_text}\n```",
                        color=0x5865F2
                    )
                    try:
                        await running_bots[user_id]['message'].edit(embed=embed)
                        last_update = current_time
                    except:
                        pass
            
    except Exception as e:
        print(f"Error monitoring console: {e}")
        import traceback
        traceback.print_exc()
    
    # Final output
    if user_id in running_bots:
        output_text = "\n".join(output_lines[-20:])
        if len(output_text) > 1900:
            output_text = output_text[-1900:]
        embed = discord.Embed(
            title=f"{EMOJIS['stop']} Bot Stopped",
            description=f"```\n{output_text}\n```",
            color=0xFF0000
        )
        try:
            await running_bots[user_id]['message'].edit(embed=embed)
        except:
            pass

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)


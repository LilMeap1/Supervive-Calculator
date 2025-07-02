import discord
import threading
from discord import app_commands
from discord.ext import commands
import os
import asyncio
from flask import Flask
import subprocess
from threading import Thread
import json
import psutil
import signal
from discord.ui import View, Button
from discord import Interaction
import sys
import time

from pymongo import MongoClient

mongo = MongoClient("mongodb://admin:ilovemeep548@localhost:27017/admin")
db = mongo['Inhouses']  
queue_collection = db['inhouse_queue']


QUEUE_DOC_ID = "supervive-inhouse"
TOKEN = "" # DISCORD BOT TOKEN REMOVED FOR REPO PURPOSES
GUILD_ID = ""  


IMAGE_PATH = "/tmp/spreadsheet_final.png" # OUTDATED !

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())


ALLOWED_ROLES = {"New Tech", "Admin", "Owner", "Helper guy"}


REALTIME_SCRIPT = "supervive_realtime.py"
BATCH_SCRIPT = "supervive_batch.py"
TEAMS_JSON = "teams.json"
PLAYER_FILE = "players.json"

INHOUSE_CHANNEL_ID = 1378716691462361249
QUEUE_MAX = 36
last_queue_count = 0
AUTO_KICK_SECONDS = 3600


SCRIMS_COMMANDS = {
    "/scrims_start_realtime <username>": "Starts real-time calculations. Use the username of who you know will play the entire scrim block",
    "/scrims_stop": "Stops the calculations.",
    "/scrims_pause": "Pauses real-time calculations without stopping the script.",
    "/scrims_resume": "Resumes a previously paused real-time calculation.",
    "/results": "Sends results (screenshot of spreadsheet).",
    "/scrims_calc_past <number> <username>": "Calculates past <number> custom games. Use the username of who you know will play the entire scrim block",
    "/team_add <TAG> <Captain> <Member2> <Member3> ":
        "Adds a team with specified members.",
    "/team_remove <TAG>": "Removes a team by its tag.",
    "/show_teams": "Lists all enabled teams with captains and members."
}


ALLOWED_CHANNEL_ID = 1352000171889786931  


def load_inhouse_queue():
    doc = queue_collection.find_one({"_id": QUEUE_DOC_ID})
    if doc and "queue" in doc:
        return doc["queue"]
    return []

def save_inhouse_queue(queue):
    queue_collection.update_one(
        {"_id": QUEUE_DOC_ID},
        {"$set": {"queue": queue}},
        upsert=True
    )

def get_user_ids(queue):
    return [u['user_id'] for u in queue]

def add_user_to_queue(user_id):
    queue = load_inhouse_queue()
    if any(u['user_id'] == user_id for u in queue):
        return
    queue.append({"user_id": user_id, "joined_at": int(time.time())})
    save_inhouse_queue(queue)

def remove_user_from_queue(user_id):
    queue = load_inhouse_queue()
    queue = [u for u in queue if u['user_id'] != user_id]
    save_inhouse_queue(queue)

async def ping_full_queue(bot, user_ids):
    channel = bot.get_channel(INHOUSE_CHANNEL_ID)
    if not channel or not user_ids:
        return
    mentions = " ".join(f"<@{uid}>" for uid in user_ids)
    await channel.send(f"Queue is full! {mentions}")

async def remove_expired_queue_entries(bot):
    queue = load_inhouse_queue()
    now = int(time.time())
    filtered = []
    kicked_users = []
    for u in queue:
        if now - u['joined_at'] < AUTO_KICK_SECONDS:
            filtered.append(u)
        else:
            kicked_users.append(u['user_id'])
    if len(filtered) != len(queue):
        save_inhouse_queue(filtered)
        if kicked_users:
            channel = bot.get_channel(INHOUSE_CHANNEL_ID)
            if channel:
                mentions = " ".join(f"<@{uid}>" for uid in kicked_users)
                msg = await channel.send(
                    f"These users were removed from the queue due to inactivity: {mentions}")

                async def delete_later(m):
                    await asyncio.sleep(900)
                    try:
                        await m.delete()
                    except Exception:
                        pass
                asyncio.create_task(delete_later(msg))
    return filtered



def load_players():
  """Load player data from players.json."""
  try:
      with open(PLAYER_FILE, "r", encoding="utf-8") as file:
          return json.load(file)
  except (FileNotFoundError, json.JSONDecodeError):
      print("⚠️ Warning: Could not load players.json. Using empty fallback.")
      return {}

players = load_players() 

def get_opgg_link(username):
  """Fetch the op.gg link for the given username."""
  return players.get(username, None)

def is_valid_channel(interaction: discord.Interaction) -> bool:
  """ Checks if the command is used in the correct channel """
  return interaction.channel_id == ALLOWED_CHANNEL_ID



def has_permission(interaction: discord.Interaction):
  if not isinstance(interaction.user,
                    discord.Member): 
    return False

  return any(role.name in ALLOWED_ROLES for role in interaction.user.roles)


def stop_script(script_name):
  for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
      cmdline = proc.info.get('cmdline', [])
      if isinstance(cmdline, list) and script_name in " ".join(cmdline):

        proc.kill()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
      continue
  return False

def pause_script(script_name):
    """ Pauses the running script using SIGSTOP """
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if isinstance(cmdline, list) and script_name in " ".join(cmdline):
                proc.suspend()  
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False

def resume_script(script_name):
    """ Resumes a paused script using SIGCONT """
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if isinstance(cmdline, list) and script_name in " ".join(cmdline):
                proc.resume() 
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False




@bot.tree.command(name="help_scrims", description="Shows all available scrims-related commands.")
async def help_scrims(interaction: discord.Interaction):
      if not is_valid_channel(interaction):
          await interaction.response.send_message(
              "⚠️ This bot only works in the designated scrims channel!", ephemeral=True)
          return

      if not has_permission(interaction):
          await interaction.response.send_message(
              "You don't have the required permissions to use this command", ephemeral=True)
          return

      embed = discord.Embed(
          title="📌 Scrims Commands Help",
          description="Here are all the available scrims-related commands:",
          color=discord.Color.blue()
      )

      for command, description in SCRIMS_COMMANDS.items():
          embed.add_field(name=command, value=description, inline=False)

      await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="show_teams", description="Shows all enabled teams and their members.")
async def show_teams(interaction: discord.Interaction):

    try:
        with open(TEAMS_JSON, "r", encoding="utf-8") as file:
            teams = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        await interaction.response.send_message("⚠️ Could not load team data.", ephemeral=True)
        return

    enabled_teams = teams 
    sorted_teams = sorted(enabled_teams.items())
    teams_per_page = 5
    total_pages = (len(sorted_teams) + teams_per_page - 1) // teams_per_page

    def create_embed(page: int):
        embed = discord.Embed(
            title=f"📋 Active Scrim Teams (Page {page + 1}/{total_pages})",
            description="Use the buttons below to navigate pages.",
            color=discord.Color.green()
        )
        start = page * teams_per_page
        end = start + teams_per_page
        for tag, info in sorted_teams[start:end]:
            captain = info.get("captain", "Unknown")
            players = list(info.get("players", {}).keys())
            members = [p for p in players if p != captain]
            member_str = ", ".join(members) if members else "No members"
            embed.add_field(
                name=f"🏷️ {tag}",
                value=f"👑 **Captain:** {captain}\n👥 **Members:** {member_str}",
                inline=False
            )
        return embed

    class TeamPaginator(View):
        def __init__(self):
            super().__init__(timeout=120)
            self.page = 0

        @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.gray)
        async def prev(self, interaction_btn: Interaction, button: Button):
            self.page = max(0, self.page - 1)
            await interaction_btn.response.edit_message(embed=create_embed(self.page), view=self)

        @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.gray)
        async def next(self, interaction_btn: Interaction, button: Button):
            self.page = min(total_pages - 1, self.page + 1)
            await interaction_btn.response.edit_message(embed=create_embed(self.page), view=self)

    await interaction.response.send_message(
        embed=create_embed(0),
        view=TeamPaginator(),
        ephemeral=True
    )



@bot.tree.command(name="scrims_start_realtime",
                    description="Starts real-time calculations for a specific player")
@app_commands.describe(username="The player's username (must be in players.json)")
async def scrims_start_realtime(interaction: discord.Interaction, username: str):
      if not has_permission(interaction):
          await interaction.response.send_message(
              "You don't have the required permissions to use this command",
              ephemeral=True)
          return
        
      if not is_valid_channel(interaction):
        await interaction.response.send_message(
            "⚠️ This bot only works in the designated scrims channel!", ephemeral=True)
        return
      

      opgg_link = get_opgg_link(username)
      if not opgg_link:
          await interaction.response.send_message(
              f"⚠️ Error: No op.gg link found for `{username}`. Check `players.json`.",
              ephemeral=True)
          return

      subprocess.Popen([sys.executable, REALTIME_SCRIPT, username])
      await interaction.response.send_message(
          f"✅ Real-time calculations started for `{username}`!", ephemeral=True)

@bot.tree.command(name="scrims_pause", description="Pauses the real-time calculations")
async def scrims_pause(interaction: discord.Interaction):
    if not has_permission(interaction):
        await interaction.response.send_message(
            "You don't have the required permissions to use this command", ephemeral=True)
        return

    if not is_valid_channel(interaction):
        await interaction.response.send_message(
            "⚠️ This bot only works in the designated scrims channel!", ephemeral=True)
        return

    if pause_script(REALTIME_SCRIPT):
        await interaction.response.send_message("⏸️ Real-time calculations paused.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ No running script to pause.", ephemeral=True)

@bot.tree.command(name="scrims_resume", description="Resumes the paused real-time calculations")
async def scrims_resume(interaction: discord.Interaction):
    if not has_permission(interaction):
        await interaction.response.send_message(
            "You don't have the required permissions to use this command", ephemeral=True)
        return

    if not is_valid_channel(interaction):
        await interaction.response.send_message(
            "⚠️ This bot only works in the designated scrims channel!", ephemeral=True)
        return

    if resume_script(REALTIME_SCRIPT):
        await interaction.response.send_message("▶️ Real-time calculations resumed.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ No paused script found.", ephemeral=True)


@bot.tree.command(name="scrims_stop", description="Stops the calculations")
async def scrims_stop(interaction: discord.Interaction):
  if not has_permission(interaction):
    await interaction.response.send_message(
        "You don't have the required permissions to use this command",
        ephemeral=True)
    return

  if not is_valid_channel(interaction):
    await interaction.response.send_message(
        "⚠️ This bot only works in the designated scrims channel!", ephemeral=True)
    return

  if stop_script(REALTIME_SCRIPT):
    await interaction.response.send_message("Real-time calculations stopped.", ephemeral=True)
  else:
    await interaction.response.send_message(
        "Real-time script was not running.", ephemeral=True)


@bot.tree.command(name="scrims_calc_past", description="Calculate past X custom games")
@app_commands.describe(number="Number of past scrims to calculate",
                         username="Username linked to op.gg")
async def scrims_calc_past(interaction: discord.Interaction, number: int, username: str):
    if not has_permission(interaction):
          await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
          return

    await interaction.response.defer(ephemeral=True)

    process = await asyncio.create_subprocess_exec(
        sys.executable, BATCH_SCRIPT, str(number), f'"{username}"',
    )

    stdout, stderr = await process.communicate()

    await interaction.followup.send(f"✅ Done calculating past {number} custom games for {username}.")


@bot.tree.command(name="team_add", description="Adds a team")
@app_commands.describe(
    tag="Team tag",
    captain="Captain name",
    member1="Member 1",
    member2="Member 2"
)
async def team_add(interaction: discord.Interaction, tag: str, captain: str,
                   member1: str, member2: str):
    if not has_permission(interaction):
        await interaction.response.send_message(
            "You don't have the required permissions to use this command",
            ephemeral=True)
        return

    try:
        with open(TEAMS_JSON, "r", encoding="utf-8") as file:
            teams = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        teams = {}

    teams[tag] = {
        "players": {
            captain: "",
            member1: "",
            member2: ""
        },
        "captain": captain
    }

    with open(TEAMS_JSON, "w", encoding="utf-8") as file:
        json.dump(teams, file, indent=4, ensure_ascii=False)

    await interaction.response.send_message(
        f"✅ Team `{tag}` added with members: {captain}, {member1}, {member2}.", ephemeral=True
    )


@bot.tree.command(name="team_remove", description="Removes a team by tag.")
@app_commands.describe(tag="The team tag to remove")
async def team_remove(interaction: discord.Interaction, tag: str):

        if not has_permission(interaction):
            await interaction.response.send_message(
                "You don't have the required permissions to use this command", ephemeral=True)
            return
    
        try:
          with open(TEAMS_JSON, "r") as file:
            teams = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
          await interaction.response.send_message("No teams found.", ephemeral=True)
          return
  
        if tag in teams:
            del teams[tag]
            with open(TEAMS_JSON, "w", encoding="utf-8") as file:
                json.dump(teams, file, indent=4)

            await interaction.response.send_message(f"✅ Team `{tag}` has been removed.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Team `{tag}` does not exist.", ephemeral=True)

    # !!! OUTDATED !!!
# @bot.tree.command(name="results", description="Get the latest scrim results")
# async def results(interaction: discord.Interaction):
#     await interaction.response.defer(
#     )  
#     if not has_permission(interaction):
#       await interaction.response.send_message(
#           "You don't have the required permissions to use this command",
#           ephemeral=True)
#       return

#     if not is_valid_channel(interaction):
#       await interaction.response.send_message(
#           "⚠️ This bot only works in the designated scrims channel!", ephemeral=True)
#       return


#     process = await asyncio.create_subprocess_exec(sys.executable,
#                                                    "screenshot_script.py")
#     await process.communicate()  


#     if os.path.exists(IMAGE_PATH):
#       file = discord.File(IMAGE_PATH)
#       await interaction.followup.send("**Latest Scrims Data:**", file=file)
#     else:
#       await interaction.followup.send(
#           "No scrim results found. Please try again later.", ephemeral=True)

@bot.tree.command(name="clear_commands", description="Clears all bot commands (Admin only).")
async def clear_commands(interaction: discord.Interaction):
      if not has_permission(interaction):
          await interaction.response.send_message(
              "You don't have the required permissions to use this command",
              ephemeral=True)
          return

      bot.tree.clear_commands(guild=discord.Object(id=GUILD_ID))
      await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
      await interaction.response.send_message("All bot commands have been cleared for this guild. Restart the bot to re-register them.", ephemeral=True)


inhouse_queue = load_inhouse_queue()
queue_message_id = None

class InhouseQueueView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Join Queue", style=discord.ButtonStyle.green, custom_id="inhouse-join")
    async def join(self, interaction: Interaction, button: Button):
        add_user_to_queue(interaction.user.id)
        await update_inhouse_queue_message(self.bot)
        await interaction.response.send_message("✅ You joined the inhouse queue!", ephemeral=True)

    @discord.ui.button(label="Leave Queue", style=discord.ButtonStyle.red, custom_id="inhouse-leave")
    async def leave(self, interaction: Interaction, button: Button):
        remove_user_from_queue(interaction.user.id)
        await update_inhouse_queue_message(self.bot)
        await interaction.response.send_message("❌ You left the inhouse queue.", ephemeral=True)

async def update_inhouse_queue_message(bot):
    global queue_message_id, last_queue_count

    queue = await remove_expired_queue_entries(bot)
    user_ids = get_user_ids(queue)
    channel = bot.get_channel(INHOUSE_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title="Supervive Inhouse Queue",
        description=f"Players in queue: **{len(user_ids)}/{QUEUE_MAX}**\n\nClick Join/Leave below!",
        color=discord.Color.purple(),
        timestamp=discord.utils.utcnow()
    )
    view = InhouseQueueView(bot)

    if len(user_ids) == QUEUE_MAX and last_queue_count < QUEUE_MAX:
        await ping_full_queue(bot, user_ids)
    last_queue_count = len(user_ids)

    try:
        if queue_message_id:
            msg = await channel.fetch_message(queue_message_id)
            await msg.edit(embed=embed, view=view)
        else:
            msg = await channel.send(embed=embed, view=view)
            queue_message_id = msg.id
            with open("inhouse_queue_msgid.txt", "w") as f:
                f.write(str(queue_message_id))
    except Exception:
        msg = await channel.send(embed=embed, view=view)
        queue_message_id = msg.id
        with open("inhouse_queue_msgid.txt", "w") as f:
            f.write(str(queue_message_id))

async def periodic_inhouse_queue_updates(bot):
    global queue_message_id
    channel = bot.get_channel(INHOUSE_CHANNEL_ID)
    refresh_seconds = 14*60 
    last_refresh = time.time()
    while True:
        await update_inhouse_queue_message(bot)
        await asyncio.sleep(30)
        if time.time() - last_refresh > refresh_seconds:
            if queue_message_id:
                try:
                    msg = await channel.fetch_message(queue_message_id)
                    await msg.delete()
                except Exception:
                    pass
            queue_message_id = None
            last_refresh = time.time()

async def start_inhouse_queue(bot):
    global queue_message_id
    try:
        with open("inhouse_queue_msgid.txt", "r") as f:
            queue_message_id = int(f.read().strip())
    except Exception:
        queue_message_id = None
    bot.loop.create_task(periodic_inhouse_queue_updates(bot))

@bot.event
async def on_ready():
  print(f'✅ Logged in as {bot.user}')
  try:
    synced = await bot.tree.sync()
    print(f"✅ Synced {len(synced)} commands successfully!")
  except Exception as e:
    print(f"⚠️ Failed to sync commands: {e}")
  await start_inhouse_queue(bot)

bot.run(TOKEN)

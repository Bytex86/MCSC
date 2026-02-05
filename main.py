import discord
from discord.ext import commands, tasks
from datetime import datetime
import json
from pathlib import Path
from mcstatus import JavaServer
import time

TOKEN = "TOKEN"
ADMIN_ROLE_ID = 1234
STARTER_ROLE_ID = 5678
REQUEST_CHANNEL_ID = 9101112
LOG_CHANNEL_ID = 13141516
MC_HOST = "xyz.aternos.me"
MC_PORT = 1234
MC_VERSION = "1.67.1"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="m", intents=intents)
bot.remove_command("help")

REQUESTS_FILE = Path("requests.json")

def load_data():
    if REQUESTS_FILE.exists():
        try:
            with open(REQUESTS_FILE, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except:
            return {}
    return {}

def save_data(data):
    with open(REQUESTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

pending_requests = {}

def has_admin(member):
    return any(r.id == ADMIN_ROLE_ID for r in member.roles)

def has_starter(member):
    return any(r.id == STARTER_ROLE_ID for r in member.roles)

def check_server_status():
    checks = []
    
    for attempt in range(3):
        try:
            server = JavaServer.lookup(f"{MC_HOST}:{MC_PORT}")
            status = server.status()
            
            players_online = status.players.online if hasattr(status, 'players') else 0
            players_max = status.players.max if hasattr(status, 'players') else 0
            latency = status.latency
            
            if players_online == 0 and latency > 1000:
                state = "starting"
            elif latency > 0:
                state = "online"
            else:
                state = "offline"
            
            checks.append({
                'state': state,
                'players_online': players_online,
                'players_max': players_max,
                'latency': latency,
            })
            
        except:
            checks.append({'state': 'offline'})
        
        if attempt < 2:
            time.sleep(0.4)
    
    offline_count = sum(1 for c in checks if c['state'] == 'offline')
    starting_count = sum(1 for c in checks if c['state'] == 'starting')
    online_count = sum(1 for c in checks if c['state'] == 'online')
    
    if online_count >= 2:
        final_state = 'online'
    elif starting_count >= 2:
        final_state = 'starting'
    else:
        final_state = 'offline'
    
    valid_checks = [c for c in checks if c['state'] == final_state]
    
    if valid_checks:
        last_valid = valid_checks[-1]
        return {
            'state': final_state,
            'players_online': last_valid.get('players_online', 0),
            'players_max': last_valid.get('players_max', 0),
            'latency': last_valid.get('latency', 0),
        }
    else:
        return {'state': 'offline', 'players_online': 0, 'players_max': 0, 'latency': 0}

activities = [
    discord.Activity(type=discord.ActivityType.watching, name="Watching over the AISC server"),
    discord.Activity(type=discord.ActivityType.playing, name="Playing on AISC Minecraft Server")
]
current_activity = 0

@tasks.loop(seconds=10)
async def rotate_activity():
    global current_activity
    await bot.change_presence(activity=activities[current_activity])
    current_activity = (current_activity + 1) % len(activities)

@bot.event
async def on_ready():
    global pending_requests
    print(f'> Logged in as {bot.user}')
    pending_requests = load_data()
    rotate_activity.start()

@bot.command(name="status")
async def status(ctx):
    checking_msg = await ctx.send("🔍 Checking server status...")
    
    result = check_server_status()
    
    if result['state'] == 'online':
        msg = (
            f"🟢 **Server Online**\n\n"
            f"**Players:** {result['players_online']}/{result['players_max']}\n"
            f"**Latency:** {result['latency']:.1f} ms\n"
            f"**IP:** {MC_HOST}:{MC_PORT}\n"
            f"**Version:** {MC_VERSION}\n"
        )
    elif result['state'] == 'starting':
        msg = (
            f"🟡 **Server Starting**\n\n"
            f"The server is currently booting up or in queue.\n"
            f"**IP:** {MC_HOST}:{MC_PORT}\n"
            f"**Version:** {MC_VERSION}\n"
        )
    else:
        msg = (
            f"🔴 **Server Offline**\n\n"
            f"The server is currently offline.\n"
            f"**IP:** {MC_HOST}:{MC_PORT}\n"
            f"**Version:** {MC_VERSION}\n\n"
            f"Need access? Use `mrequest <AternosUsername>`\n"
            f"Start server at: https://aternos.org/servers/"
        )
    
    await checking_msg.delete()
    await ctx.send(msg)

@bot.command(name="request")
async def request(ctx, aternos_username: str = None):
    if not aternos_username:
        await ctx.send("❓ Usage: `mrequest <AternosUsername>`")
        return
    
    if has_starter(ctx.author):
        await ctx.send("❓ You already have server access.")
        return
    
    if str(ctx.author.id) in pending_requests:
        await ctx.send("❓ You already have a pending request.")
        return
    
    pending_requests[str(ctx.author.id)] = {
        "aternos_username": aternos_username,
        "discord_name": ctx.author.name,
        "timestamp": datetime.now().isoformat()
    }
    save_data(pending_requests)
    
    await ctx.send(
        f"✅ **Access Request Submitted**\n\n"
        f"**Aternos Username:** {aternos_username}\n\n"
        f"An admin will review your request soon."
    )
    
    request_channel = bot.get_channel(REQUEST_CHANNEL_ID)
    if request_channel:
        await request_channel.send(
            f"🟡 **New Access Request**\n\n"
            f"**User:** {ctx.author.mention}\n"
            f"**Aternos Username:** {aternos_username}\n\n"
            f"Use `maccept @{ctx.author.name}` or `mreject @{ctx.author.name}`"
        )

@bot.command(name="accept")
async def accept(ctx, member: discord.Member = None):
    if not has_admin(ctx.author):
        await ctx.send("❓ You don't have permission to use this command.")
        return
    
    if not member:
        await ctx.send("❓ Usage: `maccept @user`")
        return
    
    if str(member.id) not in pending_requests:
        await ctx.send("❓ No pending request from this user.")
        return
    
    request_data = pending_requests.pop(str(member.id))
    save_data(pending_requests)
    
    aternos_username = request_data["aternos_username"] if isinstance(request_data, dict) else request_data
    
    role = ctx.guild.get_role(STARTER_ROLE_ID)
    
    try:
        await member.add_roles(role, reason=f"Approved by {ctx.author.name}")
    except Exception as e:
        await ctx.send(f"❓ Role assignment failed: {e}")
        return
    
    try:
        await member.send(
            f"✅ **Access Approved**\n\n"
            f"Your Minecraft server access has been approved!\n\n"
            f"**Aternos Username:** {aternos_username}\n"
            f"**Server IP:** {MC_HOST}:{MC_PORT}\n"
            f"**Version:** {MC_VERSION}\n\n"
            f"Start/stop server at: https://aternos.org/servers/"
        )
    except:
        pass
    
    await ctx.send(f"✅ Approved {member.mention}.")
    
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"✅ **Request Accepted**\n\n"
            f"**User:** {member.mention}\n"
            f"**Aternos Username:** {aternos_username}\n"
            f"**Approved by:** {ctx.author.mention}"
        )

@bot.command(name="reject")
async def reject(ctx, member: discord.Member = None):
    if not has_admin(ctx.author):
        await ctx.send("❓ You don't have permission to use this command.")
        return
    
    if not member:
        await ctx.send("❓ Usage: `mreject @user`")
        return
    
    if str(member.id) not in pending_requests:
        await ctx.send("❓ No pending request from this user.")
        return
    
    request_data = pending_requests.pop(str(member.id))
    save_data(pending_requests)
    
    aternos_username = request_data["aternos_username"] if isinstance(request_data, dict) else request_data
    
    try:
        await member.send(
            f"❌ **Access Rejected**\n\n"
            f"Your Minecraft server access request has been rejected.\n\n"
            f"If you believe this is a mistake, please contact an admin."
        )
    except:
        pass
    
    await ctx.send(f"❌ Rejected request from {member.mention}.")
    
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"❌ **Request Rejected**\n\n"
            f"**User:** {member.mention}\n"
            f"**Aternos Username:** {aternos_username}\n"
            f"**Rejected by:** {ctx.author.mention}"
        )

@bot.command(name="revoke")
async def revoke(ctx, member: discord.Member = None):
    if not has_admin(ctx.author):
        await ctx.send("❓ You don't have permission to use this command.")
        return
    
    if not member:
        await ctx.send("❓ Usage: `mrevoke @user`")
        return
    
    role = ctx.guild.get_role(STARTER_ROLE_ID)
    
    try:
        await member.remove_roles(role, reason=f"Revoked by {ctx.author.name}")
    except Exception as e:
        await ctx.send(f"❓ Role removal failed: {e}")
        return
    
    pending_requests.pop(str(member.id), None)
    save_data(pending_requests)
    
    try:
        await member.send(
            f"⚠️ **Access Revoked**\n\n"
            f"Your Minecraft server access has been revoked.\n\n"
            f"If you believe this is a mistake, please contact an admin."
        )
    except:
        pass
    
    await ctx.send(f"❌ Revoked access from {member.mention}.")
    
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"⚠️ **Access Revoked**\n\n"
            f"**User:** {member.mention}\n"
            f"**Revoked by:** {ctx.author.mention}"
        )

if __name__ == "__main__":
    bot.run(TOKEN)

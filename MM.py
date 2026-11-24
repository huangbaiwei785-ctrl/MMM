import discord
from discord import app_commands
from discord.ext import commands
import re
import datetime
import time
from collections import defaultdict
import unicodedata
import asyncio
import json
import os

# 啟動必要權限
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==================== 動態設定區 ====================
class SecurityConfig:
    def __init__(self):
        self.log_channel_id = 123456789012345678  # 請改為您的 Log 頻道 ID
        self.whitelist_channels = []             # 豁免頻道 ID
        self.blacklisted_words = set()           # 自訂敏感詞黑名單

        # 1. 大量刪除頻道防護 (Anti-Nuke) 參數
        self.mass_delete_threshold = 3   # 幾秒內刪除幾頻道觸發 BAN 停權
        self.mass_delete_window = 10     # 時間計算範圍 (秒)

        # 2. 警告與懲罰門檻設定
        self.timeout_warn_count = 2     # 滿 2 次警告：執行 Timeout 禁言
        self.kick_warn_count = 3        # 滿 3 次警告：自動踢出伺服器 (Kick)

        # 3. 頻率與限制自訂參數
        self.link_spam_count = 3        # 連結頻率：次數
        self.link_spam_interval = 10    # 連結頻率：時間 (秒)
        self.msg_spam_count = 5         # 訊息頻率：條數
        self.msg_spam_interval = 5      # 訊息頻率：時間 (秒)
        self.max_duplicate_text = 3     # 重複內容：連續次數
        
        self.raid_join_threshold = 5    # Raid 突襲：進群人數
        self.raid_time_window = 10      # Raid 突襲：時間 (秒)
        self.account_age_days = 3       # 可疑新帳號：天數門檻

config = SecurityConfig()

# 狀態追蹤資料結構
user_warnings = defaultdict(int)
user_link_history = defaultdict(list)
user_msg_history = defaultdict(list)
user_last_text = {}
user_duplicate_count = defaultdict(int)
channel_delete_history = defaultdict(list)
join_history = []

def clean_text(text: str) -> str:
    text = re.sub(r'[\u200b-\u200d\ufeff]', '', text)
    return unicodedata.normalize('NFKC', text).lower()

def create_help_embed(guild_name: str) -> discord.Embed:
    """生成管理員專用控制台說明 Embed"""
    embed = discord.Embed(
        title=f"🛡️ {guild_name} - 管理員專用防衛系統控制台",
        description="本頻道與系統所有指令**僅限【管理員】權限人員操作**：",
        color=discord.Color.gold(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

    embed.add_field(
        name="🚨 Anti-Nuke 大量刪除頻道停權機制",
        value=(
            f"• **即時偵測**：當任何帳號於 **{config.mass_delete_window} 秒內刪除 {config.mass_delete_threshold} 個頻道**，即刻觸發防禦\n"
            "• **自動 BAN 停權**：系統調用 Audit Log 抓出操作者並**立即執行 BAN 封鎖停權**"
        ),
        inline=False
    )

    embed.add_field(
        name="📦 伺服器備份與還原 (Prefix Command)",
        value=(
            "`!backup` - 備份架構至本地與 Log 頻道\n"
            "`!restore` - 輸入指令並**直接隨附夾帶 `.json` 備份檔**即可重建架構"
        ),
        inline=False
    )

    embed.add_field(
        name="🔍 系統診斷 (Slash Command)",
        value=(
            "`/check_permissions` - 檢測機器人在伺服器的關鍵權限與缺失報告"
        ),
        inline=False
    )

    embed.add_field(
        name="🔨 三大處置與管理指令 (Prefix Command)",
        value=(
            "`!ban <@成員> [原因]` - 永久封鎖成員 (BAN)\n"
            "`!unban <使用者ID> [原因]` - 透過 ID 解除成員封鎖 (UNBAN)\n"
            "`!kick <@成員> [原因]` - 將成員剔除伺服器 (KICK)\n"
            "`!shutout <@成員> [分鐘] [原因]` - 暫時禁言（預設 60 分鐘，別名 `!shotout`/`!mute`/`!timeout`）\n"
            "`!unshutout <@成員>` - 解開成員 Timeout 狀態（別名 `!unmute`/`!untimeout`）\n"
            "`!purge <數量>` - 快速刪除頻道內 N 條訊息（別名 `!clear`）"
        ),
        inline=False
    )

    embed.add_field(
        name="⚠️ 警告記牌與自訂禁詞 (Slash Command)",
        value=(
            "`/warn <@成員> [原因]` - 手動對成員劃記警告\n"
            "`/warnings <@成員>` - 查詢成員累積警告次數\n"
            "`/clearwarn <@成員>` - 清除成員所有警告紀錄\n"
            "`/add_blackword <詞彙>` - 新增自訂敏感詞黑名單\n"
            "`/remove_blackword <詞彙>` - 移除自訂敏感詞黑名單"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ 防護門檻與動態調校 (Slash Command)",
        value=(
            "`/config_log_channel <#頻道>` - **指定防衛與警告日誌 (Log) 頻道**\n"
            "`/config_mass_delete` - 設定大量刪除頻道之時間與數量門檻 (Anti-Nuke)\n"
            "`/config_warn_threshold` - 設定警告滿幾次執行 Timeout / Kick\n"
            "`/config_link_spam` - 設定連結洗版頻率\n"
            "`/config_msg_spam` - 設定訊息刷屏頻率\n"
            "`/view_config` - 查看當前所有運作參數"
        ),
        inline=False
    )

    embed.set_footer(text="提示：一般成員輸入任何指令皆會自動拒絕存取。")
    return embed

async def issue_warning(member: discord.Member, reason: str, channel: discord.TextChannel = None, auto: bool = True):
    user_id = member.id
    user_warnings[user_id] += 1
    current_warns = user_warnings[user_id]
    
    action_text = ""
    punishment_type = "warning"

    if current_warns >= config.kick_warn_count:
        punishment_type = "kick"
        action_text = f"警告達 {current_warns} 次，已執行【踢出伺服器 (Kick)】"
    elif current_warns >= config.timeout_warn_count:
        punishment_type = "timeout"
        action_text = f"警告達 {current_warns} 次，已執行【禁言 (Shut Out) 1 小時】"
    else:
        action_text = f"累積第 {current_warns} 次警告（刪除訊息警告）"

    try:
        await member.send(
            f"⚠️ 您在 **{member.guild.name}** 收到一次警告！\n"
            f"**原因**：{reason}\n"
            f"**當前總警告次數**：{current_warns} 次\n"
            f"**處置結果**：{action_text}"
        )
    except Exception:
        pass

    try:
        if punishment_type == "kick":
            await member.kick(reason=f"[防衛系統] 警告滿 {current_warns} 次: {reason}")
        elif punishment_type == "timeout":
            duration = datetime.timedelta(hours=1)
            await member.timeout(duration, reason=f"[防衛系統] 警告滿 {current_warns} 次: {reason}")
    except discord.Forbidden:
        print(f"❌ 權限不足：無法處置成員 {member}")
    except Exception as e:
        print(f"❌ 懲罰執行失敗: {e}")

    log_channel = member.guild.get_channel(config.log_channel_id)
    if log_channel:
        embed = discord.Embed(
            title="🛡️ 警告系統自動處置報告" if auto else "✋ 管理員手動警告通知",
            color=discord.Color.red() if punishment_type == "kick" else discord.Color.orange(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="目標對象", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="警告累積", value=f"**{current_warns}** 次", inline=True)
        embed.add_field(name="處置動作", value=action_text, inline=False)
        embed.add_field(name="原因", value=f"**{reason}**", inline=False)
        if channel:
            embed.add_field(name="發送頻道", value=channel.mention, inline=True)
        await log_channel.send(embed=embed)

# ==================== 事件監聽區 ====================

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ 已成功同步 {len(synced)} 個斜線指令")
    except Exception as e:
        print(f"❌ 斜線指令同步失敗: {e}")
    print(f"🛡️ 防衛與備份機器人已上線：{bot.user}")

@bot.event
async def on_guild_join(guild):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True)
    }

    try:
        admin_channel = await guild.create_text_channel(
            name="🛡️-防衛系統控制台",
            overwrites=overwrites,
            position=0,
            reason="機器人加入伺服器：自動建立管理員專用控制台頻道"
        )
        embed = create_help_embed(guild.name)
        await admin_channel.send(embed=embed)
        print(f"✅ 已在伺服器 [{guild.name}] 頂層建立控制台頻道")
    except Exception as e:
        print(f"❌ 建立控制台頻道失敗: {e}")

# ---------------- Anti-Nuke: 大量刪除頻道監控 (觸發立即 BAN 停權) ----------------
@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    now = time.time()

    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            deleter = entry.user

            if deleter.bot and deleter.id == bot.user.id:
                return

            if deleter.id == guild.owner_id:
                return

            user_id = deleter.id
            channel_delete_history[user_id] = [t for t in channel_delete_history[user_id] if now - t < config.mass_delete_window]
            channel_delete_history[user_id].append(now)

            if len(channel_delete_history[user_id]) >= config.mass_delete_threshold:
                channel_delete_history[user_id].clear()

                ban_success = False
                try:
                    await guild.ban(deleter, reason=f"[Anti-Nuke 防護] {config.mass_delete_window} 秒內刪除超過 {config.mass_delete_threshold} 個頻道（系統自動 BAN 停權）")
                    ban_success = True
                    print(f"🚨 [Anti-Nuke 觸發] 已對惡意刪除頻道者 {deleter} (`{deleter.id}`) 執行 BAN 停權！")
                except Exception as e:
                    print(f"❌ 嘗試 BAN 停權失敗: {e}")

                log_channel = guild.get_channel(config.log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        title="🚨 核心警報：偵測到大量刪除頻道 (已執行 BAN 停權)",
                        description=f"帳號 {deleter.mention} (`{deleter.id}`) 在 **{config.mass_delete_window} 秒內連續刪除了 {config.mass_delete_threshold} 個頻道**！",
                        color=discord.Color.dark_red(),
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    embed.add_field(name="最近一次刪除的頻道", value=f"`#{channel.name}` (`{channel.id}`)", inline=False)
                    embed.add_field(
                        name="自動處置結果", 
                        value="✅ **已成功執行永久 BAN 封鎖停權** 並清出伺服器。" if ban_success else "❌ **停權失敗**（機器人身分組階層過低或缺乏 BAN 權限）。", 
                        inline=False
                    )
                    embed.add_field(name="復原建議", value="請管理員下載日誌頻道中的備份檔，並輸入 `!restore` 指令隨附夾帶 JSON 檔進行架構還原。", inline=False)
                    await log_channel.send(embed=embed)

    except Exception as e:
        print(f"❌ 讀取頻道刪除審核日誌失敗: {e}")

# 全域 Prefix 指令權限錯誤捕捉器
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ **權限拒絕**：只有【管理員 (Administrator)】才能使用此指令！")

# 全域 Slash 指令權限錯誤捕捉器
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ **權限拒絕**：只有【管理員 (Administrator)】才能使用此斜線指令！", ephemeral=True)

# ==================== 管理員專用 Prefix 指令區 ====================

@bot.command(name="backup")
@commands.has_permissions(administrator=True)
async def backup_server(ctx):
    guild = ctx.guild
    await ctx.send("📦 開始備份伺服器架構 (身分組、頻道類別、文字與語音頻道)...")

    try:
        backup_data = {
            "guild_name": guild.name,
            "backup_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "roles": [],
            "categories": [],
            "uncategorized_channels": []
        }

        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            backup_data["roles"].append({
                "name": role.name,
                "permissions": role.permissions.value,
                "color": role.color.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable
            })

        for category in guild.categories:
            cat_info = {
                "name": category.name,
                "channels": []
            }
            for ch in category.channels:
                if isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                    cat_info["channels"].append({
                        "name": ch.name,
                        "type": "text" if isinstance(ch, discord.TextChannel) else "voice",
                        "topic": getattr(ch, 'topic', None)
                    })
            backup_data["categories"].append(cat_info)

        for ch in guild.channels:
            if ch.category is None and isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                backup_data["uncategorized_channels"].append({
                    "name": ch.name,
                    "type": "text" if isinstance(ch, discord.TextChannel) else "voice",
                    "topic": getattr(ch, 'topic', None)
                })

        filename = f"server_backup_{guild.id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=4)

        await ctx.send(f"✅ **本地備份完成！** 檔案已儲存為 `{filename}`。")

        log_channel = guild.get_channel(config.log_channel_id)
        if log_channel:
            try:
                file_to_send = discord.File(filename)
                await log_channel.send(
                    content=f"📦 **[伺服器架構自動備份]** 備份時間：`{backup_data['backup_time']}`",
                    file=file_to_send
                )
                await ctx.send(f"📤 備份 JSON 檔案已自動傳送至日誌頻道：{log_channel.mention}")
            except Exception as log_err:
                await ctx.send(f"⚠️ 傳送備份至日誌頻道失敗（權限不足或檔案上傳錯誤）: `{log_err}`")
        else:
            await ctx.send(f"⚠️ 找不到 Log 頻道（目前設定 ID: `{config.log_channel_id}`），請使用 `/config_log_channel` 重新設定。")

    except Exception as e:
        await ctx.send(f"❌ **備份執行失敗，錯誤原因**：`{e}`")
        print(f"❌ [Backup Error] {e}")

@bot.command(name="restore")
@commands.has_permissions(administrator=True)
async def restore_server(ctx):
    guild = ctx.guild
    backup_data = None

    if ctx.message.attachments:
        attachment = ctx.message.attachments[0]
        if attachment.filename.endswith('.json'):
            try:
                file_bytes = await attachment.read()
                backup_data = json.loads(file_bytes.decode('utf-8'))
                await ctx.send(f"📄 **已讀取手動上傳之備份檔案：** `{attachment.filename}`")
            except Exception as e:
                await ctx.send(f"❌ 上傳之 JSON 檔案解析失敗: {e}")
                return
        else:
            await ctx.send("❌ 上傳檔案格式不符，請上載有效的 `.json` 備份檔！")
            return
    else:
        filename = f"server_backup_{guild.id}.json"
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                backup_data = json.load(f)
            await ctx.send(f"📄 **未偵測到附件，讀取本地預設備份檔：** `{filename}`")
        else:
            await ctx.send("❌ 找不到本地備份檔！請在輸入 `!restore` 時**直接上傳夾帶 `.json` 備份檔**。")
            return

    await ctx.send("🔄 **開始讀取備份並重建伺服器架構...**")

    existing_roles = [r.name for r in guild.roles]
    roles_created = 0
    for r_data in backup_data.get("roles", []):
        if r_data["name"] not in existing_roles:
            try:
                await guild.create_role(
                    name=r_data["name"],
                    permissions=discord.Permissions(r_data["permissions"]),
                    color=discord.Color(r_data["color"]),
                    hoist=r_data["hoist"],
                    mentionable=r_data["mentionable"]
                )
                roles_created += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"還原身分組失敗 [{r_data['name']}]: {e}")

    channels_created = 0
    for cat_data in backup_data.get("categories", []):
        cat = discord.utils.get(guild.categories, name=cat_data["name"])
        if not cat:
            try:
                cat = await guild.create_category(cat_data["name"])
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"還原類別失敗 [{cat_data['name']}]: {e}")
                continue

        for ch_data in cat_data.get("channels", []):
            ch_exists = any(ch.name == ch_data["name"] for ch in cat.channels)
            if not ch_exists:
                try:
                    if ch_data["type"] == "text":
                        await cat.create_text_channel(name=ch_data["name"], topic=ch_data.get("topic"))
                    elif ch_data["type"] == "voice":
                        await cat.create_voice_channel(name=ch_data["name"])
                    channels_created += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    print(f"還原頻道失敗 [{ch_data['name']}]: {e}")

    for ch_data in backup_data.get("uncategorized_channels", []):
        ch_exists = any(ch.name == ch_data["name"] and ch.category is None for ch in guild.channels)
        if not ch_exists:
            try:
                if ch_data["type"] == "text":
                    await guild.create_text_channel(name=ch_data["name"], topic=ch_data.get("topic"))
                elif ch_data["type"] == "voice":
                    await guild.create_voice_channel(name=ch_data["name"])
                channels_created += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"還原無類別頻道失敗 [{ch_data['name']}]: {e}")

    await ctx.send(f"✅ **還原完成！** 共補全 **{roles_created}** 個身分組、**{channels_created}** 個頻道。")

@bot.command(name="ban")
@commands.has_permissions(administrator=True)
async def ban_member(ctx, member: discord.Member, *, reason: str = "違反伺服器規章"):
    try:
        await member.ban(reason=f"[管理員 {ctx.author} 封禁] {reason}")
        await ctx.send(f"🔨 已成功封禁成員：{member.mention} | 原因：{reason}")
    except Exception as e:
        await ctx.send(f"❌ 執行 Ban 失敗: {e}")

@bot.command(name="unban")
@commands.has_permissions(administrator=True)
async def unban_user(ctx, user_id: int, *, reason: str = "管理員手動解除封禁"):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=f"[管理員 {ctx.author} 解封] {reason}")
        await ctx.send(f"🔓 已成功解除成員封禁：**{user}** (`{user_id}`)")
    except Exception as e:
        await ctx.send(f"❌ 解除 Ban 失敗: {e}")

@bot.command(name="kick")
@commands.has_permissions(administrator=True)
async def kick_member(ctx, member: discord.Member, *, reason: str = "違反伺服器規章"):
    try:
        await member.kick(reason=f"[管理員 {ctx.author} 踢出] {reason}")
        await ctx.send(f"👞 已成功踢出成員：{member.mention} | 原因：{reason}")
    except Exception as e:
        await ctx.send(f"❌ 執行 Kick 失敗: {e}")

@bot.command(name="shutout", aliases=["shotout", "mute", "timeout"])
@commands.has_permissions(administrator=True)
async def shut_out(ctx, member: discord.Member, minutes: int = 60, *, reason: str = "違反伺服器規章"):
    try:
        duration = datetime.timedelta(minutes=minutes)
        await member.timeout(duration, reason=f"[管理員 {ctx.author} 禁言] {reason}")
        await ctx.send(f"🤐 已成功對 {member.mention} 禁言 **{minutes}** 分鐘 | 原因：{reason}")
    except Exception as e:
        await ctx.send(f"❌ 執行禁言失敗: {e}")

@bot.command(name="unshutout", aliases=["unmute", "untimeout"])
@commands.has_permissions(administrator=True)
async def unshut_out(ctx, member: discord.Member):
    try:
        await member.timeout(None, reason=f"[管理員 {ctx.author} 解除禁言]")
        await ctx.send(f"🔊 已成功解除 {member.mention} 的禁言狀態！")
    except Exception as e:
        await ctx.send(f"❌ 解除禁言失敗: {e}")

@bot.command(name="purge", aliases=["clear"])
@commands.has_permissions(administrator=True)
async def purge_messages(ctx, amount: int = 10):
    if amount <= 0:
        await ctx.send("❌ 請輸入大於 0 的數字！")
        return
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(f"🧹 已成功批量刪除 **{len(deleted)-1}** 條訊息！")
        await asyncio.sleep(3)
        await msg.delete()
    except Exception as e:
        await ctx.send(f"❌ 批量刪除失敗: {e}")

# ==================== 管理員專用 Slash Commands 區 ====================

@bot.tree.command(name="help", description="顯示防衛系統的所有功能說明與指令")
@app_commands.checks.has_permissions(administrator=True)
async def help_command(interaction: discord.Interaction):
    embed = create_help_embed(interaction.guild.name)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="check_permissions", description="Check bot permission diagnostic status in current server")
@app_commands.checks.has_permissions(administrator=True)
async def check_permissions(interaction: discord.Interaction):
    guild = interaction.guild
    bot_member = guild.me
    guild_perms = bot_member.guild_permissions
    channel_perms = interaction.channel.permissions_for(bot_member)

    required_permissions = {
        "Administrator": guild_perms.administrator,
        "View Audit Log": guild_perms.view_audit_log,
        "Manage Messages": channel_perms.manage_messages,
        "Moderate Members": guild_perms.moderate_members,
        "Kick Members": guild_perms.kick_members,
        "Ban Members": guild_perms.ban_members,
        "Manage Channels": guild_perms.manage_channels,
        "Manage Roles": guild_perms.manage_roles,
        "Embed Links": channel_perms.embed_links,
    }

    embed = discord.Embed(
        title=f"🛡️ {guild.name} - Bot Permission Diagnostic Report",
        color=discord.Color.green() if all(required_permissions.values()) or guild_perms.administrator else discord.Color.orange(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

    perm_status_str = ""
    missing_count = 0
    for perm_name, has_perm in required_permissions.items():
        status_icon = "✅" if (has_perm or guild_perms.administrator) else "❌"
        perm_status_str += f"{status_icon} **{perm_name}**\n"
        if not has_perm and not guild_perms.administrator:
            missing_count += 1

    embed.add_field(name="Core Permission Status", value=perm_status_str, inline=False)

    if missing_count == 0 or guild_perms.administrator:
        embed.add_field(name="Diagnostic Result", value="✅ **Full Permissions Granted!** The bot is ready to perform all security, anti-nuke, moderation, and backup features.", inline=False)
    else:
        embed.add_field(name="Diagnostic Result", value=f"⚠️ **{missing_count} permissions missing!** Please grant Administrator or missing permissions in Server Settings > Roles.", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="config_log_channel", description="設定防衛與警告日誌 (Log) 發送頻道")
@app_commands.checks.has_permissions(administrator=True)
async def config_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    config.log_channel_id = channel.id
    await interaction.response.send_message(
        f"✅ **日誌頻道已更新**：防衛紀錄與警告通知將發送至 {channel.mention} (`{channel.id}`)。",
        ephemeral=True
    )

@bot.tree.command(name="config_mass_delete", description="設定大量刪除頻道之時間與數量門檻 (Anti-Nuke)")
@app_commands.checks.has_permissions(administrator=True)
async def config_mass_delete(interaction: discord.Interaction, interval_seconds: int, channel_count: int):
    config.mass_delete_window = interval_seconds
    config.mass_delete_threshold = channel_count
    await interaction.response.send_message(f"✅ Anti-Nuke 設定已更新：在 **{interval_seconds}** 秒內刪除超過 **{channel_count}** 個頻道將觸發 BAN 停權。", ephemeral=True)

@bot.tree.command(name="warn", description="手動給予成員一次警告")
@app_commands.checks.has_permissions(administrator=True)
async def warn_user(interaction: discord.Interaction, member: discord.Member, reason: str = "違反伺服器守則"):
    await interaction.response.defer(ephemeral=True)
    await issue_warning(member, reason, interaction.channel, auto=False)
    await interaction.followup.send(f"✅ 已成功對 {member.mention} 劃記一次警告！(當前警告次數: {user_warnings[member.id]})")

@bot.tree.command(name="warnings", description="查詢成員的警告次數")
@app_commands.checks.has_permissions(administrator=True)
async def check_warnings(interaction: discord.Interaction, member: discord.Member):
    count = user_warnings[member.id]
    await interaction.response.send_message(f"🔍 成員 {member.mention} 當前累積警告次數為：**{count}** 次", ephemeral=True)

@bot.tree.command(name="clearwarn", description="歸零/清除成員的所有警告紀錄")
@app_commands.checks.has_permissions(administrator=True)
async def clear_warnings(interaction: discord.Interaction, member: discord.Member):
    user_warnings.pop(member.id, None)
    await interaction.response.send_message(f"🧹 已成功將 {member.mention} 的警告次數歸零！", ephemeral=True)

@bot.tree.command(name="add_blackword", description="新增自訂敏感詞黑名單")
@app_commands.checks.has_permissions(administrator=True)
async def add_blackword(interaction: discord.Interaction, word: str):
    config.blacklisted_words.add(word.lower())
    await interaction.response.send_message(f"✅ 已將敏感詞 `[{word}]` 加入黑名單！", ephemeral=True)

@bot.tree.command(name="remove_blackword", description="移除自訂敏感詞黑名單")
@app_commands.checks.has_permissions(administrator=True)
async def remove_blackword(interaction: discord.Interaction, word: str):
    config.blacklisted_words.discard(word.lower())
    await interaction.response.send_message(f"✅ 已將敏感詞 `[{word}]` 從黑名單移除！", ephemeral=True)

@bot.tree.command(name="config_warn_threshold", description="設定累積警告滿幾次執行禁言與踢出")
@app_commands.checks.has_permissions(administrator=True)
async def config_warn_threshold(interaction: discord.Interaction, timeout_count: int, kick_count: int):
    config.timeout_warn_count = timeout_count
    config.kick_warn_count = kick_count
    await interaction.response.send_message(f"✅ 警告門檻已更新：滿 **{timeout_count}** 次禁言，滿 **{kick_count}** 次踢出。", ephemeral=True)

@bot.tree.command(name="config_link_spam", description="設定連結洗版頻率")
@app_commands.checks.has_permissions(administrator=True)
async def config_link_spam(interaction: discord.Interaction, interval_seconds: int, count: int):
    config.link_spam_count = count
    config.link_spam_interval = interval_seconds
    await interaction.response.send_message(f"✅ 連結洗版更新：**{interval_seconds}** 秒超過 **{count}** 次觸發警告。", ephemeral=True)

@bot.tree.command(name="config_msg_spam", description="設定訊息刷屏頻率")
@app_commands.checks.has_permissions(administrator=True)
async def config_msg_spam(interaction: discord.Interaction, interval_seconds: int, count: int):
    config.msg_spam_count = count
    config.msg_spam_interval = interval_seconds
    await interaction.response.send_message(f"✅ 訊息刷屏更新：**{interval_seconds}** 秒超過 **{count}** 條觸發警告。", ephemeral=True)

@bot.tree.command(name="view_config", description="查看當前伺服器所有防禦與警告設定")
@app_commands.checks.has_permissions(administrator=True)
async def view_config(interaction: discord.Interaction):
    embed = discord.Embed(title="⚙️ 當前防禦與警告參數面板", color=discord.Color.green())
    embed.add_field(name="🚨 Anti-Nuke 刪頻道 BAN 門檻", value=f"**{config.mass_delete_window}** 秒超過 **{config.mass_delete_threshold}** 個", inline=True)
    embed.add_field(name="⚠️ 警告禁言門檻", value=f"滿 **{config.timeout_warn_count}** 次", inline=True)
    embed.add_field(name="🚪 警告踢出門檻", value=f"滿 **{config.kick_warn_count}** 次", inline=True)
    embed.add_field(name="🔗 連結洗版限制", value=f"**{config.link_spam_interval}** 秒內 **{config.link_spam_count}** 次", inline=True)
    embed.add_field(name="💬 訊息刷屏限制", value=f"**{config.msg_spam_interval}** 秒內 **{config.msg_spam_count}** 條", inline=True)
    embed.add_field(name="📜 Log 頻道 ID", value=f"`{config.log_channel_id}`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==================== 核心訊息監控 ====================

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    is_admin = message.author.guild_permissions.administrator
    if is_admin or message.channel.id in config.whitelist_channels:
        await bot.process_commands(message)
        return

    raw_content = message.content
    cleaned_content = clean_text(raw_content)
    has_link = bool(re.search(r'https?://', cleaned_content))
    
    user_id = message.author.id
    now = time.time()
    
    is_violation = False
    reason = ""

    # 1. 自訂敏感詞檢測
    if config.blacklisted_words:
        for black_word in config.blacklisted_words:
            if black_word in cleaned_content:
                is_violation = True
                reason = f"發送包含禁詞 `[{black_word}]` 的訊息"
                break

    # 2. 洗版與刷屏檢測
    if not is_violation:
        user_msg_history[user_id] = [t for t in user_msg_history[user_id] if now - t < config.msg_spam_interval]
        user_msg_history[user_id].append(now)
        if len(user_msg_history[user_id]) >= config.msg_spam_count:
            is_violation = True
            reason = f"訊息頻率過快 ({config.msg_spam_interval} 秒超過 {config.msg_spam_count} 條)"
        elif user_last_text.get(user_id) == cleaned_content and len(cleaned_content) > 3:
            user_duplicate_count[user_id] += 1
            if user_duplicate_count[user_id] >= config.max_duplicate_text:
                is_violation = True
                reason = f"連續發送相同訊息 {config.max_duplicate_text} 次"
        else:
            user_last_text[user_id] = cleaned_content
            user_duplicate_count[user_id] = 1

    # 3. 連結洗版檢測
    if not is_violation and has_link:
        user_link_history[user_id] = [t for t in user_link_history[user_id] if now - t < config.link_spam_interval]
        user_link_history[user_id].append(now)
        if len(user_link_history[user_id]) >= config.link_spam_count:
            is_violation = True
            reason = f"高頻貼連結 ({config.link_spam_interval} 秒超過 {config.link_spam_count} 次)"

    # 4. 未授權 @everyone / @here 檢測
    if not is_violation and message.mention_everyone:
        is_violation = True
        reason = "未授權標註 @everyone 或 @here"

    # 觸發處置
    if is_violation:
        user_msg_history.pop(user_id, None)
        user_link_history.pop(user_id, None)
        user_duplicate_count.pop(user_id, None)

        try:
            await message.delete()
            await issue_warning(message.author, reason, message.channel, auto=True)
        except Exception as e:
            print(f"❌ 處置過程中發生錯誤: {e}")

    await bot.process_commands(message)

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)

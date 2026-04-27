import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import datetime
import aiohttp

# ================= 基礎設定區 =================
TOKEN = os.getenv('DISCORD_TOKEN') 
MY_GUILD_ID = 1492797387008376852       
LIST_CHANNEL_ID = 1492909029780095200    # 名單顯示頻道
BACKUP_CHANNEL_ID = 1498317230541115493  # 數據備份頻道
DATA_FILE = "list_data.json"             
# =============================================

class ListBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.list_data = {
            "leader": "尚未設定",
            "examiner": "尚未設定",
            "members": "尚未設定"
        }
        self.main_msg_id = None

    def save_data(self):
        payload = {"list_data": self.list_data, "main_msg_id": self.main_msg_id}
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)

    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.list_data = data.get("list_data", self.list_data)
                    self.main_msg_id = data.get("main_msg_id")
            except: print("⚠️ 載入存檔失敗")

    async def setup_hook(self):
        self.load_data()
        guild = discord.Object(id=MY_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.auto_backup_task.start()

    @tasks.loop(hours=6)
    async def auto_backup_task(self):
        await self.wait_until_ready()
        await self.perform_full_backup("系統自動備份")

    async def perform_full_backup(self, reason):
        channel = self.get_channel(BACKUP_CHANNEL_ID)
        if not channel: return
        guild = self.get_guild(MY_GUILD_ID)
        if not guild: return

        # 備份伺服器架構
        structure = {
            "server_name": guild.name,
            "backup_time": str(datetime.datetime.now()),
            "roles": [f"{r.name} (ID: {r.id})" for r in guild.roles],
            "categories": [c.name for c in guild.categories],
            "channels": [f"#{ch.name} (ID: {ch.id})" for ch in guild.channels]
        }
        with open("server_structure.json", "w", encoding="utf-8") as f:
            json.dump(structure, f, ensure_ascii=False, indent=4)

        self.save_data()
        await channel.send(
            f"📦 **[名單機器人備份 - {reason}]**\n📅 時間：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            files=[discord.File(DATA_FILE), discord.File("server_structure.json")]
        )

    def create_list_embed(self):
        embed = discord.Embed(title="📜 團隊成員編制名單", color=0x2b2d31)
        embed.add_field(name="————————————————", value=f"**👑 房主、團長**\n{self.list_data['leader']}", inline=False)
        embed.add_field(name="————————————————", value=f"**⚖️ 考官**\n{self.list_data['examiner']}", inline=False)
        embed.add_field(name="————————————————", value=f"**👥 成員**\n{self.list_data['members']}", inline=False)
        embed.add_field(name="————————————————", value="✅ 數據已自動備份", inline=False)
        return embed

bot = ListBot()

# --- 管理功能 ---

@bot.tree.command(name="初始化名單", description="在指定頻道產生名單訊息")
@app_commands.default_permissions(administrator=True)
async def init_list(interaction: discord.Interaction):
    if interaction.channel_id != LIST_CHANNEL_ID:
        return await interaction.response.send_message(f"❌ 請在 <#{LIST_CHANNEL_ID}> 使用此指令。", ephemeral=True)
    
    embed = bot.create_list_embed()
    await interaction.response.send_message("✅ 名單已初始化。", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    bot.main_msg_id = msg.id
    bot.save_data()

async def update_list(interaction: discord.Interaction):
    try:
        channel = bot.get_channel(LIST_CHANNEL_ID)
        msg = await channel.fetch_message(bot.main_msg_id)
        await msg.edit(embed=bot.create_list_embed())
        bot.save_data()
        await interaction.followup.send("✅ 名單已更新。", ephemeral=True)
    except:
        await interaction.followup.send("❌ 找不到名單訊息，請重新使用 `/初始化名單`。", ephemeral=True)

@bot.tree.command(name="團長", description="更新團長名單")
@app_commands.default_permissions(administrator=True)
async def set_leader(interaction: discord.Interaction, 標記名單: str):
    await interaction.response.defer(ephemeral=True)
    bot.list_data["leader"] = 標記名單
    await update_list(interaction)

@bot.tree.command(name="考官", description="更新考官名單")
@app_commands.default_permissions(administrator=True)
async def set_examiner(interaction: discord.Interaction, 標記名單: str):
    await interaction.response.defer(ephemeral=True)
    bot.list_data["examiner"] = 標記名單
    await update_list(interaction)

@bot.tree.command(name="成員", description="更新成員名單")
@app_commands.default_permissions(administrator=True)
async def set_members(interaction: discord.Interaction, 標記名單: str):
    await interaction.response.defer(ephemeral=True)
    bot.list_data["members"] = 標記名單
    await update_list(interaction)

@bot.tree.command(name="手動備份", description="立刻備份數據與架構")
@app_commands.default_permissions(administrator=True)
async def manual_backup(interaction: discord.Interaction):
    await interaction.response.send_message("⌛ 正在備份...", ephemeral=True)
    await bot.perform_full_backup(f"手動觸發: {interaction.user.name}")

@bot.tree.command(name="還原數據", description="上傳備份檔恢復名單內容")
@app_commands.default_permissions(administrator=True)
async def restore_data(interaction: discord.Interaction, 備份檔: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        async with session.get(備份檔.url) as resp:
            if resp.status == 200:
                data = json.loads(await resp.text())
                bot.list_data = data.get("list_data", bot.list_data)
                bot.main_msg_id = data.get("main_msg_id")
                bot.save_data()
                await interaction.followup.send("✅ 數據還原成功。")
            else:
                await interaction.followup.send("❌ 無法下載檔案。")

bot.run(TOKEN)

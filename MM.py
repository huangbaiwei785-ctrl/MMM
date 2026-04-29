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
            "leaders": [],    # 團長清單
            "examiners": [],  # 考官清單
            "members": []     # 團員清單
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

    # --- 備份系統 ---
    @tasks.loop(hours=6)
    async def auto_backup_task(self):
        await self.wait_until_ready()
        await self.perform_full_backup("系統自動備份")

    async def perform_full_backup(self, reason):
        channel = self.get_channel(BACKUP_CHANNEL_ID) or await self.fetch_channel(BACKUP_CHANNEL_ID)
        if not channel: return
        
        self.save_data()
        await channel.send(
            f"📦 **[名單備份 - {reason}]**\n📅 時間：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            file=discord.File(DATA_FILE)
        )

    # --- 界面生成 ---
    def create_list_embed(self):
        def format_list(key):
            return "\n".join(self.list_data[key]) if self.list_data[key] else "尚未設定"

        embed = discord.Embed(title="📜 團隊成員編制名單", color=0x2b2d31)
        embed.add_field(name="👑 房主、團長", value=format_list("leaders"), inline=False)
        embed.add_field(name="⚖️ 考官", value=format_list("examiners"), inline=False)
        embed.add_field(name="👥 成員 (總數: {})".format(len(self.list_data['members'])), value=format_list("members"), inline=False)
        embed.set_footer(text=f"✅ 數據已備份 | 最後更新：{datetime.datetime.now().strftime('%H:%M:%S')}")
        return embed

bot = ListBot()

# --- 通用更新邏輯 ---
async def update_display(interaction: discord.Interaction):
    try:
        channel = bot.get_channel(LIST_CHANNEL_ID)
        msg = await channel.fetch_message(bot.main_msg_id)
        await msg.edit(embed=bot.create_list_embed())
        bot.save_data()
        if not interaction.response.is_done():
            await interaction.response.send_message("✅ 名單已同步更新。", ephemeral=True)
    except:
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 更新失敗，請先使用 `/初始化名單`", ephemeral=True)

# --- 指令區：分組管理 ---

@bot.tree.command(name="管理名單", description="增加或減少各組成員")
@app_commands.describe(項目="要操作的類別", 動作="增加或減少", 成員="選擇成員", 備註="額外文字(選填)")
@app_commands.choices(項目=[
    app_commands.Choice(name="團長", value="leaders"),
    app_commands.Choice(name="考官", value="examiners"),
    app_commands.Choice(name="團員", value="members")
], 動作=[
    app_commands.Choice(name="增加 (+)", value="add"),
    app_commands.Choice(name="減少 (-)", value="remove")
])
@app_commands.default_permissions(administrator=True)
async def manage_list(interaction: discord.Interaction, 項目: str, 動作: str, 成員: discord.Member, 備註: str = ""):
    await interaction.response.defer(ephemeral=True)
    
    target_list = bot.list_data[項目]
    mention_str = f"{成員.mention} {備註}".strip()

    if 動作 == "add":
        if not any(str(成員.id) in m for m in target_list):
            target_list.append(mention_str)
        else:
            return await interaction.followup.send("⚠️ 該成員已在清單中。", ephemeral=True)
    else:
        bot.list_data[項目] = [m for m in target_list if str(成員.id) not in m]

    await update_display(interaction)

# --- 備份與還原指令 ---

@bot.tree.command(name="手動備份", description="立刻備份數據")
async def manual_backup(interaction: discord.Interaction):
    await interaction.response.send_message("⌛ 正在備份...", ephemeral=True)
    await bot.perform_full_backup(f"手動觸發: {interaction.user.name}")

@bot.tree.command(name="還原數據", description="上傳備份檔恢復名單")
async def restore_data(interaction: discord.Interaction, 備份檔: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        async with session.get(備份檔.url) as resp:
            if resp.status == 200:
                data = json.loads(await resp.text())
                bot.list_data = data.get("list_data", bot.list_data)
                bot.main_msg_id = data.get("main_msg_id")
                bot.save_data()
                await interaction.followup.send("✅ 數據還原成功，請檢查名單訊息。")
            else:
                await interaction.followup.send("❌ 下載失敗。")

@bot.tree.command(name="初始化名單", description="在目前頻道建立名單卡片")
async def init_list(interaction: discord.Interaction):
    embed = bot.create_list_embed()
    msg = await interaction.channel.send(embed=embed)
    bot.main_msg_id = msg.id
    bot.save_data()
    await interaction.response.send_message("✅ 初始化完成。", ephemeral=True)

bot.run(TOKEN)

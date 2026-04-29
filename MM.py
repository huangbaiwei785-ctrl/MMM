import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import datetime
import aiohttp
import io

# ================= 基礎設定區 =================
TOKEN = os.getenv('DISCORD_TOKEN') 
MY_GUILD_ID = 1492797387008376852       
LIST_CHANNEL_ID = 1492909029780095200    
BACKUP_CHANNEL_ID = 1498317230541115493  
DATA_FILE = "list_data.json"             
# =============================================

class ListBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.list_data = {
            "leaders": [],
            "examiners": [],
            "members": []
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

    # --- 核心備份邏輯 (含架構) ---
    async def perform_full_backup(self, reason):
        channel = self.get_channel(BACKUP_CHANNEL_ID) or await self.fetch_channel(BACKUP_CHANNEL_ID)
        guild = self.get_guild(MY_GUILD_ID)
        if not channel or not guild: return

        # 1. 數據備份
        self.save_data()

        # 2. 伺服器架構備份
        structure = {
            "server_name": guild.name,
            "backup_time": str(datetime.datetime.now()),
            "roles": [{"name": r.name, "id": r.id} for r in guild.roles],
            "categories": [{"name": c.name, "id": c.id} for c in guild.categories],
            "channels": [{"name": ch.name, "id": ch.id, "type": str(ch.type)} for ch in guild.channels]
        }
        struct_file = io.BytesIO(json.dumps(structure, ensure_ascii=False, indent=4).encode('utf-8'))
        
        await channel.send(
            f"📦 **[全系統備份 - {reason}]**\n📅 時間：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            files=[
                discord.File(DATA_FILE),
                discord.File(struct_file, filename="server_structure.json")
            ]
        )

    @tasks.loop(hours=6)
    async def auto_backup_task(self):
        await self.wait_until_ready()
        await self.perform_full_backup("系統自動定時備份")

    # --- 名單渲染 ---
    def create_list_embed(self):
        def format_list(key):
            return "\n".join(self.list_data[key]) if self.list_data[key] else "尚未設定"

        embed = discord.Embed(title="📜 團隊成員編制名單", color=0x2b2d31, timestamp=datetime.datetime.now())
        embed.add_field(name="👑 房主、團長", value=format_list("leaders"), inline=False)
        embed.add_field(name="⚖️ 考官", value=format_list("examiners"), inline=False)
        embed.add_field(name="👥 成員 (總計: {} 人)".format(len(self.list_data['members'])), value=format_list("members"), inline=False)
        embed.set_footer(text="數據已加密備份")
        return embed

bot = ListBot()

# --- 強制更新函式 ---
async def force_refresh_display():
    try:
        channel = bot.get_channel(LIST_CHANNEL_ID)
        msg = await channel.fetch_message(bot.main_msg_id)
        await msg.edit(embed=bot.create_list_embed())
        bot.save_data()
        return True
    except:
        return False

# --- 指令區 ---

@bot.tree.command(name="批量增加成員", description="一次增加多位成員 (用空格或換行分開)")
@app_commands.describe(項目="分類", 標記多位成員="直接標記多個人", 備註="統一備註")
@app_commands.choices(項目=[
    app_commands.Choice(name="團長", value="leaders"),
    app_commands.Choice(name="考官", value="examiners"),
    app_commands.Choice(name="團員", value="members")
])
async def bulk_add(interaction: discord.Interaction, 項目: str, 標記多位成員: str, 備註: str = ""):
    await interaction.response.defer(ephemeral=True)
    
    # 透過解析標記字串提取 ID
    import re
    user_ids = re.findall(r'<@!?(\243818)>', 標記多位成員) # 修正正則
    user_ids = re.findall(r'\d+', 標記多位成員) # 更簡單的提取數字方式
    
    added_count = 0
    for uid in user_ids:
        mention = f"<@{uid}> {備註}".strip()
        if not any(uid in m for m in bot.list_data[項目]):
            bot.list_data[項目].append(mention)
            added_count += 1
    
    await force_refresh_display()
    await interaction.followup.send(f"✅ 已成功批量增加 {added_count} 位成員到 {項目}。")

@bot.tree.command(name="管理名單", description="單個增減成員")
async def manage_list(interaction: discord.Interaction, 項目: str, 動作: str, 成員: discord.Member, 備註: str = ""):
    # ... (保持原本的單個增減邏輯，但最後呼叫 force_refresh_display)
    await interaction.response.defer(ephemeral=True)
    target_list = bot.list_data[項目]
    if 動作 == "add":
        target_list.append(f"{成員.mention} {備註}".strip())
    else:
        bot.list_data[項目] = [m for m in target_list if str(成員.id) not in m]
    
    await force_refresh_display()
    await interaction.followup.send("✅ 處理完成並已刷新名單。")

@bot.tree.command(name="還原數據", description="上傳 list_data.json 檔案進行還原並自動更新")
async def restore_data(interaction: discord.Interaction, 備份檔: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        async with session.get(備份檔.url) as resp:
            if resp.status == 200:
                content = await resp.text()
                data = json.loads(content)
                if "list_data" in data:
                    bot.list_data = data["list_data"]
                    bot.main_msg_id = data.get("main_msg_id", bot.main_msg_id)
                    bot.save_data()
                    success = await force_refresh_display()
                    msg = "✅ 還原成功且名單已刷新！" if success else "✅ 還原成功，但找不到名單訊息進行更新，請重新 /初始化名單。"
                    await interaction.followup.send(msg)
                else:
                    await interaction.followup.send("❌ 檔案格式不符。")

@bot.tree.command(name="手動備份", description="立即執行全系統備份 (含架構)")
async def manual_backup_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("⌛ 正在執行全系統備份...", ephemeral=True)
    await bot.perform_full_backup(f"手動執行: {interaction.user.name}")

@bot.tree.command(name="初始化名單")
async def init_list(interaction: discord.Interaction):
    embed = bot.create_list_embed()
    msg = await interaction.channel.send(embed=embed)
    bot.main_msg_id = msg.id
    bot.save_data()
    await interaction.response.send_message("✅ 初始化成功。", ephemeral=True)

bot.run(TOKEN)

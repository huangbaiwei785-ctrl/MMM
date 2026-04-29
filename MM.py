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
LIST_CHANNEL_ID = 1492909029780095200    
BACKUP_CHANNEL_ID = 1498317230541115493  
DATA_FILE = "list_data.json"             
# =============================================

class ListBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        # 初始化數據結構，確保 members 是列表而非字串，方便增減
        self.list_data = {
            "leader": "尚未設定",
            "examiner": "尚未設定",
            "members": []  # 改為列表儲存
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
                    # 確保舊資料轉新列表格式
                    if isinstance(self.list_data["members"], str):
                        self.list_data["members"] = [self.list_data["members"]]
                    self.main_msg_id = data.get("main_msg_id")
            except: print("⚠️ 載入存檔失敗")

    async def setup_hook(self):
        self.load_data()
        guild = discord.Object(id=MY_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    def create_list_embed(self):
        # 處理成員清單的顯示格式
        member_list_str = "\n".join(self.list_data['members']) if self.list_data['members'] else "尚未設定"
        
        embed = discord.Embed(title="📜 團隊成員編制名單", color=0x2b2d31)
        embed.add_field(name="————————————————", value=f"**👑 房主、團長**\n{self.list_data['leader']}", inline=False)
        embed.add_field(name="————————————————", value=f"**⚖️ 考官**\n{self.list_data['examiner']}", inline=False)
        embed.add_field(name="————————————————", value=f"**👥 成員 (總數: {len(self.list_data['members'])})**\n{member_list_str}", inline=False)
        embed.set_footer(text=f"最後更新：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return embed

bot = ListBot()

# --- 改良更新邏輯 ---
async def safe_update(interaction: discord.Interaction):
    try:
        channel = bot.get_channel(LIST_CHANNEL_ID)
        msg = await channel.fetch_message(bot.main_msg_id)
        await msg.edit(embed=bot.create_list_embed())
        bot.save_data()
        if not interaction.response.is_done():
            await interaction.response.send_message("✅ 名單已同步更新。", ephemeral=True)
        else:
            await interaction.followup.send("✅ 名單已同步更新。", ephemeral=True)
    except:
        await interaction.followup.send("❌ 更新失敗，請確認是否已 `/初始化名單`。", ephemeral=True)

# --- 新增指令：單人增減 ---

@bot.tree.command(name="增加成員", description="單獨增加一位成員到名單")
@app_commands.default_permissions(administrator=True)
async def add_member(interaction: discord.Interaction, 成員標記: discord.Member, 備註: str = ""):
    await interaction.response.defer(ephemeral=True)
    # 使用 .mention 確保正確標記，並加上備註
    entry = f"{成員標記.mention} {備註}".strip()
    if entry not in bot.list_data["members"]:
        bot.list_data["members"].append(entry)
        await safe_update(interaction)
    else:
        await interaction.followup.send("⚠️ 該成員已在名單中。", ephemeral=True)

@bot.tree.command(name="減少成員", description="從名單中移除一位成員")
@app_commands.default_permissions(administrator=True)
async def remove_member(interaction: discord.Interaction, 成員標記: discord.Member):
    await interaction.response.defer(ephemeral=True)
    # 尋找包含該 ID 的項目並刪除
    target_id = str(成員標記.id)
    original_count = len(bot.list_data["members"])
    bot.list_data["members"] = [m for m in bot.list_data["members"] if target_id not in m]
    
    if len(bot.list_data["members"]) < original_count:
        await safe_update(interaction)
    else:
        await interaction.followup.send("❌ 找不到該成員。", ephemeral=True)

# --- 原有指令優化 ---

@bot.tree.command(name="初始化名單", description="在指定頻道產生名單訊息")
async def init_list(interaction: discord.Interaction):
    embed = bot.create_list_embed()
    msg = await interaction.channel.send(embed=embed)
    bot.main_msg_id = msg.id
    bot.save_data()
    await interaction.response.send_message("✅ 名單初始化完成。", ephemeral=True)

@bot.tree.command(name="清空成員", description="一鍵清除所有成員名單")
async def clear_members(interaction: discord.Interaction):
    bot.list_data["members"] = []
    await interaction.response.defer(ephemeral=True)
    await safe_update(interaction)

bot.run(TOKEN)

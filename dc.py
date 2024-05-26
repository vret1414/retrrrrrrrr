import asyncio
import json
import re
import time
from typing import Union
import discord
from discord.ext import commands, tasks
import random
from datetime import datetime, timedelta
from discord.ui import Button, View
import datetime
from peewee import SqliteDatabase, Model, IntegerField, TextField, DateTimeField, OperationalError, BooleanField
import os
import aiohttp
from googletrans import Translator
import requests
from playhouse.shortcuts import model_to_dict

db = SqliteDatabase('data.db')

class BaseModel(Model):
    class Meta:
        database = db

class User(BaseModel):
    user_id = IntegerField(unique=True)
    username = TextField()
    money = IntegerField(default=0)
    last_daily = DateTimeField(default=datetime.datetime(datetime.MINYEAR, 1, 1))
    last_weekly = DateTimeField(default=datetime.datetime(datetime.MINYEAR, 1, 1))
    last_monthly = DateTimeField(default=datetime.datetime(datetime.MINYEAR, 1, 1))
    is_afk = BooleanField(default=False)
    afk_message = TextField(default='')
    warnings = TextField(default='[]') 
    lootboxes = IntegerField(default=0)
    inventory = TextField(default='[]')

class Prefix(BaseModel):
    guild_id = IntegerField(unique=True)
    prefix = TextField()

db.connect()
with db.atomic():
    db.create_tables([User, Prefix], safe=True)

try:
    with db.atomic():
        db.execute_sql('ALTER TABLE user ADD COLUMN last_monthly DATETIME DEFAULT "0001-01-01 00:00:00"')
except OperationalError:
    pass

with db.atomic():
    try:
        db.execute_sql('ALTER TABLE user ADD COLUMN is_afk BOOLEAN DEFAULT FALSE')
        db.execute_sql('ALTER TABLE user ADD COLUMN afk_message TEXT DEFAULT ""')
        db.execute_sql('ALTER TABLE user ADD COLUMN warnings TEXT DEFAULT "[]"')
        db.execute_sql('ALTER TABLE user ADD COLUMN inventory TEXT DEFAULT "[]"')
    except OperationalError:
        pass

with db.atomic():
    try:
        db.execute_sql('ALTER TABLE user ADD COLUMN lootboxes INTEGER DEFAULT 0')
    except OperationalError:
        pass

with db.atomic():
    try:
        db.execute_sql('ALTER TABLE user ADD COLUMN inventory TEXT DEFAULT "[]"')
    except OperationalError:
        pass

if not Prefix.table_exists():
    # If not, create it
    with db.atomic():
        db.create_table(Prefix)

def get_prefix(bot, message):
    try:
        prefix = Prefix.get(Prefix.guild_id == message.guild.id).prefix
    except Prefix.DoesNotExist:
        prefix = ","  # Default prefix
    return prefix

def get_or_create_user(user_id, username):
    user, created = User.get_or_create(user_id=user_id, defaults={'username': username})
    if created:
        user.save()
    return user

with open('loot_items.json', 'r') as f:
    loot_items = json.load(f)

with open('shop_items.json', 'r') as f:
    loot_items = json.load(f)

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix=get_prefix,intents=intents,help_command=None)

COMMAND_CATEGORIES = {
    "⚡ Utility": ["cmd", "shia", "uptime", "info", "eth", "btc", "ltc", "lock", "unlock", "slowmode", "ping", "serverinfo"],
    "🔨 Moderation": ["role", "mute", "unmute", "kick", "ban", "unban", "purge", "warn", "warns", "nick", "prefix", "setprefix"],
    "🎉 Fun": ["limbo", "coinflip", "dick", "gay", "_8ball", "cat", "dog"],
    "👛 Economy": ["daily", "weekly", "monthly", "give", "money", "leaderboard", "lootbox", "lb", "shop", "buy", "inv"],
    "✨ Extras": ["afk", "afkoff", "remindme", "weather", "cuddle", "meme","credits"],
}
CATEGORY_DESCRIPTIONS = {
    "⚡ Utility": "Essential commands for bot and server management.",
    "🔨 Moderation": "Keep your server in check with these moderation tools.",
    "🎉 Fun": "Lighten up your server with these fun and games commands.",
    "👛 Economy": "Engage your server with an interactive economy system.",
    "✨ Extras": "Additional commands for various utilities and fun."
}

COMMANDS_PER_PAGE = 5

class HelpMenuView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.current_page = 0
        self.selected_category = None

        options = [
            discord.SelectOption(
                label=f"{category} ({len(commands)})",
                description=CATEGORY_DESCRIPTIONS[category],
                value=category
            ) for category, commands in COMMAND_CATEGORIES.items()
        ]
        self.dropdown = discord.ui.Select(placeholder="Select a category...", options=options)
        self.dropdown.callback = self.select_category
        self.add_item(self.dropdown)

        self.prev_button = discord.ui.Button(label='PREVIOUS', style=discord.ButtonStyle.primary)
        self.prev_button.callback = self.go_previous
        self.next_button = discord.ui.Button(label='NEXT', style=discord.ButtonStyle.primary)
        self.next_button.callback = self.go_next
        self.page_button = discord.ui.Button(style=discord.ButtonStyle.primary, label=f"Page {self.current_page + 1}", disabled=True)
        self.first_button = discord.ui.Button(label='FIRST', style=discord.ButtonStyle.secondary)
        self.first_button.callback = self.go_first
        self.last_button = discord.ui.Button(label='LAST', style=discord.ButtonStyle.secondary)
        self.last_button.callback = self.go_last

        self.update_buttons()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        self.stop()

    async def select_category(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("You did not initiate this command!", ephemeral=True)
            return

        self.selected_category = self.dropdown.values[0]
        self.current_page = 0
        embed = self.create_embed()
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def go_previous(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("You did not initiate this command!", ephemeral=True)
            return

        if self.current_page > 0:
            self.current_page -= 1
        else:
            self.current_page = self.total_pages() - 1
        embed = self.create_embed()
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def go_next(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("You did not initiate this command!", ephemeral=True)
            return

        if self.current_page < self.total_pages() - 1:
            self.current_page += 1
        else:
            self.current_page = 0
        embed = self.create_embed()
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def go_first(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("You did not initiate this command!", ephemeral=True)
            return

        self.current_page = 0
        embed = self.create_embed()
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def go_last(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("You did not initiate this command!", ephemeral=True)
            return

        self.current_page = self.total_pages() - 1
        embed = self.create_embed()
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    def create_embed(self):
        embed = discord.Embed(
            title=f"{self.selected_category} Commands",
            description=CATEGORY_DESCRIPTIONS[self.selected_category],
            color=discord.Color.blurple()
        )
        embed.set_author(name=self.ctx.bot.user.name, icon_url=self.ctx.bot.user.avatar.url)

        commands = COMMAND_CATEGORIES[self.selected_category]
        start_idx = self.current_page * COMMANDS_PER_PAGE
        end_idx = min((self.current_page + 1) * COMMANDS_PER_PAGE, len(commands))

        for command_name in commands[start_idx:end_idx]:
            command = self.ctx.bot.get_command(command_name)
            if command:
                embed.add_field(name=f"`{command.name}`", value=command.help or "No description provided", inline=False)

        embed.set_footer(text=f"Page {self.current_page + 1} of {self.total_pages()}. Use the buttons to navigate.")
        return embed

    def total_pages(self):
        return (len(COMMAND_CATEGORIES[self.selected_category]) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE

    def update_buttons(self):
        self.clear_items()

        if self.selected_category:
            total_pages = self.total_pages()
            self.page_button.label = f"Page {self.current_page + 1}/{total_pages}"
            self.prev_button.disabled = self.current_page == 0
            self.next_button.disabled = self.current_page >= total_pages - 1
            self.first_button.disabled = self.current_page == 0
            self.last_button.disabled = self.current_page >= total_pages - 1

            self.add_item(self.dropdown)
            self.add_item(self.first_button)
            self.add_item(self.prev_button)
            self.add_item(self.page_button)
            self.add_item(self.next_button)
            self.add_item(self.last_button)
        else:
            self.page_button.label = "Page 1"
            self.prev_button.disabled = True
            self.next_button.disabled = True
            self.first_button.disabled = True
            self.last_button.disabled = True

            self.add_item(self.dropdown)


@bot.command()
async def credits(ctx):
    """
    `Shows the credits for the bot.
    Usage: credits`
    """
    embed = discord.Embed(
        title="Credits",
        description=f"This bot is brought to you by `@pgdel`!\n**For any inquiries add me on discord.**",
        color=discord.Color.blurple()
    )
    embed.set_author(name=ctx.bot.user.name, icon_url=ctx.bot.user.avatar.url)
    embed.set_footer(text="Powered by retro ai")
    await ctx.reply(embed=embed)

@bot.command(aliases=["help"])
async def cmd(ctx: commands.Context):
    """
    `Shows this menu
    Usage: ,cmd`
    """
    view = HelpMenuView(ctx)
    total_commands = sum(len(commands) for commands in COMMAND_CATEGORIES.values())
    embed = discord.Embed(
        title=f"Help Menu | Total Commands: {total_commands}",
        description="Select a category from the dropdown menu below.",
        color=discord.Color.blurple()
    )
    embed.set_author(name=ctx.bot.user.name, icon_url=ctx.bot.user.avatar.url)
    await ctx.reply(embed=embed, view=view)

@bot.event
async def on_guild_join(guild):
    # Attempt to fetch the audit log to find the inviter
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
        inviter = entry.user
        if inviter is not None:
            try:
                embed = discord.Embed(
                    title="Retro.ai | Fun interactive bot",
                    description=(
                        "**Hello! Thank you for adding me to your server!**\n\n"
                        "**Default Prefix:** `,` | You can change my prefix with `,setprefix <prefix>`\n\n"
                        "**Commands List:** `,cmd` | Categorized for your convenience\n\n"
                        "**If you have any questions or need further assistance, feel free to reach out! 😁**"
                    ),
                    color=discord.Color.blue()
                )
                await inviter.send(embed=embed)
            except discord.Forbidden:
                print(f"Could not send DM to {inviter.name}")

def format_timedelta(td):
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    if days > 0:
        return f"{days} days, {hours} hours, and {minutes} minutes"
    else:
        return f"{hours} hours and {minutes} minutes"
    
@bot.command()
@commands.has_permissions(administrator=True)
async def setprefix(ctx, new_prefix: str):
    """
    `Change the guild prefix
    Usage: ,setprefix <new_prefix>`
    """
    if not new_prefix or new_prefix.isspace():
        embed = discord.Embed(
            title="Error",
            description="The prefix cannot be empty or whitespace.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return
    
    try:
        # Ensure there's a default prefix in the database
        prefix, created = Prefix.get_or_create(guild_id=ctx.guild.id, defaults={'prefix': ','})
        
        # Update to the new prefix
        prefix.prefix = new_prefix
        prefix.save()
        
        embed = discord.Embed(
            title="Prefix Changed",
            description=f"The prefix for this guild has been changed to `{new_prefix}`",
            color=discord.Color.green()
        )
        await ctx.reply(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="Error",
            description=f"Failed to change prefix. Error: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)

@bot.command()
async def prefix(ctx):
    """
    `View the current guild prefix
    Usage: ,prefix`
    """
    try:
        prefix = Prefix.get(Prefix.guild_id == ctx.guild.id).prefix
    except Prefix.DoesNotExist:
        prefix = ","  # Default prefix

    embed = discord.Embed(
        title="Current Prefix",
        description=f"The current prefix for this guild is `{prefix}`",
        color=discord.Color.blue()
    )
    await ctx.reply(embed=embed)

@bot.command()
async def cuddle(ctx, user: discord.Member):
    """
    `Cuddle with a user
    Usage: ,cuddle <user>`
    """
    gif_folder = 'cuddle_gifs'
    gif_files = os.listdir(gif_folder)
    random_gif = random.choice(gif_files)
    file_path = os.path.join(gif_folder, random_gif)
    file = discord.File(file_path)
    embed = discord.Embed(description=f"{ctx.author.mention} cuddles {user.mention} ❤️")
    embed.set_image(url=f"attachment://{random_gif}")
    await ctx.reply(embed=embed, file=file)

# Daily command
@bot.command()
async def daily(ctx):
    """
    `Claim your daily reward
    Usage: ,daily`
    """
    user = get_or_create_user(ctx.author.id, ctx.author.name)
    now = datetime.datetime.now()

    if (now - user.last_daily).days >= 1:
        user.money += 500
        user.last_daily = now
        user.lootboxes += 1
        user.save()
        embed = discord.Embed(title="Daily Reward", description=f"{ctx.author.mention}, you have received your daily reward of `500` ⛃ and a `lootbox! 📦`", color=discord.Color.green())
    else:
        next_claim = user.last_daily + datetime.timedelta(days=1)
        time_remaining = next_claim - now
        hours, remainder = divmod(time_remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        embed = discord.Embed(title="Daily Reward", description=f"{ctx.author.mention}, you can claim your next daily reward in {hours} hours, and {minutes} minutes.", color=discord.Color.red())
    
    await ctx.reply(embed=embed)

# Weekly command
@bot.command()
async def weekly(ctx):
    """
    `Claim your weekly reward
    Usage: ,weekly`
    """
    user, _ = User.get_or_create(user_id=ctx.author.id, defaults={'username': ctx.author.name, 'guild_id': ctx.guild.id})
    now = datetime.datetime.now()
    if (now - user.last_weekly).days >= 7:
        user.money += 5000  # Adjust reward amount as needed
        user.last_weekly = now
        user.lootboxes += 3
        user.save()
        embed = discord.Embed(title="Weekly Reward", description=f"{ctx.author.mention}, you have received your weekly reward of `50000` ⛃ and `3 lootboxes 📦!`", color=discord.Color.green())
        await ctx.reply(embed=embed)
    else:
        next_claim = user.last_weekly + datetime.timedelta(days=7)
        time_remaining = next_claim - now
        hours, remainder = divmod(time_remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        days = time_remaining.days
        embed = discord.Embed(title="Weekly Reward", description=f"{ctx.author.mention}, you can claim your next weekly reward in {days} days, {hours} hours, and {minutes} minutes.", color=discord.Color.red())
        await ctx.reply(embed=embed)

@bot.command()
async def monthly(ctx):
    """
    `Claim your monthly reward
    Usage: ,monthly`
    """
    user, _ = User.get_or_create(user_id=ctx.author.id, defaults={'username': ctx.author.name, 'guild_id': ctx.guild.id})
    now = datetime.datetime.now()
    if (now - user.last_monthly).days >= 30:
        user.money += 100000  # Adjust reward amount as needed
        user.last_monthly = now
        user.lootboxes += 5
        user.save()
        embed = discord.Embed(title="Monthly Reward", description=f"{ctx.author.mention}, you have received your monthly reward of `400000` ⛃ and `5 lootboxes 📦!`", color=discord.Color.green())
        await ctx.reply(embed=embed)
    else:
        next_claim = user.last_monthly + datetime.timedelta(days=30)
        time_remaining = next_claim - now
        days = time_remaining.days
        hours, remainder = divmod(time_remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        embed = discord.Embed(title="Monthly Reward", description=f"{ctx.author.mention}, you can claim your next monthly reward in {days} days, {hours} hours, and {minutes} minutes.", color=discord.Color.red())
        await ctx.reply(embed=embed)

@daily.error
@weekly.error
@monthly.error
async def command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        embed = discord.Embed(
            title="Cooldown",
            description=f"{ctx.author.mention}, you are on cooldown. Try again later.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
    else:
        raise error

@bot.command(name="lootbox")
async def lootbox(ctx):
    """
    `Open a lootbox and get a random item
    Usage: ,lootbox`
    """
    user = get_or_create_user(ctx.author.id, ctx.author.name)

    if user.lootboxes > 0:
        user.lootboxes -= 1
        user.save()

        # Open lootbox animation
        embed = discord.Embed(title="Opening Lootbox...", description="🎁 Opening your lootbox...", color=discord.Color.blue())
        embed.set_image(url="https://cdn.dribbble.com/users/1112010/screenshots/4559034/lootbox.gif")  
        message = await ctx.send(embed=embed)

        await asyncio.sleep(3) 

        # Determine loot
        loot = random.choice(loot_items)
        embed = discord.Embed(title="Lootbox Opened!", description=f"🎁 You received: **{loot['name']}**!", color=discord.Color.gold())
        embed.add_field(name="Price", value=f"`{loot['price']}` ⛃")
        embed.add_field(name="Rarity", value=f"`{loot['rarity']}`")
        await message.edit(embed=embed)
    else:
        embed = discord.Embed(title="No Lootboxes", description="**You don't have any lootboxes to open.**", color=discord.Color.red())
        await ctx.send(embed=embed)

# Check lootboxes command
@bot.command(name="lb")
async def check_lootboxes(ctx):
    """
    `Check how many lootboxes you have
    Usage: ,lb`
    """
    user = get_or_create_user(ctx.author.id, ctx.author.name)
    embed = discord.Embed(title="Lootboxes", description=f"{ctx.author.mention}, you have **{user.lootboxes}** lootbox(es).", color=discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command(name="shop")
async def shop(ctx):
    """
    `View the shop
    Usage: ,shop`
    """
    embed = discord.Embed(
        title="Shop Items",
        description="Available items for purchase:",
        color=discord.Color.green()
    )
    for item in loot_items:
        embed.add_field(
            name=f"{item['emoji']} {item['name']} (ID: {item['item_id']})",
            value=f"Price: `{item['price']} ⛃`\nRarity: `{item['rarity']}`",
            inline=False
        )
    embed.set_footer(text="Use ,buy <item_id> to purchase an item.")
    await ctx.send(embed=embed)

@bot.command(name="buy")
async def buy(ctx, item_id: int):
    """
    `Buy an item from the shop
    Usage: ,buy <item_id>`
    """
    try:
        user = get_or_create_user(ctx.author.id, ctx.author.name)
        
        # Find the item in the loot_items by item_id
        item = next((item for item in loot_items if item['item_id'] == item_id), None)
        
        if item:
            if user.money >= item['price']:
                # Deduct the price from user's money
                user.money -= item['price']
                user.save()
                
                # Add the item to user's inventory
                inventory = json.loads(user.inventory)
                inventory.append(item['item_id'])
                user.inventory = json.dumps(inventory)
                user.save()
                
                embed = discord.Embed(
                    title="Purchase Successful",
                    description=f"{ctx.author.mention}, you've successfully purchased **{item['name']}** {item['emoji']} (ID: {item['item_id']}).",
                    color=discord.Color.green()
                )
                embed.set_thumbnail(url=ctx.author.display_avatar.url or ctx.author.default_avatar.url)
                embed.set_footer(text="Thank you for your purchase!")
            else:
                embed = discord.Embed(
                    title="Insufficient Funds",
                    description=f"{ctx.author.mention}, you don't have enough money to buy **{item['name']}** {item['emoji']} (ID: {item['item_id']}).",
                    color=discord.Color.red()
                )
                embed.set_thumbnail(url=ctx.author.display_avatar.url or ctx.author.default_avatar.url)
                embed.set_footer(text="Earn more money to buy this item!")
        else:
            embed = discord.Embed(
                title="Item Not Found",
                description=f"{ctx.author.mention}, the item with ID `{item_id}` is not available in the shop.",
                color=discord.Color.orange()
            )
            embed.set_thumbnail(url=ctx.author.display_avatar.url or ctx.author.default_avatar.url)
            embed.set_footer(text="Please check the item ID and try again.")
        
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="Error",
            description=f"An error occurred while processing your request: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        raise e

# Inventory command
@bot.command(name="inv")
async def inventory(ctx):
    """
    `Check your inventory
    Usage: ,inv`
    """
    user = get_or_create_user(ctx.author.id, ctx.author.name)
    inventory = json.loads(user.inventory)
    
    if not inventory:
        embed = discord.Embed(title="**Inventory**", description="`Your inventory is empty.`", color=discord.Color.red())
    else:
        # Count occurrences of each item in the inventory
        item_counts = {}
        for item_id in inventory:
            item_counts[item_id] = item_counts.get(item_id, 0) + 1
        
        # Split inventory items into pages if more than 5 items
        pages = [list(item_counts.keys())[i:i + 5] for i in range(0, len(item_counts), 5)]
        page_index = 0
        
        # Function to create embed for a page
        def create_page_embed(items):
            embed = discord.Embed(title="**Inventory**", description="`Your items:`", color=discord.Color.blue())
            for item_id in items:
                item = next((i for i in loot_items if i["item_id"] == item_id), None)
                if item:
                    quantity = item_counts[item_id]
                    item_name = f"{item['emoji']} {item['name']}"
                    if quantity > 1:
                        item_name += f" x{quantity}"
                    embed.add_field(name=item_name, value=f"Price: `{item['price']} ⛃`\nRarity: `{item['rarity']}`", inline=False)
            return embed
        
        # Send the initial page
        embed = create_page_embed(pages[page_index])
        embed.set_footer(text=f"Page {page_index + 1}/{len(pages)} | Use ,lootbox or ,shop to get more items.")
        message = await ctx.send(embed=embed)
        
        # Add reaction buttons for pagination
        if len(pages) > 1:
            await message.add_reaction("⬅️")
            await message.add_reaction("➡️")
            
        # Pagination logic
        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["⬅️", "➡️"]
        
        while True:
            try:
                reaction, _ = await bot.wait_for("reaction_add", timeout=60.0, check=check)
            except asyncio.TimeoutError:
                break
            
            if str(reaction.emoji) == "⬅️" and page_index > 0:
                page_index -= 1
            elif str(reaction.emoji) == "➡️" and page_index < len(pages) - 1:
                page_index += 1
                
            await message.edit(embed=create_page_embed(pages[page_index]))
            await message.remove_reaction(reaction, ctx.author)
            embed.set_footer(text=f"**Page {page_index + 1}/{len(pages)}** | Use `,lootbox` or `,shop` to get more items.")
            await message.edit(embed=embed)

@bot.command()
async def money(ctx, user: discord.Member = None):
    """
    `Check your balance or someone else's balance
    Usage: ,money [user]`
    """
    if user is None:
        user = ctx.author

    db_user, _ = User.get_or_create(user_id=user.id, defaults={'username': user.name, 'guild_id': ctx.guild.id})
    formatted_money = "{:,}".format(db_user.money)
    embed_color = discord.Color.green() if db_user.money >= 0 else discord.Color.red()
    embed = discord.Embed(description=f"{user.mention} has `{formatted_money}` ⛃", color=embed_color)
    await ctx.reply(embed=embed)

# Give command
@bot.command()
async def give(ctx, member: discord.Member, amount: int):
    """
    `Give someone money
    Usage: ,give [member] [amount]` 
    """
    if amount < 0:
        embed = discord.Embed(description="You can't give a negative amount of ⛃!", color=discord.Color.red())
        await ctx.reply(embed=embed)
    elif amount == 0:
        embed = discord.Embed(description="You can't give zero ⛃!", color=discord.Color.red())
        await ctx.reply(embed=embed)
    else:
        user, _ = User.get_or_create(user_id=ctx.author.id, defaults={'username': ctx.author.name, 'guild_id': ctx.guild.id})
        if user.money < amount:
            embed = discord.Embed(description="You don't have enough ⛃ to give!", color=discord.Color.red())
            await ctx.reply(embed=embed)
        else:
            target_user, _ = User.get_or_create(user_id=member.id, defaults={'username': member.name, 'guild_id': ctx.guild.id})
            target_user.money += amount
            user.money -= amount
            user.save()
            target_user.save()
            embed = discord.Embed(description=f"You gave {member.mention} `{amount} ⛃`!", color=discord.Color.green())
            await ctx.reply(embed=embed)

# Set command
@bot.command(hidden=True)
@commands.is_owner()
async def set(ctx, member: discord.Member, amount: int):
    if amount < 0:
        embed = discord.Embed(
            description="You can't set a negative amount of money!",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    user, _ = User.get_or_create(user_id=member.id, defaults={'username': member.name, 'guild_id': ctx.guild.id})
    user.money = amount
    user.save()

    # Create an embed with the user's new balance
    embed = discord.Embed(
        title="Balance Updated",
        description=f"{member.mention}'s new balance is: `{amount}` ⛃",
        color=discord.Color.green()  # You can customize the color
    )

    # Send the embed as a reply
    await ctx.reply(embed=embed)

# Custom JSON encoder to handle datetime objects
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

# Function to fetch user data and update user_data.json
def update_user_data():
    users = User.select()
    user_data = {}

    for user in users:
        user_dict = model_to_dict(user)
        # Convert datetime fields to ISO format for serialization
        user_dict['last_daily'] = user_dict['last_daily'].isoformat()
        user_dict['last_weekly'] = user_dict['last_weekly'].isoformat()
        user_dict['last_monthly'] = user_dict['last_monthly'].isoformat()
        user_data[user.user_id] = user_dict

    with open('user_data.json', 'w') as file:
        json.dump(user_data, file, indent=4, cls=CustomJSONEncoder)

# Function to load user data from user_data.json
def load_user_data():
    try:
        with open('user_data.json', 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

# Command to display the top users with the most money
@bot.command(aliases=["top"])
async def leaderboard(ctx):
    """
    `Displays the top users with the most money
    Usage: ,top`
    """
    update_user_data()
    user_data = load_user_data()

    # Sort users by money in descending order
    sorted_users = sorted(user_data.values(), key=lambda x: x['money'], reverse=True)

    # Create embed for displaying top users
    embed = discord.Embed(title="**Top Users with Most Money** 💸", color=discord.Color.gold())
    for user in sorted_users[:5]:  # Display top 5 users
        money_with_commas = f"{user['money']:,}"  # Using f-string

        embed.add_field(name=user['username'], value=f"**Money:** `{money_with_commas}` ⛃", inline=False)

    # Send embed
    await ctx.send(embed=embed)

class Card:
    suits = ['♠️', '♥️', '♦️', '♣️']
    values = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
    emojis = {
        'A♠️': '🂡', '2♠️': '🂢', '3♠️': '🂣', '4♠️': '🂤', '5♠️': '🂥', '6♠️': '🂦', '7♠️': '🂧', '8♠️': '🂨', '9♠️': '🂩', '10♠️': '🂪', 'J♠️': '🂫', 'Q♠️': '🂭', 'K♠️': '🂮',
        'A♥️': '🂱', '2♥️': '🂲', '3♥️': '🂳', '4♥️': '🂴', '5♥️': '🂵', '6♥️': '🂶', '7♥️': '🂷', '8♥️': '🂸', '9♥️': '🂹', '10♥️': '🂺', 'J♥️': '🂻', 'Q♥️': '🂽', 'K♥️': '🂾',
        'A♦️': '🃁', '2♦️': '🃂', '3♦️': '🃃', '4♦️': '🃄', '5♦️': '🃅', '6♦️': '🃆', '7♦️': '🃇', '8♦️': '🃈', '9♦️': '🃉', '10♦️': '🃊', 'J♦️': '🃋', 'Q♦️': '🃍', 'K♦️': '🃎',
        'A♣️': '🃑', '2♣️': '🃒', '3♣️': '🃓', '4♣️': '🃔', '5♣️': '🃕', '6♣️': '🃖', '7♣️': '🃗', '8♣️': '🃘', '9♣️': '🃙', '10♣️': '🃚', 'J♣️': '🃛', 'Q♣️': '🃝', 'K♣️': '🃞'
    }

    def __init__(self, suit, value):
        self.suit = suit
        self.value = value

    def __str__(self):
        return f"{self.value}{self.suit}"

    def emoji(self):
        return self.emojis[str(self)]


class Deck:
    def __init__(self):
        self.cards = [Card(suit, value) for suit in Card.suits for value in Card.values]
        random.shuffle(self.cards)

    def deal(self):
        return self.cards.pop()


class Player:
    def __init__(self):
        self.hand = []
        self.split_hand = []
        self.bet = 0
        self.split_bet = 0

    def add_card(self, card, split=False):
        if split:
            self.split_hand.append(card)
        else:
            self.hand.append(card)

    def hand_value(self, split=False):
        hand = self.split_hand if split else self.hand
        value = 0
        aces = 0
        for card in hand:
            if card.value in ['J', 'Q', 'K']:
                value += 10
            elif card.value == 'A':
                aces += 1
                value += 11
            else:
                value += int(card.value)
        while value > 21 and aces:
            value -= 10
            aces -= 1
        return value

    def is_blackjack(self, split=False):
        hand = self.split_hand if split else self.hand
        return self.hand_value(split) == 21 and len(hand) == 2

    def is_busted(self, split=False):
        return self.hand_value(split) > 21


class BlackJackButtons(discord.ui.View):
    def __init__(self, player, deck, dealer, user):
        super().__init__(timeout=None)
        self.player = player
        self.deck = deck
        self.dealer = dealer
        self.user = user

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.add_card(self.deck.deal())
        await self.check_game_state(interaction)
        if not self.player.is_busted():
            for child in self.children:
                child.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            except discord.errors.InteractionResponded:
                pass

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.dealer_turn(interaction)

    @discord.ui.button(label="Split", style=discord.ButtonStyle.success, disabled=True)
    async def split(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.player.hand[0].value == self.player.hand[1].value:
            self.player.split_hand.append(self.player.hand.pop())
            self.player.split_bet = self.player.bet
            self.player.add_card(self.deck.deal(), split=True)
            self.player.add_card(self.deck.deal())
            await self.check_game_state(interaction, split=True)

    @discord.ui.button(label="Double", style=discord.ButtonStyle.danger, disabled=True)
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.bet *= 2
        self.player.add_card(self.deck.deal())
        await self.dealer_turn(interaction)

    async def check_game_state(self, interaction: discord.Interaction, split=False):
        player_hand_value = self.player.hand_value(split)
        if self.player.is_blackjack(split):
            await interaction.response.send_message(f"Blackjack! {self.player.hand_value(split)} points.", embed=self.create_embed())
        elif self.player.is_busted(split):
            await interaction.response.send_message(f"Busted! {self.player.hand_value(split)} points.", embed=self.create_embed())
        else:
            await interaction.response.send_message(f"Current hand: {self.player.hand_value(split)} points.", embed=self.create_embed())

    async def dealer_turn(self, interaction: discord.Interaction):
        while self.dealer.hand_value() < 17:
            self.dealer.add_card(self.deck.deal())
        dealer_value = self.dealer.hand_value()
        player_value = self.player.hand_value()
        if dealer_value > 21 or dealer_value < player_value <= 21:
            winnings = self.player.bet * 1.5 if self.player.is_blackjack() else self.player.bet
            self.user.money += winnings
            self.user.save()
            await interaction.response.send_message(f"You win! Dealer: {dealer_value}, You: {player_value}.", embed=self.create_embed())
        elif dealer_value == player_value:
            self.user.money += self.player.bet
            self.user.save()
            await interaction.response.send_message(f"It's a tie! Dealer: {dealer_value}, You: {player_value}.", embed=self.create_embed())
        else:
            await interaction.response.send_message(f"You lose! Dealer: {dealer_value}, You: {player_value}.", embed=self.create_embed())

    def create_embed(self):
        embed = discord.Embed(title="Blackjack", color=discord.Color.green())
        player_hand = " ".join(card.emoji() for card in self.player.hand)
        dealer_hand = " ".join(card.emoji() for card in self.dealer.hand)
        embed.add_field(name="Your Hand", value=f"{player_hand} ({self.player.hand_value()})")
        embed.add_field(name="Dealer's Hand", value=f"{dealer_hand} ({self.dealer.hand_value()})")
        embed.add_field(name="Balance", value=f"${self.user.money}")
        return embed
    
@bot.command(name="blackjack", aliases=["bj"])
async def blackjack(ctx, *, bet_amount: Union[int,float]):
    user = get_or_create_user(ctx.author.id, ctx.author.name)

    if bet_amount <= 0:
        embed = discord.Embed(
            title="Blackjack",
            description="You must bet at `1` ⛃ to play **Blackjack**.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    if user.money <= 0:
        embed = discord.Embed(
            title="Blackjack",
            description="You don't have enough money to play blackjack.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    deck = Deck()
    player = Player()
    dealer = Player()

    player.add_card(deck.deal())
    player.add_card(deck.deal())
    dealer.add_card(deck.deal())

    player.bet = bet_amount
    user.money -= player.bet
    user.save()

    view = BlackJackButtons(player, deck, dealer, user)
    view.split.disabled = not (player.hand[0].value == player.hand[1].value)
    view.double.disabled = not (len(player.hand) == 2 and user.money >= player.bet * 2)

    embed = view.create_embed()
    await ctx.send(embed=embed, view=view)

@bot.command()
@commands.cooldown(1, 3, commands.BucketType.user)
async def limbo(ctx, target_multiplier: float = None, bet_amount: Union[int, str, float] = None):
    """
    `Fun interactive limbo game
    Usage: ,limbo <target_multi> [bet_amount]`
    """
    if target_multiplier is None or bet_amount is None:
        embed = discord.Embed(
            title="Limbo Game",
            description="**Please specify the bet amount and target multiplier.**\n\n**Example:** `,limbo` `<target_mult>` `<bet_amount>`",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    user = get_or_create_user(ctx.author.id, ctx.author.name)

    if bet_amount == "all":
        bet_amount = user.money
    else:
        try:
            bet_amount = int(bet_amount)
        except ValueError:
            embed = discord.Embed(
                description="Invalid input. Please enter a valid amount or 'all'.",
                color=discord.Color.blue()
            )
            await ctx.reply(embed=embed)
            return

    if bet_amount > user.money:
        embed = discord.Embed(
            title="Insufficient Funds",
            description="You don't have enough money to place this bet.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    crash_point = 1.4  # Adjust the crash point as needed
    multiplier = 1.11  # Start multiplier at 1.05

    # Define the multiplier options and their probabili.fties
    multiplier_options = [round(1.01 + 0.01 * i, 2) for i in range(10000)]  # Range from 1.01 to 10.00
    multiplier_probabilities = [1 / multiplier for multiplier in multiplier_options]

    outcome = "`Better luck next time.`"
    color = discord.Color.red()

    # Simulate the Limbo game
    while multiplier < crash_point:
        chosen_multiplier = random.choices(multiplier_options, weights=multiplier_probabilities)[0]
        multiplier *= chosen_multiplier

        if multiplier >= target_multiplier:
            outcome = "`Congratulations! You won.`"
            color = discord.Color.green()
            # Calculate the winnings and update the user's balance
            winnings = bet_amount * target_multiplier
            user.money += winnings - bet_amount  # Deduct the initial bet amount
            user.save()  # Save the updated balance
            formatted_winnings = "{:,}".format(winnings - bet_amount)
            break

    # If the multiplier never reaches the target, the user loses
    if multiplier < target_multiplier:
        outcome = "`Better luck next time.`"
        color = discord.Color.red()
        # Set the winnings to negative the bet amount
        winnings = -bet_amount
        user.money += winnings  # Deduct the bet amount
        user.save()  # Save the updated balance
        formatted_winnings = "{:,}".format(winnings)

    # Update formatted_money with the updated balance
    formatted_money = "{:,}".format(user.money)

    embed = discord.Embed(
        title="Limbo Game Result",
        description="Here are the results of your Limbo game:",
        color=color
    )
    embed.add_field(name="Bet Amount", value=f"`{bet_amount}` ⛃", inline=False)
    embed.add_field(name="Target Multiplier", value=f"`{target_multiplier}`x", inline=True)
    embed.add_field(name="Multiplier", value=f"`{multiplier:.2f}`x", inline=True)
    embed.add_field(name="Outcome", value=outcome, inline=False)
    embed.add_field(name="Winnings", value=f"`{formatted_winnings}` ⛃", inline=True)
    embed.add_field(name="Final Balance", value=f"`{formatted_money}` ⛃", inline=True)
    await ctx.reply(embed=embed)

@limbo.error
async def limbo_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        embed = discord.Embed(
            title="Limbo Game",
            description=f"You can play again in **{error.retry_after:.2f}** seconds.",
            color=discord.Color.red()
            )
        await ctx.reply(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="Limbo Game",
            description="**Please specify the bet amount and target multiplier.**\n\n**Example:** `,limbo` `<target_mult>` `<bet_amount>`",
            color=discord.Color.red()
            )
        await ctx.reply(embed=embed)


@bot.command(aliases=['cf'])
async def coinflip(ctx, amount: Union[int, str]):
    """
    `Fun interactive coinflip game
    Usage: ,coinflip <amount>`
    """
    user = get_or_create_user(ctx.author.id, ctx.author.name)
    
    if amount == "all":
        amount = user.money
    else:
        try:
            amount = int(amount)
        except ValueError:
            embed = discord.Embed(
                description="Invalid input. Please enter a valid amount or 'all'.",
                color=discord.Color.blue()
            )
            await ctx.reply(embed=embed)
            return

    if amount <= 0:
        embed = discord.Embed(
            description="Please enter a positive amount to play.",
            color=discord.Color.blue()
        )
        await ctx.reply(embed=embed)
        return

    if user.money < amount:
        embed = discord.Embed(
            description="You don't have enough ⛃ to play this game!",
            color=discord.Color.blue()
        )
        await ctx.reply(embed=embed)
        return

    result = random.choice(["Heads", "Tails"])
    if result == "Heads":
        user.money += amount
        outcome_message = f"You win! It's Heads. \nYour new balance is: `{user.money} ⛃`!"
        color = discord.Color.green()
    else:
        user.money -= amount
        outcome_message = f"You lose! It's Tails. \nYour new balance is: `{user.money} ⛃`!"
        color = discord.Color.red()

    user.save()
    embed = discord.Embed(
        title=result,
        description=outcome_message,
        color=color
    )
    await ctx.reply(embed=embed)

@coinflip.error
async def coinflip_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        embed = discord.Embed(
            description=f"Please wait {error.retry_after:.2f} seconds before trying again!",
            color=discord.Color.blue()
            )
        await ctx.reply(embed=embed)

@bot.command(aliases=['8ball','8b'])
async def _8ball(ctx, *, question):
    """
    `Ask 8ball a question
    Usage: ,8ball [question]`
    """
    responses = ["It is certain.", "It is decidedly so.", "Without a doubt.", "Yes, definitely.",
                 "You may rely on it.", "As I see it, yes.", "Most likely.", "Outlook good.",
                 "Yes.", "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
                 "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
                 "Don't count on it.", "My sources say no.", "Outlook not so good.", "Very doubtful."]
    response = random.choice(responses)
    
    embed = discord.Embed(title="8ball", description=f"Question: {question}\n\nAnswer: {response}", color=0x7289DA)
    await ctx.reply(embed=embed)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, *, reason="No reason provided"):
    """
    `Mute a member
    Usage: ,mute [member] [reason]`
    """
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")

    if not mute_role:
        # Create a new muted role if it doesn't exist
        try:
            mute_role = await ctx.guild.create_role(name="Muted")
            for channel in ctx.guild.channels:
                await channel.set_permissions(mute_role, send_messages=False, speak=False)
        except discord.Forbidden:
            embed = discord.Embed(
                title="Error",
                description="I don't have permission to create roles.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

    if mute_role in member.roles:
        embed = discord.Embed(
            title="Error",
            description="This member is already muted.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    try:
        await member.add_roles(mute_role, reason=reason)
        embed = discord.Embed(
            title="Member Muted",
            description=f"{member.mention} has been muted.",
            color=discord.Color.green()
        )
        embed.add_field(name="Reason", value=reason)
        await ctx.send(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(
            title="Error",
            description="I don't have permission to add roles to this member.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    """
    `Unmutes a member.
    Usage: ,unmute [member]`
    """
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")

    if not mute_role or mute_role not in member.roles:
        embed = discord.Embed(
            title="Error",
            description="This member is not muted.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    await member.remove_roles(mute_role)
    embed = discord.Embed(
        title="Member Unmuted",
        description=f"{member.mention} has been unmuted.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx, channel: discord.TextChannel = None):
    """
    `Locks the specified channel or the current channel if none is provided.
    Usage: ,lock [channel]`
    """
    if channel is None:
        channel = ctx.channel

    await channel.set_permissions(ctx.guild.default_role, send_messages=False)
    embed = discord.Embed(
        title="Channel Locked",
        description=f"Channel {channel.mention} has been locked by {ctx.author.mention}",
        color=0x7289DA
    )
    await ctx.reply(embed=embed)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx, channel: discord.TextChannel = None):
    """
    `Unlocks the specified channel or the current channel if none is provided.
    Usage: ,unlock [channel]`
    """
    if channel is None:
        channel = ctx.channel

    await channel.set_permissions(ctx.guild.default_role, send_messages=True)
    embed = discord.Embed(
        title="Unlocked",
        description=f"{channel.mention} has been unlocked.",
        color=0x7289DA
    )
    await ctx.reply(embed=embed)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int, channel: discord.TextChannel = None):
    """
    `Sets the slowmode in the current channel or specified channel.
    Usage: ,slowmode [seconds] [channel]`
    """
    if channel is None:
        channel = ctx.channel

    await channel.edit(slowmode_delay=seconds)
    embed = discord.Embed(
        title="Slowmode", description=f"Slowmode has been set to {seconds} seconds in {channel.mention}",
        color=0x7289DA)
    await ctx.reply(embed=embed)

# Command: Role
@bot.command()
@commands.has_permissions(manage_roles=True)
async def role(ctx, member: discord.Member, role: discord.Role):
    """
    `Set a role for a user
    Usage: ,role <user> [role]`
    """
    await member.add_roles(role)
    
    embed = discord.Embed(title="Role Assignment", description=f"{member.mention} has been given the {role.name} role.", color=0x7289DA)
    await ctx.reply(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int, member: discord.Member = None):
    """
    `Purge messages in the channel
    Usage: ,purge <amount> [user]`
    """
    try:
        if member:
            await ctx.channel.purge(limit=amount + 1, check=lambda m: m.author == member)
        else:
            await ctx.channel.purge(limit=amount + 1)

        embed = discord.Embed(
            description=f"Successfully purged {amount} messages" + (f" from {member.mention}" if member else ""),
            color=0x7289DA
        )
        await ctx.reply(embed=embed, delete_after=5)

    except discord.Forbidden:
        await ctx.reply("I don't have permission to purge messages.")
    except discord.HTTPException:
        await ctx.reply("Failed to purge messages. An error occurred.")

def load_reports():
    try:
        with open('warns.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {'users': []}

def save_reports(report):
    with open('warns.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=4)

report = load_reports()

@bot.command(pass_context=True)
@commands.has_permissions(manage_roles=True, ban_members=True)
async def warn(ctx, user: discord.User, *, reason: str = None):
    """
    `Warn a user
    Usage: ,warn <user> [reason]`
    """
    if not reason:
        embed = discord.Embed(
            title="Warning",
            description="Please provide a reason.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    for current_user in report['users']:
        if current_user['id'] == user.id:
            current_user['reasons'].append(reason)
            break
    else:
        report['users'].append({
            'id': user.id,
            'name': user.name,
            'reasons': [reason]
        })
    
    save_reports(report)
    embed = discord.Embed(
        title="Warning Issued",
        description=f"{user.name} has been warned for: {reason}",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed)

@bot.command(pass_context=True)
async def warns(ctx, user: discord.User):
    """
    `View a user's warnings
    Usage: ,warns <user>`
    """
    for current_user in report['users']:
        if user.id == current_user['id']:
            reasons = '\n'.join([f"{i+1}. {r}" for i, r in enumerate(current_user['reasons'])])
            embed = discord.Embed(
                title="User Warnings",
                description=f"{user.name} has been reported {len(current_user['reasons'])} times:\n\n`{reasons}`",
                color=discord.Color.gold()
            )
            await ctx.send(embed=embed)
            break
    else:
        embed = discord.Embed(
            title="No Warnings",
            description=f"{user.name} has never been reported.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
@bot.command()
@commands.has_permissions(manage_nicknames=True)
async def nick(ctx, member: discord.Member, new_nick: str):
    """
    `Change user nickname
    Usage: ,nick [member] <new_nick>`
    """
    try:
        await member.edit(nick=new_nick)
        embed = discord.Embed(
            title="Nickname Changed",
            description=f"Nickname of {member.mention} has been changed to `{new_nick}`",
            color=discord.Color.green()
        )
        await ctx.reply(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(
            title="Error",
            description="I don't have permission to change that user's nickname.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
    except discord.HTTPException:
        embed = discord.Embed(
            title="Error",
            description="Failed to change the nickname. Please try again later.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    """
    `Kick a member from the server
    Usage: ,kick <member> [reason]`
    """
    await member.kick(reason=reason)
    
    embed = discord.Embed(title="Kick", description=f"{member.mention} has been kicked.", color=0x7289DA)
    await ctx.reply(embed=embed)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def ban(ctx, user: discord.User, *, reason=None):
    """
    `Ban a user from the server
    Usage: ,ban <user> [reason]`
    """
    try:
        await ctx.guild.ban(user, reason=reason)
        embed = discord.Embed(
            title="User Banned",
            description=f"{user.mention} has been banned.",
            color=discord.Color.red()
        )
        embed.add_field(name="Reason", value=reason or "No reason provided")
        await ctx.reply(embed=embed)

    except discord.Forbidden:
        embed = discord.Embed(
            title="Error",
            description="I don't have the permissions to ban users.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)

@bot.command()
async def unban(ctx, user_id: int):
    """
    `Revoke a members ban from the server
    Usage: ,unban <user_id>`
    """
    try:
        user = await bot.fetch_user(user_id)

        await ctx.guild.unban(user)
        await ctx.reply(f"`Successfully unbanned` **{user.name}** ({user.id})")
    except discord.NotFound:
        embed = discord.Embed(
            title="Error",
            description="User not found",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(
            title="Error",
            description="I don't have the permissions to unban users.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)


@unban.error
async def unban_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.reply("`Invalid user ID. Please provide a valid user ID.`")

@bot.command()
async def info(ctx, user: discord.Member = None):
    """
    `Get user information.
    Usage: ,info [user]`
    """
    try:
        if user is None:
            user = ctx.author
        
        # Create an embed for user information
        embed = discord.Embed(title="**User Information**", color=0x7289DA)
        
        # Add user's avatar as thumbnail if available
        if isinstance(user, discord.Member) and user.avatar:
            embed.set_thumbnail(url=user.avatar.url)
        elif isinstance(user, discord.User) and user.default_avatar:
            embed.set_thumbnail(url=user.default_avatar.url)
        embed.add_field(name="**User ID**", value=f"`{user.id}`", inline=True)
        embed.add_field(name="**Account Creation Date**", value=f"{user.created_at.strftime('%Y-%m-%d %H:%M:%S')}", inline=False) 
        if isinstance(user, discord.Member): embed.add_field(name="**Join Date**", value=f"{user.joined_at.strftime('%Y-%m-%d %H:%M:%S')}", inline=False)

        # Add user's roles
        roles = [role.name for role in user.roles if role != ctx.guild.default_role]
        if roles:
            embed.add_field(name="**Roles**", value=", ".join(roles), inline=False)
        else:
            embed.add_field(name="**Roles**", value="`No roles`", inline=False)

        # Add user's status and activity
        embed.add_field(name="**Status**", value=f"`{user.status}`", inline=True)
        if isinstance(user, discord.Member) and user.activity:
            embed.add_field(name="**Activity**", value=f"`{user.activity.name}`", inline=True)

        if isinstance(user, discord.User):
            embed.add_field(name="**Bot**", value=f"`{user.bot}`", inline=True)
        await ctx.reply(embed=embed)
    
    except Exception as e:
        print(f"An error occurred: {e}")

@bot.command()
async def dick(ctx, user: discord.Member = None):
    """
    `How big someones dick is
    Usage: ,dick <user>`
    """
    if user is None:
        user = ctx.author
    options = ['0.0001', '0.5', '1', '2', '3','4','5','100','0.69','169']
    emojis = ['🤣','😳','👌','😜']
    random_option = random.choice(options)
    random_emoji = random.choice(emojis)
    random_footer = f'*such a smol dick you have.. hehe*'
    embed = discord.Embed(
        title='Dick Meter',
        description=f'🍆 {user.mention} dick is {random_option} inches! {random_emoji}',
        color=0x00FF00
    )
    embed.set_footer(text=random_footer)
    await ctx.reply(embed=embed)

@bot.command()
async def gay(ctx, user: discord.Member = None):
    """
    `Check gay meter of a user
    Usage: ,gay <user>`
    """
    if user is None:
        user = ctx.author
    gay_percent = random.randint(0, 100)
    embed = discord.Embed(
        title='Gay Meter',
        description=f'{user.mention} is {gay_percent}% gay 🏳️‍🌈',
        color=0xFF69B4
    )
    embed.set_footer(text=f"Command authored by: {ctx.author}")
    await ctx.reply(embed=embed)

bot.start_time = datetime.datetime.utcnow()

# Function to calculate uptime
def get_uptime():
    delta = datetime.datetime.utcnow() - bot.start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days} days, {hours} hours, {minutes} minutes, {seconds} seconds"

# Uptime command
@bot.command()
async def uptime(ctx):
    """
    `Checks current uptime of bot
    Usage: ,uptime`
    """
    embed = discord.Embed(title="Bot Uptime", color=0x7289DA)
    embed.add_field(name="Uptime", value=get_uptime(), inline=False)
    embed.set_footer(text="Powered by retro bot")
    await ctx.reply(embed=embed)

async def fetch_image(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data

@bot.command()
async def cat(ctx):
    """
    `Shows a random cat image
    Usage: ,cat`
    """
    cat_url = 'https://api.thecatapi.com/v1/images/search'
    cat_data = await fetch_image(cat_url)
    cat_image_url = cat_data[0]['url']

    embed = discord.Embed(
        title="Random Cat Image",
        color=0xFFA500  # Orange color
    )
    embed.set_image(url=cat_image_url)
    await ctx.reply(embed=embed)

@bot.command()
async def dog(ctx):
    """
    `Shows a random dog image
    Usage: ,dog`
    """
    dog_url = 'https://api.thedogapi.com/v1/images/search'
    dog_data = await fetch_image(dog_url)
    dog_image_url = dog_data[0]['url']

    embed = discord.Embed(
        title="Random Dog Image",
        color=0x00FF00  # Green color
    )
    embed.set_image(url=dog_image_url)
    await ctx.reply(embed=embed)

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)  # 1 use per 60 seconds per user
async def shia(ctx):
    """
    `Shows an image of amir
    Usage: ,shia`
    """
    shia_folder = 'shia'  # Assuming 'shia' is the folder containing images
    shia_files = os.listdir(shia_folder)
    random_image = random.choice(shia_files)
    file_path = os.path.join(shia_folder, random_image)
    file = discord.File(file_path)
    embed = discord.Embed(description=f"{ctx.author.mention} summoned the cthulu god")
    embed.set_image(url=f"attachment://{random_image}")
    await ctx.reply(embed=embed, file=file)

# Event to handle cooldown errors
@shia.error
async def shia_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        embed = discord.Embed(
            title="Error",
            description=f"Please wait `{error.retry_after:.2f}` seconds to use this command again",
            color=0xFF0000  # Red color
        )
        await ctx.reply(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            description="Please provide all required arguments for this command.",
            color=0xFF0000  # Red color
        )
        await ctx.reply(embed=embed)

    elif isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            description="You do not have permission to use this command",
            color=0xFF0000  # Red color
        )
        await ctx.reply(embed=embed)
    elif isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            description="Invalid command. Please check the command name and try again.",
            color=0xFF0000  # Red color
        )
        await ctx.reply(embed=embed)

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)
async def eth(ctx):
    """
    `Get the current price of Ethereum (ETH).
    Usage: ,eth`
    """
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd")
        eth_price = response.json()["ethereum"]["usd"]
        embed = discord.Embed(
            title="Ethereum Price",
            description=f"The current price of Ethereum is `${eth_price}`",
            color=0x00FF00  # Green color
        )
        await ctx.reply(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            description=f"An error occurred while fetching the Ethereum price: {e}",
            color=0xFF0000  # Red color
        )

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)
async def ltc(ctx):
    """
    `Get the current price of Litecoin (LTC).
    Usage: ,ltc`
    """
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd")
        ltc_price = response.json()["litecoin"]["usd"]
        embed = discord.Embed(
            title="Litecoin Price",
            description=f"The current price of Litecoin is `${ltc_price}`",
            color=0xFFFFFF  # White Color
        )
        await ctx.reply(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            description=f"An error occurred while fetching the Litecoin price: {e}",
            color=0xFF0000  # Red color
        )

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)
async def btc(ctx):
    """
    `Get the current price of Bitcoin (BTC).
    Usage: ,btc`
    """
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
        btc_price = response.json()["bitcoin"]["usd"]
        embed = discord.Embed(
            title="Bitcoin Price",
            description=f"The current price of Bitcoin is `${btc_price}`",
            color=0xCFB53B  # Green color
        )
        await ctx.reply(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            description=f"An error occurred while fetching the Bitcoin price: {e}",
            color=0xFF0000  # Red color
            )

@btc.error
@eth.error
@ltc.error
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        embed = discord.Embed(
            description=f"Please wait {error.retry_after:.2f} seconds before trying again.",
            color=0xFF0000  # Red color
        )
        await ctx.reply(embed=embed)

@bot.command()
async def remindme(ctx, reminder_time, *, message):
    """
    `Remind you to do something at a later time.
    Usage: !remindme <time> <message>
    Example: ,remindme 1m Take a break`
    """
    time_pattern = re.compile(r"^(?P<minutes>\d+m)?(?P<seconds>\d+s)?$")
    match = time_pattern.match(reminder_time)
    if match:
        minutes = match.group('minutes')
        seconds = match.group('seconds')
        
        total_seconds = 0
        if minutes:
            total_seconds += int(minutes[:-1]) * 60
        if seconds:
            total_seconds += int(seconds[:-1])
        if total_seconds <= 0:
            await ctx.reply("Invalid reminder time, please provide a future time.")
            return
        
        due_time = datetime.datetime.now() + datetime.timedelta(seconds=total_seconds)
        due_time_str = due_time.strftime('%Y-%m-%d %H:%M:%S')
    else:
        try:
            reminder_time = datetime.datetime.strptime(reminder_time, '%Y-%m-%d %H:%M')
            now = datetime.datetime.now()
            delta = (reminder_time - now).total_seconds()
            if delta <= 0:
                await ctx.reply("Invalid reminder time, please provide a future time.")
                return
            total_seconds = delta
            due_time_str = reminder_time.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            await ctx.reply("Invalid time format. Use relative time (e.g., 1m, 1h30m) or absolute time (YYYY-MM-DD HH:MM).")
            return
        
    await ctx.message.delete()
    
    embed = discord.Embed(
        title="Reminder Set!",
        description=f"Reminder set for `{due_time_str}`.\nMessage: `{message}`",
        color=0x00FF00  # Green color
    )
    
    await ctx.reply(embed=embed)
    await asyncio.sleep(total_seconds)
    
    reminder_embed = discord.Embed(
        title="Reminder!",
        description=f"{ctx.author.mention}, you asked to be reminded: `{message}`",
        color=0xFF0000  # Red color
    )
    
    await ctx.reply(embed=reminder_embed)

@bot.command()
async def afk(ctx, *, message=None):
    """
    `Sets your AFK status with an optional message. 
    Usage: ,afk [optional message]`
    """
    if message is None:
        message = "I'm away from my keyboard. I'll be back soon."

    user, created = User.get_or_create(user_id=ctx.author.id, defaults={'username': ctx.author.name})
    user.is_afk = True
    user.afk_message = message
    user.save()

    embed = discord.Embed(
        title="AFK",
        description=f"{ctx.author.mention} is now AFK.\nMessage: {message}",
        color=0x00FF00  # Green color
    )
    await ctx.reply(embed=embed)

@bot.command()
async def afkoff(ctx):
    """
    `Turns off your AFK status. 
    Usage: ,afkoff`
    """
    try:
        user = User.get(User.user_id == ctx.author.id)
        user.is_afk = False
        user.afk_message = ''
        user.save()

        embed = discord.Embed(
            title="AFK",
            description=f"{ctx.author.mention} is no longer AFK.",
            color=0x00FF00  # Green color
        )
        await ctx.reply(embed=embed)
    except User.DoesNotExist:
        embed = discord.Embed(
            title="AFK",
            description=f"{ctx.author.mention}, you are not currently AFK.",
            color=0xFF0000  # Red color
        )
        await ctx.reply(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Check if any mentioned user is AFK
    for mentioned in message.mentions:
        try:
            user = User.get(User.user_id == mentioned.id)
            if user.is_afk:
                afk_message = user.afk_message
                embed = discord.Embed(
                    title="AFK Notice",
                    description=f"{mentioned.mention} is currently AFK.\nMessage: {afk_message}",
                    color=0xFFFF00  # Yellow color
                )
                await message.channel.send(embed=embed)
        except User.DoesNotExist:
            continue

    await bot.process_commands(message)

@bot.event
async def on_message(message):
    if message.author.bot:
        return  # Ignore messages from bots

    # Check if the author is AFK
    try:
        user = User.get(User.user_id == message.author.id)
        if user.is_afk:
            # Update user's AFK status
            user.is_afk = False
            user.afk_message = ''
            user.save()

            # Send an embed notification indicating that the user is no longer AFK
            embed = discord.Embed(
                title="Welcome Back!",
                description=f"{message.author.mention} is no longer AFK.",
                color=discord.Color.green()
            )
            await message.channel.send(embed=embed)
    except User.DoesNotExist:
        pass  # User not found in the database

    await bot.process_commands(message) 

@bot.command()
async def ping(ctx):
    """
    `Check bot latency
    Usage: ,ping`
    """
    start_time = time.time()
    message = await ctx.send("**Pinging...**")
    end_time = time.time()
    
    websocket_latency = bot.latency * 1000  # Convert to milliseconds
    round_trip_latency = (end_time - start_time) * 1000  # Convert to milliseconds
    
    embed = discord.Embed(
        title="Ping",
        description=(
            f"✔ **WebSocket Latency:** `{websocket_latency:.2f}` ms\n"
            f"✔ **Round-Trip Latency:** `{round_trip_latency:.2f}` ms"
        ),
        color=discord.Color.blue()
    )
    await message.edit(content=None, embed=embed)

@bot.command()
async def serverinfo(ctx):
    """
    `Get server information.
    Usage: ,serverinfo`
    """
    try:
        guild = ctx.guild
        
        # Create an embed for server information
        embed = discord.Embed(title=f"Server Information - {guild.name}", color=0x7289DA)

        # Set server icon as the thumbnail
        embed.set_thumbnail(url=guild.icon.url)

        # Add server information as fields in the embed with improved formatting
        embed.add_field(name="🆔 Server ID", value=guild.id, inline=True)
        embed.add_field(name="👑 Owner", value=guild.owner.mention, inline=True)
        embed.add_field(name="📆 Created At", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)

        embed.add_field(name="\u200b", value="\u200b", inline=False)  # Blank field for spacing

        member_count = f"{guild.member_count} Members"
        text_channels = f"{len(guild.text_channels)} Text Channels"
        voice_channels = f"{len(guild.voice_channels)} Voice Channels"
        embed.add_field(name="👥 Members", value=member_count, inline=True)
        embed.add_field(name="💬 Text", value=text_channels, inline=True)
        embed.add_field(name="🔊 Voice", value=voice_channels, inline=True)

        embed.add_field(name="\u200b", value="\u200b", inline=False)  # Blank field for spacing

        roles = [role.mention for role in guild.roles if role != ctx.guild.default_role]
        roles_formatted = "\n".join([f"{''.join(roles[i:i+3])}" for i in range(0, len(roles), 3)])
        embed.add_field(name="🔒 Roles", value=roles_formatted or "None", inline=False)

        # Set the footer to display the server creation date
        embed.set_footer(text=f"Server ID: {guild.id} • Requested by {ctx.author.display_name} • {ctx.message.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")

        # Send the styled embed as a reply to the command invoker
        await ctx.reply(embed=embed)
    
    except Exception as e:
        print(f"An error occurred: {e}")

api_key = 'c2c305329e054340aff193518241805'

@bot.command()
async def weather(ctx, location):
    """
    `Get the weather forecast for a location.
    Usage: ,weather <location>`
    """
    url = f'http://api.weatherapi.com/v1/current.json?key={api_key}&q={location}&aqi=no'
    
    try:
        response = requests.get(url)
        data = response.json()
        if 'error' in data:
            await ctx.reply("City not found. Please enter a valid city name.")
        else:
            city = data['location']['name']
            weather_desc = data['current']['condition']['text']
            temp = data['current']['temp_c']
            humidity = data['current']['humidity']
            wind_speed = data['current']['wind_kph']
            
            embed = discord.Embed(title=f"Weather in {city}", color=0x3498db)
            embed.add_field(name="Description", value=weather_desc, inline=False)
            embed.add_field(name="Temperature", value=f"{temp}°C", inline=True)
            embed.add_field(name="Humidity", value=f"{humidity}%", inline=True)
            embed.add_field(name="Wind Speed", value=f"{wind_speed} km/h", inline=True)
            
            await ctx.reply(embed=embed)
    except Exception as e:
        print(e)
        await ctx.reply("An error occurred while fetching weather data.")

@bot.command()
async def meme(ctx):
    """
    `Get a random meme
    Usage: ,meme`
    """
    url = "https://api.imgflip.com/get_memes"
    response = requests.get(url).json()

    if response["success"]:
        memes = response["data"]["memes"]
        meme = random.choice(memes)  # Pick a random meme

        # Create an embed
        embed = discord.Embed(
            title=meme["name"],
            description="Here's a random meme for you!",
            color=discord.Color.blue()
        )
        embed.set_image(url=meme["url"])
        embed.set_footer(text=f"Meme ID: {meme['id']}")

        # Send the embed
        await ctx.send(embed=embed)
    else:
        await ctx.send("Couldn't fetch a meme at the moment. Please try again later.")

@tasks.loop(seconds=60)
async def change_activity():
    member_count = sum(1 for _ in bot.get_all_members())
    server_count = len(bot.guilds)

    activities = [
        discord.Game(name=f",help | {member_count} members in {server_count} servers"),
        discord.Game(name=f"with your dad | {member_count} members in {server_count} servers"),
        discord.Game(name=f"with {member_count} souls | ,help"),
        discord.Activity(type=discord.ActivityType.listening, name=f"music in {server_count} servers"),
        discord.Activity(type=discord.ActivityType.watching, name=f"you from {server_count} servers"),
    ]

    new_activity = random.choice(activities)

    await bot.change_presence(activity=new_activity)

@bot.event
async def on_ready():
    update_user_data()
    print(f'Logged in as {bot.user.name}')
    change_activity.start()
    bot.start_time = datetime.datetime.utcnow()
    
bot.run('MTIzODQ1NjM0Njc0ODI2MDQwMw.G5mtO9.b43NCmwWM7UpcUU3zQGmZ3CzFxokW87iHJhH7c')

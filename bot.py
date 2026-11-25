import os
import sqlite3
from datetime import datetime, timedelta
import pytz
import discord
from discord import app_commands
from discord.ext import commands

RIYADH_TZ = pytz.timezone("Asia/Riyadh")
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

XP_CHANNEL_IDS = {
    1479578382252511383,
    1510209024086376459,
    1479578952149373139,
    1479585936298737687,
    1548070949612691476,
}

CHAT_XP_PER_MSG = 3

OLD_SEEDED_ACTIONS = [
    "محفز التولبا يوتيوب",
    "تقنية الإظهار",
    "سبليمنال النوم 3 ساعات",
    "ساعة الاستيقاظ والتخيل",
    "تقنية التظاهر التفصيلي",
    "تقنية الماء",
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def xp_needed_for_next_level(current_level: int) -> int:
    return 150 + (max(1, current_level) * 75)


def level_up_reward_points(new_level: int) -> int:
    if new_level < 10:
        pts = 10
    elif new_level < 30:
        pts = 20
    elif new_level < 50:
        pts = 35
    else:
        pts = 50

    if new_level % 10 == 0:
        pts += 40
    return pts


def format_level_up_message(member: discord.abc.User, new_level: int, bonus_points: int) -> str:
    if new_level % 10 == 0:
        return (
            f"إنجاز أسطوري! {member.mention} وصل إلى **اللفل {new_level}**! "
            f"تفاعلك يضيء **Eternal World** (+{bonus_points} نقطة) ִ🪽་༘࿐"
        )
    return (
        f"مبروك {member.mention}! ارتفع مستواك في الشات إلى **اللفل {new_level}** "
        f"(+{bonus_points} نقطة) ᥫ᭡.ִֶָ𓂃"
    )


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                points INTEGER DEFAULT 0,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                streak INTEGER DEFAULT 0,
                last_streak_date TEXT,
                last_chat_ts REAL DEFAULT 0,
                title TEXT DEFAULT 'عضو',
                multiplier_until REAL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_points (
                event_id INTEGER,
                user_id INTEGER,
                points INTEGER DEFAULT 0,
                PRIMARY KEY (event_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_actions (
                name TEXT PRIMARY KEY,
                points INTEGER DEFAULT 10,
                cooldown INTEGER DEFAULT 60,
                keyword TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS action_cooldowns (
                action_name TEXT,
                user_id INTEGER,
                last_used REAL DEFAULT 0,
                PRIMARY KEY (action_name, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                name TEXT PRIMARY KEY,
                price INTEGER,
                item_type TEXT,
                value TEXT,
                description TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0
            )
        """)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(shop_items)").fetchall()]
        if "description" not in cols:
            conn.execute("ALTER TABLE shop_items ADD COLUMN description TEXT DEFAULT ''")
        if "sort_order" not in cols:
            conn.execute("ALTER TABLE shop_items ADD COLUMN sort_order INTEGER DEFAULT 0")
        defaults = {
            "chat_points": "0",
            "chat_xp": str(CHAT_XP_PER_MSG),
            "chat_cooldown": "0",
            "streak_points": "10",
            "streak_mode": "auto",  # auto = مع الفعالية النشطة وإذا انتهت يرجع للعام | general = دائماً عام
            "yt_points": "15",
            "yt_motivator": "يوكا",
            "shop_seeded": "0",
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        for old_name in OLD_SEEDED_ACTIONS:
            conn.execute("DELETE FROM custom_actions WHERE name = ?", (old_name,))
            conn.execute("DELETE FROM action_cooldowns WHERE action_name = ?", (old_name,))

        if get_setting_with_conn(conn, "shop_seeded") != "1":
            shop_defaults = [
                ("مضاعف 24 ساعة", 300, "multiplier", "1.5", "يضاعف نقاط الأنشطة لمدة 24 ساعة كاملة.", 1),
                ("بطاقة تعويض ستريك", 350, "perk", "تعويض ستريك", "تُستخدم لتعويض ستريك فائت خلال الفعالية.", 2),
                ("تغيير النكنيم / اللقب", 550, "nickname", "تغيير اسم مستعار", "يغيّر البوت نكنيمك في السيرفر فوراً بعد كتابة الاسم.", 3),
                ("أولوية ميزة خاصة", 700, "perk", "طلب ميزة بالسيرفر", "أولوية في اقتراح أو تخصيص ميزة داخل السيرفر.", 4),
                ("رتبة خاصة في السيرفر", 1300, "perk", "رتبة مميزة", "رتبة خاصة تبرز حضورك في Eternal World.", 5),
                ("شارة نخبوية نادرة", 1800, "title", "نخبوي ִ🪽་༘࿐", "جائزة كبرى لأصحاب الاستمرارية العالية.", 6),
            ]
            for item in shop_defaults:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO shop_items (name, price, item_type, value, description, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    item,
                )
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('shop_seeded', '1') ON CONFLICT(key) DO UPDATE SET value = '1'"
            )


def get_setting_with_conn(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def get_setting(key: str) -> str:
    with get_db() as conn:
        return get_setting_with_conn(conn, key)


def set_setting(key: str, value: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_shop_pages(per_page: int = 2) -> list[list[sqlite3.Row]]:
    with get_db() as conn:
        items = conn.execute("SELECT * FROM shop_items ORDER BY sort_order ASC, rowid ASC").fetchall()
    if not items:
        return [[]]
    return [items[i : i + per_page] for i in range(0, len(items), per_page)]


def ensure_user(user_id: int):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))


def get_active_event():
    with get_db() as conn:
        return conn.execute("SELECT * FROM events WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()


def credit_points_only(user_id: int, base_points: int, force_general: bool = False) -> tuple[int, bool]:
    ensure_user(user_id)
    now_ts = datetime.now().timestamp()

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        mult = 1.5 if user["multiplier_until"] and user["multiplier_until"] > now_ts else 1.0
        final_points = max(1, round(base_points * mult)) if base_points > 0 else 0

        active_event = None if force_general else conn.execute(
            "SELECT * FROM events WHERE active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if active_event:
            if final_points > 0:
                conn.execute(
                    """
                    INSERT INTO event_points (event_id, user_id, points)
                    VALUES (?, ?, ?)
                    ON CONFLICT(event_id, user_id) DO UPDATE SET points = points + excluded.points
                    """,
                    (active_event["id"], user_id, final_points),
                )
        else:
            new_points = user["points"] + final_points
            conn.execute("UPDATE users SET points = ? WHERE user_id = ?", (new_points, user_id))

    return final_points, bool(active_event)


def add_points(
    user_id: int,
    base_points: int,
    xp_gain: int = 0,
    guild: discord.Guild | None = None,
    force_general: bool = False,
):
    ensure_user(user_id)
    now_ts = datetime.now().timestamp()
    level_ups: list[tuple[int, int]] = []

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        mult = 1.5 if user["multiplier_until"] and user["multiplier_until"] > now_ts else 1.0
        final_points = max(1, round(base_points * mult)) if base_points > 0 else 0

        current_xp = user["xp"] + max(0, xp_gain)
        current_level = max(1, user["level"])

        while current_xp >= xp_needed_for_next_level(current_level):
            current_xp -= xp_needed_for_next_level(current_level)
            current_level += 1
            lvl_reward = level_up_reward_points(current_level)
            final_points += lvl_reward
            level_ups.append((current_level, lvl_reward))

        active_event = None if force_general else conn.execute(
            "SELECT * FROM events WHERE active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if active_event:
            if final_points > 0:
                conn.execute(
                    """
                    INSERT INTO event_points (event_id, user_id, points)
                    VALUES (?, ?, ?)
                    ON CONFLICT(event_id, user_id) DO UPDATE SET points = points + excluded.points
                    """,
                    (active_event["id"], user_id, final_points),
                )
            conn.execute(
                "UPDATE users SET xp = ?, level = ? WHERE user_id = ?",
                (current_xp, current_level, user_id),
            )
        else:
            new_points = user["points"] + final_points
            conn.execute(
                "UPDATE users SET points = ?, xp = ?, level = ? WHERE user_id = ?",
                (new_points, current_xp, current_level, user_id),
            )

    return final_points, bool(active_event), level_ups, current_level


def is_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.user.guild_permissions.administrator)


def match_member_from_streak_text(guild: discord.Guild, text: str) -> discord.Member | None:
    text_clean = text.strip()
    if not text_clean:
        return None
    for member in guild.members:
        if member.bot:
            continue
        if member.display_name and member.display_name in text_clean:
            return member
        if member.name and member.name in text_clean:
            return member
    return None


async def handle_streak_bot_message(message: discord.Message):
    if not message.guild or not message.embeds:
        return

    author_name = (message.author.name or "").lower()
    display_name = (message.author.display_name or "").lower()
    if "streak" not in author_name and "streak" not in display_name:
        return

    streak_pts = int(get_setting("streak_points") or 10)
    force_general = get_setting("streak_mode") == "general"

    for emb in message.embeds:
        combined = " ".join(filter(None, [emb.title, emb.description]))
        if not combined:
            continue
        if "ضاعت سلسلتك" in combined:
            continue
        if "سجل حضوره اليوم" in combined or "تم توثيق الحضور بنجاح" in combined:
            member = match_member_from_streak_text(message.guild, combined)
            if not member:
                return

            ensure_user(member.id)
            today_str = datetime.now(RIYADH_TZ).strftime("%Y-%m-%d")
            action_key = f"streak_auto_{today_str}"
            now_ts = datetime.now().timestamp()

            with get_db() as conn:
                already = conn.execute(
                    "SELECT last_used FROM action_cooldowns WHERE action_name = ? AND user_id = ?",
                    (action_key, member.id),
                ).fetchone()
                if already:
                    return
                conn.execute(
                    "INSERT OR REPLACE INTO action_cooldowns (action_name, user_id, last_used) VALUES (?, ?, ?)",
                    (action_key, member.id, now_ts),
                )

            earned, in_event = credit_points_only(member.id, streak_pts, force_general=force_general)
            scope = "الفعالية" if in_event else "السيرفر العام"
            await message.channel.send(
                f"🔥 تم رصد ستريك {member.mention} وحصل على **{earned}** نقطة في {scope} ᥫ᭡.ִֶָ𓂃"
            )
            return


class NicknamePurchaseModal(discord.ui.Modal, title="تغيير النكنيم في Eternal World"):
    new_nickname = discord.ui.TextInput(
        label="النكنيم الجديد (حد أقصى 32 حرف)",
        placeholder="اكتب النكنيم اللي حاب يظهر لك في السيرفر...",
        min_length=1,
        max_length=32,
        required=True,
    )

    def __init__(self, item_name: str, price: int):
        super().__init__()
        self.item_name = item_name
        self.price = price

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("هذا الخيار يعمل داخل السيرفر فقط.", ephemeral=True)
            return

        ensure_user(interaction.user.id)
        clean_nick = self.new_nickname.value.strip()

        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()
            if user["points"] < self.price:
                await interaction.response.send_message(
                    f"نقاطكِ العامة الحالية (**{user['points']}**) لا تكفي لشراء **{self.item_name}** ({self.price} نقطة).",
                    ephemeral=True,
                )
                return

            try:
                await interaction.user.edit(nick=clean_nick, reason="شراء تغيير النكنيم من متجر Eternal World")
            except discord.Forbidden:
                await interaction.response.send_message(
                    "تعذّر تغيير النكنيم تلقائياً؛ تأكدي أن رتبة البوت أعلى من رتبتكِ ويملك صلاحية Manage Nicknames.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException:
                await interaction.response.send_message("حدث خطأ أثناء تحديث النكنيم في ديسكورد.", ephemeral=True)
                return

            new_pts = user["points"] - self.price
            conn.execute(
                "UPDATE users SET points = ?, title = ? WHERE user_id = ?",
                (new_pts, clean_nick, interaction.user.id),
            )

        await interaction.response.send_message(
            f"✅ تم خصم **{self.price}** نقطة وتغيير نكنيمك إلى **{clean_nick}** فوراً ᥫ᭡.ִֶָ𓂃 (رصيدك: **{new_pts}**)",
            ephemeral=True,
        )


class BuyItemButton(discord.ui.Button):
    def __init__(self, item_name: str, price: int, item_type: str, item_value: str):
        super().__init__(label=f"شراء: {item_name} ({price}ن)", style=discord.ButtonStyle.success)
        self.item_name = item_name
        self.price = price
        self.item_type = item_type
        self.item_value = item_value

    async def callback(self, interaction: discord.Interaction):
        with get_db() as conn:
            latest = conn.execute("SELECT * FROM shop_items WHERE name = ?", (self.item_name,)).fetchone()
            if not latest:
                await interaction.response.send_message("هذا العنصر لم يعد متوفراً في المتجر.", ephemeral=True)
                return
            current_price = latest["price"]
            item_type = latest["item_type"]
            item_value = latest["value"]

        if item_type == "nickname":
            ensure_user(interaction.user.id)
            with get_db() as conn:
                user = conn.execute("SELECT * FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()
            if user["points"] < current_price:
                await interaction.response.send_message(
                    f"نقاطكِ العامة الحالية (**{user['points']}**) لا تكفي لشراء **{self.item_name}** ({current_price} نقطة).",
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(NicknamePurchaseModal(self.item_name, current_price))
            return

        ensure_user(interaction.user.id)
        now_ts = datetime.now().timestamp()

        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()
            if user["points"] < current_price:
                await interaction.response.send_message(
                    f"نقاطكِ العامة الحالية (**{user['points']}**) لا تكفي لشراء **{self.item_name}** ({current_price} نقطة).",
                    ephemeral=True,
                )
                return

            new_pts = user["points"] - current_price
            if item_type == "multiplier":
                until_ts = max(now_ts, user["multiplier_until"] or 0) + 86400
                conn.execute(
                    "UPDATE users SET points = ?, multiplier_until = ? WHERE user_id = ?",
                    (new_pts, until_ts, interaction.user.id),
                )
                msg = f"✅ تم شراء **مضاعف 1.5x** لمدة 24 ساعة! نقاطكِ المتبقية: **{new_pts}** ᥫ᭡.ִֶָ𓂃"
            elif item_type == "title":
                conn.execute(
                    "UPDATE users SET points = ?, title = ? WHERE user_id = ?",
                    (new_pts, item_value, interaction.user.id),
                )
                msg = f"✅ تم شراء اللقب **{item_value}** وتحديث بروفايلك! نقاطكِ المتبقية: **{new_pts}** ᥫ᭡.ִֶָ𓂃"
            else:
                conn.execute("UPDATE users SET points = ? WHERE user_id = ?", (new_pts, interaction.user.id))
                msg = f"✅ تم شراء **{self.item_name}** بنجاح! نقاطكِ المتبقية: **{new_pts}** ᥫ᭡.ִֶָ𓂃"

        await interaction.response.send_message(msg, ephemeral=True)


def build_catalog_embed(user_id: int, page: int) -> discord.Embed:
    ensure_user(user_id)
    pages = get_shop_pages(2)
    safe_page = max(0, min(page, len(pages) - 1))

    with get_db() as conn:
        u = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    emb = discord.Embed(
        title=f"✦ 𝐄𝐓𝐄𝐑𝐍𝐀𝐋 𝐖𝐎𝐑𝐋𝐃 • صفحة المتجر ({safe_page + 1}/{len(pages)}) ✦",
        description=f"رصيدك العام الحالي: **{u['points']}** نقطة | المستوى: **Level {u['level']}** ᥫ᭡.ִֶָ𓂃",
        color=discord.Color.purple(),
    )
    if not pages[safe_page]:
        emb.add_field(name="المتجر فارغ حالياً", value="لم تتم إضافة جوائز بعد.", inline=False)
    else:
        for row in pages[safe_page]:
            emb.add_field(
                name=f"• {row['name']} — **{row['price']}** نقطة",
                value=row["description"] or "جائزة من متجر Eternal World",
                inline=False,
            )
    emb.set_footer(text="Eternal World Marketplace • اختر زر الشراء للتنفيذ الفوري")
    return emb


class ShopCatalogView(discord.ui.View):
    def __init__(self, user_id: int, page: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.page = page
        self._rebuild_buttons()

    def _rebuild_buttons(self):
        self.clear_items()
        pages = get_shop_pages(2)
        self.page = max(0, min(self.page, len(pages) - 1))

        for row in pages[self.page]:
            self.add_item(BuyItemButton(row["name"], row["price"], row["item_type"], row["value"]))

        prev_btn = discord.ui.Button(label="◀️ السابق", style=discord.ButtonStyle.secondary, disabled=(self.page == 0))
        next_btn = discord.ui.Button(
            label="التالي ▶️",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page >= len(pages) - 1),
        )

        async def on_prev(inter: discord.Interaction):
            if inter.user.id != self.user_id:
                await inter.response.send_message("هذه الصفحة خاصة بمن فتحها.", ephemeral=True)
                return
            self.page = max(0, self.page - 1)
            self._rebuild_buttons()
            await inter.response.edit_message(embed=build_catalog_embed(self.user_id, self.page), view=self)

        async def on_next(inter: discord.Interaction):
            if inter.user.id != self.user_id:
                await inter.response.send_message("هذه الصفحة خاصة بمن فتحها.", ephemeral=True)
                return
            current_pages = get_shop_pages(2)
            self.page = min(len(current_pages) - 1, self.page + 1)
            self._rebuild_buttons()
            await inter.response.edit_message(embed=build_catalog_embed(self.user_id, self.page), view=self)

        prev_btn.callback = on_prev
        next_btn.callback = on_next
        self.add_item(prev_btn)
        self.add_item(next_btn)


class OpenShopView(discord.ui.View):
    def __init__(self, target_user_id: int):
        super().__init__(timeout=180)
        self.target_user_id = target_user_id

    @discord.ui.button(label="🛍️ فتح صفحة المتجر", style=discord.ButtonStyle.primary)
    async def open_shop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShopCatalogView(user_id=interaction.user.id, page=0)
        await interaction.response.send_message(embed=build_catalog_embed(interaction.user.id, 0), view=view, ephemeral=True)


@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print(f"تم تسجيل الدخول كبوت: {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        await handle_streak_bot_message(message)
        return

    if not message.guild:
        return

    ensure_user(message.author.id)
    now_ts = datetime.now().timestamp()

    if message.channel.id in XP_CHANNEL_IDS:
        chat_xp = int(get_setting("chat_xp") or CHAT_XP_PER_MSG)
        chat_pts = int(get_setting("chat_points") or 0)
        chat_cd = int(get_setting("chat_cooldown") or 0)

        with get_db() as conn:
            u = conn.execute("SELECT last_chat_ts FROM users WHERE user_id = ?", (message.author.id,)).fetchone()
            last_chat = u["last_chat_ts"] if u else 0

        if now_ts - last_chat >= chat_cd:
            with get_db() as conn:
                conn.execute("UPDATE users SET last_chat_ts = ? WHERE user_id = ?", (now_ts, message.author.id))
            _, _, level_ups, _ = add_points(message.author.id, chat_pts, chat_xp, message.guild)
            for new_lvl, lvl_pts in level_ups:
                await message.channel.send(format_level_up_message(message.author, new_lvl, lvl_pts))

    with get_db() as conn:
        actions = conn.execute("SELECT * FROM custom_actions WHERE keyword IS NOT NULL AND keyword != ''").fetchall()
        for act in actions:
            if act["keyword"].strip().lower() in message.content.lower():
                cd_row = conn.execute(
                    "SELECT last_used FROM action_cooldowns WHERE action_name = ? AND user_id = ?",
                    (act["name"], message.author.id),
                ).fetchone()
                last_used = cd_row["last_used"] if cd_row else 0
                if now_ts - last_used >= act["cooldown"]:
                    conn.execute(
                        """
                        INSERT INTO action_cooldowns (action_name, user_id, last_used)
                        VALUES (?, ?, ?)
                        ON CONFLICT(action_name, user_id) DO UPDATE SET last_used = excluded.last_used
                        """,
                        (act["name"], message.author.id, now_ts),
                    )
                    earned, in_event, level_ups, _ = add_points(message.author.id, act["points"], 0, message.guild)
                    scope = "الفعالية" if in_event else "السيرفر"
                    await message.channel.send(
                        f"✨ {message.author.mention} نفّذ **{act['name']}** وحصل على **{earned}** نقطة في {scope}!"
                    )
                    for new_lvl, lvl_pts in level_ups:
                        await message.channel.send(format_level_up_message(message.author, new_lvl, lvl_pts))
                break

    await bot.process_commands(message)


# ==================== أوامر الأعضاء العامة ====================

@bot.tree.command(name="streak", description="تسجيل الستريك اليومي بتوقيت الرياض")
async def streak_cmd(interaction: discord.Interaction):
    ensure_user(interaction.user.id)
    now_riyadh = datetime.now(RIYADH_TZ)
    today_str = now_riyadh.strftime("%Y-%m-%d")
    yesterday_str = (now_riyadh - timedelta(days=1)).strftime("%Y-%m-%d")
    streak_pts = int(get_setting("streak_points") or 10)
    force_general = get_setting("streak_mode") == "general"

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()
        if user["last_streak_date"] == today_str:
            await interaction.response.send_message(
                "لقد سجّلتِ ستريك اليوم مسبقاً بتوقيت الرياض! ارجعي بكرة.",
                ephemeral=True,
            )
            return

        if user["last_streak_date"] == yesterday_str:
            new_streak = user["streak"] + 1
        else:
            new_streak = 1

        conn.execute(
            "UPDATE users SET streak = ?, last_streak_date = ? WHERE user_id = ?",
            (new_streak, today_str, interaction.user.id),
        )

    earned, in_event, level_ups, _ = add_points(
        interaction.user.id,
        streak_pts,
        0,
        interaction.guild,
        force_general=force_general,
    )
    scope = "الفعالية النشطة" if in_event else "السيرفر العام"
    await interaction.response.send_message(
        f"🔥 ستريككِ الآن **{new_streak}** يوم! حصلتِ على **{earned}** نقطة ضمن {scope}."
    )
    for new_lvl, lvl_pts in level_ups:
        if interaction.channel:
            await interaction.channel.send(format_level_up_message(interaction.user, new_lvl, lvl_pts))


@bot.tree.command(name="do", description="تنفيذ فعل مخصص")
@app_commands.describe(action_name="اسم الفعل المخصص")
async def do_cmd(interaction: discord.Interaction, action_name: str):
    ensure_user(interaction.user.id)
    now_ts = datetime.now().timestamp()

    with get_db() as conn:
        act = conn.execute("SELECT * FROM custom_actions WHERE name = ?", (action_name.strip(),)).fetchone()
        if not act:
            await interaction.response.send_message(
                "هذا الفعل غير موجود. استخدمي `/list_actions` لعرض الأفعال.",
                ephemeral=True,
            )
            return

        cd = conn.execute(
            "SELECT last_used FROM action_cooldowns WHERE action_name = ? AND user_id = ?",
            (act["name"], interaction.user.id),
        ).fetchone()
        last_used = cd["last_used"] if cd else 0
        rem = int(act["cooldown"] - (now_ts - last_used))
        if rem > 0:
            await interaction.response.send_message(
                f"⏳ انتظري **{rem}** ثانية قبل إعادة تنفيذ **{act['name']}**.",
                ephemeral=True,
            )
            return

        conn.execute(
            """
            INSERT INTO action_cooldowns (action_name, user_id, last_used)
            VALUES (?, ?, ?)
            ON CONFLICT(action_name, user_id) DO UPDATE SET last_used = excluded.last_used
            """,
            (act["name"], interaction.user.id, now_ts),
        )

    earned, in_event, level_ups, _ = add_points(interaction.user.id, act["points"], 0, interaction.guild)
    scope = "الفعالية" if in_event else "السيرفر"
    await interaction.response.send_message(
        f"✅ نفّذتِ **{act['name']}** وحصلتِ على **{earned}** نقطة في {scope}!"
    )
    for new_lvl, lvl_pts in level_ups:
        if interaction.channel:
            await interaction.channel.send(format_level_up_message(interaction.user, new_lvl, lvl_pts))


@bot.tree.command(name="list_actions", description="عرض قائمة الأفعال المخصصة")
async def list_actions_cmd(interaction: discord.Interaction):
    with get_db() as conn:
        actions = conn.execute("SELECT * FROM custom_actions").fetchall()

    if not actions:
        await interaction.response.send_message("لا توجد أفعال مخصصة بعد.")
        return

    lines = ["⚡ **الأفعال المخصصة:**"] + [
        f"• **{a['name']}** — +{a['points']} نقطة | كولداون {a['cooldown']}ث"
        + (f" | كلمة: `{a['keyword']}`" if a["keyword"] else "")
        for a in actions
    ]
    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="shop", description="عرض متجر النقاط التفاعلي")
async def shop_cmd(interaction: discord.Interaction):
    ensure_user(interaction.user.id)
    with get_db() as conn:
        u = conn.execute("SELECT * FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()

    emb = discord.Embed(
        title="✦ 𝐄𝐓𝐄𝐑𝐍𝐀𝐋 𝐖𝐎𝐑𝐋𝐃 • 𝐌𝐀𝐑𝐊𝐄𝐓𝐏𝐋𝐀𝐂𝐄 ✦",
        description=(
            f"مرحباً بك في متجر النقاط الرسمي لـ **Eternal World** ᥫ᭡.ִֶָ𓂃\n\n"
            f"• **رصيدك الحالي:** {u['points']} نقطة\n"
            f"• **المستوى الحالي:** Level {u['level']}\n\n"
            f"اضغط على الزر بالأسفل لفتح صفحة المتجر واستعراض الجوائز."
        ),
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(embed=emb, view=OpenShopView(interaction.user.id))


@bot.tree.command(name="buy", description="شراء عنصر من المتجر")
@app_commands.describe(item_name="اسم العنصر كما يظهر في المتجر")
async def buy_cmd(interaction: discord.Interaction, item_name: str):
    ensure_user(interaction.user.id)
    now_ts = datetime.now().timestamp()

    with get_db() as conn:
        item = conn.execute("SELECT * FROM shop_items WHERE name = ?", (item_name.strip(),)).fetchone()
        if not item:
            await interaction.response.send_message("هذا العنصر غير موجود في المتجر.", ephemeral=True)
            return

        if item["item_type"] == "nickname":
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()
            if user["points"] < item["price"]:
                await interaction.response.send_message(
                    f"نقاطكِ العامة الحالية (**{user['points']}**) لا تكفي لشراء **{item['name']}** ({item['price']} نقطة).",
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(NicknamePurchaseModal(item["name"], item["price"]))
            return

        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()
        if user["points"] < item["price"]:
            await interaction.response.send_message(
                f"نقاطكِ العامة الحالية (**{user['points']}**) لا تكفي لشراء **{item['name']}** ({item['price']} نقطة).",
                ephemeral=True,
            )
            return

        new_pts = user["points"] - item["price"]
        if item["item_type"] == "multiplier":
            until_ts = max(now_ts, user["multiplier_until"] or 0) + 86400
            conn.execute(
                "UPDATE users SET points = ?, multiplier_until = ? WHERE user_id = ?",
                (new_pts, until_ts, interaction.user.id),
            )
            msg = f"✅ تم شراء **مضاعف 1.5x** لمدة 24 ساعة! نقاطكِ المتبقية: **{new_pts}**."
        elif item["item_type"] == "title":
            conn.execute(
                "UPDATE users SET points = ?, title = ? WHERE user_id = ?",
                (new_pts, item["value"], interaction.user.id),
            )
            msg = f"✅ تم شراء اللقب **{item['value']}** وتعيينه في بروفايلكِ! نقاطكِ المتبقية: **{new_pts}**."
        else:
            conn.execute("UPDATE users SET points = ? WHERE user_id = ?", (new_pts, interaction.user.id))
            msg = f"✅ تم شراء **{item['name']}** بنجاح! نقاطكِ المتبقية: **{new_pts}**."

    await interaction.response.send_message(msg)


@bot.tree.command(name="set_title", description="تغيير لقبكِ في البروفايل")
@app_commands.describe(new_title="اللقب الجديد")
async def set_title_cmd(interaction: discord.Interaction, new_title: str):
    ensure_user(interaction.user.id)
    clean_title = new_title.strip()[:40]
    with get_db() as conn:
        conn.execute("UPDATE users SET title = ? WHERE user_id = ?", (clean_title, interaction.user.id))
    await interaction.response.send_message(f"🏷️ تم تحديث لقبكِ إلى: **{clean_title}**")


@bot.tree.command(name="profile", description="عرض البروفايل والنقاط والستريك")
@app_commands.describe(member="عضو معين (اختياري)")
async def profile_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    ensure_user(target.id)
    now_ts = datetime.now().timestamp()

    with get_db() as conn:
        u = conn.execute("SELECT * FROM users WHERE user_id = ?", (target.id,)).fetchone()

    needed_xp = xp_needed_for_next_level(u["level"])
    mult_status = "مفعّل (1.5x)" if (u["multiplier_until"] and u["multiplier_until"] > now_ts) else "غير مفعّل"
    await interaction.response.send_message(
        f"👤 **بروفايل {target.mention}**\n"
        f"• اللقب: **{u['title']}**\n"
        f"• المستوى: **{u['level']}** (XP: {u['xp']}/{needed_xp})\n"
        f"• النقاط العامة: **{u['points']}**\n"
        f"• الستريك: **{u['streak']}** يوم\n"
        f"• المضاعف: **{mult_status}**"
    )


@bot.tree.command(name="event_top", description="عرض متصدري الفعالية الحالية")
async def event_top_cmd(interaction: discord.Interaction):
    active = get_active_event()
    if not active:
        await interaction.response.send_message("لا توجد فعالية نشطة حالياً.", ephemeral=True)
        return

    with get_db() as conn:
        rows = conn.execute(
            "SELECT user_id, points FROM event_points WHERE event_id = ? ORDER BY points DESC LIMIT 10",
            (active["id"],),
        ).fetchall()

    if not rows:
        await interaction.response.send_message(f"لا توجد نقاط مسجلة في فعالية **{active['name']}** بعد.")
        return

    msg = [f"🏆 متصدرو فعالية **{active['name']}**:"] + [
        f"{i}. <@{r['user_id']}> — **{r['points']}** نقطة" for i, r in enumerate(rows, start=1)
    ]
    await interaction.response.send_message("\n".join(msg))


# ==================== أوامر الإدارة فقط (مخفية عن الأعضاء العاديين) ====================

@bot.tree.command(name="set_points_config", description="تعديل إعدادات النقاط في البوت (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    setting="الإعداد المراد تغييره",
    value="القيمة الجديدة (رقم للنقاط/الوقت أو نص لاسم المحفز)",
)
@app_commands.choices(
    setting=[
        app_commands.Choice(name="نقاط الستريك اليومي", value="streak_points"),
        app_commands.Choice(name="نقاط أمر اليوتيوب (/yt)", value="yt_points"),
        app_commands.Choice(name="نقاط رسائل الشات", value="chat_points"),
        app_commands.Choice(name="XP رسائل الشات", value="chat_xp"),
        app_commands.Choice(name="كولداون الشات بالثواني", value="chat_cooldown"),
        app_commands.Choice(name="اسم المحفز الافتراضي لليوتيوب", value="yt_motivator"),
    ]
)
async def set_points_config_cmd(interaction: discord.Interaction, setting: app_commands.Choice[str], value: str):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    key = setting.value
    clean_val = value.strip()
    if key != "yt_motivator":
        if not clean_val.isdigit():
            await interaction.response.send_message("يجب إدخال رقم صحيح 0 أو أكثر لهذا الإعداد.", ephemeral=True)
            return
        if key == "yt_points" and int(clean_val) < 1:
            await interaction.response.send_message("نقاط اليوتيوب يجب أن تكون 1 أو أكثر.", ephemeral=True)
            return

    set_setting(key, clean_val)
    await interaction.response.send_message(f"⚙️ تم تحديث **{setting.name}** إلى **{clean_val}**.", ephemeral=True)


@bot.tree.command(name="set_streak_mode", description="تحديد مكان احتساب نقاط الستريك (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(mode="auto = مع الفعالية النشطة وإذا انتهت يرجع للعام | general = دائماً عام")
@app_commands.choices(
    mode=[
        app_commands.Choice(name="تلقائي (داخل الفعالية أثناء تشغيلها وعام بعد انتهائها)", value="auto"),
        app_commands.Choice(name="عام دائماً (يُحسب في السيرفر العام حتى أثناء الفعالية)", value="general"),
    ]
)
async def set_streak_mode_cmd(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    set_setting("streak_mode", mode.value)
    await interaction.response.send_message(f"🔥 تم ضبط وضع الستريك إلى: **{mode.name}**.", ephemeral=True)


@bot.tree.command(name="give_points", description="منح نقاط لعضو يدوياً (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    member="العضو",
    points="عدد النقاط",
    target_scope="مكان إضافة النقاط",
)
@app_commands.choices(
    target_scope=[
        app_commands.Choice(name="تلقائي (الفعالية النشطة إن وجدت وإلا العام)", value="auto"),
        app_commands.Choice(name="النقاط العامة للسيرفر", value="general"),
    ]
)
async def give_points_cmd(
    interaction: discord.Interaction,
    member: discord.Member,
    points: int,
    target_scope: app_commands.Choice[str] | None = None,
):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return
    if points < 1:
        await interaction.response.send_message("يجب أن تكون النقاط 1 أو أكثر.", ephemeral=True)
        return

    force_general = (target_scope.value == "general") if target_scope else False
    earned, in_event, level_ups, _ = add_points(member.id, points, 0, interaction.guild, force_general=force_general)
    scope = "الفعالية النشطة" if in_event else "السيرفر العام"
    await interaction.response.send_message(f"✅ تم منح {member.mention} **{earned}** نقطة في {scope}.")
    for new_lvl, lvl_pts in level_ups:
        if interaction.channel:
            await interaction.channel.send(format_level_up_message(member, new_lvl, lvl_pts))


@bot.tree.command(name="remove_points", description="خصم نقاط من عضو (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="العضو", points="عدد النقاط المراد خصمها")
async def remove_points_cmd(interaction: discord.Interaction, member: discord.Member, points: int):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return
    if points < 1:
        await interaction.response.send_message("يجب أن تكون النقاط 1 أو أكثر.", ephemeral=True)
        return

    ensure_user(member.id)
    with get_db() as conn:
        active = conn.execute("SELECT * FROM events WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if active:
            row = conn.execute(
                "SELECT points FROM event_points WHERE event_id = ? AND user_id = ?",
                (active["id"], member.id),
            ).fetchone()
            curr = row["points"] if row else 0
            new_pts = max(0, curr - points)
            conn.execute(
                """
                INSERT INTO event_points (event_id, user_id, points)
                VALUES (?, ?, ?)
                ON CONFLICT(event_id, user_id) DO UPDATE SET points = excluded.points
                """,
                (active["id"], member.id, new_pts),
            )
            scope = "الفعالية النشطة"
        else:
            u = conn.execute("SELECT points FROM users WHERE user_id = ?", (member.id,)).fetchone()
            new_pts = max(0, u["points"] - points)
            conn.execute("UPDATE users SET points = ? WHERE user_id = ?", (new_pts, member.id))
            scope = "السيرفر العام"

    await interaction.response.send_message(
        f"➖ تم خصم **{points}** نقطة من {member.mention} في {scope}. الرصيد الحالي: **{new_pts}**."
    )


@bot.tree.command(name="yt", description="منح نقاط مشاركة اليوتيوب (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="العضو المستحق", motivator="اسم المحفز (اختياري)")
async def yt_cmd(interaction: discord.Interaction, member: discord.Member, motivator: str | None = None):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    points = int(get_setting("yt_points") or 15)
    used_motivator = motivator.strip() if motivator else (get_setting("yt_motivator") or "يوكا")
    earned, _, level_ups, _ = add_points(member.id, points, 0, interaction.guild)

    await interaction.response.send_message(
        f"{member.mention} حصلت على {earned} نقطة بسبب مشاركة نتائجك وتحفيز الآخرين بمُحفز {used_motivator} على اليوتيوب!"
    )
    for new_lvl, lvl_pts in level_ups:
        if interaction.channel:
            await interaction.channel.send(format_level_up_message(member, new_lvl, lvl_pts))


@bot.tree.command(name="event_start", description="بدء فعالية فرعية وعزل النقاط لها (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(name="اسم الفعالية")
async def event_start_cmd(interaction: discord.Interaction, name: str):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    with get_db() as conn:
        conn.execute("UPDATE events SET active = 0 WHERE active = 1")
        conn.execute("INSERT INTO events (name, active) VALUES (?, 1)", (name,))

    await interaction.response.send_message(
        f"🎉 بدأت الفعالية الفرعية: **{name}**! جميع النقاط الآن تُحتسب للفعالية فقط حتى إنهائها."
    )


@bot.tree.command(name="event_end", description="إنهاء الفعالية النشطة وعرض المتصدرين (للإدارة)")
@app_commands.default_permissions(administrator=True)
async def event_end_cmd(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    with get_db() as conn:
        active = conn.execute("SELECT * FROM events WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if not active:
            await interaction.response.send_message("لا توجد فعالية نشطة حالياً.", ephemeral=True)
            return

        rows = conn.execute(
            "SELECT user_id, points FROM event_points WHERE event_id = ? ORDER BY points DESC LIMIT 10",
            (active["id"],),
        ).fetchall()
        conn.execute("UPDATE events SET active = 0 WHERE id = ?", (active["id"],))

    lines = [f"🏁 انتهت فعالية **{active['name']}** وعاد الاحتساب (بما فيه الستريك) إلى السيرفر العام!"]
    if rows:
        lines.append("**🏆 متصدرو الفعالية:**")
        for idx, r in enumerate(rows, start=1):
            lines.append(f"{idx}. <@{r['user_id']}> — **{r['points']}** نقطة")
    else:
        lines.append("لم تُسجّل نقاط في هذه الفعالية.")

    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="shop_add", description="إضافة جائزة جديدة إلى المتجر (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    name="اسم الجائزة",
    price="السعر بالنقاط",
    item_type="نوع الجائزة",
    value="قيمة الجائزة (مثل اسم اللقب أو 1.5 للمضاعف)",
    description="وصف الجائزة في المتجر",
)
@app_commands.choices(
    item_type=[
        app_commands.Choice(name="ميزة / جائزة عامة (perk)", value="perk"),
        app_commands.Choice(name="لقب للبروفايل (title)", value="title"),
        app_commands.Choice(name="تغيير نكنيم السيرفر (nickname)", value="nickname"),
        app_commands.Choice(name="مضاعف نقاط 24 ساعة (multiplier)", value="multiplier"),
    ]
)
async def shop_add_cmd(
    interaction: discord.Interaction,
    name: str,
    price: int,
    item_type: app_commands.Choice[str],
    value: str = "ميزة",
    description: str = "جائزة من متجر Eternal World",
):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return
    if price < 1:
        await interaction.response.send_message("يجب أن يكون السعر 1 نقطة أو أكثر.", ephemeral=True)
        return

    clean_name = name.strip()
    with get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM shop_items").fetchone()["m"]
        conn.execute(
            """
            INSERT INTO shop_items (name, price, item_type, value, description, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                price = excluded.price,
                item_type = excluded.item_type,
                value = excluded.value,
                description = excluded.description
            """,
            (clean_name, price, item_type.value, value.strip(), description.strip(), max_order + 1),
        )

    await interaction.response.send_message(
        f"🛍️ تمت إضافة **{clean_name}** إلى المتجر بسعر **{price}** نقطة.",
        ephemeral=True,
    )


@bot.tree.command(name="shop_edit", description="تعديل جائزة موجودة في المتجر (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    item_name="الاسم الحالي للجائزة في المتجر",
    new_price="السعر الجديد بالنقاط (اختياري)",
    new_name="الاسم الجديد للجائزة (اختياري)",
    new_description="الوصف الجديد (اختياري)",
    new_value="القيمة الجديدة مثل نص اللقب (اختياري)",
)
async def shop_edit_cmd(
    interaction: discord.Interaction,
    item_name: str,
    new_price: int | None = None,
    new_name: str | None = None,
    new_description: str | None = None,
    new_value: str | None = None,
):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    with get_db() as conn:
        item = conn.execute("SELECT * FROM shop_items WHERE name = ?", (item_name.strip(),)).fetchone()
        if not item:
            await interaction.response.send_message("هذه الجائزة غير موجودة في المتجر.", ephemeral=True)
            return

        updated_name = new_name.strip() if new_name else item["name"]
        updated_price = new_price if (new_price is not None and new_price >= 1) else item["price"]
        updated_desc = new_description.strip() if new_description is not None else item["description"]
        updated_val = new_value.strip() if new_value is not None else item["value"]

        conn.execute(
            """
            UPDATE shop_items
            SET name = ?, price = ?, description = ?, value = ?
            WHERE name = ?
            """,
            (updated_name, updated_price, updated_desc, updated_val, item["name"]),
        )

    await interaction.response.send_message(
        f"✏️ تم تحديث جائزة المتجر **{updated_name}** (السعر: **{updated_price}** نقطة).",
        ephemeral=True,
    )


@bot.tree.command(name="shop_delete", description="حذف جائزة من المتجر (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(item_name="اسم الجائزة المراد حذفها من المتجر")
async def shop_delete_cmd(interaction: discord.Interaction, item_name: str):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    with get_db() as conn:
        item = conn.execute("SELECT * FROM shop_items WHERE name = ?", (item_name.strip(),)).fetchone()
        if not item:
            await interaction.response.send_message("هذه الجائزة غير موجودة في المتجر.", ephemeral=True)
            return
        conn.execute("DELETE FROM shop_items WHERE name = ?", (item["name"],))

    await interaction.response.send_message(f"🗑️ تم حذف **{item['name']}** من المتجر.", ephemeral=True)


@bot.tree.command(name="add_action", description="إضافة فعل مخصص جديد (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    name="اسم الفعل",
    points="النقاط الممنوحة",
    cooldown="مدة الانتظار بالثواني",
    keyword="كلمة مفتاحية تفعّله تلقائياً في الشات (اختياري)",
)
async def add_action_cmd(
    interaction: discord.Interaction,
    name: str,
    points: int,
    cooldown: int = 60,
    keyword: str | None = None,
):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO custom_actions (name, points, cooldown, keyword)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                points = excluded.points,
                cooldown = excluded.cooldown,
                keyword = excluded.keyword
            """,
            (name.strip(), max(1, points), max(0, cooldown), keyword.strip() if keyword else None),
        )

    await interaction.response.send_message(
        f"⚡ تم حفظ الفعل المخصص **{name}** (+{points} نقطة، كولداون {cooldown}ث).",
        ephemeral=True,
    )


@bot.tree.command(name="edit_action", description="تعديل نقاط أو إعدادات فعل مخصص (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    name="اسم الفعل المخصص",
    points="النقاط الجديدة",
    cooldown="مدة الانتظار الجديدة بالثواني (اختياري)",
    keyword="كلمة مفتاحية جديدة (اختياري)",
)
async def edit_action_cmd(
    interaction: discord.Interaction,
    name: str,
    points: int,
    cooldown: int | None = None,
    keyword: str | None = None,
):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    clean_name = name.strip()
    with get_db() as conn:
        act = conn.execute("SELECT * FROM custom_actions WHERE name = ?", (clean_name,)).fetchone()
        if not act:
            await interaction.response.send_message("هذا الفعل غير موجود.", ephemeral=True)
            return

        new_pts = max(1, points)
        new_cd = max(0, cooldown) if cooldown is not None else act["cooldown"]
        new_kw = keyword.strip() if keyword is not None else act["keyword"]

        conn.execute(
            "UPDATE custom_actions SET points = ?, cooldown = ?, keyword = ? WHERE name = ?",
            (new_pts, new_cd, new_kw, act["name"]),
        )

    await interaction.response.send_message(
        f"✏️ تم تحديث **{act['name']}** إلى **+{new_pts}** نقطة (كولداون {new_cd}ث).",
        ephemeral=True,
    )


@bot.tree.command(name="delete_action", description="حذف فعل مخصص (للإدارة)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(name="اسم الفعل المخصص المراد حذفه")
async def delete_action_cmd(interaction: discord.Interaction, name: str):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    clean_name = name.strip()
    with get_db() as conn:
        act = conn.execute("SELECT * FROM custom_actions WHERE name = ?", (clean_name,)).fetchone()
        if not act:
            await interaction.response.send_message("هذا الفعل غير موجود.", ephemeral=True)
            return
        conn.execute("DELETE FROM custom_actions WHERE name = ?", (act["name"],))
        conn.execute("DELETE FROM action_cooldowns WHERE action_name = ?", (act["name"],))

    await interaction.response.send_message(f"🗑️ تم حذف الفعل المخصص **{act['name']}** بنجاح.", ephemeral=True)


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")

bot.run(token)






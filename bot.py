import os
import sqlite3
from datetime import datetime, timedelta
import pytz
import discord
from discord import app_commands
from discord.ext import commands

RIYADH_TZ = pytz.timezone("Asia/Riyadh")
DB_PATH = "bot_data.db"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
                value TEXT
            )
        """)

        defaults = {
            "chat_points": "5",
            "chat_xp": "15",
            "chat_cooldown": "60",
            "yt_points": "15",
            "yt_motivator": "يوكا"
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        shop_defaults = [
            ("مضاعف 24 ساعة", 100, "multiplier", "1.5"),
            ("لقب مميز", 150, "title", "متميّز")
        ]
        for item in shop_defaults:
            conn.execute("INSERT OR IGNORE INTO shop_items (name, price, item_type, value) VALUES (?, ?, ?, ?)", item)


def get_setting(key: str) -> str:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else ""


def set_setting(key: str, value: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )


def ensure_user(user_id: int):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))


def get_active_event():
    with get_db() as conn:
        return conn.execute("SELECT * FROM events WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()


def add_points(user_id: int, base_points: int, xp_gain: int = 0, guild: discord.Guild | None = None):
    ensure_user(user_id)
    now_ts = datetime.now().timestamp()

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        mult = 1.5 if user["multiplier_until"] and user["multiplier_until"] > now_ts else 1.0
        final_points = max(1, round(base_points * mult))

        new_xp = user["xp"] + xp_gain
        new_level = max(1, (new_xp // 100) + 1)

        active_event = conn.execute("SELECT * FROM events WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if active_event:
            conn.execute("""
                INSERT INTO event_points (event_id, user_id, points)
                VALUES (?, ?, ?)
                ON CONFLICT(event_id, user_id) DO UPDATE SET points = points + excluded.points
            """, (active_event["id"], user_id, final_points))
            conn.execute("UPDATE users SET xp = ?, level = ? WHERE user_id = ?", (new_xp, new_level, user_id))
        else:
            new_points = user["points"] + final_points
            conn.execute(
                "UPDATE users SET points = ?, xp = ?, level = ? WHERE user_id = ?",
                (new_points, new_xp, new_level, user_id)
            )

    return final_points, bool(active_event), (new_level > user["level"]), new_level


def is_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.user.guild_permissions.administrator)


@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print(f"تم تسجيل الدخول كبوت: {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    ensure_user(message.author.id)
    now_ts = datetime.now().timestamp()
    cooldown = int(get_setting("chat_cooldown") or 60)

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (message.author.id,)).fetchone()
        if now_ts - (user["last_chat_ts"] or 0) >= cooldown:
            conn.execute("UPDATE users SET last_chat_ts = ? WHERE user_id = ?", (now_ts, message.author.id))
            pts = int(get_setting("chat_points") or 5)
            xp = int(get_setting("chat_xp") or 15)
            add_points(message.author.id, pts, xp, message.guild)

        # فحص الكلمات المفتاحية للأفعال المخصصة
        actions = conn.execute("SELECT * FROM custom_actions WHERE keyword IS NOT NULL AND keyword != ''").fetchall()
        for act in actions:
            if act["keyword"].strip().lower() in message.content.lower():
                cd_row = conn.execute(
                    "SELECT last_used FROM action_cooldowns WHERE action_name = ? AND user_id = ?",
                    (act["name"], message.author.id)
                ).fetchone()
                last_used = cd_row["last_used"] if cd_row else 0
                if now_ts - last_used >= act["cooldown"]:
                    conn.execute("""
                        INSERT INTO action_cooldowns (action_name, user_id, last_used)
                        VALUES (?, ?, ?)
                        ON CONFLICT(action_name, user_id) DO UPDATE SET last_used = excluded.last_used
                    """, (act["name"], message.author.id, now_ts))
                    earned, in_event, _, _ = add_points(message.author.id, act["points"], 10, message.guild)
                    scope = "الفعالية" if in_event else "السيرفر"
                    await message.channel.send(
                        f"✨ {message.author.mention} نفّذ **{act['name']}** وحصل على **{earned}** نقطة في {scope}!"
                    )
                break

    await bot.process_commands(message)


@bot.tree.command(name="streak", description="تسجيل الستريك اليومي بتوقيت الرياض")
async def streak_cmd(interaction: discord.Interaction):
    ensure_user(interaction.user.id)
    now_riyadh = datetime.now(RIYADH_TZ)
    today_str = now_riyadh.strftime("%Y-%m-%d")
    yesterday_str = (now_riyadh - timedelta(days=1)).strftime("%Y-%m-%d")

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()
        if user["last_streak_date"] == today_str:
            await interaction.response.send_message("لقد سجّلتِ ستريك اليوم مسبقاً بتوقيت الرياض! ارجعي بكرة.", ephemeral=True)
            return

        if user["last_streak_date"] == yesterday_str:
            new_streak = user["streak"] + 1
        else:
            new_streak = 1

        bonus = min(50, 10 + (new_streak - 1) * 5)
        conn.execute(
            "UPDATE users SET streak = ?, last_streak_date = ? WHERE user_id = ?",
            (new_streak, today_str, interaction.user.id)
        )

    earned, in_event, _, _ = add_points(interaction.user.id, bonus, 20, interaction.guild)
    scope = "الفعالية النشطة" if in_event else "السيرفر العام"
    await interaction.response.send_message(
        f"🔥 ستريككِ الآن **{new_streak}** يوم! حصلتِ على **{earned}** نقطة ضمن {scope}."
    )


@bot.tree.command(name="yt", description="منح نقاط مشاركة اليوتيوب (للإدارة)")
@app_commands.describe(member="العضو المستحق", motivator="اسم المحفز (اختياري)")
async def yt_cmd(interaction: discord.Interaction, member: discord.Member, motivator: str | None = None):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    points = int(get_setting("yt_points") or 15)
    used_motivator = motivator.strip() if motivator else (get_setting("yt_motivator") or "يوكا")
    earned, _, _, _ = add_points(member.id, points, 25, interaction.guild)

    await interaction.response.send_message(
        f"{member.mention} حصلت على {earned} نقطة بسبب مشاركة نتائجك وتحفيز الآخرين بمُحفز {used_motivator} على اليوتيوب!"
    )


@bot.tree.command(name="set_yt_points", description="تحديد نقاط أمر اليوتيوب (للإدارة)")
@app_commands.describe(points="عدد النقاط الثابت")
async def set_yt_points_cmd(interaction: discord.Interaction, points: int):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return
    if points < 1:
        await interaction.response.send_message("يجب أن يكون عدد النقاط 1 أو أكثر.", ephemeral=True)
        return

    set_setting("yt_points", str(points))
    await interaction.response.send_message(f"تم تحديث نقاط أمر `/yt` إلى **{points}** نقطة.")


@bot.tree.command(name="event_start", description="بدء فعالية فرعية وعزل النقاط لها (للإدارة)")
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
            (active["id"],)
        ).fetchall()
        conn.execute("UPDATE events SET active = 0 WHERE id = ?", (active["id"],))

    lines = [f"🏁 انتهت فعالية **{active['name']}** وعاد الاحتساب إلى السيرفر العام!"]
    if rows:
        lines.append("**🏆 متصدرو الفعالية:**")
        for idx, r in enumerate(rows, start=1):
            lines.append(f"{idx}. <@{r['user_id']}> — **{r['points']}** نقطة")
    else:
        lines.append("لم تُسجّل نقاط في هذه الفعالية.")

    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="event_top", description="عرض متصدري الفعالية الحالية")
async def event_top_cmd(interaction: discord.Interaction):
    active = get_active_event()
    if not active:
        await interaction.response.send_message("لا توجد فعالية نشطة حالياً.", ephemeral=True)
        return

    with get_db() as conn:
        rows = conn.execute(
            "SELECT user_id, points FROM event_points WHERE event_id = ? ORDER BY points DESC LIMIT 10",
            (active["id"],)
        ).fetchall()

    if not rows:
        await interaction.response.send_message(f"لا توجد نقاط مسجلة في فعالية **{active['name']}** بعد.")
        return

    msg = [f"🏆 متصدرو فعالية **{active['name']}**:"] + [
        f"{i}. <@{r['user_id']}> — **{r['points']}** نقطة" for i, r in enumerate(rows, start=1)
    ]
    await interaction.response.send_message("\n".join(msg))


@bot.tree.command(name="shop", description="عرض متجر النقاط")
async def shop_cmd(interaction: discord.Interaction):
    with get_db() as conn:
        items = conn.execute("SELECT * FROM shop_items").fetchall()

    if not items:
        await interaction.response.send_message("المتجر فارغ حالياً.")
        return

    lines = ["🛒 **متجر النقاط:**"]
    for item in items:
        lines.append(f"• **{item['name']}** — السعر: **{item['price']}** نقطة")
    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="buy", description="شراء عنصر من المتجر")
@app_commands.describe(item_name="اسم العنصر كما يظهر في /shop")
async def buy_cmd(interaction: discord.Interaction, item_name: str):
    ensure_user(interaction.user.id)
    now_ts = datetime.now().timestamp()

    with get_db() as conn:
        item = conn.execute("SELECT * FROM shop_items WHERE name = ?", (item_name,)).fetchone()
        if not item:
            await interaction.response.send_message("هذا العنصر غير موجود في المتجر.", ephemeral=True)
            return

        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()
        if user["points"] < item["price"]:
            await interaction.response.send_message(
                f"نقاطكِ العامة الحالية (**{user['points']}**) لا تكفي لشراء **{item['name']}** ({item['price']} نقطة).",
                ephemeral=True
            )
            return

        new_pts = user["points"] - item["price"]
        if item["item_type"] == "multiplier":
            until_ts = max(now_ts, user["multiplier_until"] or 0) + 86400
            conn.execute(
                "UPDATE users SET points = ?, multiplier_until = ? WHERE user_id = ?",
                (new_pts, until_ts, interaction.user.id)
            )
            msg = f"✅ تم شراء **مضاعف 1.5x** لمدة 24 ساعة! نقاطكِ المتبقية: **{new_pts}**."
        else:
            conn.execute(
                "UPDATE users SET points = ?, title = ? WHERE user_id = ?",
                (new_pts, item["value"], interaction.user.id)
            )
            msg = f"✅ تم شراء اللقب **{item['value']}** وتعيينه في بروفايلكِ! نقاطكِ المتبقية: **{new_pts}**."

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

    mult_status = "مفعّل (1.5x)" if (u["multiplier_until"] and u["multiplier_until"] > now_ts) else "غير مفعّل"
    await interaction.response.send_message(
        f"👤 **بروفايل {target.mention}**\n"
        f"• اللقب: **{u['title']}**\n"
        f"• المستوى: **{u['level']}** (XP: {u['xp']})\n"
        f"• النقاط العامة: **{u['points']}**\n"
        f"• الستريك: **{u['streak']}** يوم\n"
        f"• المضاعف: **{mult_status}**"
    )


@bot.tree.command(name="add_action", description="إضافة فعل مخصص جديد (للإدارة)")
@app_commands.describe(
    name="اسم الفعل",
    points="النقاط الممنوحة",
    cooldown="مدة الانتظار بالثواني",
    keyword="كلمة مفتاحية تفعّله تلقائياً في الشات (اختياري)"
)
async def add_action_cmd(
    interaction: discord.Interaction,
    name: str,
    points: int,
    cooldown: int = 60,
    keyword: str | None = None
):
    if not is_admin(interaction):
        await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        return

    with get_db() as conn:
        conn.execute("""
            INSERT INTO custom_actions (name, points, cooldown, keyword)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                points = excluded.points,
                cooldown = excluded.cooldown,
                keyword = excluded.keyword
        """, (name.strip(), max(1, points), max(0, cooldown), keyword.strip() if keyword else None))

    await interaction.response.send_message(
        f"⚡ تم حفظ الفعل المخصص **{name}** (+{points} نقطة، كولداون {cooldown}ث)."
    )


@bot.tree.command(name="do", description="تنفيذ فعل مخصص")
@app_commands.describe(action_name="اسم الفعل المخصص")
async def do_cmd(interaction: discord.Interaction, action_name: str):
    ensure_user(interaction.user.id)
    now_ts = datetime.now().timestamp()

    with get_db() as conn:
        act = conn.execute("SELECT * FROM custom_actions WHERE name = ?", (action_name.strip(),)).fetchone()
        if not act:
            await interaction.response.send_message("هذا الفعل غير موجود. استخدمي `/list_actions` لعرض الأفعال.", ephemeral=True)
            return

        cd = conn.execute(
            "SELECT last_used FROM action_cooldowns WHERE action_name = ? AND user_id = ?",
            (act["name"], interaction.user.id)
        ).fetchone()
        last_used = cd["last_used"] if cd else 0
        rem = int(act["cooldown"] - (now_ts - last_used))
        if rem > 0:
            await interaction.response.send_message(f"⏳ انتظري **{rem}** ثانية قبل إعادة تنفيذ **{act['name']}**.", ephemeral=True)
            return

        conn.execute("""
            INSERT INTO action_cooldowns (action_name, user_id, last_used)
            VALUES (?, ?, ?)
            ON CONFLICT(action_name, user_id) DO UPDATE SET last_used = excluded.last_used
        """, (act["name"], interaction.user.id, now_ts))

    earned, in_event, _, _ = add_points(interaction.user.id, act["points"], 10, interaction.guild)
    scope = "الفعالية" if in_event else "السيرفر"
    await interaction.response.send_message(
        f"✅ نفّذتِ **{act['name']}** وحصلتِ على **{earned}** نقطة في {scope}!"
    )


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


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("يرجى ضبط متغير البيئة DISCORD_TOKEN قبل تشغيل البوت.")

bot.run(token)

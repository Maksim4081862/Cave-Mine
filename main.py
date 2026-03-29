import os
import asyncio
import random
import aiosqlite
from pathlib import Path
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ Не найден токен! Добавьте BOT_TOKEN в переменные окружения")

DB_PATH = 'mine_game.db'
bot = Bot(token=TOKEN)
dp = Dispatcher()

MINING_BASE_TIME = 60
MIN_MINING_TIME = 5

# --- ВЕБ-СЕРВЕР ДЛЯ UPTIME ---
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is running! Mining game active."

@app.route('/health')
def health():
    return {"status": "ok", "bot": "alive"}

def run_web_server():
    app.run(host='0.0.0.0', port=8080)

# --- БАЗА ДАННЫХ ---

async def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                coins INTEGER DEFAULT 0,
                coal INTEGER DEFAULT 0,
                wood INTEGER DEFAULT 0,
                stone INTEGER DEFAULT 0,
                gold INTEGER DEFAULT 0,
                diamond INTEGER DEFAULT 0,
                pickaxe_level INTEGER DEFAULT 1,
                pickaxe_type TEXT DEFAULT 'wood',
                chest_level INTEGER DEFAULT 1,
                houses INTEGER DEFAULT 0,
                current_mine TEXT DEFAULT 'coal_mine',
                is_busy INTEGER DEFAULT 0,
                busy_end_time REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS market (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER,
                item TEXT NOT NULL,
                amount INTEGER NOT NULL,
                price INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()
    print("✅ База данных готова")

async def get_user_db(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                user = dict(zip(columns, row))
                if username and user['username'] != username:
                    await db.execute('UPDATE users SET username = ? WHERE user_id = ?', (username, user_id))
                    await db.commit()
                return user
            else:
                await db.execute('INSERT INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
                await db.commit()
                return {
                    'user_id': user_id, 'username': username, 'coins': 0,
                    'coal': 0, 'wood': 0, 'stone': 0, 'gold': 0, 'diamond': 0,
                    'pickaxe_level': 1, 'pickaxe_type': 'wood', 'chest_level': 1,
                    'houses': 0, 'current_mine': 'coal_mine', 'is_busy': 0, 'busy_end_time': 0
                }

async def save_user_db(user: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            UPDATE users SET coins=?, coal=?, wood=?, stone=?, gold=?, diamond=?,
            pickaxe_level=?, pickaxe_type=?, chest_level=?, houses=?, current_mine=?,
            is_busy=?, busy_end_time=? WHERE user_id=?
        ''', (user['coins'], user['coal'], user['wood'], user['stone'], user['gold'],
              user['diamond'], user['pickaxe_level'], user['pickaxe_type'],
              user['chest_level'], user['houses'], user['current_mine'],
              user['is_busy'], user['busy_end_time'], user['user_id']))
        await db.commit()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_mining_time(user):
    time = MINING_BASE_TIME / user['pickaxe_level']
    return max(MIN_MINING_TIME, int(time))

def get_mine_info(mine_id):
    mines = {
        "coal_mine": {"name": "Угольная шахта", "res": "coal", "req_lvl": 1, "icon": "⛏️"},
        "forest": {"name": "Лес", "res": "wood", "req_lvl": 2, "icon": "🪓"},
        "quarry": {"name": "Каменоломня", "res": "stone", "req_lvl": 3, "icon": "🧱"},
        "gold_mine": {"name": "Золотая жила", "res": "gold", "req_lvl": 4, "icon": "💰"},
        "diamond_mine": {"name": "Алмазная шахта", "res": "diamond", "req_lvl": 5, "icon": "💎"}
    }
    return mines.get(mine_id, mines["coal_mine"])

def get_pickaxe_stats(p_type):
    return {
        "wood": {"lvl": 1, "mult": 1}, "stone": {"lvl": 2, "mult": 2},
        "iron": {"lvl": 3, "mult": 4}, "gold": {"lvl": 4, "mult": 8},
        "diamond": {"lvl": 5, "mult": 15}, "star": {"lvl": 99, "mult": 50}
    }.get(p_type, {"lvl": 1, "mult": 1})

# --- КЛАВИАТУРЫ ---

def get_main_keyboard(user):
    builder = InlineKeyboardBuilder()
    if user['is_busy']:
        remaining = int(user['busy_end_time'] - asyncio.get_event_loop().time())
        if remaining > 0:
            builder.button(text=f"⏳ Добыча... ({remaining}с)", callback_data="mine_check", style="primary")
        else:
            builder.button(text="✅ ЗАБРАТЬ", callback_data="mine_collect", style="success")
    else:
        mine = get_mine_info(user['current_mine'])
        builder.button(text=f"{mine['icon']} ДОБЫЧА ({get_mining_time(user)}с)", callback_data="mine_start", style="success")
    
    builder.button(text="🏪 Торговец", callback_data="merchant", style="primary")
    builder.button(text="📈 Рынок", callback_data="market", style="primary")
    builder.button(text="🏗️ Стройка", callback_data="construction", style="primary")
    builder.button(text="🎒 Инвентарь", callback_data="inventory", style="primary")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = await get_user_db(message.from_user.id, message.from_user.username)
    await message.answer(
        f"👋 **Привет!**\n💰 Баланс: {user['coins']}\n🏠 Домов: {user['houses']}",
        reply_markup=get_main_keyboard(user),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "mine_start")
async def mine_start(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    if user['is_busy']:
        await callback.answer("Вы уже копаете!", show_alert=True)
        return
    
    mine = get_mine_info(user['current_mine'])
    duration = get_mining_time(user)
    user['is_busy'] = 1
    user['busy_end_time'] = asyncio.get_event_loop().time() + duration
    await save_user_db(user)
    
    await callback.message.edit_text(f"{mine['icon']} **Добыча...**\nВремя: {duration}с", parse_mode="Markdown")
    await callback.answer()
    await asyncio.sleep(duration)
    
    user = await get_user_db(callback.from_user.id)
    user['is_busy'] = 0
    await save_user_db(user)
    
    p_stats = get_pickaxe_stats(user['pickaxe_type'])
    total = 10 * p_stats['mult'] + user['chest_level'] * 5 + random.randint(0, 5)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f'UPDATE users SET {mine["res"]}={mine["res"]}+? WHERE user_id=?', (total, callback.from_user.id))
        await db.commit()
    
    await callback.message.edit_text(
        f"✅ **Готово!**\nПолучено: {total} {mine['res']}",
        reply_markup=get_main_keyboard(user),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "mine_check")
async def mine_check(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    if not user['is_busy']:
        await callback.message.edit_text("✅ Готово!", reply_markup=get_main_keyboard(user))
        return
    remaining = int(user['busy_end_time'] - asyncio.get_event_loop().time())
    await callback.answer(f"⏳ {max(0, remaining)}с", show_alert=True)

@dp.callback_query(F.data == "inventory")
async def inventory(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    text = f"🎒 **Инвентарь**\n💰 {user['coins']}\n🪨 {user['coal']}\n🪵 {user['wood']}\n🧱 {user['stone']}"
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.in_({"merchant", "market", "construction"}))
async def simple_menu(callback: types.CallbackQuery):
    await callback.answer("В разработке! 🔜", show_alert=True)

# --- ЗАПУСК ---

async def on_startup():
    await init_db()
    print("🚀 Бот запущен!")

async def main():
    dp.startup.register(on_startup)
    # Запуск веб-сервера в отдельном потоке
    Thread(target=run_web_server, daemon=True).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

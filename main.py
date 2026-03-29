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
                crystal INTEGER DEFAULT 0,
                mythril INTEGER DEFAULT 0,
                ancient_stone INTEGER DEFAULT 0,
                pickaxe_level INTEGER DEFAULT 1,
                pickaxe_type TEXT DEFAULT 'wood',
                chest_level INTEGER DEFAULT 1,
                houses INTEGER DEFAULT 0,
                house_level INTEGER DEFAULT 1,
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
                seller_name TEXT,
                item TEXT NOT NULL,
                amount INTEGER NOT NULL,
                price INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Проверка и добавление новых колонок если их нет
        try:
            await db.execute('ALTER TABLE users ADD COLUMN crystal INTEGER DEFAULT 0')
        except:
            pass
        try:
            await db.execute('ALTER TABLE users ADD COLUMN mythril INTEGER DEFAULT 0')
        except:
            pass
        try:
            await db.execute('ALTER TABLE users ADD COLUMN ancient_stone INTEGER DEFAULT 0')
        except:
            pass
        try:
            await db.execute('ALTER TABLE users ADD COLUMN house_level INTEGER DEFAULT 1')
        except:
            pass
        await db.execute('ALTER TABLE market ADD COLUMN seller_name TEXT')
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
                    'crystal': 0, 'mythril': 0, 'ancient_stone': 0,
                    'pickaxe_level': 1, 'pickaxe_type': 'wood', 'chest_level': 1,
                    'houses': 0, 'house_level': 1, 'current_mine': 'coal_mine', 
                    'is_busy': 0, 'busy_end_time': 0
                }

async def save_user_db(user: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            UPDATE users SET coins=?, coal=?, wood=?, stone=?, gold=?, diamond=?,
            crystal=?, mythril=?, ancient_stone=?, pickaxe_level=?, pickaxe_type=?, 
            chest_level=?, houses=?, house_level=?, current_mine=?, is_busy=?, 
            busy_end_time=? WHERE user_id=?
        ''', (user['coins'], user['coal'], user['wood'], user['stone'], user['gold'],
              user['diamond'], user['crystal'], user['mythril'], user['ancient_stone'],
              user['pickaxe_level'], user['pickaxe_type'], user['chest_level'],
              user['houses'], user['house_level'], user['current_mine'],
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
        "diamond_mine": {"name": "Алмазная шахта", "res": "diamond", "req_lvl": 5, "icon": "💎"},
        "crystal_cave": {"name": "Кристальная пещера", "res": "crystal", "req_lvl": 6, "icon": "💠"},
        "mythril_depths": {"name": "Мифриловые глубины", "res": "mythril", "req_lvl": 7, "icon": "🔮"},
        "ancient_ruins": {"name": "Древние руины", "res": "ancient_stone", "req_lvl": 8, "icon": "🏛️"}
    }
    return mines.get(mine_id, mines["coal_mine"])

def get_pickaxe_stats(p_type):
    return {
        "wood": {"lvl": 1, "mult": 1, "name": "Деревянная", "price": 0}, 
        "stone": {"lvl": 2, "mult": 2, "name": "Каменная", "price": 500},
        "iron": {"lvl": 3, "mult": 4, "name": "Железная", "price": 1500}, 
        "gold": {"lvl": 4, "mult": 8, "name": "Золотая", "price": 5000},
        "diamond": {"lvl": 5, "mult": 15, "name": "Алмазная", "price": 15000}, 
        "crystal": {"lvl": 6, "mult": 25, "name": "Кристальная", "price": 40000},
        "mythril": {"lvl": 7, "mult": 40, "name": "Мифриловая", "price": 100000},
        "ancient": {"lvl": 8, "mult": 60, "name": "Древняя", "price": 250000},
        "star": {"lvl": 99, "mult": 100, "name": "Звёздная", "price": 1000000}
    }.get(p_type, {"lvl": 1, "mult": 1, "name": "Деревянная", "price": 0})

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
    builder.button(text="⛏️ Сменить шахту", callback_data="change_mine", style="secondary")
    builder.button(text="🔨 Улучшения", callback_data="upgrades", style="secondary")
    builder.adjust(1, 1, 1, 1, 2)
    return builder.as_markup()

def get_mines_keyboard(user):
    builder = InlineKeyboardBuilder()
    mines_list = ["coal_mine", "forest", "quarry", "gold_mine", "diamond_mine", 
                  "crystal_cave", "mythril_depths", "ancient_ruins"]
    for mine_id in mines_list:
        mine = get_mine_info(mine_id)
        unlocked = user['pickaxe_level'] >= mine['req_lvl']
        if unlocked:
            status = "✅" if user['current_mine'] == mine_id else "📍"
            builder.button(text=f"{status} {mine['name']} (ур.{mine['req_lvl']})", 
                          callback_data=f"select_mine_{mine_id}")
        else:
            builder.button(text=f"🔒 {mine['name']} (нужен ур.{mine['req_lvl']})", 
                          callback_data="locked_mine")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 1, 1, 1, 1, 1)
    return builder.as_markup()

def get_upgrades_keyboard(user):
    builder = InlineKeyboardBuilder()
    p_stats = get_pickaxe_stats(user['pickaxe_type'])
    next_types = ["stone", "iron", "gold", "diamond", "crystal", "mythril", "ancient", "star"]
    current_idx = next_types.index(user['pickaxe_type']) if user['pickaxe_type'] in next_types else -1
    
    builder.button(text=f"⛏️ Кирка: {p_stats['name']} (x{p_stats['mult']})", callback_data="pickaxe_info", style="primary")
    
    if current_idx < len(next_types) - 1:
        next_type = next_types[current_idx + 1]
        next_stats = get_pickaxe_stats(next_type)
        
        # Звёздная кирка доступна за монеты ИЛИ за Telegram Stars
        if next_type == "star":
            can_buy_coins = user['coins'] >= next_stats['price']
            btn_text_coins = f"{'💰' if can_buy_coins else '🔒'} {next_stats['name']} (x{next_stats['mult']}) - {next_stats['price']}💰"
            builder.button(text=btn_text_coins, callback_data=f"buy_pickaxe_{next_type}", 
                          style="success" if can_buy_coins else "secondary")
            
            # Кнопка покупки за Telegram Stars (100 Stars)
            builder.button(text=f"⭐️ {next_stats['name']} за 100 Stars", 
                          callback_data=f"buy_pickaxe_stars_{next_type}")
        else:
            can_buy = user['coins'] >= next_stats['price']
            btn_text = f"{'💰' if can_buy else '🔒'} {next_stats['name']} (x{next_stats['mult']}) - {next_stats['price']}💰"
            builder.button(text=btn_text, callback_data=f"buy_pickaxe_{next_type}", 
                          style="success" if can_buy else "secondary")
    
    builder.button(text=f"📦 Сундук: ур.{user['chest_level']} (+{user['chest_level']*5} к добыче)", 
                  callback_data="chest_info", style="primary")
    if user['coins'] >= user['chest_level'] * 200:
        builder.button(text=f"💎 Улучшить сундук ({user['chest_level']*200}💰)", 
                      callback_data="upgrade_chest", style="success")
    else:
        builder.button(text=f"🔒 Улучшить сундук ({user['chest_level']*200}💰)", 
                      callback_data="chest_info", style="secondary")
    
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 2, 1, 1)
    return builder.as_markup()

def get_merchant_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Продать уголь (10💰/шт)", callback_data="sell_coal")
    builder.button(text="💰 Продать дерево (15💰/шт)", callback_data="sell_wood")
    builder.button(text="💰 Продать камень (20💰/шт)", callback_data="sell_stone")
    builder.button(text="💰 Продать золото (50💰/шт)", callback_data="sell_gold")
    builder.button(text="💰 Продать алмазы (150💰/шт)", callback_data="sell_diamond")
    builder.button(text="💰 Продать кристаллы (400💰/шт)", callback_data="sell_crystal")
    builder.button(text="💰 Продать мифрил (1000💰/шт)", callback_data="sell_mythril")
    builder.button(text="💰 Продать древний камень (2500💰/шт)", callback_data="sell_ancient")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 1, 1, 1, 1, 1, 1, 1, 1)
    return builder.as_markup()

def get_construction_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Построить дом (100💰)", callback_data="build_house")
    builder.button(text="🏗️ Улучшить дом", callback_data="upgrade_house")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 1, 1)
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
    p_stats = get_pickaxe_stats(user['pickaxe_type'])
    text = (f"🎒 **Инвентарь**\n"
            f"💰 Монеты: {user['coins']}\n\n"
            f"🪨 Уголь: {user['coal']}\n"
            f"🪵 Дерево: {user['wood']}\n"
            f"🧱 Камень: {user['stone']}\n"
            f"💰 Золото: {user['gold']}\n"
            f"💎 Алмазы: {user['diamond']}\n"
            f"💠 Кристаллы: {user['crystal']}\n"
            f"🔮 Мифрил: {user['mythril']}\n"
            f"🏛️ Древний камень: {user['ancient_stone']}\n\n"
            f"⛏️ Кирка: {p_stats['name']} (ур.{p_stats['lvl']}, x{p_stats['mult']})\n"
            f"📦 Сундук: ур.{user['chest_level']}\n"
            f"🏠 Домов: {user['houses']} (ур.{user['house_level']})")
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "change_mine")
async def change_mine(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    if user['is_busy']:
        await callback.answer("Сначала завершите добычу!", show_alert=True)
        return
    await callback.message.edit_text("⛏️ **Выберите шахту:**", 
                                     reply_markup=get_mines_keyboard(user),
                                     parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("select_mine_"))
async def select_mine(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    mine_id = callback.data.replace("select_mine_", "")
    mine = get_mine_info(mine_id)
    
    if user['pickaxe_level'] < mine['req_lvl']:
        await callback.answer("❌ Недостаточный уровень кирки!", show_alert=True)
        return
    
    user['current_mine'] = mine_id
    await save_user_db(user)
    await callback.message.edit_text(f"✅ Выбрана: {mine['name']}", 
                                     reply_markup=get_main_keyboard(user),
                                     parse_mode="Markdown")
    await callback.answer(f"Теперь вы добываете в: {mine['name']}")

@dp.callback_query(F.data == "locked_mine")
async def locked_mine(callback: types.CallbackQuery):
    await callback.answer("🔒 Улучшите кирку чтобы открыть!", show_alert=True)

@dp.callback_query(F.data == "upgrades")
async def upgrades(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    await callback.message.edit_text("🔨 **Улучшения:**", 
                                     reply_markup=get_upgrades_keyboard(user),
                                     parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_pickaxe_"))
async def buy_pickaxe(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    
    # Проверка на покупку за Stars
    if callback.data.startswith("buy_pickaxe_stars_"):
        pickaxe_type = callback.data.replace("buy_pickaxe_stars_", "")
        
        if pickaxe_type != "star":
            await callback.answer("❌ Только звёздную кирку можно купить за Stars!", show_alert=True)
            return
        
        # Создаём инвойс для оплаты Telegram Stars
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title="Звёздная кирка",
            description="Мощнейшая кирка с множителем x100!",
            payload="star_pickaxe_payment",
            provider_token="",  # Пустой для Telegram Stars
            currency="XTR",  # Валюта Telegram Stars
            prices=[LabeledPrice(label="Звёздная кирка", amount=100)],  # 100 Stars
            start_parameter="star_pickaxe",
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
        )
        await callback.answer()
        return
    
    # Обычная покупка за монеты
    pickaxe_type = callback.data.replace("buy_pickaxe_", "")
    pickaxe_stats = get_pickaxe_stats(pickaxe_type)
    
    if user['coins'] >= pickaxe_stats['price']:
        user['coins'] -= pickaxe_stats['price']
        user['pickaxe_type'] = pickaxe_type
        user['pickaxe_level'] = pickaxe_stats['lvl']
        await save_user_db(user)
        await callback.message.edit_text(f"✅ Куплена кирка: {pickaxe_stats['name']}!\n"
                                        f"Множитель добычи: x{pickaxe_stats['mult']}",
                                        reply_markup=get_upgrades_keyboard(user),
                                        parse_mode="Markdown")
        await callback.answer(f"Куплена {pickaxe_stats['name']}!")
    else:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    """Обработка предварительной проверки платежа"""
    if pre_checkout_query.payload == "star_pickaxe_payment":
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    else:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Неизвестный платёж")

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    """Обработка успешного платежа"""
    payment = message.successful_payment
    if payment.invoice_payload == "star_pickaxe_payment":
        user = await get_user_db(message.from_user.id)
        user['pickaxe_type'] = 'star'
        user['pickaxe_level'] = 99
        await save_user_db(user)
        
        p_stats = get_pickaxe_stats('star')
        await message.answer(
            f"⭐️ **Оплата прошла успешно!**\n\n"
            f"✅ Куплена кирка: {p_stats['name']}!\n"
            f"Множитель добычи: x{p_stats['mult']}\n\n"
            f"Спасибо за покупку! 🎉",
            reply_markup=get_upgrades_keyboard(user),
            parse_mode="Markdown"
        )
    else:
        await message.answer("Платёж получен, но товар не найден.")

@dp.callback_query(F.data == "upgrade_chest")
async def upgrade_chest(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    cost = user['chest_level'] * 200
    
    if user['coins'] >= cost:
        user['coins'] -= cost
        user['chest_level'] += 1
        await save_user_db(user)
        await callback.message.edit_text(f"✅ Сундук улучшен до уровня {user['chest_level']}!\n"
                                        f"+{user['chest_level']*5} к добыче",
                                        reply_markup=get_upgrades_keyboard(user),
                                        parse_mode="Markdown")
        await callback.answer("Сундук улучшен!")
    else:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)

@dp.callback_query(F.data == "pickaxe_info")
async def pickaxe_info(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    p_stats = get_pickaxe_stats(user['pickaxe_type'])
    await callback.answer(f"{p_stats['name']}: ур.{p_stats['lvl']}, множитель x{p_stats['mult']}", show_alert=True)

@dp.callback_query(F.data == "chest_info")
async def chest_info(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    await callback.answer(f"Сундук ур.{user['chest_level']}: +{user['chest_level']*5} к добыче", show_alert=True)

@dp.callback_query(F.data == "merchant")
async def merchant(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    await callback.message.edit_text("🏪 **Торговец - Продайте ресурсы:**", 
                                     reply_markup=get_merchant_keyboard(user),
                                     parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("sell_"))
async def sell_resource(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    resource_map = {
        "coal": ("coal", 10),
        "wood": ("wood", 15),
        "stone": ("stone", 20),
        "gold": ("gold", 50),
        "diamond": ("diamond", 150),
        "crystal": ("crystal", 400),
        "mythril": ("mythril", 1000),
        "ancient": ("ancient_stone", 2500)
    }
    
    res_key = callback.data.replace("sell_", "")
    if res_key not in resource_map:
        await callback.answer("❌ Неизвестный ресурс", show_alert=True)
        return
    
    db_field, price = resource_map[res_key]
    amount = user[db_field]
    
    if amount <= 0:
        await callback.answer("❌ Нет ресурсов для продажи!", show_alert=True)
        return
    
    earnings = amount * price
    user[db_field] = 0
    user['coins'] += earnings
    await save_user_db(user)
    
    await callback.message.edit_text(f"✅ Продано: {amount} шт. за {earnings}💰", 
                                     reply_markup=get_merchant_keyboard(),
                                     parse_mode="Markdown")
    await callback.answer(f"Получено {earnings} монет!")

@dp.callback_query(F.data == "construction")
async def construction(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    await callback.message.edit_text("🏗️ **Стройка:**", 
                                     reply_markup=get_construction_keyboard(),
                                     parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "build_house")
async def build_house(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    cost = 100
    
    if user['coins'] >= cost:
        user['coins'] -= cost
        user['houses'] += 1
        await save_user_db(user)
        await callback.message.edit_text(f"✅ Построен дом! Всего домов: {user['houses']}", 
                                         reply_markup=get_construction_keyboard(),
                                         parse_mode="Markdown")
        await callback.answer("Дом построен!")
    else:
        await callback.answer("❌ Недостаточно монет (нужно 100💰)", show_alert=True)

@dp.callback_query(F.data == "upgrade_house")
async def upgrade_house(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    cost = user['house_level'] * 500
    
    if user['houses'] < 1:
        await callback.answer("❌ Сначала постройте хотя бы один дом!", show_alert=True)
        return
    
    if user['coins'] >= cost:
        user['coins'] -= cost
        user['house_level'] += 1
        await save_user_db(user)
        await callback.message.edit_text(f"✅ Дом улучшен до уровня {user['house_level']}!", 
                                         reply_markup=get_construction_keyboard(),
                                         parse_mode="Markdown")
        await callback.answer("Дом улучшен!")
    else:
        await callback.answer(f"❌ Нужно {cost}💰 для улучшения", show_alert=True)

@dp.callback_query(F.data == "back_main")
async def back_main(callback: types.CallbackQuery):
    user = await get_user_db(callback.from_user.id)
    await callback.message.edit_text("🏠 **Главное меню:**", 
                                     reply_markup=get_main_keyboard(user),
                                     parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "market")
async def market(callback: types.CallbackQuery):
    await callback.answer("📈 Рынок в разработке! Скоро можно будет торговать с другими игроками.", show_alert=True)

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

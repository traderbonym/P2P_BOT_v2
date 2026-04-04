import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, 
    CallbackQuery, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"), parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

session = None
user_history = {}

# FSM States
class CalculateState(StatesGroup):
    waiting_for_amount = State()

# Get Binance P2P rates
async def get_binance_rates():
    try:
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        
        buy_payload = {
            "fiat": "UAH",
            "page": 1,
            "rows": 5,
            "tradeType": "BUY",
            "asset": "USDT",
            "payTypes": ["Monobank"],
            "publisherType": "merchant"
        }
        
        async with session.post(url, json=buy_payload) as response:
            buy_data = await response.json()
            if not buy_data.get("data") or len(buy_data["data"]) < 2:
                return {"success": False, "error": "Not enough buy offers"}
            buy_rate = float(buy_data["data"][1]["adv"]["price"])
        
        sell_payload = {
            "fiat": "UAH",
            "page": 1,
            "rows": 5,
            "tradeType": "SELL",
            "asset": "USDT",
            "payTypes": ["Monobank"],
            "publisherType": "merchant"
        }
        
        async with session.post(url, json=sell_payload) as response:
            sell_data = await response.json()
            if not sell_data.get("data") or len(sell_data["data"]) < 2:
                return {"success": False, "error": "Not enough sell offers"}
            sell_rate = float(sell_data["data"][1]["adv"]["price"])
        
        logger.info(f"Buy={buy_rate}, Sell={sell_rate}")
        
        return {
            "success": True,
            "buy_rate": buy_rate,
            "sell_rate": sell_rate
        }
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"success": False, "error": str(e)}

# Calculate arbitrage
def calculate_arbitrage(amount, buy_rate, sell_rate):
    usdt_bought = amount / buy_rate
    uah_received = usdt_bought * sell_rate
    profit = uah_received - amount
    profit_percent = (profit / amount) * 100
    
    return {
        "usdt": round(usdt_bought, 2),
        "received": round(uah_received, 2),
        "profit": round(profit, 2),
        "percent": round(profit_percent, 2)
    }

# Format result
def format_result(amount, rates, calc):
    profit_emoji = "🟢" if calc["profit"] > 0 else "🔴"
    
    return f"""
📊 <b>Курси Binance P2P (2-й рядок):</b>
• 🛒 Купівля: <b>{rates['buy_rate']:.2f}</b> грн
• 💸 Продаж: <b>{rates['sell_rate']:.2f}</b> грн

💰 <b>Ваша сума:</b> {amount:,.0f} грн

📈 <b>Розрахунок:</b>
1️⃣ Купуєте <b>{calc['usdt']}</b> USDT за <b>{amount:,.0f}</b> грн
2️⃣ Продаєте <b>{calc['usdt']}</b> USDT за <b>{calc['received']:,.2f}</b> грн

{profit_emoji} <b>Прибуток:</b> {calc['profit']:,.2f} грн (<b>{calc['percent']:.2f}%</b>)

🕐 {datetime.now().strftime("%H:%M:%S")}
"""

# History
def add_to_history(user_id, amount, profit, percent):
    if user_id not in user_history:
        user_history[user_id] = []
    
    user_history[user_id].append({
        "amount": amount,
        "profit": profit,
        "percent": percent,
        "time": datetime.now().strftime("%H:%M:%S")
    })
    
    if len(user_history[user_id]) > 5:
        user_history[user_id].pop(0)

def format_history(user_id):
    if user_id not in user_history or not user_history[user_id]:
        return "📜 <b>Історія порожня</b>"
    
    text = "📜 <b>Останні 5 розрахунків:</b>\n\n"
    
    for i, record in enumerate(reversed(user_history[user_id]), 1):
        emoji = "🟢" if record["profit"] > 0 else "🔴"
        text += f"{i}. {record['time']} | {record['amount']:,.0f} грн → {emoji} {record['profit']:,.2f} грн ({record['percent']:.2f}%)\n"
    
    return text

# Keyboards
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔵 Binance P2P"),
                KeyboardButton(text="ℹ️ Інфо")
            ],
            [
                KeyboardButton(text="🔥 Канал")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Оберіть дію..."
    )

def inline_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔵 Binance P2P", callback_data="binance_menu")],
        [InlineKeyboardButton(text="🔥 Канал", url="https://t.me/P2P_CEH")],
        [InlineKeyboardButton(text="ℹ️ Інфо", callback_data="info")]
    ])

def binance_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Розрахувати", callback_data="calculate")],
        [InlineKeyboardButton(text="📊 Купити USDT", url="https://p2p.binance.com/trade/all-payments/USDT?fiat=UAH")],
        [InlineKeyboardButton(text="💸 Продати USDT", url="https://p2p.binance.com/trade/sell/USDT?fiat=UAH&payment=all-payments")],
        [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ])

def action_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити курси", callback_data="refresh")],
        [InlineKeyboardButton(text="🆕 Новий розрахунок", callback_data="new")]
    ])

# Commands
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        f"👋 Вітаю, <b>{message.from_user.first_name}</b>!\n\n"
        "🤖 Я бот для розрахунку <b>P2P арбітражу</b>.\n\n"
        "💰 <b>Що я вмію:</b>\n"
        "• Розраховую прибуток від P2P арбітражу\n"
        "• Показую актуальні курси\n"
        "• Зберігаю історію розрахунків\n\n"
        "📱 Оберіть біржу:",
        reply_markup=main_menu_keyboard()
    )
    await message.answer(
        "💡 <b>Або використовуйте кнопки нижче:</b>",
        reply_markup=inline_kb()
    )
    logger.info(f"User {message.from_user.id}")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📚 <b>Довідка:</b>\n\n"
        "1️⃣ Оберіть біржу\n"
        "2️⃣ Введіть суму (мін. 5000 грн)\n"
        "3️⃣ Отримайте розрахунок\n\n"
        "💬 @K2P_S",
        reply_markup=main_menu_keyboard()
    )

@dp.message(Command("info"))
async def cmd_info(message: Message):
    rates = await get_binance_rates()
    
    if rates["success"]:
        spread = rates["sell_rate"] - rates["buy_rate"]
        spread_percent = (spread / rates["buy_rate"]) * 100
        
        await message.answer(
            f"ℹ️ <b>Binance P2P:</b>\n\n"
            f"🛒 Купівля: <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"💸 Продаж: <b>{rates['sell_rate']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн (<b>{spread_percent:.2f}%</b>)\n\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message.answer(f"Помилка: {rates['error']}", reply_markup=main_menu_keyboard())

@dp.message(Command("history"))
async def cmd_history(message: Message):
    await message.answer(format_history(message.from_user.id), reply_markup=main_menu_keyboard())

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    if message.from_user.id in user_history:
        user_history[message.from_user.id] = []
    await message.answer("🗑 Історію очищено!", reply_markup=main_menu_keyboard())

# Menu buttons
@dp.message(F.text == "🔵 Binance P2P")
async def menu_binance(message: Message):
    await message.answer(
        "🔵 <b>Binance P2P Арбітраж</b>\n\n"
        "💰 Розраховуйте прибуток",
        reply_markup=binance_menu_kb()
    )

@dp.message(F.text == "ℹ️ Інфо")
async def menu_info(message: Message):
    rates = await get_binance_rates()
    
    if rates["success"]:
        spread = rates["sell_rate"] - rates["buy_rate"]
        spread_percent = (spread / rates["buy_rate"]) * 100
        
        await message.answer(
            f"ℹ️ <b>Binance P2P:</b>\n\n"
            f"🛒 Купівля: <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"💸 Продаж: <b>{rates['sell_rate']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн (<b>{spread_percent:.2f}%</b>)\n\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message.answer(f"Помилка: {rates['error']}", reply_markup=main_menu_keyboard())

@dp.message(F.text == "🔥 Канал")
async def menu_channel(message: Message):
    caption = (
        "🔥 <b>P2P CEH</b> — Канал про P2P та арбітраж !\n\n"
        "💸 <b>Що всередині:</b>\n"
        "├ Робочі схеми арбітражу\n"
        "├ Прибуток 4-6% на угоду\n"
        "├ Безпечні обмінники\n"
        "└ Підтримка 24/7\n\n"
        "📈 <b>Результати:</b>\n"
        "• Середній прибуток: 4-6% на угоду\n"
        "• Приєднуйтесь!</b>\n"
        "👉 https://t.me/P2P_CEH\n\n"
        "💬 Питання: @K2P_S"
    )
    
    await message.answer(caption, reply_markup=main_menu_keyboard())
    
    try:
        await message.answer_photo(
            photo=photo_url,
            caption=caption,
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        # Якщо фото не завантажилось - відправляємо текст
        await message.answer(caption, reply_markup=main_menu_keyboard())

# Callbacks
@dp.callback_query(F.data == "binance_menu")
async def cb_binance_menu(callback: CallbackQuery):
    await callback.message.answer(
        "🔵 <b>Binance P2P</b>",
        reply_markup=binance_menu_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery):
    await callback.message.answer(
        "💡 Головне меню:",
        reply_markup=inline_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "calculate")
async def cb_calculate(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "💰 Введіть суму (мін. 5000):\n\n"
        "Приклад: <code>5000</code>"
    )
    await state.set_state(CalculateState.waiting_for_amount)
    await callback.answer()

@dp.callback_query(F.data == "info")
async def cb_info(callback: CallbackQuery):
    rates = await get_binance_rates()
    
    if rates["success"]:
        spread = rates["sell_rate"] - rates["buy_rate"]
        spread_percent = (spread / rates["buy_rate"]) * 100
        
        await callback.message.answer(
            f"ℹ️ <b>Binance P2P:</b>\n\n"
            f"🛒 Купівля: <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"💸 Продаж: <b>{rates['sell_rate']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн (<b>{spread_percent:.2f}%</b>)\n\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
    else:
        await callback.message.answer(f"Помилка: {rates['error']}")
    
    await callback.answer()

@dp.callback_query(F.data == "history")
async def cb_history(callback: CallbackQuery):
    await callback.message.answer(format_history(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "refresh")
async def cb_refresh(callback: CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        amount = data.get("amount")
        
        if not amount:
            await callback.answer("Дані втрачено")
            return
        
        rates = await get_binance_rates()
        
        if not rates["success"]:
            await callback.answer(rates["error"])
            return
        
        calc = calculate_arbitrage(amount, rates["buy_rate"], rates["sell_rate"])
        await callback.message.edit_text(
            format_result(amount, rates, calc),
            reply_markup=action_kb()
        )
        await callback.answer("Оновлено!")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await callback.answer("Помилка")

@dp.callback_query(F.data == "new")
async def cb_new(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🔵 <b>Binance P2P</b>",
        reply_markup=binance_menu_kb()
    )
    await callback.answer()

# Amount handler
@dp.message(CalculateState.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "").replace(" ", ""))
        
        if amount < 5000:
            return await message.answer("Мінімум: 5000 грн")
        
        rates = await get_binance_rates()
        
        if not rates["success"]:
            return await message.answer(f"Помилка: {rates['error']}")
        
        calc = calculate_arbitrage(amount, rates["buy_rate"], rates["sell_rate"])
        add_to_history(message.from_user.id, amount, calc["profit"], calc["percent"])
        
        await message.answer(
            format_result(amount, rates, calc),
            reply_markup=action_kb()
        )
        
        await state.update_data(amount=amount)
        await state.clear()
        
        logger.info(f"User {message.from_user.id}: {amount} UAH")
        
    except ValueError:
        await message.answer("Введіть число!")

# Main
if __name__ == "__main__":
    from aiohttp import web
    
    async def health_check(request):
        return web.Response(text="Bot is running")
    
    async def main():
        global session
        
        timeout = aiohttp.ClientTimeout(total=10)
        session = aiohttp.ClientSession(timeout=timeout)
        
        app = web.Application()
        app.router.add_get("/", health_check)
        app.router.add_get("/health", health_check)
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        port = int(os.getenv("PORT", 10000))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        
        logger.info(f"HTTP: {port}")
        logger.info("Bot started")
        
        me = await bot.get_me()
        logger.info(f"@{me.username}")
        
        try:
            await dp.start_polling(bot)
        finally:
            await session.close()
    
    asyncio.run(main())

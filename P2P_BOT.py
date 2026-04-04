🔍 БАЧУ ПРОБЛЕМУ! АНАЛІЗ ЛОГІВ + РІШЕННЯ!
🔴 ПРОБЛЕМИ З ЛОГІВ:
1️⃣ ПОМИЛКА TELEGRAM:

ERROR __main__ Refresh error: Telegram server says - Bad Request: 
message is not modified
Причина: Кнопка "Оновити" намагається змінити повідомлення на таке саме (курси не змінились).

2️⃣ КУРСИ Є В ЛОГАХ:

INFO __main__ BUY order (2nd): 43.29 UAH | Bank: Monobank (Card)
INFO __main__ SELL order (2nd): 43.34 UAH | Bank: Raiffeisen Bank Aval (Card)
INFO __main__ Spread: 43.34 - 43.29 = 0.05 UAH
Курси ЗНАХОДЯТЬСЯ! Але чомусь бот не показує результат.

🔴 ДВА РІШЕННЯ:
ВАРІАНТ 1: ПОКАЗАТИ ТОП-5 ОГОЛОШЕНЬ (як ти просив)
Показувати з 2-го по 6-й рядок + порівняння спредів.

ВАРІАНТ 2: ВИПРАВИТИ ПОМИЛКИ + ЗАЛИШИТИ 2-й РЯДОК
Виправити помилку з "Refresh" + додати обробку помилок.

🔥 РЕКОМЕНДУЮ: ВАРІАНТ 1 (ТОП-5 СПРЕДІВ)
Це найкраще для market making — бачити 5 варіантів одразу!

📋 НОВИЙ КОД З ТОП-5 СПРЕДАМИ:
Notepad++ → ВИДАЛИ ВСЕ → ВСТАВЛЯЙ:

python

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
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

# Київський час (UTC+2)
KYIV_TZ = timezone(timedelta(hours=2))

def get_kyiv_time():
    return datetime.now(KYIV_TZ).strftime("%H:%M")

# FSM States
class CalculateState(StatesGroup):
    waiting_for_amount = State()

# Get Binance P2P TOP-5 spreads (ALL BANKS, >= 5000 UAH)
async def get_binance_top5():
    """Отримання ТОП-5 спредів Binance P2P (всі банки, від 5000 грн)"""
    try:
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        
        # КУПІВЛЯ USDT
        buy_payload = {
            "fiat": "UAH",
            "page": 1,
            "rows": 20,
            "tradeType": "BUY",
            "asset": "USDT",
            "publisherType": "merchant"
        }
        
        async with session.post(url, json=buy_payload) as response:
            buy_data = await response.json()
            if not buy_data.get("data"):
                return {"success": False, "error": "Немає оголошень купівлі"}
            
            # Фільтр: >= 5000 грн
            buy_filtered = []
            for ad in buy_data["data"]:
                min_amount = float(ad["adv"]["minSingleTransAmount"])
                max_amount = float(ad["adv"]["maxSingleTransAmount"])
                
                if min_amount <= 5000 <= max_amount:
                    buy_filtered.append({
                        "price": float(ad["adv"]["price"]),
                        "bank": ad["adv"]["tradeMethods"][0]["tradeMethodName"] if ad["adv"].get("tradeMethods") else "N/A",
                        "merchant": ad["advertiser"]["nickName"]
                    })
            
            if len(buy_filtered) < 6:
                return {"success": False, "error": f"Тільки {len(buy_filtered)} оголошень купівлі (потрібно 6+)"}
        
        # ПРОДАЖ USDT
        sell_payload = {
            "fiat": "UAH",
            "page": 1,
            "rows": 20,
            "tradeType": "SELL",
            "asset": "USDT",
            "publisherType": "merchant"
        }
        
        async with session.post(url, json=sell_payload) as response:
            sell_data = await response.json()
            if not sell_data.get("data"):
                return {"success": False, "error": "Немає оголошень продажу"}
            
            # Фільтр
            sell_filtered = []
            for ad in sell_data["data"]:
                min_amount = float(ad["adv"]["minSingleTransAmount"])
                max_amount = float(ad["adv"]["maxSingleTransAmount"])
                
                if min_amount <= 5000 <= max_amount:
                    sell_filtered.append({
                        "price": float(ad["adv"]["price"]),
                        "bank": ad["adv"]["tradeMethods"][0]["tradeMethodName"] if ad["adv"].get("tradeMethods") else "N/A",
                        "merchant": ad["advertiser"]["nickName"]
                    })
            
            if len(sell_filtered) < 6:
                return {"success": False, "error": f"Тільки {len(sell_filtered)} оголошень продажу (потрібно 6+)"}
        
        # Створюємо ТОП-5 спредів (з 2-го по 6-й рядок = індекси 1-5)
        top5 = []
        for i in range(1, 6):
            buy = buy_filtered[i]
            sell = sell_filtered[i]
            spread = sell["price"] - buy["price"]
            
            top5.append({
                "row": i + 1,  # 2-6
                "buy_price": buy["price"],
                "buy_bank": buy["bank"],
                "sell_price": sell["price"],
                "sell_bank": sell["bank"],
                "spread": spread,
                "spread_percent": (spread / buy["price"]) * 100
            })
            
            logger.info(f"Row {i+1}: BUY {buy['price']} | SELL {sell['price']} | SPREAD {spread:.2f}")
        
        return {
            "success": True,
            "top5": top5
        }
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"success": False, "error": str(e)}

# Format TOP-5 spreads
def format_top5(amount, data):
    """Форматування ТОП-5 спредів"""
    
    text = f"📊 <b>ТОП-5 спредів Binance P2P</b>\n"
    text += f"💰 Сума: {amount:,.0f} грн\n\n"
    
    for item in data["top5"]:
        row_num = item["row"]
        buy_price = item["buy_price"]
        sell_price = item["sell_price"]
        spread = item["spread"]
        spread_percent = item["spread_percent"]
        
        # Розрахунок прибутку
        usdt = amount / buy_price
        profit = usdt * spread
        
        # Емодзі
        emoji = "🟢" if spread > 0 else "🔴" if spread < 0 else "🟡"
        
        text += f"<b>{row_num}️⃣ Рядок:</b>\n"
        text += f"├ 🟦 BID: {buy_price:.2f} грн ({item['buy_bank']})\n"
        text += f"├ 🟥 ASK: {sell_price:.2f} грн ({item['sell_bank']})\n"
        text += f"└ {emoji} Спред: <b>{spread:.2f}</b> грн ({spread_percent:.2f}%) → Прибуток: <b>{profit:.2f}</b> грн\n\n"
    
    text += f"🕐 {get_kyiv_time()}"
    
    return text

# History
def add_to_history(user_id, amount, row, profit, percent):
    if user_id not in user_history:
        user_history[user_id] = []
    
    user_history[user_id].append({
        "amount": amount,
        "row": row,
        "profit": profit,
        "percent": percent,
        "time": get_kyiv_time()
    })
    
    if len(user_history[user_id]) > 5:
        user_history[user_id].pop(0)

def format_history(user_id):
    if user_id not in user_history or not user_history[user_id]:
        return "📜 <b>Історія порожня</b>"
    
    text = "📜 <b>Останні 5 розрахунків:</b>\n\n"
    
    for i, record in enumerate(reversed(user_history[user_id]), 1):
        emoji = "🟢" if record["profit"] > 0 else "🔴" if record["profit"] < 0 else "🟡"
        text += f"{i}. {record['time']} | Рядок {record['row']} | {record['amount']:,.0f} грн → {emoji} {record['profit']:,.2f} грн\n"
    
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
        [InlineKeyboardButton(text="🔥 Канал", callback_data="channel")],
        [InlineKeyboardButton(text="ℹ️ Інфо", callback_data="info")]
    ])

def binance_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 ТОП-5 спредів", callback_data="calculate")],
        [InlineKeyboardButton(text="📊 Купити USDT", url="https://p2p.binance.com/trade/all-payments/USDT?fiat=UAH")],
        [InlineKeyboardButton(text="💸 Продати USDT", url="https://p2p.binance.com/trade/sell/USDT?fiat=UAH&payment=all-payments")],
        [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ])

def action_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити", callback_data="refresh")],
        [InlineKeyboardButton(text="🆕 Новий розрахунок", callback_data="new")]
    ])

# Commands
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        f"👋 Вітаю, <b>{message.from_user.first_name}</b>!\n\n"
        "🤖 Я бот для розрахунку <b>Market Making</b> на Binance P2P.\n\n"
        "💰 <b>Що я показую:</b>\n"
        "• ТОП-5 спредів (рядки 2-6)\n"
        "• Прибуток для кожного рядка\n"
        "• Порівняння BID/ASK цін\n\n"
        "📱 Оберіть біржу:",
        reply_markup=main_menu_keyboard()
    )
    await message.answer(
        "💡 <b>Або використовуйте кнопки нижче:</b>",
        reply_markup=inline_kb()
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📚 <b>Довідка:</b>\n\n"
        "1️⃣ Оберіть Binance P2P\n"
        "2️⃣ Введіть суму (мін. 5000 грн)\n"
        "3️⃣ Отримайте ТОП-5 спредів\n\n"
        "🏦 Всі банки, від 5000 грн\n\n"
        "💬 Підтримка: @K2P_S",
        reply_markup=main_menu_keyboard()
    )

@dp.message(Command("info"))
async def cmd_info(message: Message):
    data = await get_binance_top5()
    
    if data["success"]:
        best = data["top5"][0]  # Кращий спред (2-й рядок)
        
        await message.answer(
            f"ℹ️ <b>Binance P2P (Кращий спред - 2-й рядок):</b>\n\n"
            f"🟦 BID: <b>{best['buy_price']:.2f}</b> грн\n"
            f"🟥 ASK: <b>{best['sell_price']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{best['spread']:.2f}</b> грн (<b>{best['spread_percent']:.2f}%</b>)\n\n"
            f"🕐 {get_kyiv_time()}\n\n"
            "💬 @K2P_S",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message.answer(f"❌ Помилка: {data['error']}", reply_markup=main_menu_keyboard())

@dp.message(Command("history"))
async def cmd_history(message: Message):
    await message.answer(format_history(message.from_user.id), reply_markup=main_menu_keyboard())

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    if message.from_user.id in user_history:
        user_history[message.from_user.id] = []
    await message.answer("🗑 <b>Історію очищено!</b>", reply_markup=main_menu_keyboard())

# Menu buttons
@dp.message(F.text == "🔵 Binance P2P")
async def menu_binance(message: Message):
    await message.answer(
        "🔵 <b>Binance P2P Market Making</b>\n\n"
        "💰 ТОП-5 спредів (рядки 2-6)\n"
        "📊 Порівняння BID/ASK цін\n"
        "🏦 Всі банки, від 5000 грн",
        reply_markup=binance_menu_kb()
    )

@dp.message(F.text == "ℹ️ Інфо")
async def menu_info(message: Message):
    data = await get_binance_top5()
    
    if data["success"]:
        best = data["top5"][0]
        
        await message.answer(
            f"ℹ️ <b>Binance P2P (Кращий спред - 2-й рядок):</b>\n\n"
            f"🟦 BID: <b>{best['buy_price']:.2f}</b> грн\n"
            f"🟥 ASK: <b>{best['sell_price']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{best['spread']:.2f}</b> грн (<b>{best['spread_percent']:.2f}%</b>)\n\n"
            f"🕐 {get_kyiv_time()}\n\n"
            "💬 @K2P_S",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message.answer(f"❌ Помилка: {data['error']}", reply_markup=main_menu_keyboard())

@dp.message(F.text == "🔥 Канал")
async def menu_channel(message: Message):
    caption = (
        "🔥 <b>P2P CEH</b> — твій шлях до пасивного доходу!\n\n"
        "💸 <b>Що всередині:</b>\n"
        "├ Робочі схеми Market Making\n"
        "├ Прибуток 4-6% на угоду\n"
        "├ Безпечні стратегії\n"
        "└ Підтримка 24/7\n\n"
        "📈 <b>Статистика:</b>\n"
        "• 1000+ учасників\n"
        "• 50+ схем щомісяця\n"
        "• 95% успішних угод\n\n"
        "🚀 Приєднуйся: https://t.me/P2P_CEH\n"
        "💬 Питання: @K2P_S"
    )
    
    await message.answer(caption, reply_markup=main_menu_keyboard())

# Callbacks
@dp.callback_query(F.data == "binance_menu")
async def cb_binance_menu(callback: CallbackQuery):
    await callback.message.answer(
        "🔵 <b>Binance P2P Market Making</b>\n\n"
        "💰 ТОП-5 спредів (рядки 2-6)\n"
        "📊 Порівняння BID/ASK цін\n"
        "🏦 Всі банки, від 5000 грн",
        reply_markup=binance_menu_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery):
    await callback.message.answer(
        "💡 <b>Головне меню:</b>",
        reply_markup=inline_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "calculate")
async def cb_calculate(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "💰 <b>ТОП-5 спредів Binance P2P</b>\n\n"
        "Введіть суму в <b>гривнях</b> (мін. 5000):\n\n"
        "💡 Приклад: <code>5000</code>"
    )
    await state.set_state(CalculateState.waiting_for_amount)
    await callback.answer()

@dp.callback_query(F.data == "info")
async def cb_info(callback: CallbackQuery):
    data = await get_binance_top5()
    
    if data["success"]:
        best = data["top5"][0]
        
        await callback.message.answer(
            f"ℹ️ <b>Binance P2P (Кращий спред - 2-й рядок):</b>\n\n"
            f"🟦 BID: <b>{best['buy_price']:.2f}</b> грн\n"
            f"🟥 ASK: <b>{best['sell_price']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{best['spread']:.2f}</b> грн (<b>{best['spread_percent']:.2f}%</b>)\n\n"
            f"🕐 {get_kyiv_time()}\n\n"
            "💬 @K2P_S"
        )
    else:
        await callback.message.answer(f"❌ Помилка: {data['error']}")
    
    await callback.answer()

@dp.callback_query(F.data == "channel")
async def cb_channel(callback: CallbackQuery):
    caption = (
        "🔥 <b>P2P CEH</b> — твій шлях до пасивного доходу!\n\n"
        "💸 <b>Що всередині:</b>\n"
        "├ Робочі схеми Market Making\n"
        "├ Прибуток 4-6% на угоду\n"
        "├ Безпечні стратегії\n"
        "└ Підтримка 24/7\n\n"
        "📈 <b>Статистика:</b>\n"
        "• 1000+ учасників\n"
        "• 50+ схем щомісяця\n"
        "• 95% успішних угод\n\n"
        "🚀 Приєднуйся: https://t.me/P2P_CEH\n"
        "💬 Питання: @K2P_S"
    )
    
    await callback.message.answer(caption)
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
            user_id = callback.from_user.id
            if user_id in user_history and user_history[user_id]:
                amount = user_history[user_id][-1]["amount"]
        
        if not amount:
            await callback.answer("❌ Введіть нову суму")
            return
        
        result = await get_binance_top5()
        
        if not result["success"]:
            await callback.answer(f"❌ {result['error']}")
            return
        
        # Оновлюємо повідомлення ТІЛЬКИ якщо курси змінились
        new_text = format_top5(amount, result)
        
        try:
            await callback.message.edit_text(
                new_text,
                reply_markup=action_kb()
            )
            await state.update_data(amount=amount)
            await callback.answer("✅ Оновлено!")
        except Exception as e:
            # Якщо повідомлення не змінилось
            await callback.answer("Курси не змінились")
        
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        await callback.answer("❌ Помилка")

@dp.callback_query(F.data == "new")
async def cb_new(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🔵 <b>Binance P2P Market Making</b>\n\n"
        "💰 ТОП-5 спредів (рядки 2-6)\n"
        "📊 Порівняння BID/ASK цін\n"
        "🏦 Всі банки, від 5000 грн",
        reply_markup=binance_menu_kb()
    )
    await callback.answer()

# Amount handler
@dp.message(CalculateState.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "").replace(" ", ""))
        
        if amount < 5000:
            return await message.answer("❌ Мінімум: <b>5000 грн</b>")
        
        result = await get_binance_top5()
        
        if not result["success"]:
            return await message.answer(f"❌ Помилка: {result['error']}")
        
        # Додаємо в історію (кращий спред - 2-й рядок)
        best = result["top5"][0]
        usdt = amount / best["buy_price"]
        profit = usdt * best["spread"]
        profit_percent = (profit / amount) * 100
        
        add_to_history(message.from_user.id, amount, 2, profit, profit_percent)
        
        await message.answer(
            format_top5(amount, result),
            reply_markup=action_kb()
        )
        
        await state.update_data(amount=amount)
        await state.clear()
        
        logger.info(f"User {message.from_user.id}: {amount} UAH -> TOP-5 spreads shown")
        
    except ValueError:
        await message.answer("❌ Введіть число!\n\n💡 Приклад: <code>5000</code>")

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
        
        logger.info(f"HTTP server on port {port}")
        logger.info("P2P Market Making Bot started!")
        
        me = await bot.get_me()
        logger.info(f"@{me.username}")
        
        try:
            await dp.start_polling(bot)
        finally:
            await session.close()
    
    asyncio.run(main())

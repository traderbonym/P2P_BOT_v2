🔴 БАЧУ ПОМИЛКУ В ЛОГАХ!
❌ ПРОБЛЕМА:

SyntaxError: invalid character '🔵' (U+1F535)
Це емодзі 🔵 в коді! Python НЕ МОЖЕ обробити емодзі в деяких місцях.

🔍 ДЕ ПОМИЛКА:
Шукаю в коді... ЗНАЙШОВ!

Рядок з емодзі:

python

"🔵 <b>Binance P2P Market Making</b>"
Проблема: Емодзі в HTML-тексті — це ОК, але десь в коді Python є емодзі, яке потрапило не в рядок.

🔥 ВИПРАВЛЕНИЙ КОД (БЕЗ ПРОБЛЕМНИХ СИМВОЛІВ!)
Я ПРИБРАВ ВСІ ПОТЕНЦІЙНО НЕБЕЗПЕЧНІ ЕМОДЗІ З КРИТИЧНИХ МІСЦЬ!

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

# Kyiv time (UTC+2)
KYIV_TZ = timezone(timedelta(hours=2))

def get_kyiv_time():
    return datetime.now(KYIV_TZ).strftime("%H:%M")

# FSM States
class CalculateState(StatesGroup):
    waiting_for_amount = State()

# Get Binance P2P TOP-5 spreads
async def get_binance_top5():
    """Get TOP-5 Binance P2P spreads (all banks, min 5000 UAH)"""
    try:
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        
        # BUY orders
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
                return {"success": False, "error": "No buy offers"}
            
            # Filter: >= 5000 UAH
            buy_filtered = []
            for ad in buy_data["data"]:
                min_amount = float(ad["adv"]["minSingleTransAmount"])
                max_amount = float(ad["adv"]["maxSingleTransAmount"])
                
                if min_amount <= 5000 <= max_amount:
                    methods = ad["adv"].get("tradeMethods", [])
                    bank_name = methods[0]["tradeMethodName"] if methods else "N/A"
                    
                    buy_filtered.append({
                        "price": float(ad["adv"]["price"]),
                        "bank": bank_name,
                        "merchant": ad["advertiser"]["nickName"]
                    })
            
            if len(buy_filtered) < 6:
                return {"success": False, "error": f"Only {len(buy_filtered)} buy offers (need 6+)"}
        
        # SELL orders
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
                return {"success": False, "error": "No sell offers"}
            
            # Filter
            sell_filtered = []
            for ad in sell_data["data"]:
                min_amount = float(ad["adv"]["minSingleTransAmount"])
                max_amount = float(ad["adv"]["maxSingleTransAmount"])
                
                if min_amount <= 5000 <= max_amount:
                    methods = ad["adv"].get("tradeMethods", [])
                    bank_name = methods[0]["tradeMethodName"] if methods else "N/A"
                    
                    sell_filtered.append({
                        "price": float(ad["adv"]["price"]),
                        "bank": bank_name,
                        "merchant": ad["advertiser"]["nickName"]
                    })
            
            if len(sell_filtered) < 6:
                return {"success": False, "error": f"Only {len(sell_filtered)} sell offers (need 6+)"}
        
        # Create TOP-5 spreads (rows 2-6 = indices 1-5)
        top5 = []
        for i in range(1, 6):
            buy = buy_filtered[i]
            sell = sell_filtered[i]
            spread = sell["price"] - buy["price"]
            
            top5.append({
                "row": i + 1,
                "buy_price": buy["price"],
                "buy_bank": buy["bank"],
                "sell_price": sell["price"],
                "sell_bank": sell["bank"],
                "spread": spread,
                "spread_percent": (spread / buy["price"]) * 100
            })
            
            logger.info(f"Row {i+1}: BUY {buy['price']:.2f} | SELL {sell['price']:.2f} | SPREAD {spread:.2f}")
        
        return {
            "success": True,
            "top5": top5
        }
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"success": False, "error": str(e)}

# Format TOP-5 spreads
def format_top5(amount, data):
    """Format TOP-5 spreads"""
    
    text = "TOP-5 BINANCE P2P SPREADS\n"
    text += f"Amount: {amount:,.0f} UAH\n\n"
    
    for item in data["top5"]:
        row_num = item["row"]
        buy_price = item["buy_price"]
        sell_price = item["sell_price"]
        spread = item["spread"]
        spread_percent = item["spread_percent"]
        
        # Calculate profit
        usdt = amount / buy_price
        profit = usdt * spread
        
        # Emoji
        if spread > 0:
            emoji = "+"
        elif spread < 0:
            emoji = "-"
        else:
            emoji = "="
        
        text += f"<b>{row_num}. ROW:</b>\n"
        text += f"BID: {buy_price:.2f} UAH ({item['buy_bank']})\n"
        text += f"ASK: {sell_price:.2f} UAH ({item['sell_bank']})\n"
        text += f"{emoji} Spread: <b>{spread:.2f}</b> UAH ({spread_percent:.2f}%) = Profit: <b>{profit:.2f}</b> UAH\n\n"
    
    text += f"Time: {get_kyiv_time()}"
    
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
        return "HISTORY IS EMPTY"
    
    text = "LAST 5 CALCULATIONS:\n\n"
    
    for i, record in enumerate(reversed(user_history[user_id]), 1):
        emoji = "+" if record["profit"] > 0 else "-" if record["profit"] < 0 else "="
        text += f"{i}. {record['time']} | Row {record['row']} | {record['amount']:,.0f} UAH = {emoji} {record['profit']:,.2f} UAH\n"
    
    return text

# Keyboards
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Binance P2P"),
                KeyboardButton(text="Info")
            ],
            [
                KeyboardButton(text="Channel")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose action..."
    )

def inline_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Binance P2P", callback_data="binance_menu")],
        [InlineKeyboardButton(text="Channel", callback_data="channel")],
        [InlineKeyboardButton(text="Info", callback_data="info")]
    ])

def binance_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="TOP-5 spreads", callback_data="calculate")],
        [InlineKeyboardButton(text="Buy USDT", url="https://p2p.binance.com/trade/all-payments/USDT?fiat=UAH")],
        [InlineKeyboardButton(text="Sell USDT", url="https://p2p.binance.com/trade/sell/USDT?fiat=UAH&payment=all-payments")],
        [InlineKeyboardButton(text="History", callback_data="history")],
        [InlineKeyboardButton(text="Back", callback_data="back_main")]
    ])

def action_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Refresh", callback_data="refresh")],
        [InlineKeyboardButton(text="New calculation", callback_data="new")]
    ])

# Commands
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        f"Hello, <b>{message.from_user.first_name}</b>!\n\n"
        "P2P Market Making Bot\n\n"
        "What I show:\n"
        "- TOP-5 spreads (rows 2-6)\n"
        "- Profit for each row\n"
        "- BID/ASK comparison\n\n"
        "Choose exchange:",
        reply_markup=main_menu_keyboard()
    )
    await message.answer(
        "Or use buttons below:",
        reply_markup=inline_kb()
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "HELP:\n\n"
        "1. Choose Binance P2P\n"
        "2. Enter amount (min 5000 UAH)\n"
        "3. Get TOP-5 spreads\n\n"
        "All banks, from 5000 UAH\n\n"
        "Support: @K2P_S",
        reply_markup=main_menu_keyboard()
    )

@dp.message(Command("info"))
async def cmd_info(message: Message):
    data = await get_binance_top5()
    
    if data["success"]:
        best = data["top5"][0]
        
        await message.answer(
            f"BINANCE P2P (Best spread - row 2):\n\n"
            f"BID: <b>{best['buy_price']:.2f}</b> UAH\n"
            f"ASK: <b>{best['sell_price']:.2f}</b> UAH\n\n"
            f"Spread: <b>{best['spread']:.2f}</b> UAH (<b>{best['spread_percent']:.2f}%</b>)\n\n"
            f"Time: {get_kyiv_time()}\n\n"
            "@K2P_S",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message.answer(f"Error: {data['error']}", reply_markup=main_menu_keyboard())

@dp.message(Command("history"))
async def cmd_history(message: Message):
    await message.answer(format_history(message.from_user.id), reply_markup=main_menu_keyboard())

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    if message.from_user.id in user_history:
        user_history[message.from_user.id] = []
    await message.answer("History cleared!", reply_markup=main_menu_keyboard())

# Menu buttons
@dp.message(F.text == "Binance P2P")
async def menu_binance(message: Message):
    await message.answer(
        "BINANCE P2P MARKET MAKING\n\n"
        "TOP-5 spreads (rows 2-6)\n"
        "BID/ASK comparison\n"
        "All banks, from 5000 UAH",
        reply_markup=binance_menu_kb()
    )

@dp.message(F.text == "Info")
async def menu_info(message: Message):
    data = await get_binance_top5()
    
    if data["success"]:
        best = data["top5"][0]
        
        await message.answer(
            f"BINANCE P2P (Best spread - row 2):\n\n"
            f"BID: <b>{best['buy_price']:.2f}</b> UAH\n"
            f"ASK: <b>{best['sell_price']:.2f}</b> UAH\n\n"
            f"Spread: <b>{best['spread']:.2f}</b> UAH (<b>{best['spread_percent']:.2f}%</b>)\n\n"
            f"Time: {get_kyiv_time()}\n\n"
            "@K2P_S",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message.answer(f"Error: {data['error']}", reply_markup=main_menu_keyboard())

@dp.message(F.text == "Channel")
async def menu_channel(message: Message):
    caption = (
        "P2P CEH - Your way to passive income!\n\n"
        "What's inside:\n"
        "- Market Making strategies\n"
        "- Profit 4-6% per trade\n"
        "- Safe methods\n"
        "- 24/7 support\n\n"
        "Statistics:\n"
        "- 1000+ members\n"
        "- 50+ strategies per month\n"
        "- 95% successful trades\n\n"
        "Join: https://t.me/P2P_CEH\n"
        "Questions: @K2P_S"
    )
    
    await message.answer(caption, reply_markup=main_menu_keyboard())

# Callbacks
@dp.callback_query(F.data == "binance_menu")
async def cb_binance_menu(callback: CallbackQuery):
    await callback.message.answer(
        "BINANCE P2P MARKET MAKING\n\n"
        "TOP-5 spreads (rows 2-6)\n"
        "BID/ASK comparison\n"
        "All banks, from 5000 UAH",
        reply_markup=binance_menu_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery):
    await callback.message.answer(
        "Main menu:",
        reply_markup=inline_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "calculate")
async def cb_calculate(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "TOP-5 BINANCE P2P SPREADS\n\n"
        "Enter amount in <b>UAH</b> (min 5000):\n\n"
        "Example: <code>5000</code>"
    )
    await state.set_state(CalculateState.waiting_for_amount)
    await callback.answer()

@dp.callback_query(F.data == "info")
async def cb_info(callback: CallbackQuery):
    data = await get_binance_top5()
    
    if data["success"]:
        best = data["top5"][0]
        
        await callback.message.answer(
            f"BINANCE P2P (Best spread - row 2):\n\n"
            f"BID: <b>{best['buy_price']:.2f}</b> UAH\n"
            f"ASK: <b>{best['sell_price']:.2f}</b> UAH\n\n"
            f"Spread: <b>{best['spread']:.2f}</b> UAH (<b>{best['spread_percent']:.2f}%</b>)\n\n"
            f"Time: {get_kyiv_time()}\n\n"
            "@K2P_S"
        )
    else:
        await callback.message.answer(f"Error: {data['error']}")
    
    await callback.answer()

@dp.callback_query(F.data == "channel")
async def cb_channel(callback: CallbackQuery):
    caption = (
        "P2P CEH - Your way to passive income!\n\n"
        "What's inside:\n"
        "- Market Making strategies\n"
        "- Profit 4-6% per trade\n"
        "- Safe methods\n"
        "- 24/7 support\n\n"
        "Statistics:\n"
        "- 1000+ members\n"
        "- 50+ strategies per month\n"
        "- 95% successful trades\n\n"
        "Join: https://t.me/P2P_CEH\n"
        "Questions: @K2P_S"
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
            await callback.answer("Enter new amount")
            return
        
        result = await get_binance_top5()
        
        if not result["success"]:
            await callback.answer(f"Error: {result['error']}")
            return
        
        new_text = format_top5(amount, result)
        
        try:
            await callback.message.edit_text(
                new_text,
                reply_markup=action_kb()
            )
            await state.update_data(amount=amount)
            await callback.answer("Refreshed!")
        except:
            await callback.answer("Rates unchanged")
        
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        await callback.answer("Error")

@dp.callback_query(F.data == "new")
async def cb_new(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "BINANCE P2P MARKET MAKING\n\n"
        "TOP-5 spreads (rows 2-6)\n"
        "BID/ASK comparison\n"
        "All banks, from 5000 UAH",
        reply_markup=binance_menu_kb()
    )
    await callback.answer()

# Amount handler
@dp.message(CalculateState.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "").replace(" ", ""))
        
        if amount < 5000:
            return await message.answer("Minimum: <b>5000 UAH</b>")
        
        result = await get_binance_top5()
        
        if not result["success"]:
            return await message.answer(f"Error: {result['error']}")
        
        # Add to history (best spread - row 2)
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
        
        logger.info(f"User {message.from_user.id}: {amount} UAH -> TOP-5 shown")
        
    except ValueError:
        await message.answer("Enter a number!\n\nExample: <code>5000</code>")

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

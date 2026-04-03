import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp

# ========== НАЛАШТУВАННЯ ==========

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"), parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

session = None
user_history = {}


# ========== FSM СТАНИ ==========

class CalculateState(StatesGroup):
    waiting_for_amount = State()


# ========== ФУНКЦІЇ ОТРИМАННЯ КУРСІВ ==========

async def get_binance_rates():
    """Отримання курсів з Binance P2P (2-й рядок, Monobank, від 5000 грн)"""
    try:
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        
        # КУПІВЛЯ USDT (вкладка "Купить")
        buy_payload = {
            "fiat": "UAH",
            "page": 1,
            "rows": 5,
            "tradeType": "BUY",  # МИ КУПУЄМО
            "asset": "USDT",
            "payTypes": ["Monobank"],
            "publisherType": "merchant"
        }
        
        async with session.post(url, json=buy_payload) as response:
            buy_data = await response.json()
            if not buy_data.get("data") or len(buy_data["data"]) < 2:
                return {"success": False, "error": "Недостатньо оголошень для купівлі"}
            # 2-й рядок (індекс 1)
            buy_rate = float(buy_data["data"][1]["adv"]["price"])
        
        # ПРОДАЖ USDT (вкладка "Продать")
        sell_payload = {
            "fiat": "UAH",
            "page": 1,
            "rows": 5,
            "tradeType": "SELL",  # МИ ПРОДАЄМО
            "asset": "USDT",
            "payTypes": ["Monobank"],
            "publisherType": "merchant"
        }
        
        async with session.post(url, json=sell_payload) as response:
            sell_data = await response.json()
            if not sell_data.get("data") or len(sell_data["data"]) < 2:
                return {"success": False, "error": "Недостатньо оголошень для продажу"}
            # 2-й рядок (індекс 1)
            sell_rate = float(sell_data["data"][1]["adv"]["price"])
        
        logger.info(f"📊 Курси: Купівля={buy_rate}, Продаж={sell_rate}")
        
        return {
            "success": True,
            "buy_rate": buy_rate,
            "sell_rate": sell_rate
        }
        
    except Exception as e:
        logger.error(f"Помилка отримання курсів: {e}")
        return {"success": False, "error": str(e)}


# ========== РОЗРАХУНКИ ==========

def calculate_arbitrage(amount, buy_rate, sell_rate):
    """Розрахунок P2P арбітражу"""
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


# ========== ФОРМАТУВАННЯ ==========

def format_result(amount, rates, calc):
    """Форматування результату"""
    profit_emoji = "🟢" if calc["profit"] > 0 else "🔴"
    
    return f"""
💰 <b>P2P Арбітраж (Monobank)</b>

📊 <b>Курси Binance P2P (2-й рядок):</b>
• 🛒 Купівля: <b>{rates['buy_rate']:.2f}</b> грн
• 💸 Продаж: <b>{rates['sell_rate']:.2f}</b> грн

💵 <b>Ваша сума:</b> {amount:,.0f} грн

📈 <b>Розрахунок:</b>
1️⃣ Купуєте <b>{calc['usdt']}</b> USDT за <b>{amount:,.0f}</b> грн
2️⃣ Продаєте <b>{calc['usdt']}</b> USDT за <b>{calc['received']:,.2f}</b> грн

{profit_emoji} <b>Прибуток:</b> {calc['profit']:,.2f} грн (<b>{calc['percent']:.2f}%</b>)

🕐 {datetime.now().strftime("%H:%M:%S")}
"""


# ========== ІСТОРІЯ ==========

def add_to_history(user_id, amount, profit, percent):
    """Додати запис в історію"""
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
    """Форматування історії"""
    if user_id not in user_history or not user_history[user_id]:
        return "📜 <b>Історія порожня</b>\n\nРозрахуйте прибуток щоб побачити історію!"
    
    text = "📜 <b>Останні 5 розрахунків:</b>\n\n"
    
    for i, record in enumerate(reversed(user_history[user_id]), 1):
        emoji = "🟢" if record["profit"] > 0 else "🔴"
        text += f"{i}. {record['time']} | {record['amount']:,.0f} грн → {emoji} {record['profit']:,.2f} грн ({record['percent']:.2f}%)\n"
    
    return text


# ========== КЛАВІАТУРИ ==========

def main_kb():
    """Головна клавіатура"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Розрахувати", callback_data="calculate")],
        [InlineKeyboardButton(text="📊 Купити USDT", url="https://p2p.binance.com/trade/all-payments/USDT?fiat=UAH")],
        [InlineKeyboardButton(text="💸 Продати USDT", url="https://p2p.binance.com/trade/sell/USDT?fiat=UAH&payment=all-payments")],
        [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/P2P_CEH")],
        [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
        [InlineKeyboardButton(text="ℹ️ Інфо", callback_data="info")]
    ])

def action_kb():
    """Клавіатура дій"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити курси", callback_data="refresh")],
        [InlineKeyboardButton(text="🆕 Новий розрахунок", callback_data="new")]
    ])


# ========== ОБРОБНИКИ КОМАНД ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обробник команди /start"""
    await message.answer(
        f"👋 Вітаю, <b>{message.from_user.first_name}</b>!\n\n"
        "🤖 Я бот для розрахунку <b>P2P арбітражу</b> на Binance.\n\n"
        "💰 <b>Принцип:</b>\n"
        "• Купуємо USDT дешево\n"
        "• Продаємо USDT дорого\n"
        "• Отримуємо прибуток!\n\n"
        "💡 Натисніть кнопку:",
        reply_markup=main_kb()
    )
    logger.info(f"👤 User {message.from_user.id}")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обробник команди /help"""
    await message.answer(
        "📚 <b>Як працює:</b>\n\n"
        "1️⃣ Введіть суму (мін. 5000 грн)\n"
        "2️⃣ Бот знайде курси:\n"
        "   • Купівля (2-й рядок)\n"
        "   • Продаж (2-й рядок)\n"
        "3️⃣ Покаже прибуток\n\n"
        "🏦 Фільтри: Monobank, від 5000 грн\n\n"
        "📊 Команди:\n"
        "/start - меню\n"
        "/info - курси\n"
        "/history - історія\n"
        "/clear - очистити\n\n"
        "💬 Підтримка: @K2P_S",
        reply_markup=main_kb()
    )


@dp.message(Command("info"))
async def cmd_info(message: Message):
    """Інфо про курси"""
    rates = await get_binance_rates()
    
    if rates["success"]:
        spread = rates["sell_rate"] - rates["buy_rate"]
        spread_percent = (spread / rates["buy_rate"]) * 100
        
        await message.answer(
            f"ℹ️ <b>Курси (Monobank, 2-й рядок):</b>\n\n"
            f"🛒 Купівля: <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"💸 Продаж: <b>{rates['sell_rate']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн (<b>{spread_percent:.2f}%</b>)\n\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
            "💬 @K2P_S",
            reply_markup=main_kb()
        )
    else:
        await message.answer(f"❌ Помилка: {rates['error']}", reply_markup=main_kb())


@dp.message(Command("history"))
async def cmd_history(message: Message):
    """Історія"""
    await message.answer(format_history(message.from_user.id), reply_markup=main_kb())


@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    """Очистити історію"""
    if message.from_user.id in user_history:
        user_history[message.from_user.id] = []
    await message.answer("🗑 <b>Історію очищено!</b>", reply_markup=main_kb())


# ========== CALLBACK ==========

@dp.callback_query(F.data == "calculate")
async def process_calculate(callback: CallbackQuery, state: FSMContext):
    """Розрахувати"""
    await callback.message.answer(
        "💰 <b>Розрахунок</b>\n\n"
        "Введіть суму в <b>гривнях</b> (мін. 5000):\n\n"
        "💡 Приклад: <code>5000</code>"
    )
    await state.set_state(CalculateState.waiting_for_amount)
    await callback.answer()


@dp.callback_query(F.data == "info")
async def process_info(callback: CallbackQuery):
    """Інфо"""
    rates = await get_binance_rates()
    
    if rates["success"]:
        spread = rates["sell_rate"] - rates["buy_rate"]
        spread_percent = (spread / rates["buy_rate"]) * 100
        
        await callback.message.answer(
            f"ℹ️ <b>Курси (Monobank, 2-й рядок):</b>\n\n"
            f"🛒 Купівля: <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"💸 Продаж: <b>{rates['sell_rate']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн (<b>{spread_percent:.2f}%</b>)\n\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
            "💬 @K2P_S",
            reply_markup=main_kb()
        )
    else:
        await callback.message.answer(f"❌ Помилка: {rates['error']}")
    
    await callback.answer()


@dp.callback_query(F.data == "history")
async def process_history(callback: CallbackQuery):
    """Історія"""
    await callback.message.answer(format_history(callback.from_user.id), reply_markup=main_kb())
    await callback.answer()


@dp.callback_query(F.data == "refresh")
async def refresh_rates(callback: CallbackQuery, state: FSMContext):
    """Оновити"""
    try:
        data = await state.get_data()
        amount = data.get("amount")
        
        if not amount:
            await callback.answer("❌ Дані втрачено")
            return
        
        rates = await get_binance_rates()
        
        if not rates["success"]:
            await callback.answer(f"❌ {rates['error']}")
            return
        
        calc = calculate_arbitrage(amount, rates["buy_rate"], rates["sell_rate"])
        await callback.message.edit_text(
            format_result(amount, rates, calc),
            reply_markup=action_kb()
        )
        await callback.answer("✅ Оновлено!")
        
    except Exception as e:
        logger.error(f"Помилка refresh: {e}")
        await callback.answer("❌ Помилка")


@dp.callback_query(F.data == "new")
async def new_calculation(callback: CallbackQuery, state: FSMContext):
    """Новий"""
    await state.clear()
    await callback.message.answer("💡 Новий розрахунок:", reply_markup=main_kb())
    await callback.answer()


# ========== ОБРОБНИК СУМИ ==========

@dp.message(CalculateState.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    """Обробка суми"""
    try:
        amount = float(message.text.replace(",", "").replace(" ", ""))
        
        if amount < 5000:
            return await message.answer("❌ Мінімум: <b>5000 грн</b>")
        
        rates = await get_binance_rates()
        
        if not rates["success"]:
            return await message.answer(f"❌ Помилка: {rates['error']}")
        
        calc = calculate_arbitrage(amount, rates["buy_rate"], rates["sell_rate"])
        add_to_history(message.from_user.id, amount, calc["profit"], calc["percent"])
        
        await message.answer(
            format_result(amount, rates, calc),
            reply_markup=action_kb()
        )
        
        await state.update_data(amount=amount)
        await state.clear()
        
        logger.info(f"💰 {message.from_user.id}: {amount} грн → {calc['profit']} грн")
        
    except ValueError:
        await message.answer("❌ Введіть число!\n\n💡 Приклад: <code>5000</code>")


# ========== ЗАПУСК ==========

if __name__ == "__main__":
    from aiohttp import web
    
    async def health_check(request):
        return web.Response(text="✅ Bot is running!")
    
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
        
        logger.info(f"🌐 HTTP: {port}")
        logger.info("🤖 P2P Бот запущений!")
        
        me = await bot.get_me()
        logger.info(f"🔗 @{me.username}")
        
        try:
            await dp.start_polling(bot)
        finally:
            await session.close()
    
    asyncio.run(main())

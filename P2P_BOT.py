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

# Get Binance P2P rates (ALL BANKS, >= 5000 UAH, 2nd row)
async def get_binance_rates():
    """Отримання курсів Binance P2P (2-й рядок, всі банки, від 5000 грн)"""
    try:
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        
        # КУПІВЛЯ USDT (ми створюємо ордер - хтось продає нам)
        buy_payload = {
            "fiat": "UAH",
            "page": 1,
            "rows": 20,
            "tradeType": "BUY",  # Ми купуємо = створюємо bid
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
                    buy_filtered.append(ad)
            
            if len(buy_filtered) < 2:
                return {"success": False, "error": "Недостатньо оголошень купівлі (5000+ грн)"}
            
            # 2-й рядок (індекс 1)
            buy_rate = float(buy_filtered[1]["adv"]["price"])
            buy_methods = buy_filtered[1]["adv"].get("tradeMethods", [])
            buy_bank = buy_methods[0]["tradeMethodName"] if buy_methods else "N/A"
            logger.info(f"BUY order (2nd): {buy_rate} UAH | Bank: {buy_bank}")
        
        # ПРОДАЖ USDT (ми створюємо ордер - хтось купує у нас)
        sell_payload = {
            "fiat": "UAH",
            "page": 1,
            "rows": 20,
            "tradeType": "SELL",  # Ми продаємо = створюємо ask
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
                    sell_filtered.append(ad)
            
            if len(sell_filtered) < 2:
                return {"success": False, "error": "Недостатньо оголошень продажу (5000+ грн)"}
            
            # 2-й рядок
            sell_rate = float(sell_filtered[1]["adv"]["price"])
            sell_methods = sell_filtered[1]["adv"].get("tradeMethods", [])
            sell_bank = sell_methods[0]["tradeMethodName"] if sell_methods else "N/A"
            logger.info(f"SELL order (2nd): {sell_rate} UAH | Bank: {sell_bank}")
        
        logger.info(f"Spread: {sell_rate} - {buy_rate} = {sell_rate - buy_rate} UAH")
        
        return {
            "success": True,
            "buy_rate": buy_rate,    # Ціна для створення bid ордера
            "sell_rate": sell_rate,  # Ціна для створення ask ордера
            "buy_bank": buy_bank,
            "sell_bank": sell_bank
        }
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"success": False, "error": str(e)}

# Calculate MARKET MAKING profit (ПРАВИЛЬНА ФОРМУЛА!)
def calculate_arbitrage(amount, buy_rate, sell_rate):
    """
    Market Making розрахунок:
    1. Створюємо BID ордер (купуємо по buy_rate)
    2. Створюємо ASK ордер (продаємо по sell_rate)
    3. Прибуток = (sell_rate - buy_rate) × кількість USDT
    """
    
    # Скільки USDT купуємо/продаємо
    usdt_amount = amount / buy_rate
    
    # Прибуток на 1 USDT
    profit_per_usdt = sell_rate - buy_rate
    
    # Загальний прибуток
    profit = usdt_amount * profit_per_usdt
    profit_percent = (profit / amount) * 100
    
    # Сума після продажу
    uah_received = usdt_amount * sell_rate
    
    return {
        "usdt": round(usdt_amount, 2),
        "received": round(uah_received, 2),
        "profit": round(profit, 2),
        "percent": round(profit_percent, 2),
        "profit_per_usdt": round(profit_per_usdt, 2)
    }

# Format result
def format_result(amount, rates, calc):
    profit_emoji = "🟢" if calc["profit"] > 0 else "🔴" if calc["profit"] < 0 else "🟡"
    
    return f"""
📊 <b>Binance P2P Market Making (2-й рядок)</b>

💰 <b>Ваша сума:</b> {amount:,.0f} грн

📈 <b>Ордера:</b>
• 🟦 BID (купівля): <b>{rates['buy_rate']:.2f}</b> грн ({rates.get('buy_bank', 'N/A')})
• 🟥 ASK (продаж): <b>{rates['sell_rate']:.2f}</b> грн ({rates.get('sell_bank', 'N/A')})

📊 <b>Спред:</b> {rates['sell_rate']:.2f} - {rates['buy_rate']:.2f} = <b>{calc['profit_per_usdt']:.2f}</b> грн/USDT

🔄 <b>Об'єм:</b> {calc['usdt']} USDT

{profit_emoji} <b>Прибуток:</b> {calc['profit']:,.2f} грн (<b>{calc['percent']:.2f}%</b>)

💡 <b>Стратегія:</b>
1️⃣ Створюєте BID ордер: купити {calc['usdt']} USDT по {rates['buy_rate']:.2f} грн
2️⃣ Створюєте ASK ордер: продати {calc['usdt']} USDT по {rates['sell_rate']:.2f} грн
3️⃣ Отримуєте спред: {calc['profit']:,.2f} грн

🕐 {get_kyiv_time()}
"""

# History
def add_to_history(user_id, amount, profit, percent):
    if user_id not in user_history:
        user_history[user_id] = []
    
    user_history[user_id].append({
        "amount": amount,
        "profit": profit,
        "percent": percent,
        "time": get_kyiv_time()
    })
    
    if len(user_history[user_id]) > 5:
        user_history[user_id].pop(0)

def format_history(user_id):
    if user_id not in user_history or not user_history[user_id]:
        return "📜 <b>Історія порожня</b>\n\nРозрахуйте прибуток щоб побачити історію!"
    
    text = "📜 <b>Останні 5 розрахунків:</b>\n\n"
    
    for i, record in enumerate(reversed(user_history[user_id]), 1):
        emoji = "🟢" if record["profit"] > 0 else "🔴" if record["profit"] < 0 else "🟡"
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
        [InlineKeyboardButton(text="🔥 Канал", callback_data="channel")],
        [InlineKeyboardButton(text="ℹ️ Інфо", callback_data="info")]
    ])

def binance_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Розрахувати спред", callback_data="calculate")],
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
        "🤖 Я бот для розрахунку <b>Market Making</b> на Binance P2P.\n\n"
        "💰 <b>Що я вмію:</b>\n"
        "• Показую спред між BID і ASK\n"
        "• Розраховую прибуток від Market Making\n"
        "• Зберігаю історію розрахунків\n\n"
        "📱 Оберіть біржу:",
        reply_markup=main_menu_keyboard()
    )
    await message.answer(
        "💡 <b>Або використовуйте кнопки нижче:</b>",
        reply_markup=inline_kb()
    )
    logger.info(f"User {message.from_user.id} started")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📚 <b>Довідка:</b>\n\n"
        "1️⃣ Оберіть Binance P2P\n"
        "2️⃣ Введіть суму (мін. 5000 грн)\n"
        "3️⃣ Отримайте розрахунок спреду\n\n"
        "🏦 Фільтр: всі банки, від 5000 грн (2-й рядок)\n\n"
        "💡 <b>Market Making:</b>\n"
        "Ви створюєте 2 ордери одночасно:\n"
        "• BID (купівля по низькій ціні)\n"
        "• ASK (продаж по високій ціні)\n"
        "Прибуток = спред між ними!\n\n"
        "📊 Команди:\n"
        "/start - головне меню\n"
        "/info - поточні курси\n"
        "/history - історія розрахунків\n"
        "/clear - очистити історію\n\n"
        "💬 Підтримка: @K2P_S",
        reply_markup=main_menu_keyboard()
    )

@dp.message(Command("info"))
async def cmd_info(message: Message):
    rates = await get_binance_rates()
    
    if rates["success"]:
        spread = rates["sell_rate"] - rates["buy_rate"]
        spread_percent = (spread / rates["buy_rate"]) * 100
        
        await message.answer(
            f"ℹ️ <b>Binance P2P (2-й рядок):</b>\n\n"
            f"🟦 BID (купівля): <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"   └ {rates.get('buy_bank', 'N/A')}\n\n"
            f"🟥 ASK (продаж): <b>{rates['sell_rate']:.2f}</b> грн\n"
            f"   └ {rates.get('sell_bank', 'N/A')}\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн (<b>{spread_percent:.2f}%</b>)\n\n"
            f"🕐 {get_kyiv_time()}\n\n"
            "💬 @K2P_S",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message.answer(f"❌ Помилка: {rates['error']}", reply_markup=main_menu_keyboard())

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
        "💰 Розраховуйте прибуток від створення BID/ASK ордерів\n\n"
        "📊 Курси оновлюються в реальному часі\n"
        "🏦 Всі банки, від 5000 грн (2-й рядок)",
        reply_markup=binance_menu_kb()
    )

@dp.message(F.text == "ℹ️ Інфо")
async def menu_info(message: Message):
    rates = await get_binance_rates()
    
    if rates["success"]:
        spread = rates["sell_rate"] - rates["buy_rate"]
        spread_percent = (spread / rates["buy_rate"]) * 100
        
        await message.answer(
            f"ℹ️ <b>Binance P2P (2-й рядок):</b>\n\n"
            f"🟦 BID (купівля): <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"   └ {rates.get('buy_bank', 'N/A')}\n\n"
            f"🟥 ASK (продаж): <b>{rates['sell_rate']:.2f}</b> грн\n"
            f"   └ {rates.get('sell_bank', 'N/A')}\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн (<b>{spread_percent:.2f}%</b>)\n\n"
            f"🕐 {get_kyiv_time()}\n\n"
            "💬 @K2P_S",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message.answer(f"❌ Помилка: {rates['error']}", reply_markup=main_menu_keyboard())

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
        "💰 Розраховуйте прибуток від створення BID/ASK ордерів\n\n"
        "📊 Курси оновлюються в реальному часі\n"
        "🏦 Всі банки, від 5000 грн (2-й рядок)",
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
        "💰 <b>Розрахунок Market Making</b>\n\n"
        "Введіть суму в <b>гривнях</b> (мін. 5000):\n\n"
        "💡 Приклад: <code>5000</code>"
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
            f"ℹ️ <b>Binance P2P (2-й рядок):</b>\n\n"
            f"🟦 BID (купівля): <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"   └ {rates.get('buy_bank', 'N/A')}\n\n"
            f"🟥 ASK (продаж): <b>{rates['sell_rate']:.2f}</b> грн\n"
            f"   └ {rates.get('sell_bank', 'N/A')}\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн (<b>{spread_percent:.2f}%</b>)\n\n"
            f"🕐 {get_kyiv_time()}\n\n"
            "💬 @K2P_S"
        )
    else:
        await callback.message.answer(f"❌ Помилка: {rates['error']}")
    
    await callback.answer()

@dp.callback_query(F.data == "channel")
async def cb_channel(callback: CallbackQuery):
    caption = (
        "🔥 <b>P2P CEH</b> — Твій дохід у P2P!\n\n"
        "💸 <b>Що всередині:</b>\n"
        "├ Робочі схеми \n"
        "├ Прибуток 4-6% на угоду\n"
        "├ Безпечні стратегії\n"
        "└ Підтримка 24/7\n\n"
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
            await callback.answer("❌ Дані втрачено. Зробіть новий розрахунок.")
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
        
        await state.update_data(amount=amount)
        await callback.answer("✅ Оновлено!")
        logger.info(f"User {callback.from_user.id} refreshed: {amount} UAH")
        
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        await callback.answer("❌ Помилка")

@dp.callback_query(F.data == "new")
async def cb_new(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🔵 <b>Binance P2P Market Making</b>\n\n"
        "💰 Розраховуйте прибуток від створення BID/ASK ордерів\n\n"
        "📊 Курси оновлюються в реальному часі\n"
        "🏦 Всі банки, від 5000 грн (2-й рядок)",
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
        
        logger.info(f"User {message.from_user.id}: {amount} UAH -> {calc['profit']} UAH spread")
        
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

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

# Логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ініціалізація бота (ТОКЕН З ENVIRONMENT VARIABLES!)
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"), parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Глобальна сесія aiohttp
session = None


# ========== FSM СТАНИ ==========

class BuyState(StatesGroup):
    waiting_for_amount = State()

class SellState(StatesGroup):
    waiting_for_amount = State()


# ========== ФУНКЦІЇ ОТРИМАННЯ КУРСІВ ==========

async def get_binance_rates():
    """Отримання курсів з Binance P2P"""
    try:
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        
        # Курс купівлі USDT (ми купуємо = продавці продають)
        buy_payload = {
            "asset": "USDT",
            "fiat": "UAH",
            "merchantCheck": True,
            "page": 1,
            "rows": 1,
            "tradeType": "SELL",  # Продавці ПРОДАЮТЬ нам USDT
            "transAmount": "5000"
        }
        
        async with session.post(url, json=buy_payload) as response:
            buy_data = await response.json()
            buy_rate = float(buy_data["data"][0]["adv"]["price"])
        
        # Курс продажу USDT (ми продаємо = покупці купують)
        sell_payload = {
            "asset": "USDT",
            "fiat": "UAH",
            "merchantCheck": True,
            "page": 1,
            "rows": 1,
            "tradeType": "BUY",  # Покупці КУПУЮТЬ у нас USDT
            "transAmount": "5000"
        }
        
        async with session.post(url, json=sell_payload) as response:
            sell_data = await response.json()
            sell_rate = float(sell_data["data"][0]["adv"]["price"])
        
        return {
            "success": True,
            "buy_rate": buy_rate,  # За скільки МИ купуємо USDT
            "sell_rate": sell_rate  # За скільки МИ продаємо USDT
        }
        
    except Exception as e:
        logger.error(f"Помилка отримання курсів: {e}")
        return {"success": False, "error": str(e)}


# ========== РОЗРАХУНКИ ==========

def calculate_buy(amount, buy_rate, sell_rate):
    """Розрахунок для КУПІВЛІ USDT"""
    # Скільки USDT купимо
    usdt_bought = amount / buy_rate
    
    # Скільки грн отримаємо при продажі
    uah_received = usdt_bought * sell_rate
    
    # Прибуток
    profit = uah_received - amount
    profit_percent = (profit / amount) * 100
    
    return {
        "usdt": round(usdt_bought, 2),
        "received": round(uah_received, 2),
        "profit": round(profit, 2),
        "percent": round(profit_percent, 2)
    }


def calculate_sell(amount, buy_rate, sell_rate):
    """Розрахунок для ПРОДАЖУ USDT"""
    # Скільки USDT потрібно продати щоб отримати amount грн
    usdt_to_sell = amount / sell_rate
    
    # Скільки грн витратимо на купівлю цих USDT
    uah_spent = usdt_to_sell * buy_rate
    
    # Прибуток
    profit = amount - uah_spent
    profit_percent = (profit / uah_spent) * 100 if uah_spent > 0 else 0
    
    return {
        "usdt": round(usdt_to_sell, 2),
        "spent": round(uah_spent, 2),
        "profit": round(profit, 2),
        "percent": round(profit_percent, 2)
    }


# ========== ФОРМАТУВАННЯ ==========

def format_buy_result(amount, rates, calc):
    """Форматування результату КУПІВЛІ"""
    profit_emoji = "🟢" if calc["profit"] > 0 else "🔴"
    
    return f"""
💰 <b>Купівля USDT → Продаж USDT</b>

📊 <b>Курси Binance P2P:</b>
• 🛒 Купівля USDT: <b>{rates['buy_rate']:.2f}</b> грн
• 💸 Продаж USDT: <b>{rates['sell_rate']:.2f}</b> грн

💵 <b>Ваша сума:</b> {amount:,.0f} грн

📈 <b>Розрахунок:</b>
1️⃣ Купуєте <b>{calc['usdt']}</b> USDT за {amount:,.0f} грн
2️⃣ Продаєте <b>{calc['usdt']}</b> USDT за {calc['received']:,.2f} грн

{profit_emoji} <b>Прибуток:</b> {calc['profit']:,.2f} грн ({calc['percent']:.2f}%)

🕐 Оновлено: {datetime.now().strftime("%H:%M:%S")}
"""


def format_sell_result(amount, rates, calc):
    """Форматування результату ПРОДАЖУ"""
    profit_emoji = "🟢" if calc["profit"] > 0 else "🔴"
    
    return f"""
💸 <b>Купівля USDT → Продаж USDT</b>

📊 <b>Курси Binance P2P:</b>
• 🛒 Купівля USDT: <b>{rates['buy_rate']:.2f}</b> грн
• 💸 Продаж USDT: <b>{rates['sell_rate']:.2f}</b> грн

💵 <b>Бажана сума:</b> {amount:,.0f} грн

📈 <b>Розрахунок:</b>
1️⃣ Купуєте <b>{calc['usdt']}</b> USDT за {calc['spent']:,.2f} грн
2️⃣ Продаєте <b>{calc['usdt']}</b> USDT за {amount:,.0f} грн

{profit_emoji} <b>Прибуток:</b> {calc['profit']:,.2f} грн ({calc['percent']:.2f}%)

🕐 Оновлено: {datetime.now().strftime("%H:%M:%S")}
"""


# ========== КЛАВІАТУРИ ==========

def main_kb():
    """Головна клавіатура"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купити USDT", callback_data="buy")],
        [InlineKeyboardButton(text="💸 Продати USDT", callback_data="sell")],
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
        "💡 Оберіть дію:",
        reply_markup=main_kb()
    )
    logger.info(f"👤 User {message.from_user.id} (@{message.from_user.username})")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обробник команди /help"""
    await message.answer(
        "📚 <b>Довідка:</b>\n\n"
        "🛒 <b>Купити USDT</b> - розрахунок прибутку при купівлі USDT за гривні та подальшому продажу\n\n"
        "💸 <b>Продати USDT</b> - розрахунок скільки потрібно USDT для отримання бажаної суми\n\n"
        "🔄 <b>Оновити курси</b> - отримати актуальні курси Binance P2P\n\n"
        "⚡️ <b>Курси оновлюються в реальному часі з Binance P2P</b>\n\n"
        "❓ Питання: @your_support",
        reply_markup=main_kb()
    )


@dp.message(Command("info"))
async def cmd_info(message: Message):
    """Обробник команди /info"""
    rates = await get_binance_rates()
    
    if rates["success"]:
        spread = rates["sell_rate"] - rates["buy_rate"]
        spread_percent = (spread / rates["buy_rate"]) * 100
        
        await message.answer(
            "ℹ️ <b>Інформація про курси:</b>\n\n"
            f"🛒 Купівля USDT: <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"💸 Продаж USDT: <b>{rates['sell_rate']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн ({spread_percent:.2f}%)\n\n"
            f"🕐 Оновлено: {datetime.now().strftime('%H:%M:%S')}\n\n"
            "⚡️ Дані з Binance P2P в реальному часі",
            reply_markup=main_kb()
        )
    else:
        await message.answer(f"❌ Помилка отримання курсів: {rates['error']}")


# ========== ОБРОБНИКИ CALLBACK ==========

@dp.callback_query(F.data == "buy")
async def process_buy(callback: CallbackQuery, state: FSMContext):
    """Обробник кнопки 'Купити USDT'"""
    await callback.message.answer(
        "🛒 <b>Купівля USDT</b>\n\n"
        "Введіть суму в <b>гривнях</b>, яку хочете витратити на купівлю USDT:\n\n"
        "💡 Приклад: <code>5000</code>"
    )
    await state.set_state(BuyState.waiting_for_amount)
    await callback.answer()


@dp.callback_query(F.data == "sell")
async def process_sell(callback: CallbackQuery, state: FSMContext):
    """Обробник кнопки 'Продати USDT'"""
    await callback.message.answer(
        "💸 <b>Продаж USDT</b>\n\n"
        "Введіть суму в <b>гривнях</b>, яку хочете отримати після продажу USDT:\n\n"
        "💡 Приклад: <code>5000</code>"
    )
    await state.set_state(SellState.waiting_for_amount)
    await callback.answer()


@dp.callback_query(F.data == "info")
async def process_info(callback: CallbackQuery):
    """Обробник кнопки 'Інфо'"""
    rates = await get_binance_rates()
    
    if rates["success"]:
        spread = rates["sell_rate"] - rates["buy_rate"]
        spread_percent = (spread / rates["buy_rate"]) * 100
        
        await callback.message.answer(
            "ℹ️ <b>Інформація про курси:</b>\n\n"
            f"🛒 Купівля USDT: <b>{rates['buy_rate']:.2f}</b> грн\n"
            f"💸 Продаж USDT: <b>{rates['sell_rate']:.2f}</b> грн\n\n"
            f"📊 Спред: <b>{spread:.2f}</b> грн ({spread_percent:.2f}%)\n\n"
            f"🕐 Оновлено: {datetime.now().strftime('%H:%M:%S')}\n\n"
            "⚡️ Дані з Binance P2P в реальному часі",
            reply_markup=main_kb()
        )
    else:
        await callback.message.answer(f"❌ Помилка: {rates['error']}")
    
    await callback.answer()


@dp.callback_query(F.data == "refresh")
async def refresh_rates(callback: CallbackQuery, state: FSMContext):
    """Оновлення курсів"""
    try:
        data = await state.get_data()
        amount = data.get("amount")
        operation = data.get("operation")  # "buy" або "sell"
        
        if not amount or not operation:
            await callback.answer("❌ Помилка: дані втрачено")
            return
        
        # Отримуємо нові курси
        rates = await get_binance_rates()
        
        if not rates["success"]:
            await callback.answer(f"❌ Помилка: {rates['error']}")
            return
        
        # Розрахунок залежно від операції
        if operation == "buy":
            calc = calculate_buy(amount, rates["buy_rate"], rates["sell_rate"])
            text = format_buy_result(amount, rates, calc)
        else:
            calc = calculate_sell(amount, rates["buy_rate"], rates["sell_rate"])
            text = format_sell_result(amount, rates, calc)
        
        # Оновлюємо повідомлення
        await callback.message.edit_text(text, reply_markup=action_kb())
        await callback.answer("✅ Курси оновлено!")
        
        logger.info(f"🔄 User {callback.from_user.id} оновив курси")
        
    except Exception as e:
        logger.error(f"Помилка в refresh: {e}")
        await callback.answer("❌ Помилка")


@dp.callback_query(F.data == "new")
async def new_calculation(callback: CallbackQuery, state: FSMContext):
    """Новий розрахунок"""
    await state.clear()
    await callback.message.answer(
        "💡 Оберіть дію:",
        reply_markup=main_kb()
    )
    await callback.answer()


# ========== ОБРОБНИКИ СУММ ==========

@dp.message(BuyState.waiting_for_amount)
async def process_buy_amount(message: Message, state: FSMContext):
    """Обробка суми для купівлі"""
    try:
        amount = float(message.text.replace(",", "").replace(" ", ""))
        
        if amount <= 0:
            return await message.answer("❌ Сума має бути більше 0!")
        
        # Зберігаємо суму та операцію
        await state.update_data(amount=amount, operation="buy")
        await state.clear()
        
        # Отримуємо курси
        rates = await get_binance_rates()
        
        if not rates["success"]:
            return await message.answer(f"❌ Помилка: {rates['error']}")
        
        # Розрахунок
        calc = calculate_buy(amount, rates["buy_rate"], rates["sell_rate"])
        
        # Відправляємо результат
        await message.answer(
            format_buy_result(amount, rates, calc),
            reply_markup=action_kb()
        )
        
        # Зберігаємо дані для refresh
        await state.update_data(amount=amount, operation="buy")
        
        logger.info(f"🛒 User {message.from_user.id}: купівля {amount} грн")
        
    except ValueError:
        await message.answer("❌ Введіть коректну суму!\n\n💡 Приклад: <code>5000</code>")


@dp.message(SellState.waiting_for_amount)
async def process_sell_amount(message: Message, state: FSMContext):
    """Обробка суми для продажу"""
    try:
        amount = float(message.text.replace(",", "").replace(" ", ""))
        
        if amount <= 0:
            return await message.answer("❌ Сума має бути більше 0!")
        
        # Зберігаємо суму та операцію
        await state.update_data(amount=amount, operation="sell")
        await state.clear()
        
        # Отримуємо курси
        rates = await get_binance_rates()
        
        if not rates["success"]:
            return await message.answer(f"❌ Помилка: {rates['error']}")
        
        # Розрахунок
        calc = calculate_sell(amount, rates["buy_rate"], rates["sell_rate"])
        
        # Відправляємо результат
        await message.answer(
            format_sell_result(amount, rates, calc),
            reply_markup=action_kb()
        )
        
        # Зберігаємо дані для refresh
        await state.update_data(amount=amount, operation="sell")
        
        logger.info(f"💸 User {message.from_user.id}: продаж для {amount} грн")
        
    except ValueError:
        await message.answer("❌ Введіть коректну суму!\n\n💡 Приклад: <code>5000</code>")


# ========== ЗАПУСК БОТА ==========

if __name__ == "__main__":
    from aiohttp import web
    
    async def health_check(request):
        """HTTP endpoint для Render"""
        return web.Response(text="✅ Bot is running!")
    
    async def main():
        """Головна функція з HTTP-сервером"""
        global session
        
        # Ініціалізація сесії
        timeout = aiohttp.ClientTimeout(total=10)
        session = aiohttp.ClientSession(timeout=timeout)
        
        # HTTP-сервер для Render
        app = web.Application()
        app.router.add_get("/", health_check)
        app.router.add_get("/health", health_check)
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        port = int(os.getenv("PORT", 10000))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        
        logger.info(f"🌐 HTTP-сервер запущено на порту {port}")
        
        # Запуск бота
        logger.info("🤖 P2P Арбітраж Бот запущений!")
        me = await bot.get_me()
        logger.info(f"🔗 @{me.username}")
        
        try:
            await dp.start_polling(bot)
        finally:
            await session.close()
            logger.info("🛑 Сесія закрита")
    
    # Запуск
    asyncio.run(main())

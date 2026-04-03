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
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
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
        
        # Курс купівлі (buy USDT за UAH)
        buy_payload = {
            "asset": "USDT",
            "fiat": "UAH",
            "merchantCheck": True,
            "page": 1,
            "rows": 10,
            "tradeType": "BUY",
            "transAmount": "5000"
        }
        
        async with session.post(url, json=buy_payload) as response:
            buy_data = await response.json()
            buy_rate = float(buy_data["data"][0]["adv"]["price"])
        
        # Курс продажу (sell USDT за UAH)
        sell_payload = {
            "asset": "USDT",
            "fiat": "UAH",
            "merchantCheck": True,
            "page": 1,
            "rows": 10,
            "tradeType": "SELL",
            "transAmount": "5000"
        }
        
        async with session.post(url, json=sell_payload) as response:
            sell_data = await response.json()
            sell_rate = float(sell_data["data"][0]["adv"]["price"])
        
        return {
            "success": True,
            "buy_rate": buy_rate,
            "sell_rate": sell_rate
        }
        
    except Exception as e:
        logger.error(f"Помилка отримання курсів: {e}")
        return {"success": False, "error": str(e)}


# ========== РОЗРАХУНКИ ==========

def calculate(amount, buy_rate, sell_rate):
    """Розрахунок арбітражу"""
    usdt_amount = amount / buy_rate
    uah_received = usdt_amount * sell_rate
    profit = uah_received - amount
    profit_percent = (profit / amount) * 100
    
    return {
        "usdt": round(usdt_amount, 2),
        "received": round(uah_received, 2),
        "profit": round(profit, 2),
        "percent": round(profit_percent, 2)
    }


# ========== ФОРМАТУВАННЯ ==========

def format_result(amount, rates, calc):
    """Форматування результату"""
    return f"""
💰 <b>Розрахунок P2P арбітражу</b>

📊 <b>Курси Binance:</b>
• Купівля: {rates['buy_rate']:.2f} грн
• Продаж: {rates['sell_rate']:.2f} грн

💵 <b>Ваша сума:</b> {amount:,.0f} грн

📈 <b>Результат:</b>
• USDT: {calc['usdt']} USDT
• Отримаєте: {calc['received']:,.2f} грн
• Прибуток: {calc['profit']:,.2f} грн ({calc['percent']:.2f}%)

🕒 {datetime.now().strftime("%H:%M:%S")}
"""


# ========== КЛАВІАТУРИ ==========

def main_kb():
    """Головна клавіатура"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Купити USDT", callback_data="buy")],
        [InlineKeyboardButton(text="💸 Продати USDT", callback_data="sell")]
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
        "🤖 Я бот для розрахунку P2P арбітражу на Binance.\n\n"
        "💡 Оберіть дію:",
        reply_markup=main_kb()
    )
    logger.info(f"👤 Новий користувач: {message.from_user.id} (@{message.from_user.username})")


# ========== ОБРОБНИКИ CALLBACK ==========

@dp.callback_query(F.data == "buy")
async def process_buy(callback: CallbackQuery, state: FSMContext):
    """Обробник кнопки 'Купити USDT'"""
    await callback.message.answer("💰 Введіть суму в <b>гривнях</b>, яку хочете витратити:\n\n"
                                    "Приклад: <code>5000</code>")
    await state.set_state(BuyState.waiting_for_amount)
    await callback.answer()


@dp.callback_query(F.data == "sell")
async def process_sell(callback: CallbackQuery, state: FSMContext):
    """Обробник кнопки 'Продати USDT'"""
    await callback.message.answer("💸 Введіть суму в <b>гривнях</b>, яку хочете отримати:\n\n"
                                    "Приклад: <code>5000</code>")
    await state.set_state(SellState.waiting_for_amount)
    await callback.answer()


@dp.callback_query(F.data == "refresh")
async def refresh_rates(callback: CallbackQuery, state: FSMContext):
    """Оновлення курсів"""
    try:
        # Отримуємо збережену суму
        data = await state.get_data()
        amount = data.get("amount", 5000)
        
        # Отримуємо нові курси
        rates = await get_binance_rates()
        
        if not rates["success"]:
            return await callback.message.answer(f"❌ Помилка: {rates['error']}")
        
        # Розрахунок
        calc = calculate(amount, rates["buy_rate"], rates["sell_rate"])
        
        # Оновлюємо повідомлення
        await callback.message.edit_text(
            format_result(amount, rates, calc),
            reply_markup=action_kb()
        )
        
        logger.info(f"🔄 User {callback.from_user.id} оновив курси")
        await callback.answer("✅ Курси оновлено!")
        
    except Exception as e:
        logger.error(f"Помилка в refresh: {e}")
        await callback.answer("❌ Помилка")


@dp.callback_query(F.data == "new")
async def new_calculation(callback: CallbackQuery):
    """Новий розрахунок"""
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
        
        # Зберігаємо суму
        await state.update_data(amount=amount)
        await state.clear()
        
        # Отримуємо курси
        rates = await get_binance_rates()
        
        if not rates["success"]:
            return await message.answer(f"❌ Помилка: {rates['error']}")
        
        # Розрахунок
        calc = calculate(amount, rates["buy_rate"], rates["sell_rate"])
        
        # Відправляємо результат
        await message.answer(
            format_result(amount, rates, calc),
            reply_markup=action_kb()
        )
        
        logger.info(f"💰 User {message.from_user.id}: {amount} грн")
        
    except ValueError:
        await message.answer("❌ Введіть коректну суму!\n\nПриклад: <code>5000</code>")


@dp.message(SellState.waiting_for_amount)
async def process_sell_amount(message: Message, state: FSMContext):
    """Обробка суми для продажу"""
    try:
        amount = float(message.text.replace(",", "").replace(" ", ""))
        
        if amount <= 0:
            return await message.answer("❌ Сума має бути більше 0!")
        
        # Зберігаємо суму
        await state.update_data(amount=amount)
        await state.clear()
        
        # Отримуємо курси
        rates = await get_binance_rates()
        
        if not rates["success"]:
            return await message.answer(f"❌ Помилка: {rates['error']}")
        
        # Розрахунок (для продажу використовуємо інвертовані курси)
        calc = calculate(amount, rates["sell_rate"], rates["buy_rate"])
        
        # Відправляємо результат
        await message.answer(
            format_result(amount, rates, calc),
            reply_markup=action_kb()
        )
        
        logger.info(f"💸 User {message.from_user.id}: {amount} грн")
        
    except ValueError:
        await message.answer("❌ Введіть коректну суму!\n\nПриклад: <code>5000</code>")


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
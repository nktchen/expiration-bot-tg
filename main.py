import asyncio
from datetime import datetime, timedelta
import sqlite3

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from decouple import config
from apscheduler.schedulers.asyncio import AsyncIOScheduler

users = [config("user1"), config("user2")]
scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
dp = Dispatcher()
connection = sqlite3.connect('products.db')
cursor = connection.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, date INTEGER)")

class CustomState(StatesGroup):
    add = State()
    watch = State()


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer("привет! здесь ты можешь добавить продукты, которые ты покупаешь в магазине, "
                         "а я пришлю тебе уведомление, когда срок годности продукта начнет истекать")



@dp.message(Command('add'))
async def command_add_handler(message: Message, state: FSMContext) -> None:
    await message.answer('перехожу в режим добавления...')
    await message.answer('присылай мне по одному товару в сообщении в формате "ПРОДУКТ ДЕНЬ МЕСЯЦ"')
    await state.set_state(CustomState.add)




@dp.message(F.text, CustomState.add)
async def add_product(message: Message, state: FSMContext) -> None:
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer('неправильный формат! пример: сметана 21 03')
        return
    name, day, month = parts[:-2], parts[-2], parts[-1]
    try:
        datetime_object = datetime(datetime.now().year, int(month), int(day))
    except ValueError:
        await message.answer("неверная дата. убедись, что день и месяц существуют.")
        return
    timestamp = datetime.timestamp(datetime_object)

    cursor.execute("INSERT INTO products (name, date) VALUES (?, ?)", (' '.join(name), timestamp))
    product_id = cursor.lastrowid
    connection.commit()

    inline_kb_edit = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='удалить!', callback_data=f'product_edit_{product_id}')]
    ])
    await message.answer(f'продукт добавлен! {message.text}', reply_markup=inline_kb_edit)


@dp.callback_query(F.data.startswith('product_edit_'))
async def process_callback_product_edit(callback_query: types.CallbackQuery):
    product_id_str = callback_query.data.replace('product_edit_', '')
    try:
        product_id = int(product_id_str)
    except ValueError:
        await callback_query.answer("ошибка: неверный ID")
        return

    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    connection.commit()

    await callback_query.answer("продукт удалён")
    await callback_query.message.edit_text("этот продукт был удалён")


async def daily_check_db(bot: Bot):
    now = datetime.now()
    deadline_days = [1, 3, 5]
    warnings = {days: [] for days in deadline_days}


    cursor.execute("SELECT name, date FROM products")
    for name, date_ts in cursor.fetchall():
        exp_date = datetime.fromtimestamp(date_ts)
        days_left = (exp_date.date() - now.date()).days
        if days_left in warnings:
            warnings[days_left].append(name)
    if not any(warnings.values()):
        return

    messages = [
        f"через {days_left} дней истекает срок:\n" +
        '\n'.join(f"• {name}" for name in names)
        for days_left, names in warnings.items() if names
    ]
    text = '\n\n'.join(messages)
    for user in users:
        await bot.send_message(user, text)


@dp.message(F.text)
async def default(message: Message) -> None:
    await message.answer(f'окак')



async def main() -> None:
    scheduler.start()
    bot = Bot(token=config("TOKEN"))
    scheduler.add_job(daily_check_db, "interval", seconds=10, args=[bot])

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

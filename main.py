import asyncio
from datetime import datetime
import sqlite3
from typing import List, Tuple

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from decouple import config
from apscheduler.schedulers.asyncio import AsyncIOScheduler

users = [config("user1"), config("user2")]
scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
bot = Bot(token=config("TOKEN"))
dp = Dispatcher()
connection = sqlite3.connect('products.db', check_same_thread=False)
cursor = connection.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, date INTEGER)")

class CustomState(StatesGroup):
    add = State()
    delete = State()


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer("привет! здесь ты можешь добавить продукты, которые ты покупаешь в магазине, "
                         "а я пришлю тебе уведомление, когда срок годности продукта начнет истекать\n"
                         "напиши /add и введи продукт со сроком годности, например сметана 20 06")


@dp.message(Command('add'))
async def command_add_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer('перехожу в режим добавления...')
    await message.answer('присылай мне по одному товару в сообщении в формате "ПРОДУКТ ДЕНЬ МЕСЯЦ"')
    await message.answer('чтобы выйти используй команду /stop')
    await state.set_state(CustomState.add)

@dp.message(Command('stop'), CustomState.add)
async def command_stop_handler(message: Message, state: FSMContext) -> None:
    await message.answer('выхожу из режима добавления...')
    await state.clear()

@dp.message(~F.text.startswith('/'), CustomState.add)
async def add_product(message: Message) -> None:
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

    inline_kb_delete = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='удалить!', callback_data=f'product_delete_{product_id}')]
    ])
    await message.answer(f'продукт добавлен! {message.text}', reply_markup=inline_kb_delete)


def get_all_products() -> list[tuple[int, str, datetime]]:
    products: List[Tuple[int, str, datetime]] = []
    cursor.execute("SELECT id, name, date FROM products")
    for product_id, name, date_ts in cursor.fetchall():
        exp_date = datetime.fromtimestamp(date_ts)
        products.append((product_id, name, exp_date))
    return products

@dp.message(Command('get_all'))
async def command_get_all_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    products: List[Tuple[int, str, datetime]] = get_all_products()
    if not products:
        await message.answer('нет продуктов!')
        return

    products = sorted(products, key=lambda product: product[2])
    await message.answer('\n'.join([f'{name} : {date.date()}' for _, name, date in products]))



@dp.message(Command('delete'))
async def command_delete_handler(message: Message, state: FSMContext) -> None:
    await state.set_state(CustomState.delete)
    products: List[Tuple[int, str, datetime]] = get_all_products()
    if not products:
        await message.answer('нет продуктов!')
        return

    inline_kb_delete = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'удалить {name} - {date.date()}!', callback_data=f'product_delete_{product_id}')]
        for product_id, name, date in products
    ])
    await message.answer("выберите продукт для удаления:", reply_markup=inline_kb_delete)




@dp.message(Command('help'))
async def help_handler(message: Message):
    await message.answer("/add — добавить продукт\n"
                         "/stop — выйти из режима добавления\n"
                         "/get_all — показать список\n"
                         "/delete - удалить продукт\n"
                         "/help — помощь")


@dp.message(F.text)
async def default(message: Message) -> None:
    await message.answer(f'окак. я не понял. /help')



@dp.callback_query(F.data.startswith('product_delete_'))
async def process_callback_product_delete(callback_query: types.CallbackQuery, state: FSMContext):
    product_id_str = callback_query.data.replace('product_delete_', '')
    try:
        product_id = int(product_id_str)
    except ValueError:
        await callback_query.answer("ошибка: неверный ID")
        return

    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    connection.commit()

    await callback_query.answer("продукт удалён")
    if await state.get_state() == CustomState.delete:
        products: List[Tuple[int, str, datetime]] = get_all_products()
        if not products:
            await callback_query.message.edit_text('нет продуктов!')
            return

        inline_kb_delete = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f'удалить {name} - {date.date()}!',
                                  callback_data=f'product_delete_{product_id}')]
            for product_id, name, date in products
        ])
        await callback_query.message.edit_text("выберите продукт для удаления:", reply_markup=inline_kb_delete)
        return
    await callback_query.message.edit_text(f"продукт {product_id} был удален")




async def daily_check_db(bot: Bot):
    now = datetime.now()
    deadline_days = [1, 3, 5]
    expired: List[Tuple[int, str, float]] = []
    warnings = {days: [] for days in deadline_days}
    today_expiring = []


    cursor.execute("SELECT id, name, date FROM products")
    for product_id, name, date_ts in cursor.fetchall():
        exp_date = datetime.fromtimestamp(date_ts)
        days_left = (exp_date.date() - now.date()).days

        if days_left in warnings:
            warnings[days_left].append(name)
        elif days_left == 0:
            today_expiring.append(name)
        elif days_left < 0:
            expired.append((product_id, name, date_ts))

    if not any(warnings.values()):
        return

    num_to_correct_day = {
        1: 'день',
        3: 'дня',
        5: 'дней',
    }

    warnings = [
        f"через {days_left} {num_to_correct_day[days_left]} истекает срок:\n" +
        '\n'.join(name for name in names)
        for days_left, names in warnings.items() if names
    ]
    if today_expiring:
        today_text = "сегодня истекает срок годности:\n" + '\n'.join(today_expiring)
        warnings.insert(0, today_text)
    warnings_msg = '\n\n'.join(warnings)

    for user in users:
        await bot.send_message(user, warnings_msg)
        for product_id, name, date_ts in expired:
            inline_kb_delete = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='удалить!', callback_data=f'product_delete_{product_id}')]
            ])
            await bot.send_message(user,
                                   f"{name} испортилось {datetime.fromtimestamp(date_ts).date()}\n",
                                   reply_markup=inline_kb_delete)


async def main() -> None:
    scheduler.start()
    scheduler.add_job(daily_check_db, "cron", hour=10, minute=0, args=[bot])

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

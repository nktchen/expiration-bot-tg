import asyncio
from datetime import datetime
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message
from decouple import config
from apscheduler.schedulers.asyncio import AsyncIOScheduler


scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
dp = Dispatcher()
connection = sqlite3.connect('products.db')
cursor = connection.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS products (name TEXT, date INTEGER)")

class CustomState(StatesGroup):
    add = State()
    watch = State()


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer("привет! здесь ты можешь добавить продукты, которые ты покупаешь в магазине, "
                         "а я пришлю тебе уведомление, когда срок годности продукта начнет истекать")



@dp.message(Command('add'))
async def cmd_start_3(message: Message, state: FSMContext) -> None:
    await message.answer('перехожу в режим добавления...')
    await message.answer('присылай мне по одному товару в сообщении в формате "ПРОДУКТ ДЕНЬ МЕСЯЦ"')
    await state.set_state(CustomState.add)



@dp.message(F.text, CustomState.add)
async def add_product(message: Message, state: FSMContext) -> None:
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer('неправильный формат! пример: сметана 21 03')
        return
    name, day, month = parts[0], parts[1], parts[2]
    try:
        datetime_object = datetime(datetime.now().year, int(month), int(day))
    except ValueError:
        await message.answer("неверная дата. убедись, что день и месяц существуют.")
        return
    timestamp = datetime.timestamp(datetime_object)

    cursor.execute("INSERT INTO products VALUES (?, ?)", (name, timestamp))
    connection.commit()
    await message.answer(f'Продукт добавлен! {message.text}')




@dp.message(F.text)
async def default(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(f'чееее, {message.from_user.first_name} {data.get("add")}')


async def main() -> None:
    scheduler.start()
    bot = Bot(token=config("TOKEN"))
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

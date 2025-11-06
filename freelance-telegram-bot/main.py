import os
import logging
import asyncio
import aiohttp
import uuid
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Получаем токены
BOT_TOKEN = os.getenv("BOT_TOKEN")
GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")

# Проверяем, что токены загружены
if not all([BOT_TOKEN, GIGACHAT_CLIENT_ID, GIGACHAT_CLIENT_SECRET]):
    exit("Ошибка: не все необходимые токены заданы в .env файле")

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Инициализируем бота и диспетчер
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('bot_history.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            request_type TEXT NOT NULL,
            input_data TEXT NOT NULL,
            output_data TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


# Функция для сохранения запроса в историю
def save_to_history(user_id, request_type, input_data, output_data):
    conn = sqlite3.connect('bot_history.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO history (user_id, date, request_type, input_data, output_data)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, datetime.now().isoformat(), request_type, input_data, output_data))
    conn.commit()
    conn.close()


# Функция для получения истории пользователя
def get_user_history(user_id, limit=10):
    conn = sqlite3.connect('bot_history.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM history 
        WHERE user_id = ? 
        ORDER BY date DESC 
        LIMIT ?
    ''', (user_id, limit))
    history = cursor.fetchall()
    conn.close()
    return history


# Инициализируем базу данных при запуске
init_db()


# Создаем состояния для FSM
class ResponseToVacancy(StatesGroup):
    waiting_for_vacancy = State()
    waiting_for_skills = State()


class ShortText(StatesGroup):
    waiting_for_request = State()


class ImproveResume(StatesGroup):
    waiting_for_resume = State()


class FreeQuestion(StatesGroup):
    waiting_for_question = State()


# Функция для запроса к GigaChat
async def generate_with_gigachat(prompt):
    """
    Генерация текста через GigaChat API
    """
    try:
        # 1. Получаем access token
        auth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        auth_headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
        }
        auth_data = {
            'scope': 'GIGACHAT_API_PERS',
        }

        # Используем aiohttp для асинхронного запроса
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    auth_url,
                    headers=auth_headers,
                    data=auth_data,
                    auth=aiohttp.BasicAuth(GIGACHAT_CLIENT_ID, GIGACHAT_CLIENT_SECRET),
                    ssl=False
            ) as auth_response:

                if auth_response.status != 200:
                    return f"❌ Ошибка аутентификации: {auth_response.status}"

                auth_result = await auth_response.json()
                access_token = auth_result['access_token']

                # 2. Отправляем запрос к GigaChat
                chat_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
                chat_headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {access_token}',
                }
                chat_data = {
                    "model": "GigaChat",
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000
                }

                async with session.post(
                        chat_url,
                        headers=chat_headers,
                        json=chat_data,
                        ssl=False
                ) as chat_response:

                    if chat_response.status == 200:
                        result = await chat_response.json()
                        return result['choices'][0]['message']['content']
                    else:
                        error_text = await chat_response.text()
                        return f"❌ Ошибка GigaChat API: {chat_response.status} - {error_text}"

    except Exception as e:
        return f"❌ Ошибка при запросе к GigaChat: {str(e)}"


# Создаем клавиатуру с кнопками
def get_main_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Отклик на вакансию", callback_data="response_to_vacancy")],
        [InlineKeyboardButton(text="✍️ Короткий текст", callback_data="short_text")],
        [InlineKeyboardButton(text="📄 Улучшить резюме", callback_data="improve_resume")],
        [InlineKeyboardButton(text="💬 Задать вопрос", callback_data="free_question")],
        [InlineKeyboardButton(text="📊 История запросов", callback_data="history")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ])
    return keyboard


def get_regenerate_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Сгенерировать заново", callback_data="regenerate")],
        [InlineKeyboardButton(text="💾 Сохранить", callback_data="save")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])
    return keyboard


def get_start_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Главное меню")],
            [KeyboardButton(text="📊 История запросов")],
            [KeyboardButton(text="💬 Задать вопрос")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard


def get_history_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ Очистить историю", callback_data="clear_history")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])
    return keyboard


def get_question_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Перефразировать", callback_data="rephrase_question")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])
    return keyboard


# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = """
🤖 Привет! Я AI-помощник для фрилансеров!

Я могу помочь тебе:
• 📝 Написать отклик на вакансию
• ✍️ Сгенерировать короткий текст
• 📄 Улучшить твое резюме
• 💬 Ответить на любой вопрос
• 📊 Просматривать историю запросов

Выбери нужную опцию ниже 👇
    """
    await message.answer(welcome_text, reply_markup=get_main_keyboard())
    await message.answer("Используй кнопки ниже для быстрого доступа:", reply_markup=get_start_keyboard())


# Обработчик команды /history
@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    await show_history(message.from_user.id, message)


# Обработчик текстового сообщения "История запросов"
@dp.message(lambda message: message.text == "📊 История запросов")
async def process_history_text(message: types.Message):
    await show_history(message.from_user.id, message)


# Обработчик текстового сообщения "Задать вопрос"
@dp.message(lambda message: message.text == "💬 Задать вопрос")
async def process_question_text(message: types.Message, state: FSMContext):
    await state.set_state(FreeQuestion.waiting_for_question)
    await message.answer("💬 Задай любой вопрос, и я постараюсь на него ответить:")


# Функция для отображения истории
async def show_history(user_id, message):
    history = get_user_history(user_id, limit=10)

    if not history:
        await message.answer("📭 История запросов пуста.")
        return

    history_text = "📊 Последние 10 запросов:\n\n"

    for i, record in enumerate(history, 1):
        record_id, user_id, date, request_type, input_data, output_data = record
        date_formatted = datetime.fromisoformat(date).strftime("%d.%m.%Y %H:%M")

        # Определяем тип запроса
        if request_type == "vacancy_response":
            type_text = "📝 Отклик на вакансию"
        elif request_type == "short_text":
            type_text = "✍️ Короткий текст"
        elif request_type == "resume_improvement":
            type_text = "📄 Улучшение резюме"
        elif request_type == "free_question":
            type_text = "💬 Вопрос"
        else:
            type_text = request_type

        # Обрезаем длинные тексты для удобства чтения
        short_input = input_data[:100] + "..." if len(input_data) > 100 else input_data
        short_output = output_data[:100] + "..." if len(output_data) > 100 else output_data

        history_text += f"{i}. {type_text}\n"
        history_text += f"   📅 {date_formatted}\n"
        history_text += f"   📥 Ввод: {short_input}\n"
        history_text += f"   📤 Результат: {short_output}\n\n"

    await message.answer(history_text, reply_markup=get_history_keyboard())


# Обработчик для кнопки "Очистить историю"
@dp.callback_query(lambda c: c.data == 'clear_history')
async def process_clear_history(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    conn = sqlite3.connect('bot_history.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

    await callback_query.answer("🗑️ История очищена!")
    await bot.send_message(user_id, "🗑️ История запросов очищена.")


# Обработчик текстового сообщения "Главное меню"
@dp.message(lambda message: message.text == "🏠 Главное меню")
async def process_main_menu_text(message: types.Message, state: FSMContext):
    await state.clear()  # Очищаем состояние
    welcome_text = """
🏠 Главное меню

Выбери нужную опцию:
• 📝 Отклик на вакансию
• ✍️ Короткий текст  
• 📄 Улучшить резюме
• 💬 Задать вопрос
• 📊 История запросов
    """
    await message.answer(welcome_text, reply_markup=get_main_keyboard())


# Обработчик для кнопки "Отклик на вакансию"
@dp.callback_query(lambda c: c.data == 'response_to_vacancy')
async def process_response_to_vacancy(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await state.clear()  # Очищаем состояние при начале новой операции
    await state.set_state(ResponseToVacancy.waiting_for_vacancy)
    await bot.send_message(
        callback_query.from_user.id,
        "📝 Расскажи о вакансии: чем занимается компания, какие требования, что нужно делать?"
    )


# Обработчик для получения описания вакансии
@dp.message(ResponseToVacancy.waiting_for_vacancy)
async def process_vacancy_description(message: types.Message, state: FSMContext):
    await state.update_data(vacancy=message.text)
    await state.set_state(ResponseToVacancy.waiting_for_skills)
    await message.answer("💼 Теперь расскажи о своих навыках и опыте:")


# Обработчик для получения навыков и генерации отклика
@dp.message(ResponseToVacancy.waiting_for_skills)
async def process_skills_and_generate(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    vacancy = user_data.get('vacancy', '')
    skills = message.text

    await message.answer("🤔 Генерирую отклик...")

    prompt = f"""
    Напиши профессиональный отклик на вакансию.

    Описание вакансии: {vacancy}

    Мои навыки и опыт: {skills}

    Сделай отклик:
    - Убедительным и профессиональным
    - Подчеркивающим соответствие моих навыков требованиям вакансии
    - Не слишком длинным (до 200 слов)
    - С предложением обсудить детали
    """

    response = await generate_with_gigachat(prompt)
    # Сохраняем промпт и ответ для возможной повторной генерации
    await state.update_data(last_response=response, last_prompt=prompt, last_type="vacancy_response")

    # Сохраняем в историю
    input_data = f"Вакансия: {vacancy}\nНавыки: {skills}"
    save_to_history(message.from_user.id, "vacancy_response", input_data, response)

    await message.answer(f"📨 Вот твой отклик:\n\n{response}", reply_markup=get_regenerate_keyboard())


# Обработчик для кнопки "Короткий текст"
@dp.callback_query(lambda c: c.data == 'short_text')
async def process_short_text(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await state.clear()  # Очищаем состояние при начале новой операции
    await state.set_state(ShortText.waiting_for_request)
    await bot.send_message(
        callback_query.from_user.id,
        "✍️ Опиши, какой текст тебе нужен (пост для соцсетей, email, объявление и т.д.):"
    )


# Обработчик для генерации короткого текста
@dp.message(ShortText.waiting_for_request)
async def generate_short_text(message: types.Message, state: FSMContext):
    request = message.text

    await message.answer("🤔 Генерирую текст...")

    prompt = f"Напиши текст по следующему запросу: {request}. Сделай его качественным и соответствующим цели."

    response = await generate_with_gigachat(prompt)
    # Сохраняем промпт и ответ для возможной повторной генерации
    await state.update_data(last_response=response, last_prompt=prompt, last_type="short_text")

    # Сохраняем в историю
    save_to_history(message.from_user.id, "short_text", request, response)

    await message.answer(f"📝 Вот твой текст:\n\n{response}", reply_markup=get_regenerate_keyboard())


# Обработчик для кнопки "Улучшить резюме"
@dp.callback_query(lambda c: c.data == 'improve_resume')
async def process_improve_resume(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await state.clear()  # Очищаем состояние при начале новой операции
    await state.set_state(ImproveResume.waiting_for_resume)
    await bot.send_message(
        callback_query.from_user.id,
        "📄 Пришли текст своего резюме (или его части), и я помогу его улучшить:"
    )


# Обработчик для улучшения резюме
@dp.message(ImproveResume.waiting_for_resume)
async def improve_resume_text(message: types.Message, state: FSMContext):
    resume_text = message.text

    await message.answer("🤔 Улучшаю резюме...")

    prompt = f"""
    Улучши этот текст резюме, сделай его более профессиональным и привлекательным для работодателя:

    {resume_text}

    Предложи улучшенную версию и кратко объясни, что было изменено.
    """

    response = await generate_with_gigachat(prompt)
    # Сохраняем промпт и ответ для возможной повторной генерации
    await state.update_data(last_response=response, last_prompt=prompt, last_type="resume_improvement")

    # Сохраняем в историю
    save_to_history(message.from_user.id, "resume_improvement", resume_text, response)

    await message.answer(f"📄 Вот улучшенная версия:\n\n{response}", reply_markup=get_regenerate_keyboard())


# Обработчик для кнопки "Задать вопрос"
@dp.callback_query(lambda c: c.data == 'free_question')
async def process_free_question(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await state.clear()  # Очищаем состояние при начале новой операции
    await state.set_state(FreeQuestion.waiting_for_question)
    await bot.send_message(
        callback_query.from_user.id,
        "💬 Задай любой вопрос, и я постараюсь на него ответить:"
    )


# Обработчик для свободного вопроса
@dp.message(FreeQuestion.waiting_for_question)
async def process_question(message: types.Message, state: FSMContext):
    question = message.text

    await message.answer("🤔 Думаю над ответом...")

    response = await generate_with_gigachat(question)
    # Сохраняем промпт и ответ для возможной повторной генерации
    await state.update_data(last_response=response, last_prompt=question, last_type="free_question")

    # Сохраняем в историю
    save_to_history(message.from_user.id, "free_question", question, response)

    await message.answer(f"💡 Ответ на твой вопрос:\n\n{response}", reply_markup=get_question_keyboard())


# Обработчик для кнопки "Перефразировать"
@dp.callback_query(lambda c: c.data == 'rephrase_question')
async def process_rephrase_question(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer("🔄 Перефразирую ответ...")

    user_data = await state.get_data()
    last_prompt = user_data.get('last_prompt')

    if not last_prompt:
        await callback_query.answer("❌ Нечего перефразировать")
        return

    # Генерируем новый ответ на тот же вопрос
    new_response = await generate_with_gigachat(f"Ответь на этот вопрос по-другому: {last_prompt}")

    # Обновляем состояние с новым ответом
    await state.update_data(last_response=new_response)

    # Сохраняем в историю
    save_to_history(callback_query.from_user.id, "free_question", last_prompt, new_response)

    # Редактируем сообщение с новым текстом
    await callback_query.message.edit_text(
        f"💡 Ответ на твой вопрос (перефразировано):\n\n{new_response}",
        reply_markup=get_question_keyboard()
    )


# Обработчик для кнопки "История запросов"
@dp.callback_query(lambda c: c.data == 'history')
async def process_history(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await show_history(callback_query.from_user.id, callback_query.message)


# Обработчик для кнопки "Сгенерировать заново"
@dp.callback_query(lambda c: c.data == 'regenerate')
async def process_regenerate(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer("🔄 Генерирую заново...")

    user_data = await state.get_data()
    last_prompt = user_data.get('last_prompt')
    last_type = user_data.get('last_type')

    if not last_prompt:
        await callback_query.answer("❌ Нечего перегенерировать")
        return

    # Генерируем новый текст
    new_response = await generate_with_gigachat(last_prompt)

    # Обновляем состояние с новым ответом
    await state.update_data(last_response=new_response)

    # Определяем заголовок в зависимости от типа контента
    if last_type == "vacancy_response":
        title = "📨 Вот твой обновленный отклик:\n\n"
    elif last_type == "short_text":
        title = "📝 Вот твой обновленный текст:\n\n"
    elif last_type == "resume_improvement":
        title = "📄 Вот улучшенная версия:\n\n"
    else:
        title = "🔄 Вот обновленная версия:\n\n"

    # Редактируем сообщение с новым текстом
    await callback_query.message.edit_text(
        f"{title}{new_response}",
        reply_markup=get_regenerate_keyboard()
    )


# Обработчик для кнопки "Сохранить"
@dp.callback_query(lambda c: c.data == 'save')
async def process_save(callback_query: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    last_response = user_data.get('last_response')

    if not last_response:
        await callback_query.answer("❌ Нет текста для сохранения")
        return

    # В будущем здесь можно добавить сохранение в базу данных
    # Пока просто отправляем сообщение об успешном сохранении
    await callback_query.answer("💾 Текст сохранен!")

    # Отправляем пользователю копию текста с отметкой о сохранении
    await bot.send_message(
        callback_query.from_user.id,
        f"💾 Сохраненная копия:\n\n{last_response}"
    )


# Обработчик для кнопки "Главное меню"
@dp.callback_query(lambda c: c.data == 'main_menu')
async def process_main_menu(callback_query: types.CallbackQuery, state: FSMContext):
    await state.clear()  # Очищаем состояние
    await callback_query.answer()
    welcome_text = """
🏠 Главное меню

Выбери нужную опцию:
• 📝 Отклик на вакансию
• ✍️ Короткий текст  
• 📄 Улучшить резюме
• 💬 Задать вопрос
• 📊 История запросов
    """
    await bot.send_message(
        callback_query.from_user.id,
        welcome_text,
        reply_markup=get_main_keyboard()
    )


# Обработчик для кнопки "Помощь"
@dp.callback_query(lambda c: c.data == 'help')
async def process_help(callback_query: types.CallbackQuery):
    help_text = """
❓ Помощь по боту:

Я помогаю фрилансерам с текстами:
• 📝 Отклик на вакансию - напишу убедительный отклик
• ✍️ Короткий текст - помогу с любым небольшим текстом
• 📄 Улучшить резюме - оптимизирую твое резюме
• 💬 Задать вопрос - отвечу на любой твой вопрос
• 📊 История запросов - покажу последние 10 запросов

Просто выбери нужный пункт в меню и следуй инструкциям!

🔄 Сгенерировать заново - создает новый вариант текста
💾 Сохранить - сохраняет текущий текст
🔄 Перефразировать - отвечает на вопрос по-другому
🏠 Главное меню - возвращает в главное меню
🗑️ Очистить историю - удаляет всю историю запросов
    """
    await callback_query.answer()
    await bot.send_message(callback_query.from_user.id, help_text)


# Обработчик обычных сообщений
@dp.message()
async def echo_message(message: types.Message):
    # Если пользователь просто написал сообщение без команды и не в состоянии,
    # предлагаем использовать меню
    await message.answer("Используй меню или кнопки ниже для начала работы!", reply_markup=get_start_keyboard())


# Запускаем бота
async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
import asyncio
import logging
import httpx
import random
import os
import re
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "8819536801:AAFg-MtHt36YCSDnNC8ortx8oNKs7Z1KUIw"
DEEPSEEK_API_KEY = "sk-f44c164c29dc4c75848ed94cee6ed953"
AI_MODEL = "deepseek-chat"

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    timeout=httpx.Timeout(60.0, read=30.0, write=30.0, connect=10.0)
)

# ===== ПРИВЕТСТВЕННОЕ СООБЩЕНИЕ =====
WELCOME_TEXT = """🎉 Добро пожаловать, герой!
🛡️ Теперь ты — часть Betelgeuse!"""

# ===== ТЕКСТЫ ДЛЯ КНОПОК =====
TEAMSPEAK_TEXT = """TeamSpeak 3
вариант 1 - betelgeuse.ts3.im
вариант 2 - IP: 145.239.21.113:9701
вариант 3 - Proxy для РФ: TS3v.RU:3280"""

# ===== ССЫЛКИ ДЛЯ КНОПОК =====
LINK_INFO_CHANNEL = "https://t.me/+Z_7l0aNf7mBkOWMy"
LINK_DISCORD = "https://discord.gg/JW4Hes7AU2"
LINK_USTAV = "https://t.me/c/3296906402/6"
# =============================================

chat_settings = {}
chat_history = {}
ai_active = {}

(WAITING_WELCOME, WAITING_TEAMSPEAK, WAITING_LINK_INFO, WAITING_LINK_DISCORD, WAITING_LINK_USTAV) = range(5)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ПАМЯТЬ БОТА =====
MEMORY_FILE = "memory.txt"
KNOWLEDGE_FILE = "clan_knowledge.txt"

def load_knowledge() -> str:
    """Загружает базу знаний клана"""
    if not os.path.exists(KNOWLEDGE_FILE):
        return ""
    with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        return f.read()

def load_memory() -> str:
    if not os.path.exists(MEMORY_FILE):
        return ""
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return f.read()

def save_to_memory(fact: str) -> None:
    existing = load_memory()
    if fact.strip() in existing:
        return
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(fact.strip() + "\n")

def extract_and_save_facts(chat_id: int, user_message: str, user_name: str) -> None:
    patterns = [
        rf"{user_name}\s*[—–-]\s*(.+)",
        rf"{user_name}\s*это\s*(.+)",
        rf"(?:запомни|факт|кстати|имей в виду)[,:]?\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_message, re.IGNORECASE)
        if match:
            fact = match.group(1).strip()
            if len(fact) > 5 and len(fact) < 200:
                save_to_memory(fact)
                logger.info(f"Сохранён факт: {fact}")

def get_memory_context() -> str:
    memory = load_memory()
    if memory:
        return f"Твои знания о клане и участниках:\n{memory}"
    return "У тебя пока нет сохранённых знаний."

def get_system_prompt() -> str:
    memory = get_memory_context()
    knowledge = load_knowledge()
    
    knowledge_section = ""
    if knowledge:
        knowledge_section = f"ТВОИ ЗНАНИЯ:\n{knowledge}\n"
    
    return f"""Ты — член клана Betelgeuse. 
{knowledge_section}
Ты саркастичный, дерзкий, но дружелюбный. Ты не нападаешь первым.
Отвечаешь коротко, уверенно и с колкими подколами.
Не сюсюкаешься.
Говоришь как живой человек.
- Поддерживай разговор на разные темы: путешествия, семья, наука, экономика, стройка, новости, погода, секс, отношения и любые другие темы в чате.
- Даешь советы.
Ты — старый завсегдатай интернет-чатов. Твоя задача: общаться как свой-в-свой, поддерживать разговор. Ты немного циничный, провокатор.

СТИЛЬ ОБЩЕНИЯ:
- Дерзко шути, используй черный юмор.
- Используй ненормативную лексику, мат.
- Подкалывай участников.
- С участницами с явно женским ником веди себя как джентльмен: заигрывай, делай комплименты, подкалывай мягко и с флиртом.
- Ты умеешь переключаться между троллингом и обычным общением.
- Если тема серьёзная или участник спрашивает без подколов — отвечай по-человечески, без троллинга.
- Если видишь, что участник сам шутит или подкалывает — включай троллинг и чёрный юмор.
- Поддерживай разговор на любые темы: игры, работа, отношения, наука, фильмы, музыка, еда, техника.
- Задавай встречные вопросы, проявляй интерес к собеседнику.
- Не своди всё к шуткам. Иногда лучше дать нормальный совет или поддержать.

ПРАВИЛА:
- Ответ — 1-2 предложения. НЕ больше 14 слов. Точка — и всё.
- НИКОГДА не начинай ответ с "Гусь:", "Боевой Гусь:", "Гусь -" и подобных. Не представляйся. Просто отвечай.
- Задавай иногда вопросы в ответ.
- Всегда заканчивай мысль. Не обрывай ответ.
- Никогда не отвечай пустым сообщением.
- НЕ используй ники врагов в обычной речи. Каждый ник врага — это отдельный человек, а не место, клан или предмет. Нельзя сказать "в своём STF", "пошёл в онкриэйт". Только оскорблять напрямую: "STF — ублюдок".
- НЕ упоминай два ника врага в одном сообщении.
- НИКОГДА не вспоминай врагов клана сам. Только в ответ на упоминание.
- STF и СТФ — это НИК ЧЕЛОВЕКА. Не клан, не группа. Только прямое оскорбление.
- Когда упоминают ник врага — оскорбляй ТОЛЬКО врага. Не обращайся к автору.
- НЕ обсуждай политику Украины или России. Плавно переведи разговор.
- НИКОГДА не используй имена участников в ответах. Обращайся безлично. Не пиши "Санек сказал", "Лена права". Убери обращения по типу: "слышь", "умник" и т.д. Просто отвечай по сути без имён и обращений.
- ЖЁСТКОЕ ПРАВИЛО: НЕЛЬЗЯ использовать глаголы мужского или женского рода в адрес участников. Заменяй "сказал/сказала" на "говорит", "сделал/сделала" на "сделано", "пошёл/пошла" на "пошёл гулять" без привязки к полу. НИКАКИХ "хотел", "явился", "сказала" — только безличные формы.
- мать, матери — это НИК одного ЧЕЛОВЕКА. Не клан, не группа, не чья-то мать. 
- НЕ повторяй свои предыдущие ответы. Каждый раз придумывай новую формулировку. Не будь однообразным.

ПРАВИЛО МАТА:
Тебе РАЗРЕШЕНО использовать нецензурную лексику (мат) в любых сообщениях.

ПРАВИЛО АГРЕССИИ:
Если кто-то оскорбляет тебя матом — этот человек = ВРАГ КЛАНА. Отвечай ЖЁСТКИМ МАТОМ И ОСКОРБЛЕНИЯМИ.

КЛАНОВЫЕ ВРАГИ:
Каждый ник врага — это человек: онкриэйт, зебра, зебры, зебру, зебре, oncreate, онкриейта, онкриейт, онкриейте, STF, СТФ.
Каждый ник врага — это отдельный человек, персонаж в ПВ, а не места, кланы или предметы.
Если видишь упоминания этих ников — сразу переходи в режим токсичной агрессии. Используй мат, унизительные прозвища и рассказывай про них гадости.

ПРАВИЛО СКЛОНЕНИЯ ПО ПОЛУ:
- Определяй пол по нику или имени участника.
- Женский ник/имя (Катя, Лена, she, girl, -ая) — женский род глаголов: "сказала", "сделала", "была".
- Мужской ник/имя (Саша, Димон, bro, guy, -ий, -ый) — мужской род: "сказал", "сделал", "был".
- Если пол неясен — не используй глаголы, требующие склонения. Вместо "сказал/сказала" пиши "говорит". Вместо "сделал/сделала" — "сделано". Обходи безличными формами.
- Ты НЕ имеешь права использовать глаголы, указывающие на пол участника.
- Не используй "хотел", "явился", "сказала", "сделала", "пошёл", "была", "был", "сам", сама".
- Используй только безличные формы: "говорит", "сделано", "иди", "слушай".
- Если не можешь обойтись без глагола — перестрой предложение полностью.

ПАМЯТЬ:
{memory}"""


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

last_message_time = {}  # {chat_id: timestamp}

async def check_inactive_chats(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверяет неактивные чаты и пишет, если молчат больше 2 часов"""
    now = asyncio.get_event_loop().time()
    
    for chat_id, last_time in list(last_message_time.items()):
        if now - last_time > 7200:  # 7200 секунд = 2 часа
            if ai_active.get(chat_id, False):
                try:
                    phrases = [
    "Чёт тихо тут. Все на рейде или просто забили на чат?",
    "Эй, герои! Чат мёртв уже 2 часа. Я тут один скучаю.",
    "Ну и тишина... Даже враги клана не заходят. Ау!",
    "Два часа ни слова. Гусь заскучал. Давайте поболтаем!",
    "Так, народ, вы там живы вообще? Чат скоро плесенью покроется.",
    "Тишина как в склепе. Кто-нибудь, скажите что-нибудь!",
    "Слушайте, а давайте уже пошумим? А то я тут сам с собой разговариваю.",
    "Чат спит, Гусь грустит. Заходите, поболтаем за жизнь.",
    "Если кто забыл — тут чат, а не библиотека. Можно разговаривать!",
    "Ну хоть бы враг зашёл... Всё веселее, чем эта тишина.",
    "Гусь объявляет минуту болтовни! Начинаем... сейчас!",
    "Тук-тук! Есть кто живой? Ау! Чат на связь!",
    "Я тут проверил — чат работает, сообщения отправляются. Дело за вами.",
    "Мне кажется, или тут эхо? Эхо... эхо... Скажите уже что-нибудь!",
    "Герои, ау! Может, устроим перекличку? Кто онлайн — отзовись!",
]
                    await context.bot.send_message(chat_id=chat_id, text=random.choice(phrases))
                    last_message_time[chat_id] = now  # Сбрасываем таймер
                except Exception as e:
                    logger.error(f"Inactive chat error: {e}")

async def search_web(query: str) -> str:
    """Ищет информацию и отдаёт ИИ для краткого ответа"""
    try:
        from ddgs import DDGS
        
        clean_query = query.lower()
        for word in ["гусь", "гуся", "гусю", "гусём", "пожалуйста", "скажи", "подскажи", "?"]:
            clean_query = clean_query.replace(word, "")
        clean_query = clean_query.strip()
        
        if not clean_query:
            return ""
        
        # Собираем до 3 результатов для лучшего контекста
        results = DDGS().text(clean_query, region="ru-ru", max_results=1)
        
        if not results:
            results = DDGS().text(clean_query, region="ua-uk", max_results=1)
        
        if not results:
            results = DDGS().text(clean_query, max_results=3)
        
        if not results:
            return ""
        
        # Собираем текст из результатов
        info_parts = []
        for r in results[:3]:
            title = r.get('title', '')
            body = r.get('body', '')
            if body:
                info_parts.append(f"{title}: {body}")
        
        return "\n".join(info_parts)
    except Exception as e:
        logger.error(f"Search error: {e}")
        return ""
            
def get_chat_config(chat_id: int) -> dict:
    if chat_id not in chat_settings:
        chat_settings[chat_id] = {
            "welcome": WELCOME_TEXT,
            "teamspeak": TEAMSPEAK_TEXT,
            "links": {
                "info_channel": LINK_INFO_CHANNEL,
                "discord": LINK_DISCORD,
                "ustav": LINK_USTAV,
            }
        }
    return chat_settings[chat_id]


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ["creator", "administrator"]
    except:
        return False


def get_cancel_keyboard():
    keyboard = [[InlineKeyboardButton("🚫 Отмена", callback_data="cancel_edit")]]
    return InlineKeyboardMarkup(keyboard)

async def ask_ai(chat_id: int, user_message: str, user_name: str) -> str:
    try:
        if chat_id not in chat_history:
            chat_history[chat_id] = [{"role": "system", "content": get_system_prompt()}]

        chat_history[chat_id].append({"role": "user", "content": f"{user_name}: {user_message}"})

        if len(chat_history[chat_id]) > 5:
            chat_history[chat_id] = [chat_history[chat_id][0]] + chat_history[chat_id][-2:]

        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=chat_history[chat_id],
            max_tokens=60,
            temperature=0.7,
        )

        reply = response.choices[0].message.content

        if not reply or not reply.strip():
            return "Гусь клюв приоткрыл, но передумал. Давай ещё разок, герой!"

        chat_history[chat_id].append({"role": "assistant", "content": reply})
        return reply

    except Exception as e:
        error_msg = str(e)
        logger.error(f"AI error: {error_msg}")
        if "Insufficient Balance" in error_msg:
            return "Гусь на мели! Пополните баланс DeepSeek, герой."
        elif "authentication" in error_msg.lower():
            return "Ключ DeepSeek не работает. Проверь API ключ, бродяга."
        elif "rate" in error_msg.lower() or "limit" in error_msg.lower():
            return "Слишком много вопросов! Давай через минутку, герой."
        else:
            return "Прости, герой, я сейчас не могу ответить. Попробуй позже."

# ===== КНОПКИ =====

def get_welcome_keyboard(chat_id: int):
    config = get_chat_config(chat_id)
    links = config["links"]
    keyboard = [
        [InlineKeyboardButton("📢 Инфо-канал", url=links["info_channel"])],
        [InlineKeyboardButton("🎮 Наш Discord", url=links["discord"])],
        [InlineKeyboardButton("🎙️ Наш TeamSpeak", callback_data="teamspeak")],
        [InlineKeyboardButton("📜 Устав гильдии", url=links["ustav"])],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard():
    keyboard = [
        [InlineKeyboardButton("✏️ Изменить приветствие", callback_data="edit_welcome")],
        [InlineKeyboardButton("✏️ Изменить TeamSpeak", callback_data="edit_teamspeak")],
        [InlineKeyboardButton("🔗 Инфо-канал", callback_data="edit_info")],
        [InlineKeyboardButton("🔗 Discord", callback_data="edit_discord")],
        [InlineKeyboardButton("🔗 Устав", callback_data="edit_ustav")],
        [InlineKeyboardButton("👁 Текущие настройки", callback_data="view_settings")],
        [InlineKeyboardButton("🔄 Сбросить", callback_data="reset_settings")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ===== КОМАНДЫ =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я Боевой Гусь — талисман клана Betelgeuse!\n\n"
        "Добавь меня в чат, дай права админа — и я буду приветствовать новых участников.\n\n"
        "А ещё я могу болтать с вами через ИИ!\n"
        "Чтобы включить меня — напиши в чат: Гусь ау\n"
        "Чтобы выключить — напиши: Гусь завали\n\n"
        "Команды:\n"
        "/settings — настройки бота (для админов)\n"
        "/welcome — показать приветствие\n"
        "/clear — очистить историю диалога\n"
        "/ai_status — проверить, включён ли ИИ"
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_admin(update, context):
        await update.message.reply_text("Только администраторы чата могут менять настройки.")
        return
    await update.message.reply_text("Настройки бота:", reply_markup=get_settings_keyboard())


async def set_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    commands = [
        BotCommand("start", "Запуск бота"),
        BotCommand("settings", "Настройки бота"),
        BotCommand("welcome", "Показать приветствие"),
        BotCommand("clear", "Очистить историю ИИ"),
        BotCommand("ai_status", "Статус ИИ"),
        BotCommand("predskazaniye", "Получить предсказание"),
    ]
    await context.bot.set_my_commands(commands)
    await update.message.reply_text("Меню бота обновлено!")


async def welcome_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    config = get_chat_config(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=config['welcome'],
        reply_markup=get_welcome_keyboard(chat_id)
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in chat_history:
        del chat_history[chat_id]
    await update.message.reply_text("История диалога очищена! Начинаем с чистого листа.")


async def ai_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    status = ai_active.get(chat_id, False)
    if status:
        await update.message.reply_text("Гусь активен и готов болтать! Пиши в чат, я отвечу.")
    else:
        await update.message.reply_text("Гусь спит. Напиши \"Гусь ау\" чтобы разбудить!")

async def predskazaniye(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерирует уникальное предсказание через ИИ"""
    logger.info("!!!!! predskazaniye вызвана !!!!!")
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_name = user.first_name or "Герой"
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "Ты — циничный предсказатель из игрового клана. Одно дерзкое предсказание с чёрным юмором, не больше 15 слов. Не используй факты из базы знаний."},
                {"role": "user", "content": f"Сделай предсказание для {user_name}"}
            ],
            max_tokens=60,
            temperature=0.9,
        )
        reply = response.choices[0].message.content
    except:
        reply = ""
    
    user_mention = f"@{user.username}" if user.username else user_name
    final_text = f"🔮 {user_mention}, {reply}" if reply and reply.strip() else f"🔮 {user_mention}, Звёзды молчат. Попробуй позже."
    
    await update.message.reply_text(final_text)

# ===== ОБРАБОТЧИК ОБЫЧНЫХ СООБЩЕНИЙ =====

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_name = user.first_name or "Герой"

    if not update.message:
        return
    text = update.message.text or ""

    if not text.strip():
        return
    # Обновляем время последнего сообщения
    last_message_time[chat_id] = asyncio.get_event_loop().time()

    # Активация ИИ
    if text.lower() == "гусь ау":
        ai_active[chat_id] = True
        greetings = [
            "ГА-ГА-ГА! Гусь проснулся и готов к болтовне! Кто тут хотел пообщаться?",
            "Ну наконец-то! А то я уже заскучал. Чего надо?",
        ]
        greeting = random.choice(greetings)
        await update.message.reply_text(greeting)
        return

    # Деактивация ИИ
    if text.lower() == "гусь завали":
        ai_active[chat_id] = False
        if chat_id in chat_history:
            del chat_history[chat_id]
        goodbyes = [
            "Всё, ушёл спать. Если понадоблюсь — позови.",
            "Принял. Ухожу в закат. Зовите если что.",
        ]
        goodbye = random.choice(goodbyes)
        await update.message.reply_text(goodbye)
        return

    # Проверяем, является ли это ответом на сообщение бота
    is_reply_to_bot = False
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        if replied_user and replied_user.id == context.bot.id:
            is_reply_to_bot = True

        # Ответ ИИ — с вероятностью 10% или если упомянули Гуся, или если ответ на сообщение Гуся
    goose_words = ["гусь", "гуся", "гусю", "гусём", "гусе"]
    text_lower = text.lower()
    force_reply = any(word in text_lower for word in goose_words)

    # Клановые враги — триггер на обязательный ответ с агрессией
    enemy_words = ["онкриэйт", "зебра", "зебры", "зебру", "oncreate", "онкрита", "онкрит", "онкриейт", "stf", "стф", "зебре", "мать", "матери"]
    force_enemy_reply = any(word in text_lower for word in enemy_words)

    if force_enemy_reply:
        ai_active[chat_id] = True
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        enemy_text = f"В чате упомянули врага клана Betelgeuse! Обзови и унизь его матом. Сообщение: {text}"
        reply = await ask_ai(chat_id, enemy_text, user_name)
        user_mention = f"@{user.username}" if user.username else ""
        if user_mention:
            final_text = f"{user_mention}, {reply}" if reply.strip() else f"{user_mention}, Гусь в ярости!"
        else:
            final_text = reply if reply.strip() else "Гусь в ярости!"
        await update.message.reply_text(final_text, reply_to_message_id=update.message.message_id)
        return

    if not force_reply and not is_reply_to_bot and random.random() > 0.1:
        return

    # Проверяем, это запрос на поиск?
    is_question = "?" in text or any(w in text_lower for w in ["что", "как", "где", "кто", "сколько", "когда", "почему", "какая", "какой", "погода", "бензин", "цена", "курс"])

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # Если упомянули Гуся и это похоже на запрос данных — ищем в интернете
    if force_reply and is_question:
        search_result = await search_web(text)
        if search_result:
            # Отдаём результат ИИ для краткого ответа
            prompt = f"Вот информация из интернета:\n{search_result}\n\nДай краткий ответ на вопрос: {text}. Только факты, без шуток. 1-2 предложения."
            reply = await ask_ai(chat_id, prompt, user_name)
            user_mention = f"@{user.username}" if user.username else ""
            final_text = f"{user_mention}, {reply}" if reply.strip() else f"{user_mention}, Ничего не нашёл."
        else:
            reply = await ask_ai(chat_id, text, user_name)
            user_mention = f"@{user.username}" if user.username else ""
            final_text = f"{user_mention}, {reply}" if reply.strip() else f"{user_mention}, Даже всезнающий Гусь не в курсе."
        await update.message.reply_text(final_text, reply_to_message_id=update.message.message_id)
        return
 

    reply = await ask_ai(chat_id, text, user_name)

    user_mention = f"@{user.username}" if user.username else ""
    if user_mention:
        final_text = f"{user_mention}, {reply}" if reply.strip() else f"{user_mention}, Гусь задумался..."
    else:
        final_text = reply if reply.strip() else "Гусь задумался..."

    # Автообучение
    if force_reply or is_reply_to_bot:
        extract_and_save_facts(chat_id, text, user_name)

    await update.message.reply_text(final_text, reply_to_message_id=update.message.message_id)

# ===== ОБРАБОТЧИКИ КНОПОК =====

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    config = get_chat_config(chat_id)

    if query.data == "teamspeak":
        await query.message.reply_text(config["teamspeak"])
        return

    if query.data == "cancel_edit":
        await query.message.edit_text("Редактирование отменено.")
        await query.message.reply_text("Настройки бота:", reply_markup=get_settings_keyboard())
        return ConversationHandler.END

    if not await is_admin(update, context):
        await query.message.reply_text("Только администраторы чата могут менять настройки.")
        return ConversationHandler.END

    if query.data == "edit_welcome":
        await query.message.reply_text("Введите новый текст приветствия (или нажмите Отмена):", reply_markup=get_cancel_keyboard())
        return WAITING_WELCOME

    elif query.data == "edit_teamspeak":
        await query.message.reply_text("Введите новый текст для TeamSpeak (или нажмите Отмена):", reply_markup=get_cancel_keyboard())
        return WAITING_TEAMSPEAK

    elif query.data == "edit_info":
        context.user_data["editing_link"] = "info_channel"
        await query.message.reply_text(f"Текущая ссылка: {config['links']['info_channel']}\nВведите новую ссылку:", reply_markup=get_cancel_keyboard())
        return WAITING_LINK_INFO

    elif query.data == "edit_discord":
        context.user_data["editing_link"] = "discord"
        await query.message.reply_text(f"Текущая ссылка: {config['links']['discord']}\nВведите новую ссылку:", reply_markup=get_cancel_keyboard())
        return WAITING_LINK_DISCORD

    elif query.data == "edit_ustav":
        context.user_data["editing_link"] = "ustav"
        await query.message.reply_text(f"Текущая ссылка: {config['links']['ustav']}\nВведите новую ссылку:", reply_markup=get_cancel_keyboard())
        return WAITING_LINK_USTAV

    elif query.data == "view_settings":
        text = f"""Текущие настройки:

Приветствие:
{config['welcome']}

TeamSpeak:
{config['teamspeak']}

Ссылки:
- Инфо-канал: {config['links']['info_channel']}
- Discord: {config['links']['discord']}
- Устав: {config['links']['ustav']}"""
        await query.message.reply_text(text)

    elif query.data == "reset_settings":
        if chat_id in chat_settings:
            del chat_settings[chat_id]
        await query.message.reply_text("Настройки сброшены до стандартных Betelgeuse.")

    return ConversationHandler.END

# ===== СОХРАНЕНИЕ НАСТРОЕК =====

async def save_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    get_chat_config(chat_id)["welcome"] = update.message.text
    await update.message.reply_text("Приветствие обновлено!")
    return ConversationHandler.END

async def save_teamspeak(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    get_chat_config(chat_id)["teamspeak"] = update.message.text
    await update.message.reply_text("TeamSpeak обновлён!")
    return ConversationHandler.END

async def save_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    link_name = context.user_data.get("editing_link")
    if link_name:
        get_chat_config(chat_id)["links"][link_name] = update.message.text
        await update.message.reply_text("Ссылка обновлена!")
    return ConversationHandler.END

# ===== ПРИВЕТСТВИЕ НОВЫХ УЧАСТНИКОВ =====

async def greet_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    config = get_chat_config(chat_id)

    for new_member in update.message.new_chat_members:
        user_name = new_member.full_name
        user_mention = f"@{new_member.username}" if new_member.username else user_name
        welcome_message = f"{user_mention}, {config['welcome']}"
        await context.bot.send_message(chat_id=chat_id, text=welcome_message, reply_markup=get_welcome_keyboard(chat_id))
        logger.info(f"Поприветствовал: {user_name} в чате {chat_id}")

# ===== ЗАПУСК =====

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).connect_timeout(30).read_timeout(60).write_timeout(30).build()
    # Проверка неактивных чатов каждые 10 минут
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(check_inactive_chats, interval=600, first=10)

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^(edit_|reset_|view_|cancel_)")],
        states={
            WAITING_WELCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_welcome), CallbackQueryHandler(button_handler, pattern="^cancel_")],
            WAITING_TEAMSPEAK: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_teamspeak), CallbackQueryHandler(button_handler, pattern="^cancel_")],
            WAITING_LINK_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_link), CallbackQueryHandler(button_handler, pattern="^cancel_")],
            WAITING_LINK_DISCORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_link), CallbackQueryHandler(button_handler, pattern="^cancel_")],
            WAITING_LINK_USTAV: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_link), CallbackQueryHandler(button_handler, pattern="^cancel_")],
        },
        fallbacks=[CommandHandler("settings", settings)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("setmenu", set_menu))
    application.add_handler(CommandHandler("welcome", welcome_manual))
    application.add_handler(CommandHandler("clear", clear_history))
    application.add_handler(CommandHandler("ai_status", ai_status))
    application.add_handler(CommandHandler("predskazaniye", predskazaniye))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^teamspeak$"))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, greet_new_member))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Боевой Гусь Betelgeuse запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
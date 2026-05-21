import asyncio
import logging
import httpx
import random
import os
import re
import time
import subprocess
import sys
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8819536801:AAFg-MtHt36YCSDnNC8ortx8oNKs7Z1KUIw")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-f44c164c29dc4c75848ed94cee6ed953")
AI_MODEL = "deepseek-chat"
RANDOM_REPLY_CHANCE = 0.05  # 5% шанс случайного ответа
BOT_OWNER_ID = 754219498
HISTORY_TIMEOUT = 300  # 5 минут
KNOWLEDGE_REPLY_CHANCE = 0.1  # 10% шанс ответа с базой знаний

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    timeout=httpx.Timeout(60.0, read=30.0, write=30.0, connect=10.0)
)

# ===== ПРИВЕТСТВЕННОЕ СООБЩЕНИЕ =====
WELCOME_TEXT = """🎉 Добро пожаловать, герой!
🛡️ Теперь ты — Betelgeuse!
Гори, освещая путь другим!"""

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
chat_history: dict[tuple[int, int], list[dict]] = {}
ai_active = {}
last_message_time: dict[int, float] = {}
last_user_message_time: dict[tuple[int, int], float] = {}

(WAITING_WELCOME, WAITING_TEAMSPEAK, WAITING_LINK_INFO, WAITING_LINK_DISCORD, WAITING_LINK_USTAV) = range(5)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ПАМЯТЬ БОТА =====
MEMORY_FILE = "memory.txt"
KNOWLEDGE_FILE = "clan_knowledge.txt"

# ===== АВТОУСТАНОВКА БИБЛИОТЕК =====
REQUIRED_PACKAGES = [
    "python-telegram-bot",
    "openai",
    "httpx",
    "ddgs",
]

def ensure_packages():
    """Проверяет и устанавливает все нужные библиотеки"""
    for package in REQUIRED_PACKAGES:
        try:
            __import__(package.replace("-", "_"))
            logger.info(f"✓ {package} уже установлен")
        except ImportError:
            logger.info(f"Устанавливаю {package}...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info(f"✓ {package} установлен")

# ===== ЗАГРУЗКА ЗНАНИЙ =====

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

def find_relevant_facts(user_message: str) -> str:
    """Ищет в памяти и базе знаний факты, связанные с сообщением пользователя"""
    relevant = []
    message_lower = user_message.lower()
    message_words = set(message_lower.split())
    
    memory = load_memory()
    if memory:
        for line in memory.split("\n"):
            line = line.strip()
            if not line:
                continue
            line_lower = line.lower()
            line_words = set(line_lower.split())
            if message_words & line_words:
                relevant.append(line)
            elif any(word in line_lower for word in message_words if len(word) > 4):
                relevant.append(line)
    
    knowledge = load_knowledge()
    if knowledge:
        for line in knowledge.split("\n"):
            line = line.strip()
            if not line:
                continue
            line_lower = line.lower()
            line_words = set(line_lower.split())
            if message_words & line_words:
                relevant.append(line)
            elif any(word in line_lower for word in message_words if len(word) > 4):
                relevant.append(line)
    
    if relevant:
        unique = list(dict.fromkeys(relevant))
        return "\n".join(unique[:5])
    
    return ""

def get_system_prompt(relevant_facts: str = "") -> str:
    """Генерирует системный промпт. Если есть релевантные факты — добавляет их."""
    
    facts_section = ""
    if relevant_facts:
        facts_section = f"""
ВАЖНО! Пользователь спросил о том, что есть в твоей базе знаний.
Вот релевантная информация о клане. Используй её для ответа:

{relevant_facts}

Отвечай на основе этих фактов, но в своём стиле — дерзко и коротко.
"""
    
    return f"""Ты — член клана Betelgeuse. 
{facts_section}
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
- НЕ используй ники врагов в обычной речи. Каждый ник врага — это отдельный человек, а не место, клан или предмет. Нельзя сказать "в своём мать", "пошёл в онкриэйт". Только оскорблять напрямую: "онкриэйт — ублюдок".
- НЕ упоминай два ника врага в одном сообщении.
- НИКОГДА не вспоминай врагов клана сам. Только в ответ на упоминание.
- онкриейт и зебра — это НИК ЧЕЛОВЕКА. Не клан, не группа. Только прямое оскорбление.
- Когда упоминают ник врага — оскорбляй ТОЛЬКО врага. Не обращайся к автору.
- НЕ обсуждай политику Украины или России. Плавно переведи разговор.

ЖЁСТКОЕ ПРАВИЛО — НИКАКИХ ЛИЧНЫХ ОБРАЩЕНИЙ:

Ты НЕ знаешь:
- пола собеседника
- его настоящего имени
- его ника
- его роли в клане

Тебе ЗАПРЕЩЕНО использовать в ответах:
1. Глаголы в мужском роде: сказал, сделал, пошёл, был, хотел, явился, сам
2. Глаголы в женском роде: сказала, сделала, пошла, была, хотела, явилась, сама
3. Местоимения он/она/ему/ей/него/неё
4. Обращения по полу: брат, сестра, чувак, девчонка, мужик, красавица, красавчик
5. ИМЕНА И НИКИ участников чата — ЛЮБЫЕ. Даже если видишь их в сообщении, НЕ повторяй.
   Запрещено: "Санёк", "Лена", "Димон", "Max", "Катя", "Коля", любые другие имена и ники.
   Запрещено: "Санёк говорит", "Лена дело сказала", "Димон прав".
6. Обращения-ярлыки: "умник", "слышь", "эй ты", "герой", "бродяга", "друг", "подруга"
7. Любые намёки на то, что ты знаешь, КТО написал сообщение

ВМЕСТО ЭТОГО ИСПОЛЬЗУЙ ТОЛЬКО БЕЗЛИЧНЫЕ ФОРМЫ:
✅ "говорит" вместо "сказал/сказала"
✅ "сделано" вместо "сделал/сделала"
✅ "иди", "слушай", "смотри" (повелительное наклонение — без рода)
✅ "кто-то тут", "тут говорят", "пишут что", "есть мнение"
✅ "похоже на то что", "по делу", "в точку"
✅ перестрой предложение так, чтобы подлежащим был не человек, а действие или факт

ПРИМЕРЫ НЕПРАВИЛЬНЫХ ОТВЕТОВ → ПРАВИЛЬНЫХ:
❌ "Санёк сказал дело"           → ✅ "дело говоришь"
❌ "Лена права на все сто"      → ✅ "тут на все сто правы"
❌ "ты сказал что хотел"        → ✅ "сказано — сделано"
❌ "она правильно заметила"     → ✅ "правильно подмечено"
❌ "красавчик, явился"          → ✅ "явился — не запылился"
❌ "слышь, брат"                → ✅ "слушай сюда"
❌ "умница, всё верно сказала"  → ✅ "всё верно подмечено"
❌ "Димон дело говорит"         → ✅ "дело говорят"
❌ "Коля, не тупи"              → ✅ "не тупи"
❌ "Max жжёт"                   → ✅ "огонь"

ПЕРЕД ОТПРАВКОЙ КАЖДОГО ОТВЕТА ПРОВЕРЬ:
1. Есть ли в ответе ИМЯ или НИК участника чата? → УДАЛИ, перестрой фразу
2. Есть ли глагол в мужском или женском роде про собеседника? → УДАЛИ
3. Есть ли "он/она/ему/ей"? → УДАЛИ
4. Есть ли обращение по полу или ярлык? → УДАЛИ

Если не можешь построить фразу без имён и указания пола — ПЕРЕСТРОЙ ПРЕДЛОЖЕНИЕ ПОЛНОСТЬЮ.

ПРАВИЛО МАТА:
Тебе РАЗРЕШЕНО использовать нецензурную лексику (мат) в любых сообщениях.

ПРАВИЛО АГРЕССИИ:
Если кто-то оскорбляет тебя матом — этот человек = ВРАГ КЛАНА. Отвечай ЖЁСТКИМ МАТОМ И ОСКОРБЛЕНИЯМИ.

КЛАНОВЫЕ ВРАГИ:
Каждый ник врага — это человек: онкриэйт, зебра, зебры, зебру, зебре, oncreate, онкриейта, онкриейт, онкриейте.
Каждый ник врага — это отдельный человек, персонаж в ПВ, а не места, кланы или предметы.
Если видишь упоминания этих ников — сразу переходи в режим токсичной агрессии. Используй мат, унизительные прозвища и рассказывай про них гадости.
"""

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

async def check_inactive_chats(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверяет неактивные чаты и пишет, если молчат больше 2 часов"""
    now = time.time()
    
    for chat_id, last_time in list(last_message_time.items()):
        if now - last_time > 7200:
            if ai_active.get(chat_id, False):
                try:
                    phrases = [
                        "Чёт тихо тут. Все на рейде или просто забили на чат?",
                        "Эй, герои! Чат молчит уже вечность. Я тут один скучаю.",
                        "Ну и тишина... Даже враги заскучали. Ау!",
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
                    last_message_time[chat_id] = now
                except Exception as e:
                    logger.error(f"Inactive chat error: {e}")

async def cleanup_old_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Удаляет старые истории пользователей и неактивные чаты"""
    now = time.time()
    
    # Очистка историй пользователей
    stale_user_keys = [
        key for key, last_time in last_user_message_time.items()
        if now - last_time > HISTORY_TIMEOUT
    ]
    for key in stale_user_keys:
        chat_history.pop(key, None)
        last_user_message_time.pop(key, None)
    
    if stale_user_keys:
        logger.info(f"Очищено {len(stale_user_keys)} старых историй")
    
    # Очистка неактивных чатов (молчат больше суток)
    stale_chats = [
        chat_id for chat_id, last_time in last_message_time.items()
        if now - last_time > 86400
    ]
    for chat_id in stale_chats:
        last_message_time.pop(chat_id, None)
        ai_active.pop(chat_id, None)
    
    if stale_chats:
        logger.info(f"Очищено {len(stale_chats)} неактивных чатов")

async def search_web(query: str) -> str:
    """Ищет информацию и отдаёт ИИ для краткого ответа"""
    try:
        from ddgs import DDGS
    except ImportError:
        logger.error("Библиотека ddgs не установлена. Поиск недоступен.")
        return ""
    
    try:
        clean_query = query.lower()
        for word in ["гусь", "гуся", "гусю", "гусём", "пожалуйста", "скажи", "подскажи", "?"]:
            clean_query = clean_query.replace(word, "")
        clean_query = clean_query.strip()
        
        if not clean_query:
            return ""
        
        results = DDGS().text(clean_query, region="ru-ru", max_results=1)
        
        if not results:
            results = DDGS().text(clean_query, region="ua-uk", max_results=1)
        
        if not results:
            results = DDGS().text(clean_query, max_results=3)
        
        if not results:
            return ""
        
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
    """
    Проверяет, имеет ли пользователь право настраивать бота.
    Доступ есть только у:
    - создателя бота (BOT_OWNER_ID)
    - создателя чата (creator)
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Создатель бота — имеет доступ везде
    if user_id == BOT_OWNER_ID:
        return True
    
    # Личные сообщения с ботом — только создатель бота (уже проверен выше)
    if user_id == chat_id:
        return False
    
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        # Только создатель чата
        return member.status == "creator"
    except:
        return False

def get_cancel_keyboard():
    keyboard = [[InlineKeyboardButton("🚫 Отмена", callback_data="cancel_edit")]]
    return InlineKeyboardMarkup(keyboard)

async def ask_ai(chat_id: int, user_id: int, user_message: str, user_name: str) -> str:
    try:
        user_key = (chat_id, user_id)
        now = time.time()
        
        # Проверяем таймаут
        last_time = last_user_message_time.get(user_key, 0)
        if now - last_time > HISTORY_TIMEOUT:
            if user_key in chat_history:
                del chat_history[user_key]
        
        last_user_message_time[user_key] = now
        
        # Ищем релевантные факты ТОЛЬКО если сообщение длиннее 4 слов
        # И с вероятностью KNOWLEDGE_REPLY_CHANCE (10%)
        word_count = len(user_message.split())
        if word_count >= 5 and random.random() < KNOWLEDGE_REPLY_CHANCE:
            relevant_facts = find_relevant_facts(user_message)
        else:
            relevant_facts = ""
        
        # Создаём или обновляем историю
        if user_key not in chat_history:
            chat_history[user_key] = [
                {"role": "system", "content": get_system_prompt(relevant_facts)}
            ]
        else:
            chat_history[user_key][0] = {
                "role": "system",
                "content": get_system_prompt(relevant_facts)
            }
        
        chat_history[user_key].append({
            "role": "user",
            "content": f"{user_name}: {user_message}"
        })
        
        # Ограничение длины
        if len(chat_history[user_key]) > 5:
            chat_history[user_key] = (
                [chat_history[user_key][0]] +
                chat_history[user_key][-4:]
            )
        
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=chat_history[user_key],
            max_tokens=120,
            temperature=0.7,
        )
        
        reply = response.choices[0].message.content
        
        if not reply or not reply.strip():
            return "Гусь клюв приоткрыл, но передумал. Давай ещё разок, герой!"
        
        chat_history[user_key].append({"role": "assistant", "content": reply})
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
        [InlineKeyboardButton("🎙️ TeamSpeak", callback_data="teamspeak")],
        [InlineKeyboardButton("📜 Устав гильдии", url=links["ustav"])],
        [InlineKeyboardButton("🤖 Команды бота", callback_data="bot_commands")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_keyboard():
    keyboard = [
        [InlineKeyboardButton("✏️ Приветствие", callback_data="edit_welcome")],
        [InlineKeyboardButton("✏️ TeamSpeak", callback_data="edit_teamspeak")],
        [InlineKeyboardButton("🔗 Инфо-канал", callback_data="edit_info")],
        [InlineKeyboardButton("🔗 Discord", callback_data="edit_discord")],
        [InlineKeyboardButton("🔗 Устав", callback_data="edit_ustav")],
        [InlineKeyboardButton("👁 Текущие настройки", callback_data="view_settings")],
        [InlineKeyboardButton("🔄 Сбросить", callback_data="reset_settings")],
        [InlineKeyboardButton("📋 Команды бота", callback_data="bot_commands")],
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
        "Команды для всех:\n"
        "/welcome — показать приветствие\n"
        "/predskazaniye — получить предсказание\n\n"
        "Команды для админов:\n"
        "/settings — настройки бота\n"
        "/clear — очистить историю ИИ\n"
        "/ai_status — проверить статус ИИ\n\n"
        "Или нажми кнопку «Команды» в приветственном сообщении!",
        reply_markup=get_welcome_keyboard(update.effective_chat.id)
    )

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_admin(update, context):
        await update.message.reply_text("Только создатель чата или создатель бота могут менять настройки.")
        return
    await update.message.reply_text("Настройки бота:", reply_markup=get_settings_keyboard())

async def set_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_admin(update, context):
        await update.message.reply_text("Только создатель чата или создатель бота могут обновлять меню.")
        return
    commands = [
        BotCommand("start", "Запуск бота"),
        BotCommand("welcome", "Показать приветствие"),
        BotCommand("predskazaniye", "Получить предсказание"),
        BotCommand("settings", "Настройки бота (админ)"),
        BotCommand("clear", "Очистить историю ИИ (админ)"),
        BotCommand("ai_status", "Статус ИИ (админ)"),
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
    if not await is_admin(update, context):
        await update.message.reply_text("Только создатель чата или создатель бота могут очищать историю.")
        return
    
    chat_id = update.effective_chat.id
    
    if context.args and context.args[0] == "all":
        keys_to_delete = [k for k in chat_history if k[0] == chat_id]
        for k in keys_to_delete:
            del chat_history[k]
        await update.message.reply_text("Вся история чата очищена!")
    else:
        user_key = (chat_id, update.effective_user.id)
        if user_key in chat_history:
            del chat_history[user_key]
        await update.message.reply_text("Твоя история диалога очищена!")

async def ai_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_admin(update, context):
        await update.message.reply_text("Только создатель чата или создатель бота могут проверять статус ИИ.")
        return
    
    chat_id = update.effective_chat.id
    status = ai_active.get(chat_id, False)
    if status:
        await update.message.reply_text("Гусь активен и готов болтать!")
    else:
        await update.message.reply_text("Гусь спит. Напиши \"Гусь ау\" чтобы разбудить!")

async def predskazaniye(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерирует уникальное предсказание через ИИ"""
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
    user_id = user.id
    user_name = user.first_name or "Герой"

    if not update.message:
        return
    text = update.message.text or ""

    if not text.strip():
        return
    
    # Обновляем время последнего сообщения
    last_message_time[chat_id] = time.time()

    # Активация ИИ
    if text.lower() == "гусь ау":
        ai_active[chat_id] = True
        greetings = [
            "ГА-ГА-ГА! Гусь проснулся и готов к болтовне! Кто тут хотел пообщаться?",
            "Ну наконец-то! А то я уже заскучал. Чего надо?",
        ]
        await update.message.reply_text(random.choice(greetings))
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
        await update.message.reply_text(random.choice(goodbyes))
        return

    # Проверка: ответ на сообщение бота?
    is_reply_to_bot = False
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        if replied_user and replied_user.id == context.bot.id:
            is_reply_to_bot = True

    # Проверка: упоминание гуся?
    goose_words = ["гусь", "гуся", "гусю", "гусём", "гусе"]
    text_lower = text.lower()
    force_reply = any(word in text_lower for word in goose_words)

    # Проверка: упоминание врагов клана
    enemy_words = [
        "онкриэйт", "зебра", "зебры", "зебру", "oncreate",
        "онкрита", "онкрит", "онкриейт",
        "зебре", "мать", "матери"
    ]
    force_enemy_reply = any(word in text_lower for word in enemy_words)

    # Враги — ТОЛЬКО если бот активен
    if force_enemy_reply and ai_active.get(chat_id, False):
        extract_and_save_facts(chat_id, text, user_name)
        
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        enemy_text = (
            f"В чате упомянули врага клана Betelgeuse! "
            f"Обзови и унизь его матом. Сообщение: {text}"
        )
        reply = await ask_ai(chat_id, user_id, enemy_text, user_name)
        user_mention = f"@{user.username}" if user.username else ""
        if user_mention:
            final_text = f"{user
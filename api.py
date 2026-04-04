"""
Spark EGE — FastAPI бэкенд для PWA
====================================
Запуск: uvicorn api:app --host 0.0.0.0 --port 8000
Или через run_api.py
"""

import os
import json
import random
import sqlite3
import logging
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Загрузка токенов ──────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY") or __import__("config").GROQ_API_KEY
except Exception:
    GROQ_API_KEY = ""

# ─── Приложение ───────────────────────────────────────────────────────────────
app = FastAPI(title="Spark EGE API", version="1.0.0")

# CORS — разрешаем запросы от PWA (GitHub Pages и localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшне заменить на конкретный домен
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── База данных ──────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "pwa_users.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS pwa_users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            avatar TEXT,
            level TEXT DEFAULT 'B1',
            goal_xp INTEGER DEFAULT 50,
            total_xp INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            lessons_done INTEGER DEFAULT 0,
            correct INTEGER DEFAULT 0,
            total_answers INTEGER DEFAULT 0,
            last_active TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pwa_vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            word TEXT,
            translation TEXT,
            example TEXT,
            learned INTEGER DEFAULT 0,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pwa_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            section TEXT,
            correct INTEGER DEFAULT 0,
            total INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
    logger.info("✅ БД инициализирована")


init_db()

# ─── Банк заданий ─────────────────────────────────────────────────────────────
# Загружаем из нашего бота если доступно, иначе используем встроенный банк

BUILTIN_TASKS = [
    {
        "id": "g001",
        "type": "choice",
        "section": "grammar",
        "badge": "Грамматика · ЕГЭ 2024",
        "question": "By the time we arrived, the train ___ (already/leave).",
        "translation": "К тому времени, как мы прибыли, поезд (уже ушёл) ___.",
        "options": ["had already left", "has already left", "already left", "was leaving"],
        "correct": 0,
        "explanation": "Past Perfect = had + V3. Действие произошло ДО другого прошедшего. Сигнал: by the time."
    },
    {
        "id": "g002",
        "type": "choice",
        "section": "grammar",
        "badge": "Грамматика · ЕГЭ 2023",
        "question": "He suggested ___ (go) to the cinema after school.",
        "translation": "Он предложил (пойти) ___ в кино после школы.",
        "options": ["to go", "going", "go", "gone"],
        "correct": 1,
        "explanation": "После suggest всегда герундий (V+ing). Глаголы suggest, enjoy, avoid, mind → всегда +ing."
    },
    {
        "id": "g003",
        "type": "choice",
        "section": "grammar",
        "badge": "Грамматика · ЕГЭ 2025",
        "question": "The museum ___ (visit) by thousands of tourists every year.",
        "translation": "Музей (посещается) ___ тысячами туристов каждый год.",
        "options": ["is visited", "visits", "was visited", "has visited"],
        "correct": 0,
        "explanation": "Passive Voice Present Simple: is/are + V3. Every year — регулярное действие → Present Simple."
    },
    {
        "id": "g004",
        "type": "choice",
        "section": "grammar",
        "badge": "Грамматика · ЕГЭ 2023",
        "question": "If I ___ (know) the answer, I would tell you.",
        "translation": "Если бы я (знал) ___ ответ, я бы сказал тебе.",
        "options": ["knew", "know", "had known", "would know"],
        "correct": 0,
        "explanation": "Conditional Type 2: If + Past Simple, would + V. Нереальное условие в настоящем."
    },
    {
        "id": "g005",
        "type": "choice",
        "section": "grammar",
        "badge": "Грамматика · ЕГЭ 2024",
        "question": "She asked me where I ___ (go) the next day.",
        "translation": "Она спросила меня, куда я (пойду) ___ на следующий день.",
        "options": ["was going", "am going", "went", "will go"],
        "correct": 0,
        "explanation": "Косвенная речь: будущее → Future in the Past (was going). Главное предложение в прошедшем."
    },
    {
        "id": "w001",
        "type": "input",
        "section": "word_formation",
        "badge": "Словообразование · ЕГЭ 2024",
        "question": "Her ___ (achieve) in science were outstanding.",
        "translation": "Её (достижения) ___ в науке были выдающимися.",
        "correct": "achievements",
        "hint": "achieve → суффикс -ment → множественное число",
        "explanation": "achieve → achievement (суффикс -ment) → achievements (мн.ч.). Существительные из глаголов: achieve→achievement, develop→development."
    },
    {
        "id": "w002",
        "type": "input",
        "section": "word_formation",
        "badge": "Словообразование · ЕГЭ 2023",
        "question": "It is almost ___ (possible) to learn a language without practice.",
        "translation": "Почти (невозможно) ___ выучить язык без практики.",
        "correct": "impossible",
        "hint": "im- перед p/b/m: possible → impossible",
        "explanation": "Приставка im- перед p, b, m: possible→impossible, polite→impolite, balance→imbalance."
    },
    {
        "id": "w003",
        "type": "input",
        "section": "word_formation",
        "badge": "Словообразование · ЕГЭ 2024",
        "question": "The ___ (science) community was excited about the discovery.",
        "translation": "(Научное) ___ сообщество было взволновано открытием.",
        "correct": "scientific",
        "hint": "science → прилагательное с суффиксом -tific",
        "explanation": "science → scientific (прилагательное). Суффикс -ic часто образует прилагательные: hero→heroic, atom→atomic."
    },
    {
        "id": "w004",
        "type": "input",
        "section": "word_formation",
        "badge": "Словообразование · ЕГЭ 2025",
        "question": "He showed great ___ (brave) during the rescue operation.",
        "translation": "Он проявил большую (храбрость) ___ во время спасательной операции.",
        "correct": "bravery",
        "hint": "brave → существительное с суффиксом -ry или -ery",
        "explanation": "brave → bravery (суффикс -ry). Аналогично: slave→slavery, knave→knavery."
    },
    {
        "id": "r001",
        "type": "choice",
        "section": "reading",
        "badge": "Чтение · ЕГЭ 2024",
        "question": "Social media has changed the way people communicate. Users can now share information instantly across the globe. However, this has also led to the spread of misinformation.\n\nWhat is the main idea of this passage?",
        "translation": "О чём главным образом говорится в тексте?",
        "options": [
            "Social media has only positive effects",
            "Social media has transformed communication with both benefits and drawbacks",
            "Misinformation is the biggest problem today",
            "People no longer communicate in person"
        ],
        "correct": 1,
        "explanation": "Текст говорит о том, что соцсети изменили коммуникацию (позитив) и привели к дезинформации (негатив). Ответ B охватывает обе стороны."
    },
]

_used_ids: set = set()


def get_random_task(section: Optional[str] = None, level: str = "B1") -> dict:
    """Выдаёт случайное задание, избегая повторов."""
    global _used_ids

    # Пробуем загрузить из банка бота
    try:
        from content.real_ege_tasks import GRAMMAR_REAL, WORD_FORMATION_REAL
        bot_tasks = []
        for t in GRAMMAR_REAL:
            t["section"] = "grammar"
            t["type"] = "choice"
            bot_tasks.append(t)
        for t in WORD_FORMATION_REAL:
            t["section"] = "word_formation"
            t["type"] = "input"
            bot_tasks.append(t)
        tasks = bot_tasks if bot_tasks else BUILTIN_TASKS
    except ImportError:
        tasks = BUILTIN_TASKS

    # Фильтр по разделу
    if section:
        filtered = [t for t in tasks if t.get("section") == section]
        if not filtered:
            filtered = tasks
    else:
        filtered = tasks

    # Убираем уже использованные
    available = [t for t in filtered if t.get("id", "") not in _used_ids]
    if not available:
        _used_ids.clear()
        available = filtered

    task = random.choice(available)
    _used_ids.add(task.get("id", ""))
    return task


# ─── Groq клиент ──────────────────────────────────────────────────────────────
def get_groq_explanation(question: str, user_answer: str, correct_answer: str) -> str:
    """Получает объяснение ошибки от Groq."""
    if not GROQ_API_KEY:
        return f"Правильный ответ: {correct_answer}"
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        prompt = f"""Ты репетитор по английскому для подготовки к ЕГЭ.
Задание: {question}
Ответ ученика: {user_answer}
Правильный ответ: {correct_answer}

Объясни ошибку кратко (1-2 предложения) на русском языке. 
Укажи правило грамматики или словообразования.
Не пиши "Правильный ответ:" в начале — просто объяснение."""

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Groq ошибка: {e}")
        return f"Правильный ответ: {correct_answer}"


# ─── Модели запросов ──────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    user_id: str
    name: str
    avatar: str = "😊"
    level: str = "B1"
    goal_xp: int = 50


class AnswerCheck(BaseModel):
    user_id: str
    task_id: str
    question: str
    user_answer: str
    correct_answer: str
    section: str = "grammar"


class ProgressUpdate(BaseModel):
    user_id: str
    xp_earned: int
    correct: int
    total: int
    section: str = "grammar"


class VocabAdd(BaseModel):
    user_id: str
    word: str
    translation: str
    example: str = ""


# ─── Роуты ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "Spark EGE API", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.post("/user/register")
def register_user(data: UserCreate):
    """Регистрирует или обновляет пользователя PWA."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT user_id FROM pwa_users WHERE user_id = ?", (data.user_id,)
        ).fetchone()

        if existing:
            return {"status": "exists", "user_id": data.user_id}

        conn.execute("""
            INSERT INTO pwa_users (user_id, name, avatar, level, goal_xp, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data.user_id, data.name, data.avatar, data.level, data.goal_xp,
              date.today().isoformat()))

    return {"status": "created", "user_id": data.user_id}


@app.get("/user/{user_id}")
def get_user(user_id: str):
    """Возвращает данные пользователя."""
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM pwa_users WHERE user_id = ?", (user_id,)
        ).fetchone()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return dict(user)


@app.get("/task")
def get_task(section: Optional[str] = None, level: str = "B1"):
    """Выдаёт задание ЕГЭ."""
    task = get_random_task(section=section, level=level)

    # Убираем правильный ответ из ответа (для input-заданий)
    response = {k: v for k, v in task.items() if k != "correct"}
    response["task_id"] = task.get("id", "unknown")
    return response


@app.post("/check")
def check_answer(data: AnswerCheck):
    """Проверяет ответ и объясняет ошибку через Groq."""
    # Находим задание для проверки
    task = next(
        (t for t in BUILTIN_TASKS if t.get("id") == data.task_id),
        None
    )

    # Проверяем ответ
    if task:
        if task["type"] == "choice":
            is_correct = str(data.user_answer) == str(task["correct"])
            correct_answer = task["options"][task["correct"]] if is_correct is False else data.user_answer
            explanation = task.get("explanation", "")
        else:
            is_correct = data.user_answer.strip().lower() == task["correct"].strip().lower()
            correct_answer = task["correct"]
            explanation = task.get("explanation", "")
    else:
        # Если задание не найдено — используем Groq для проверки
        is_correct = data.user_answer.strip().lower() == data.correct_answer.strip().lower()
        correct_answer = data.correct_answer
        explanation = ""

    # Если неправильно — получаем объяснение от Groq
    if not is_correct and not explanation:
        explanation = get_groq_explanation(
            data.question, data.user_answer, correct_answer
        )

    return {
        "correct": is_correct,
        "correct_answer": correct_answer,
        "explanation": explanation,
        "xp_earned": 10 if is_correct else 2
    }


@app.post("/progress")
def update_progress(data: ProgressUpdate):
    """Сохраняет прогресс после урока."""
    today = date.today().isoformat()

    with get_db() as conn:
        # Обновляем пользователя
        user = conn.execute(
            "SELECT total_xp, streak, last_active, lessons_done FROM pwa_users WHERE user_id = ?",
            (data.user_id,)
        ).fetchone()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Считаем стрик
        last_active = user["last_active"]
        streak = user["streak"]
        if last_active != today:
            from datetime import timedelta
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            streak = user["streak"] + 1 if last_active == yesterday else 1

        conn.execute("""
            UPDATE pwa_users SET
                total_xp = total_xp + ?,
                streak = ?,
                lessons_done = lessons_done + 1,
                correct = correct + ?,
                total_answers = total_answers + ?,
                last_active = ?
            WHERE user_id = ?
        """, (data.xp_earned, streak, data.correct, data.total, today, data.user_id))

        # Обновляем прогресс по разделу
        existing = conn.execute(
            "SELECT id FROM pwa_progress WHERE user_id = ? AND section = ?",
            (data.user_id, data.section)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE pwa_progress SET correct = correct + ?, total = total + ?, updated_at = ?
                WHERE user_id = ? AND section = ?
            """, (data.correct, data.total, today, data.user_id, data.section))
        else:
            conn.execute("""
                INSERT INTO pwa_progress (user_id, section, correct, total, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (data.user_id, data.section, data.correct, data.total, today))

    return {"status": "ok", "streak": streak}


@app.get("/progress/{user_id}")
def get_progress(user_id: str):
    """Возвращает полный прогресс пользователя."""
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM pwa_users WHERE user_id = ?", (user_id,)
        ).fetchone()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        sections = conn.execute(
            "SELECT section, correct, total FROM pwa_progress WHERE user_id = ?",
            (user_id,)
        ).fetchall()

        section_stats = {}
        for s in sections:
            pct = round(s["correct"] / s["total"] * 100) if s["total"] > 0 else 0
            section_stats[s["section"]] = {
                "correct": s["correct"],
                "total": s["total"],
                "percent": pct
            }

        accuracy = round(user["correct"] / user["total_answers"] * 100) if user["total_answers"] > 0 else 0

        return {
            "name": user["name"],
            "avatar": user["avatar"],
            "level": user["level"],
            "total_xp": user["total_xp"],
            "streak": user["streak"],
            "lessons_done": user["lessons_done"],
            "accuracy": accuracy,
            "sections": section_stats
        }


@app.post("/vocab/add")
def add_word(data: VocabAdd):
    """Добавляет слово в словарь."""
    with get_db() as conn:
        # Проверяем дубликат
        existing = conn.execute(
            "SELECT id FROM pwa_vocab WHERE user_id = ? AND word = ?",
            (data.user_id, data.word.lower())
        ).fetchone()

        if existing:
            return {"status": "exists"}

        conn.execute("""
            INSERT INTO pwa_vocab (user_id, word, translation, example)
            VALUES (?, ?, ?, ?)
        """, (data.user_id, data.word.lower(), data.translation, data.example))

    return {"status": "added", "word": data.word}


@app.get("/vocab/{user_id}")
def get_vocab(user_id: str, learned: Optional[int] = None):
    """Возвращает словарь пользователя."""
    with get_db() as conn:
        if learned is not None:
            words = conn.execute(
                "SELECT * FROM pwa_vocab WHERE user_id = ? AND learned = ? ORDER BY added_at DESC",
                (user_id, learned)
            ).fetchall()
        else:
            words = conn.execute(
                "SELECT * FROM pwa_vocab WHERE user_id = ? ORDER BY added_at DESC",
                (user_id,)
            ).fetchall()

    return {"words": [dict(w) for w in words], "total": len(words)}


@app.post("/vocab/{word_id}/learned")
def mark_learned(word_id: int):
    """Отмечает слово как выученное."""
    with get_db() as conn:
        conn.execute(
            "UPDATE pwa_vocab SET learned = 1 WHERE id = ?", (word_id,)
        )
    return {"status": "ok"}

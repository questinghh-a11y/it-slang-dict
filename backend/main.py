
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
import random

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import (create_engine, Column, Integer, String, Text,
                        DateTime, func, or_)
from sqlalchemy.orm import declarative_base, sessionmaker, Session


import os

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'slang.db'}")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

# ---------------- модель БД ----------------
class Term(Base):
    __tablename__ = "terms"

    id = Column(Integer, primary_key=True)
    term = Column(String(200), nullable=False, unique=True, index=True)
    definition = Column(Text, nullable=False)
    example = Column(Text, nullable=False, default="")
    category = Column(String(80), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)


Base.metadata.create_all(engine)


# ---------------- схемы ----------------
class TermBase(BaseModel):
    term: str = Field(..., min_length=1, max_length=200)
    definition: str = Field(..., min_length=1)
    example: str = ""
    category: str = Field(..., min_length=1, max_length=80)


class TermCreate(TermBase):
    pass


class TermUpdate(BaseModel):
    term: Optional[str] = Field(None, min_length=1, max_length=200)
    definition: Optional[str] = Field(None, min_length=1)
    example: Optional[str] = None
    category: Optional[str] = Field(None, min_length=1, max_length=80)


class TermOut(TermBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------- зависимости ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------- приложение ----------------
app = FastAPI(
    title="IT Slang Dictionary API",
    version="1.0.0",
    description="Онлайн-словарь ИТ-сленга: чтение, поиск, добавление и правка.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ---------------- эндпоинты ----------------
@app.get("/api/terms")
def list_terms(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sort: str = Query("term", pattern="^(term|created_at|updated_at)$"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Term)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Term.term.ilike(like),
                                 Term.definition.ilike(like)))
    if category:
        query = query.filter(Term.category == category)

    total = query.count()
    items = (query.order_by(getattr(Term, sort))
                  .offset(offset).limit(limit).all())

    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [TermOut.model_validate(t).model_dump() for t in items],
    }


@app.get("/api/terms/{term_id}", response_model=TermOut)
def get_term(term_id: int, db: Session = Depends(get_db)):
    t = db.get(Term, term_id)
    if not t:
        raise HTTPException(404, "Термин не найден")
    return t


@app.post("/api/terms", response_model=TermOut, status_code=201)
def create_term(payload: TermCreate, db: Session = Depends(get_db)):
    exists = (db.query(Term)
                .filter(func.lower(Term.term) == payload.term.lower())
                .first())
    if exists:
        raise HTTPException(409, "Такой термин уже есть")
    t = Term(**payload.model_dump())
    db.add(t); db.commit(); db.refresh(t)
    return t


@app.put("/api/terms/{term_id}", response_model=TermOut)
def update_term(term_id: int, payload: TermUpdate, db: Session = Depends(get_db)):
    t = db.get(Term, term_id)
    if not t:
        raise HTTPException(404, "Термин не найден")
    data = payload.model_dump(exclude_unset=True)
    if "term" in data:
        clash = (db.query(Term)
                   .filter(func.lower(Term.term) == data["term"].lower(),
                           Term.id != term_id)
                   .first())
        if clash:
            raise HTTPException(409, "Термин с таким именем уже есть")
    for k, v in data.items():
        setattr(t, k, v)
    db.commit(); db.refresh(t)
    return t


@app.delete("/api/terms/{term_id}", status_code=204)
def delete_term(term_id: int, db: Session = Depends(get_db)):
    t = db.get(Term, term_id)
    if not t:
        raise HTTPException(404, "Термин не найден")
    db.delete(t); db.commit()


@app.get("/api/categories")
def list_categories(db: Session = Depends(get_db)):
    rows = (db.query(Term.category, func.count(Term.id))
              .group_by(Term.category)
              .order_by(Term.category)
              .all())
    return [{"name": n, "count": c} for n, c in rows]


@app.get("/api/random", response_model=TermOut)
def random_term(db: Session = Depends(get_db)):
    ids = [r[0] for r in db.query(Term.id).all()]
    if not ids:
        raise HTTPException(404, "Словарь пуст")
    return db.get(Term, random.choice(ids))


# ---------------- стартовые данные ----------------
SEED = [
    # Процесс разработки
    {"term": "Спринт", "category": "Процесс разработки",
     "definition": "Короткий фиксированный отрезок времени (обычно 1–2 недели), за который команда должна доделать выбранный набор задач.",
     "example": "В этом спринте взяли три задачи по авторизации и одну по логам."},
    {"term": "Стендап", "category": "Процесс разработки",
     "definition": "Короткая ежедневная встреча команды. Каждый отвечает на три вопроса: что сделал, что буду делать, что мешает.",
     "example": "Стендап в 10:00, за 15 минут уложились."},
    {"term": "Бэклог", "category": "Процесс разработки",
     "definition": "Список всех задач проекта, упорядоченный по приоритету. Не всё из него попадёт в работу, но всё там лежит.",
     "example": "Идея ушла в бэклог — вернёмся к ней после релиза."},
    {"term": "Код-ревью", "category": "Процесс разработки",
     "definition": "Проверка чужого кода коллегой перед вливанием в основную ветку. Цель — поймать ошибки и передать знание.",
     "example": "Пушни, я на ревью гляну."},
    {"term": "Деплой", "category": "Процесс разработки",
     "definition": "Выкатка готового кода на сервер, где им пользуются реальные люди.",
     "example": "Деплой в пятницу — плохая примета."},
    {"term": "Релиз", "category": "Процесс разработки",
     "definition": "Финальная версия продукта или обновления, которую отдают пользователям.",
     "example": "Релиз 2.0 намечен на конец месяца."},
    {"term": "Техдолг", "category": "Процесс разработки",
     "definition": "Накопленные компромиссы в коде: сделано быстро, но некрасиво. Рано или поздно придётся переделывать.",
     "example": "Половина спринта ушла на закрытие техдолга."},
    {"term": "Ретро", "category": "Процесс разработки",
     "definition": "Ретроспектива — встреча после спринта, где команда обсуждает, что было хорошо, что плохо и что менять.",
     "example": "На ретро решили не брать больше трёх задач за спринт."},

    # Код и качество
    {"term": "Баг", "category": "Код и качество",
     "definition": "Ошибка в программе, из-за которой она работает не так, как ожидалось.",
     "example": "Поймал баг: кнопка не работает, если поле пустое."},
    {"term": "Фича", "category": "Код и качество",
     "definition": "Функциональность, новая возможность программы. То, ради чего продукт вообще делают.",
     "example": "За фичу отвечает команда фронтенда."},
    {"term": "Дебажить", "category": "Код и качество",
     "definition": "Искать и исправлять ошибки в программе. От английского debug — «избавляться от жуков».",
     "example": "Вчера до трёх ночи дебажил парсер."},
    {"term": "Рефакторинг", "category": "Код и качество",
     "definition": "Переписывание кода без изменения его поведения — чтобы стало понятнее и проще поддерживать.",
     "example": "Функцию разбил на три — обычный рефакторинг."},
    {"term": "Костыль", "category": "Код и качество",
     "definition": "Временное, некрасивое решение, которое держит систему на плаву. Работает, но лучше туда не смотреть.",
     "example": "Поставил костыль, чтобы успеть к релизу."},
    {"term": "Хардкод", "category": "Код и качество",
     "definition": "Значения, прямо вписанные в код, вместо конфига или переменных. Классика зла.",
     "example": "URL хардкодом прописан — не переиспользуешь."},
    {"term": "Легаси", "category": "Код и качество",
     "definition": "Старый код, который работает, но его никто не хочет трогать. Автор давно уволился.",
     "example": "Трогать легаси страшно — там всё держится на честном слове."},
    {"term": "Говнокод", "category": "Код и качество",
     "definition": "Код, который формально работает, но написан так, что читать его больно. Сокр. ГК.",
     "example": "Открыл модуль, а там чистый ГК."},
    {"term": "Велосипед", "category": "Код и качество",
     "definition": "Самописное решение вместо готовой библиотеки. Обычно хуже, дольше и с багами.",
     "example": "Зачем свой велосипед, если есть стандартная библиотека?"},
    {"term": "Линтер", "category": "Код и качество",
     "definition": "Инструмент, который автоматически проверяет код на стиль, ошибки и подозрительные места.",
     "example": "Линтер ругается на неиспользуемую переменную."},

    # Инфраструктура
    {"term": "Сервер", "category": "Инфраструктура",
     "definition": "Компьютер (или программа), который принимает запросы и отдаёт ответы. Может быть железный или виртуальный.",
     "example": "Упал сервер — половина клиентов не смогла залогиниться."},
    {"term": "Кластер", "category": "Инфраструктура",
     "definition": "Группа серверов, работающих как один. Нужен для отказоустойчивости и нагрузки.",
     "example": "Кластер из пяти нод выдержит утро понедельника."},
    {"term": "Докер", "category": "Инфраструктура",
     "definition": "Технология упаковки приложения со всеми зависимостями в контейнер — работает одинаково везде.",
     "example": "Завернул сервис в докер, на прод уходит одной командой."},
    {"term": "Контейнер", "category": "Инфраструктура",
     "definition": "Изолированная среда с приложением и его зависимостями. Лёгкая альтернатива виртуалке.",
     "example": "Контейнеры запускаются за секунды, виртуалки — за минуты."},
    {"term": "Кубики", "category": "Инфраструктура",
     "definition": "Kubernetes (K8s) — система оркестрации контейнеров. «Кубики» — жаргонное сокращение.",
     "example": "Развернули всё в кубиках, само перезапускается при падении."},
    {"term": "Облако", "category": "Инфраструктура",
     "definition": "Чужие серверы, которые ты арендуешь по требованию. AWS, Google Cloud, Yandex Cloud.",
     "example": "Переехали в облако, забыли про закупку железа."},
    {"term": "Мониторинг", "category": "Инфраструктура",
     "definition": "Система слежения за состоянием сервиса: нагрузка, ошибки, время ответа. Чтобы узнать о проблеме раньше клиента.",
     "example": "Настроили мониторинг — узнаём о падениях раньше пользователей."},
    {"term": "Даунтайм", "category": "Инфраструктура",
     "definition": "Время, когда сервис недоступен. Обратное — аптайм.",
     "example": "После обновления был короткий даунтайм на 30 секунд."},

    # Команда и роли
    {"term": "Тимлид", "category": "Команда и роли",
     "definition": "Team Lead — руководитель команды разработчиков. Раздаёт задачи, отвечает за результат и рост людей.",
     "example": "Тимлид сказал: разбираем задачу вместе."},
    {"term": "Сеньор", "category": "Команда и роли",
     "definition": "Опытный разработчик, который решает сложные задачи сам и помогает остальным. Не «начальник», просто самый прокачанный в коде.",
     "example": "Сеньор посмотрел и за 20 минут нашёл причину."},
    {"term": "Мидл", "category": "Команда и роли",
     "definition": "Разработчик среднего уровня. Работает самостоятельно, но сложные вещи может эскалировать сеньору.",
     "example": "Джун спрашивает мидла, мидл — сеньора."},
    {"term": "Джун", "category": "Команда и роли",
     "definition": "Junior — начинающий разработчик. Учится, берёт простые задачи, задаёт много вопросов.",
     "example": "Джун сделал первую фичу — можно поздравить."},
    {"term": "Холивар", "category": "Команда и роли",
     "definition": "Жаркий бесполезный спор, обычно о вкусах. Классика: табы против пробелов, Python против JS.",
     "example": "Развели холивар в чате с самого утра."},
    {"term": "Шеринг", "category": "Команда и роли",
     "definition": "Демонстрация сделанного коллегам — короткий доклад в конце спринта.",
     "example": "На шеринге показал, что успели за две недели."},

    # Веб и API
    {"term": "Фронтенд", "category": "Веб и API",
     "definition": "Часть приложения, которую видит пользователь. Работает в браузере: HTML, CSS, JavaScript.",
     "example": "Кнопку поправит фронтенд, а логику — бэкенд."},
    {"term": "Бэкенд", "category": "Веб и API",
     "definition": "Серверная часть приложения. Обрабатывает данные, ходит в базу, отдаёт фронтенду ответы.",
     "example": "Бэкенд написан на Python с FastAPI."},
    {"term": "Фулстек", "category": "Веб и API",
     "definition": "Разработчик, который умеет и фронтенд, и бэкенд. Делает фичу целиком от кнопки до базы.",
     "example": "Фулстек-разработчик сам поднял и API, и интерфейс."},
    {"term": "API", "category": "Веб и API",
     "definition": "Application Programming Interface — набор правил, по которым одна программа говорит с другой.",
     "example": "Фронт получает данные по API."},
    {"term": "Эндпоинт", "category": "Веб и API",
     "definition": "Конкретный адрес, по которому API отвечает на запросы. Например, /api/terms.",
     "example": "Добавили новый эндпоинт для поиска."},
    {"term": "REST", "category": "Веб и API",
     "definition": "Стиль построения API, где данные — это ресурсы, а действия — это HTTP-методы: GET, POST, PUT, DELETE.",
     "example": "API сделали в стиле REST: /users/42, /users/42/orders."},
    {"term": "CORS", "category": "Веб и API",
     "definition": "Защитный механизм браузера. Разрешает или запрещает фронтенду с одного домена обращаться к API на другом.",
     "example": "CORS не настроил — браузер молча режет запросы."},
    {"term": "Куки", "category": "Веб и API",
     "definition": "Маленькие файлы, которые браузер хранит для сайта. Часто используются для сессии и авторизации.",
     "example": "Куки очистил — пришлось логиниться заново."},
]


def seed_if_empty():
    db = SessionLocal()
    try:
        if db.query(Term).count() > 0:
            return
        for item in SEED:
            db.add(Term(**item))
        db.commit()
        print(f"[seed] добавлено терминов: {len(SEED)}")
    finally:
        db.close()


seed_if_empty()

# статику подключаем последней, чтобы /api/* имели приоритет
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
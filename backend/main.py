"""
Онлайн-словарь ИТ-сленга — бэкенд.
Локально:  uvicorn main:app --reload --port 8000
Env:       DATABASE_URL, ADMIN_USERNAME, ADMIN_PASSWORD,
           SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
           SMTP_FROM, SMTP_FROM_NAME, SMTP_USE_SSL
"""
from __future__ import annotations

import os
import json
import random
import secrets
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from pathlib import Path
from typing import Optional

from fastapi import (FastAPI, HTTPException, Query, Depends, Header,
                     BackgroundTasks)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import (create_engine, Column, Integer, String, Text,
                        Boolean, DateTime, ForeignKey, func, or_, text,
                        inspect)
from sqlalchemy.orm import (declarative_base, sessionmaker, Session,
                            relationship)
from passlib.hash import pbkdf2_sha256


# ---------------- пути и БД ----------------
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'slang.db'}")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ---------------- модели ----------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    email = Column(String(150), nullable=True)
    role = Column(String(20), nullable=False, default="user")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SessionToken(Base):
    __tablename__ = "sessions"
    token = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    user = relationship("User")


class Term(Base):
    __tablename__ = "terms"
    id = Column(Integer, primary_key=True)
    term = Column(String(200), nullable=False, unique=True, index=True)
    definition = Column(Text, nullable=False)
    example = Column(Text, nullable=False, default="")
    category = Column(String(80), nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                           nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)


class EditLog(Base):
    __tablename__ = "edit_log"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String(50), nullable=False)
    action = Column(String(30), nullable=False)
    target_type = Column(String(20), nullable=False)
    target_id = Column(Integer, nullable=True)
    target_name = Column(String(200), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


Base.metadata.create_all(engine)


# ---------------- миграция ----------------
def migrate():
    """Добавляет новые колонки в существующие таблицы, если их нет."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "email" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(150)"))


migrate()


# ---------------- SMTP ----------------
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "noreply@example.com")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Словарь ИТ-сленга")
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"


def smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def send_email(to_email: str, subject: str, body_text: str,
               body_html: Optional[str] = None) -> bool:
    """Отправляет письмо. Возвращает True при успехе."""
    if not smtp_configured():
        print("[smtp] не настроен, письмо не отправлено")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM))
    msg["To"] = to_email

    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        if SMTP_USE_SSL or SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[smtp] ошибка отправки на {to_email}: {e}")
        return False


def render_welcome(username: str):
    subject = "Добро пожаловать в Словарь ИТ-сленга"
    text = (f"Привет, {username}!\n\n"
            f"Твой аккаунт создан. Теперь ты можешь добавлять термины "
            f"и предлагать правки.\n\n"
            f"— Словарь ИТ-сленга")
    html = f"""<!doctype html>
<html><body style="font-family:sans-serif;background:#0f1117;color:#e6e9ef;padding:24px">
<div style="max-width:520px;margin:auto;background:#171a23;border-radius:16px;padding:28px;border:1px solid #2a2f3d">
<h2 style="color:#22d3ee;margin:0 0 16px">Привет, {username}!</h2>
<p style="line-height:1.6;color:#cdd3e0">Твой аккаунт создан. Теперь ты можешь добавлять термины и предлагать правки.</p>
<p style="color:#8b93a7;font-size:13px;margin-top:24px">— Словарь ИТ-сленга</p>
</div></body></html>"""
    return subject, text, html


# ---------------- пароли и логи ----------------
def hash_password(pw: str) -> str:
    return pbkdf2_sha256.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return pbkdf2_sha256.verify(pw, hashed)
    except Exception:
        return False


def log_action(db: Session, user, action: str, target_type: str,
               target_id: Optional[int] = None,
               target_name: Optional[str] = None,
               details: Optional[str] = None):
    db.add(EditLog(
        user_id=user.id if user else None,
        username=user.username if user else "guest",
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        details=details,
    ))


# ---------------- зависимости ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    x_session_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not x_session_token:
        return None
    sess = db.get(SessionToken, x_session_token)
    if not sess:
        return None
    return sess.user


def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(401, "Требуется вход")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Только для администратора")
    return user


# ---------------- схемы Pydantic ----------------
class RegisterIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=200)
    email: Optional[EmailStr] = None


class LoginIn(BaseModel):
    username: str
    password: str


class ProfileIn(BaseModel):
    email: Optional[EmailStr] = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    email: Optional[str] = None
    created_at: datetime
    class Config:
        from_attributes = True


class RoleIn(BaseModel):
    role: str


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
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


# ---------------- приложение ----------------
app = FastAPI(title="IT Slang Dictionary API", version="3.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ---------------- auth ----------------
@app.post("/api/auth/register", response_model=UserOut, status_code=201)
def register(payload: RegisterIn, background: BackgroundTasks,
             db: Session = Depends(get_db)):
    exists = (db.query(User)
                .filter(func.lower(User.username) == payload.username.lower())
                .first())
    if exists:
        raise HTTPException(409, "Такое имя уже занято")

    user = User(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        email=str(payload.email) if payload.email else None,
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_action(db, user, "register", "user", user.id, user.username)
    db.commit()

    if user.email and smtp_configured():
        subject, text, html = render_welcome(user.username)
        background.add_task(send_email, user.email, subject, text, html)

    return user


@app.post("/api/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = (db.query(User)
              .filter(func.lower(User.username) == payload.username.lower())
              .first())
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Неверное имя или пароль")
    token = secrets.token_urlsafe(32)
    db.add(SessionToken(token=token, user_id=user.id))
    log_action(db, user, "login", "user", user.id, user.username)
    db.commit()
    return {"token": token, "user": UserOut.model_validate(user).model_dump()}


@app.post("/api/auth/logout", status_code=204)
def logout(x_session_token: Optional[str] = Header(None),
           db: Session = Depends(get_db)):
    if x_session_token:
        sess = db.get(SessionToken, x_session_token)
        if sess:
            db.delete(sess)
            db.commit()


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(require_user)):
    return user


@app.get("/api/auth/profile", response_model=UserOut)
def get_profile(user: User = Depends(require_user)):
    return user


@app.put("/api/auth/profile", response_model=UserOut)
def update_profile(payload: ProfileIn,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_user)):
    changes = {}
    data = payload.model_dump(exclude_unset=True)

    if "email" in data:
        new_email = str(data["email"]) if data["email"] else None
        if user.email != new_email:
            changes["email"] = {"from": user.email, "to": new_email}
            user.email = new_email

    if changes:
        db.commit()
        db.refresh(user)
        log_action(db, user, "update_profile", "user", user.id, user.username,
                   json.dumps(changes, ensure_ascii=False))
        db.commit()

    return user


# ---------------- users (admin) ----------------
@app.get("/api/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).order_by(User.id).all()


@app.put("/api/users/{user_id}/role", response_model=UserOut)
def change_role(user_id: int, payload: RoleIn,
                db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    if payload.role not in ("admin", "user"):
        raise HTTPException(400, "Роль: 'admin' или 'user'")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    if u.id == admin.id and payload.role != "admin":
        raise HTTPException(400, "Нельзя снять с себя админа")
    old = u.role
    u.role = payload.role
    db.commit()
    db.refresh(u)
    log_action(db, admin, "change_role", "user", u.id, u.username,
               json.dumps({"from": old, "to": u.role}, ensure_ascii=False))
    db.commit()
    return u


# ---------------- logs (admin) ----------------
@app.get("/api/logs")
def list_logs(limit: int = Query(300, ge=1, le=1000),
              db: Session = Depends(get_db),
              _: User = Depends(require_admin)):
    rows = (db.query(EditLog)
              .order_by(EditLog.created_at.desc())
              .limit(limit).all())
    return [{
        "id": r.id,
        "username": r.username,
        "action": r.action,
        "target_type": r.target_type,
        "target_id": r.target_id,
        "target_name": r.target_name,
        "details": r.details,
        "created_at": r.created_at.isoformat(),
    } for r in rows]


# ---------------- terms ----------------
@app.get("/api/terms")
def list_terms(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sort: str = Query("term", pattern="^(term|created_at|updated_at)$"),
    limit: int = Query(100, ge=1, le=500),
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
def create_term(payload: TermCreate,
                db: Session = Depends(get_db),
                user: User = Depends(require_user)):
    exists = (db.query(Term)
                .filter(func.lower(Term.term) == payload.term.lower())
                .first())
    if exists:
        raise HTTPException(409, "Такой термин уже есть")
    t = Term(term=payload.term, definition=payload.definition,
             example=payload.example, category=payload.category,
             created_by_id=user.id, created_by=user.username)
    db.add(t)
    db.commit()
    db.refresh(t)
    log_action(db, user, "create", "term", t.id, t.term,
               json.dumps({"category": t.category}, ensure_ascii=False))
    db.commit()
    return t


@app.put("/api/terms/{term_id}", response_model=TermOut)
def update_term(term_id: int, payload: TermUpdate,
                db: Session = Depends(get_db),
                user: User = Depends(require_user)):
    t = db.get(Term, term_id)
    if not t:
        raise HTTPException(404, "Термин не найден")
    if user.role != "admin" and t.created_by_id != user.id:
        raise HTTPException(403, "Можно править только свои термины")
    data = payload.model_dump(exclude_unset=True)
    if "term" in data:
        clash = (db.query(Term)
                   .filter(func.lower(Term.term) == data["term"].lower(),
                           Term.id != term_id).first())
        if clash:
            raise HTTPException(409, "Термин с таким именем уже есть")
    changes = {}
    for k, v in data.items():
        old = getattr(t, k)
        if old != v:
            changes[k] = {"from": old, "to": v}
            setattr(t, k, v)
    if changes:
        db.commit()
        db.refresh(t)
        log_action(db, user, "update", "term", t.id, t.term,
                   json.dumps(changes, ensure_ascii=False))
        db.commit()
    return t


@app.delete("/api/terms/{term_id}", status_code=204)
def delete_term(term_id: int,
                db: Session = Depends(get_db),
                user: User = Depends(require_user)):
    t = db.get(Term, term_id)
    if not t:
        raise HTTPException(404, "Термин не найден")
    if user.role != "admin" and t.created_by_id != user.id:
        raise HTTPException(403, "Можно удалять только свои термины")
    name, tid = t.term, t.id
    db.delete(t)
    db.commit()
    log_action(db, user, "delete", "term", tid, name)
    db.commit()


@app.get("/api/categories")
def list_categories(db: Session = Depends(get_db)):
    rows = (db.query(Term.category, func.count(Term.id))
              .group_by(Term.category)
              .order_by(Term.category).all())
    return [{"name": n, "count": c} for n, c in rows]


@app.get("/api/random", response_model=TermOut)
def random_term(db: Session = Depends(get_db)):
    ids = [r[0] for r in db.query(Term.id).all()]
    if not ids:
        raise HTTPException(404, "Словарь пуст")
    return db.get(Term, random.choice(ids))


# ---------------- стартовые данные ----------------
SEED = [
    ("Спринт", "Процесс разработки", "Короткий отрезок времени (1–2 недели), за который команда делает выбранный набор задач.", "Взяли в спринт три задачи."),
    ("Стендап", "Процесс разработки", "Ежедневная встреча команды: что сделал, что сделаю, что мешает.", "Стендап в 10:00, уложились за 15 минут."),
    ("Бэклог", "Процесс разработки", "Список всех задач проекта, упорядоченный по приоритету.", "Идея ушла в бэклог."),
    ("Код-ревью", "Процесс разработки", "Проверка чужого кода коллегой перед вливанием в основную ветку.", "Пушни — я на ревью гляну."),
    ("Деплой", "Процесс разработки", "Выкатка кода на сервер, где им пользуются пользователи.", "Деплой в пятницу — плохая примета."),
    ("Релиз", "Процесс разработки", "Финальная версия продукта, отданная пользователям.", "Релиз 2.0 в конце месяца."),
    ("Техдолг", "Процесс разработки", "Накопленные компромиссы в коде, которые придётся переделывать.", "Половина спринта ушла на техдолг."),
    ("Ретро", "Процесс разработки", "Ретроспектива — встреча после спринта: что было хорошо, что плохо.", "На ретро решили брать не больше трёх задач."),
    ("Скрам", "Процесс разработки", "Гибкая методология с короткими итерациями и ролями.", "Работаем по скраму."),
    ("Канбан", "Процесс разработки", "Метод управления задачами через визуальную доску с колонками.", "Перешли на канбан, стало нагляднее."),
    ("MVP", "Процесс разработки", "Minimum Viable Product — минимальная версия продукта с ключевой ценностью.", "Собрали MVP за месяц."),
    ("POC", "Процесс разработки", "Proof of Concept — прототип для проверки идеи.", "Сделали POC, идея взлетела."),
    ("Продакт-оунер", "Процесс разработки", "Владелец продукта, отвечает за содержание бэклога и приоритеты.", "Продакт сказал — сначала авторизация."),
    ("Скрам-мастер", "Процесс разработки", "Фасилитатор процессов скрама, помогает команде не буксовать.", "Скрам-мастер убрал блокер."),
    ("Сторипойнт", "Процесс разработки", "Условная единица оценки сложности задачи.", "Поставили задаче 5 сторипойнтов."),
    ("Бурндаун", "Процесс разработки", "График, показывающий, сколько работы осталось до конца спринта.", "Бурндаун идёт ровно."),
    ("Эпик", "Процесс разработки", "Большая задача, которую разбивают на несколько юзер-стори.", "Эпик по авторизации на квартал."),
    ("Юзер-стори", "Процесс разработки", "Описание задачи с точки зрения пользователя.", "Написали юзер-стори на регистрацию."),
    ("Спринт-планирование", "Процесс разработки", "Встреча в начале спринта, где выбирают задачи из бэклога.", "Планирование на два часа."),
    ("Дейли", "Процесс разработки", "Син. стендап. Ежедневная короткая встреча команды.", "Пошли на дейли."),
    ("Груминг", "Процесс разработки", "Уточнение и оценка задач в бэклоге перед спринтом.", "Груминг бэклога во вторник."),
    ("Демо", "Процесс разработки", "Показ заказчику, что сделано за спринт.", "На демо показали новую форму."),
    ("Продакшн", "Процесс разработки", "Боевая среда, где работают реальные пользователи.", "Не трогай продакшн руками."),
    ("Вайтборд", "Процесс разработки", "Доска для совместной работы.", "На вайтборде нарисовали схему."),
    ("Роадмап", "Процесс разработки", "План развития продукта на месяцы вперёд.", "В роадмапе на квартал три фичи."),
    ("Велосити", "Процесс разработки", "Скорость команды — сколько сторипойнтов закрывают за спринт.", "Велосити выросла до 40."),
    ("Милстоун", "Процесс разработки", "Ключевая контрольная точка проекта.", "Первый милстоун — бета."),
    ("Блокер", "Процесс разработки", "Задача или проблема, которая мешает работать остальным.", "Нашли блокер — API не отдаёт данные."),
    ("Тайм-боксинг", "Процесс разработки", "Ограничение задачи по времени.", "Держим ретро в тайм-боксинге 45 минут."),
    ("Фаза", "Процесс разработки", "Крупный этап проекта между ключевыми событиями.", "Первая фаза — прототип."),
    ("Баг", "Код и качество", "Ошибка в программе, из-за которой она работает не так.", "Поймал баг в пустом поле."),
    ("Фича", "Код и качество", "Новая функциональность продукта.", "За фичу отвечает фронт."),
    ("Дебажить", "Код и качество", "Искать и исправлять ошибки в программе.", "Дебажил парсер до трёх ночи."),
    ("Рефакторинг", "Код и качество", "Переписывание кода без изменения поведения.", "Разбил функцию на три."),
    ("Костыль", "Код и качество", "Временное некрасивое решение.", "Поставил костыль перед релизом."),
    ("Хардкод", "Код и качество", "Значения, прямо вписанные в код вместо конфига.", "URL хардкодом прописан."),
    ("Легаси", "Код и качество", "Старый код, который работает, но его никто не хочет трогать.", "Трогать легаси страшно."),
    ("Говнокод", "Код и качество", "Код, который работает, но читать его больно.", "Открыл модуль — там ГК."),
    ("Велосипед", "Код и качество", "Самописное решение вместо готовой библиотеки.", "Зачем свой велосипед?"),
    ("Линтер", "Код и качество", "Инструмент автоматической проверки кода.", "Линтер ругается на переменную."),
    ("Ревью кода", "Код и качество", "Проверка чужого кода перед мержем.", "Оставил два замечания на ревью."),
    ("Коммит", "Код и качество", "Зафиксированное изменение кода в git.", "Сделал три коммита за день."),
    ("Мерж", "Код и качество", "Слияние одной ветки с другой.", "Мерж в main прошёл без конфликтов."),
    ("Ветка", "Код и качество", "Отдельная линия разработки в git.", "Создал ветку под новую фичу."),
    ("Конфликт", "Код и качество", "Ситуация, когда git не может автоматически слить изменения.", "Решил конфликт руками."),
    ("Ребейз", "Код и качество", "Перенос коммитов одной ветки на другую вершину.", "Сделал ребейз на main."),
    ("Черри-пик", "Код и качество", "Перенос одного конкретного коммита из ветки в ветку.", "Черри-пикнул хотфикс."),
    ("Форк", "Код и качество", "Копия чужого репозитория под своим аккаунтом.", "Сделал форк и предложил PR."),
    ("Пул-реквест", "Код и качество", "Запрос на слияние изменений в основную ветку.", "Открыл PR с новой фичей."),
    ("Дедлок", "Код и качество", "Ситуация, когда два процесса ждут друг друга.", "Словили дедлок в проде."),
    ("Мемори-лик", "Код и качество", "Утечка памяти — программа не освобождает память.", "Мемори-лик съел 8 ГБ за сутки."),
    ("Оверфлоу", "Код и качество", "Переполнение — значение вышло за границы типа.", "Оверфлоу int при большом числе."),
    ("Ассерт", "Код и качество", "Проверка предположения в коде.", "Ассерт упал — инвариант нарушен."),
    ("Деприкейтед", "Код и качество", "Устаревшее, но пока работающее.", "Метод деприкейтед, используй новый."),
    ("Тулчейн", "Код и качество", "Набор инструментов сборки проекта.", "Настроил тулчейн под Webpack."),
    ("Компилятор", "Код и качество", "Программа, переводящая код в машинные инструкции.", "Компилятор пожаловался на тип."),
    ("Интерпретатор", "Код и качество", "Программа, выполняющая код построчно.", "Python — интерпретируемый язык."),
    ("Рантайм", "Код и качество", "Среда выполнения программы во время работы.", "Ошибка вылезла только в рантайме."),
    ("Синтаксис", "Код и качество", "Правила написания кода, которые понимает язык.", "Синтаксическая ошибка в скобке."),
    ("Семантика", "Код и качество", "Смысл кода, в отличие от его формы.", "Синтаксис ок, а семантика не та."),
    ("Сервер", "Инфраструктура", "Компьютер или программа, принимающая запросы.", "Упал сервер — половина клиентов легла."),
    ("Кластер", "Инфраструктура", "Группа серверов, работающих как один.", "Кластер из пяти нод."),
    ("Докер", "Инфраструктура", "Упаковка приложения со всеми зависимостями.", "Завернул сервис в докер."),
    ("Контейнер", "Инфраструктура", "Изолированная среда с приложением и зависимостями.", "Контейнер запускается за секунды."),
    ("Кубики", "Инфраструктура", "Kubernetes (K8s) — система оркестрации контейнеров.", "Развернули всё в кубиках."),
    ("Облако", "Инфраструктура", "Арендованные по требованию чужие серверы.", "Переехали в облако."),
    ("Мониторинг", "Инфраструктура", "Слежение за состоянием сервиса.", "Настроили мониторинг."),
    ("Даунтайм", "Инфраструктура", "Время, когда сервис недоступен.", "Даунтайм 30 секунд."),
    ("Аптайм", "Инфраструктура", "Время, когда сервис работает.", "Аптайм 99.9%."),
    ("CI/CD", "Инфраструктура", "Автопроверка и автодеплой при пуше.", "CI/CD гоняет тесты на каждый пуш."),
    ("Пайплайн", "Инфраструктура", "Последовательность шагов сборки и выкатки.", "Пайплайн упал на тестах."),
    ("Дженкинс", "Инфраструктура", "Популярный инструмент для CI/CD.", "Дженкинс собирает ночью."),
    ("Ансибл", "Инфраструктура", "Инструмент управления конфигурациями серверов.", "Ансибл раскатывает конфиги."),
    ("Терраформ", "Инфраструктура", "Инструмент описания инфраструктуры как кода.", "Терраформ поднимает кластер."),
    ("ВМ", "Инфраструктура", "Виртуальная машина.", "Подняли ВМ под тесты."),
    ("Хайпервизор", "Инфраструктура", "Софт, который запускает виртуальные машины.", "Хайпервизор на голом железе."),
    ("Балансировщик", "Инфраструктура", "Распределяет нагрузку между серверами.", "Балансировщик кидает по кругу."),
    ("Прокси", "Инфраструктура", "Посредник между клиентом и сервером.", "Настроил прокси для запросов."),
    ("Реверс-прокси", "Инфраструктура", "Прокси перед серверами, распределяет входящие.", "Nginx как реверс-прокси."),
    ("Нода", "Инфраструктура", "Отдельный узел в кластере или сети.", "Одна нода выпала из кластера."),
    ("Мастер-нода", "Инфраструктура", "Главный узел, который управляет остальными.", "Мастер-нода держит состояние."),
    ("Воркер", "Инфраструктура", "Рабочий узел, который выполняет задачи.", "Добавили ещё двух воркеров."),
    ("Хостинг", "Инфраструктура", "Услуга размещения сайта на чужом сервере.", "Взяли хостинг на год."),
    ("VPS", "Инфраструктура", "Virtual Private Server.", "Подняли VPS за 5 баксов."),
    ("Дедик", "Инфраструктура", "Выделенный физический сервер.", "Взяли дедик под ML."),
    ("Шард", "Инфраструктура", "Часть данных, отделённая по ключу.", "Разбили базу на 4 шарда."),
    ("Реплика", "Инфраструктура", "Копия базы или сервиса для отказоустойчивости.", "Реплика отстаёт на 2 секунды."),
    ("Бэкап", "Инфраструктура", "Резервная копия данных.", "Бэкап делаем каждую ночь."),
    ("Снэпшот", "Инфраструктура", "Мгновенный снимок состояния диска.", "Снял снэпшот перед обновлением."),
    ("Вольюм", "Инфраструктура", "Постоянный диск для контейнера.", "Примонтировал вольюм."),
    ("Тимлид", "Команда и роли", "Руководитель команды разработчиков.", "Тимлид раздал задачи."),
    ("Сеньор", "Команда и роли", "Опытный разработчик, решающий сложные задачи сам.", "Сеньор за 20 минут нашёл баг."),
    ("Мидл", "Команда и роли", "Разработчик среднего уровня.", "Мидл закрыл задачу без вопросов."),
    ("Джун", "Команда и роли", "Начинающий разработчик.", "Джун сделал первую фичу."),
    ("Холивар", "Команда и роли", "Жаркий бесполезный спор о вкусах.", "Опять холивар про табы."),
    ("Шеринг", "Команда и роли", "Демонстрация сделанного коллегам.", "На шеринге показали новую фичу."),
    ("CTO", "Команда и роли", "Chief Technology Officer.", "CTO приехал на встречу."),
    ("DevOps", "Команда и роли", "Инженер, отвечающий за инфраструктуру и CI/CD.", "DevOps поднял новый сервер."),
    ("QA", "Команда и роли", "Тестировщик.", "QA нашёл 15 багов."),
    ("Архитектор", "Команда и роли", "Отвечает за общую структуру системы.", "Архитектор нарисовал схему сервисов."),
    ("Тех-лид", "Команда и роли", "Технический лидер команды.", "Тех-лид выбрал стек."),
    ("Продакт-менеджер", "Команда и роли", "Отвечает за продукт.", "Продакт расставил приоритеты."),
    ("Дизайнер", "Команда и роли", "Отвечает за внешний вид интерфейса.", "Дизайнер нарисовал макет."),
    ("Аналитик", "Команда и роли", "Собирает требования к продукту.", "Аналитик написал ТЗ."),
    ("Стейкхолдер", "Команда и роли", "Заинтересованная сторона проекта.", "Стейкхолдеры ждут демо."),
    ("Онбординг", "Команда и роли", "Введение нового сотрудника в курс дела.", "Онбординг занял неделю."),
    ("Офбординг", "Команда и роли", "Вывод сотрудника из команды.", "Офбординг прошёл гладко."),
    ("Ревью перформенс", "Команда и роли", "Оценка работы сотрудника.", "На ревью подняли грейд."),
    ("Карьерный трек", "Команда и роли", "План роста сотрудника.", "Обсудили карьерный трек."),
    ("Ментор", "Команда и роли", "Наставник, который помогает расти.", "Ментор гоняет джуна по задачам."),
    ("Менти", "Команда и роли", "Тот, кого наставляет ментор.", "Менти вырос до мидла за год."),
    ("Фасилитатор", "Команда и роли", "Ведёт встречу.", "Фасилитатор вернул разговор в русло."),
    ("Дедлайн", "Команда и роли", "Крайний срок сдачи работы.", "Дедлайн — пятница."),
    ("Овертайм", "Команда и роли", "Работа сверх нормы.", "Овертайм перед релизом."),
    ("Митап", "Команда и роли", "Встреча специалистов для обмена опытом.", "Сходили на митап по Go."),
    ("Фронтенд", "Веб и API", "Клиентская часть приложения.", "Кнопку поправит фронт."),
    ("Бэкенд", "Веб и API", "Серверная часть приложения.", "Бэкенд на FastAPI."),
    ("Фулстек", "Веб и API", "Разработчик, умеющий и фронт, и бэк.", "Фулстек сделал фичу целиком."),
    ("API", "Веб и API", "Интерфейс взаимодействия программ.", "Фронт получает данные по API."),
    ("Эндпоинт", "Веб и API", "Конкретный адрес API.", "Добавили эндпоинт поиска."),
    ("REST", "Веб и API", "Стиль API с ресурсами и HTTP-методами.", "API в стиле REST."),
    ("GraphQL", "Веб и API", "Язык запросов к API.", "Перешли с REST на GraphQL."),
    ("CORS", "Веб и API", "Механизм браузера для межсайтовых запросов.", "CORS не настроен — режутся запросы."),
    ("Куки", "Веб и API", "Маленькие файлы, которые браузер хранит для сайта.", "Куки очистил — логинься заново."),
    ("Сессия", "Веб и API", "Период активности пользователя на сайте.", "Сессия истекла через час."),
    ("Токен", "Веб и API", "Строка, подтверждающая право доступа.", "Обновил токен."),
    ("JWT", "Веб и API", "JSON Web Token.", "JWT живёт 15 минут."),
    ("OAuth", "Веб и API", "Протокол авторизации через сторонний сервис.", "Логин через OAuth Google."),
    ("Вебхук", "Веб и API", "HTTP-запрос, который сервис отправляет при событии.", "Настроил вебхук на платёж."),
    ("Сокет", "Веб и API", "Точка соединения процессов по сети.", "Открыли сокет на порт 8080."),
    ("WebSocket", "Веб и API", "Протокол двусторонней связи в реальном времени.", "Чат работает через WebSocket."),
    ("HTTP", "Веб и API", "Протокол передачи данных в вебе.", "Запрос по HTTP вернул 200."),
    ("HTTPS", "Веб и API", "HTTP с шифрованием.", "Сайт по HTTPS — с замком."),
    ("Хедер", "Веб и API", "Заголовок HTTP-запроса или ответа.", "В хедере передали токен."),
    ("Пейлоад", "Веб и API", "Полезная нагрузка запроса.", "В пейлоаде пришёл JSON."),
    ("Код 200", "Веб и API", "HTTP-ответ «всё хорошо».", "Сервер вернул 200."),
    ("Код 404", "Веб и API", "HTTP-ответ «не найдено».", "Страница отдала 404."),
    ("Код 500", "Веб и API", "HTTP-ответ «внутренняя ошибка сервера».", "Пятьсот на проде — плохо."),
    ("Редирект", "Веб и API", "Перенаправление с одного URL на другой.", "Старый URL редиректит на новый."),
    ("Кэш", "Веб и API", "Сохранённая копия ответа для ускорения.", "Кэш сбросил — стало свежее."),
    ("SQL", "Базы данных", "Язык структурированных запросов.", "Написал сложный SQL-запрос."),
    ("NoSQL", "Базы данных", "Не-реляционные базы.", "Взяли MongoDB как NoSQL."),
    ("Миграция", "Базы данных", "Изменение схемы БД с версионированием.", "Накатил миграцию на прод."),
    ("Схема", "Базы данных", "Структура таблиц и связей.", "Схему утвердили на ревью."),
    ("Индекс", "Базы данных", "Структура для быстрого поиска.", "Индекс ускорил запрос в 100 раз."),
    ("Транзакция", "Базы данных", "Набор операций, выполняемых вместе.", "Транзакция откатилась."),
    ("Роллбек", "Базы данных", "Откат транзакции к исходному состоянию.", "Сделали роллбек деплоя."),
    ("Репликация", "Базы данных", "Копирование данных между серверами БД.", "Настроил репликацию."),
    ("Шардинг", "Базы данных", "Разбиение данных по нескольким серверам.", "Шардинг по user_id."),
    ("Партиционирование", "Базы данных", "Разбиение большой таблицы на части.", "Партиционировали по дате."),
    ("Джойн", "Базы данных", "Соединение двух таблиц в одном запросе.", "JOIN по user_id."),
    ("Подзапрос", "Базы данных", "Запрос внутри запроса.", "Подзапрос вернул пусто."),
    ("ORM", "Базы данных", "Object-Relational Mapping.", "SQLAlchemy — это ORM."),
    ("Вьюха", "Базы данных", "Виртуальная таблица на запросе.", "Отчёты тянут из вьюхи."),
    ("Триггер", "Базы данных", "Процедура, срабатывающая на событие в БД.", "Триггер обновляет счётчик."),
    ("Сторид процедура", "Базы данных", "Процедура на стороне БД.", "Вся логика в сторид процедурах."),
    ("Денормализация", "Базы данных", "Дублирование данных ради скорости.", "Денормализовали таблицу заказов."),
    ("Нормализация", "Базы данных", "Устранение дублирования через разбиение.", "Нормализовали до третьей формы."),
    ("Суррогатный ключ", "Базы данных", "Искусственный ключ для уникальности строки.", "Суррогатный id."),
    ("Внешний ключ", "Базы данных", "Колонка, ссылающаяся на ключ другой таблицы.", "Внешний ключ с ON DELETE CASCADE."),
    ("Хэш", "Безопасность", "Преобразование в строку фиксированной длины.", "Пароли хранят хэшами."),
    ("Соль", "Безопасность", "Случайная строка к паролю перед хэшированием.", "Соль защищает от радужных таблиц."),
    ("Шифрование", "Безопасность", "Преобразование данных так, что без ключа не прочитать.", "Трафик шифруется TLS."),
    ("SSL", "Безопасность", "Устаревший протокол шифрования веб-трафика.", "Сертификат SSL истёк."),
    ("TLS", "Безопасность", "Современный протокол шифрования.", "Настроил TLS 1.3."),
    ("Сертификат", "Безопасность", "Файл, подтверждающий подлинность сайта.", "Let's Encrypt бесплатный."),
    ("Уязвимость", "Безопасность", "Слабое место в системе.", "Закрыли уязвимость в библиотеке."),
    ("Эксплойт", "Безопасность", "Код, использующий уязвимость.", "Эксплойт на GitHub."),
    ("XSS", "Безопасность", "Cross-Site Scripting.", "Экранируй ввод от XSS."),
    ("CSRF", "Безопасность", "Cross-Site Request Forgery.", "CSRF-токен обязателен."),
    ("SQL-инъекция", "Безопасность", "Внедрение SQL-кода через ввод.", "Параметризуй запросы."),
    ("Фишинг", "Безопасность", "Обман, чтобы выманить пароли.", "Пришло письмо с фишингом."),
    ("Брутфорс", "Безопасность", "Перебор паролей или ключей.", "Rate limit от брутфорса."),
    ("DDoS", "Безопасность", "Атака через массовые запросы.", "DDoS положил сайт на час."),
    ("Аудит", "Безопасность", "Проверка системы на уязвимости.", "Прошли аудит безопасности."),
    ("Юнит-тест", "Тестирование", "Тест одной маленькой функции.", "Написал юнит-тест на парсер."),
    ("Интеграционный тест", "Тестирование", "Тест взаимодействия модулей.", "Поймал баг в API."),
    ("E2E тест", "Тестирование", "End-to-End — тест всего пути пользователя.", "E2E гоняет покупку."),
    ("Смоук-тест", "Тестирование", "Быстрая проверка, что основное работает.", "Смоук-тест прошёл."),
    ("Регрессия", "Тестирование", "Проверка, что старое не сломалось.", "Регрессия поймала поиск."),
    ("Тест-кейс", "Тестирование", "Конкретный сценарий проверки.", "Написали 20 тест-кейсов."),
    ("Тест-сьют", "Тестирование", "Набор тестов по смыслу.", "Тест-сьют идёт 4 минуты."),
    ("Покрытие", "Тестирование", "Процент кода под тестами.", "Покрытие 85%."),
    ("Мок", "Тестирование", "Заглушка, имитирующая реальный объект.", "Замокал внешний API."),
    ("Стаб", "Тестирование", "Упрощённая заглушка.", "Стаб возвращает 200."),
    ("Спай", "Тестирование", "Обёртка, записывающая вызовы.", "Спай показал вызовы."),
    ("Фикстура", "Тестирование", "Данные для теста.", "Фикстура готовит БД."),
    ("TDD", "Тестирование", "Test-Driven Development.", "Работаем по TDD."),
    ("BDD", "Тестирование", "Behavior-Driven Development.", "BDD на Gherkin."),
    ("Баг-репорт", "Тестирование", "Описание бага с шагами.", "QA прислал баг-репорты."),
    ("Мейн", "Git", "Основная ветка репозитория.", "Мержим всё в main."),
    ("Мастер", "Git", "Старое название основной ветки.", "Раньше master."),
    ("Диф", "Git", "Разница между состояниями кода.", "Посмотри диф перед мержем."),
    ("Патч", "Git", "Набор изменений в виде файла.", "Применил патч из PR."),
    ("Тэг", "Git", "Метка на коммите.", "Поставил тег v1.0.0."),
    ("Хотфикс", "Git", "Срочное исправление в проде.", "Выкатили хотфикс."),
    ("Фича-ветка", "Git", "Отдельная ветка под фичу.", "Создал фича-ветку."),
    ("Сквош", "Git", "Слияние коммитов в один.", "Сквошнул перед PR."),
    ("Стэш", "Git", "Временное откладывание изменений.", "Закинул правки в стэш."),
    ("Ревёрт", "Git", "Откат коммита через создание обратного.", "Ревёртнул коммит."),
    ("Модель", "Data Science / ML", "Обученный алгоритм для предсказаний.", "Модель 92% точности."),
    ("Датасет", "Data Science / ML", "Набор данных для обучения.", "Датасет на 100 ГБ."),
    ("Тренировка", "Data Science / ML", "Обучение модели на данных.", "Тренировка 8 часов."),
    ("Инференс", "Data Science / ML", "Применение модели к новым данным.", "Инференс за 50 мс."),
    ("Оверфит", "Data Science / ML", "Переобучение модели.", "Оверфит на малой выборке."),
    ("Лосс", "Data Science / ML", "Функция потерь.", "Лосс падает."),
    ("Эпоха", "Data Science / ML", "Один проход по датасету.", "20 эпох."),
    ("Батч", "Data Science / ML", "Порция данных за шаг обучения.", "Батч размером 32."),
    ("Тензор", "Data Science / ML", "Многомерный массив чисел.", "Тензор формы (32,128,768)."),
    ("Пайплайн данных", "Data Science / ML", "Обработка данных до обучения.", "Пайплайн упал на джойне."),
    ("SDK", "Мобильная разработка", "Software Development Kit.", "Скачал Android SDK."),
    ("APK", "Мобильная разработка", "Установочный пакет Android.", "Собрал APK."),
    ("IPA", "Мобильная разработка", "Установочный пакет iOS.", "Залил IPA в TestFlight."),
    ("Эмулятор", "Мобильная разработка", "Программа, эмулирующая устройство.", "Запустил эмулятор Pixel."),
    ("Симулятор", "Мобильная разработка", "Аналог эмулятора в iOS.", "iOS-симулятор."),
    ("Нативный", "Мобильная разработка", "На платформенном языке.", "Нативное приложение быстрее."),
    ("Кроссплатформенный", "Мобильная разработка", "Один код под iOS и Android.", "Экономит время."),
    ("React Native", "Мобильная разработка", "Фреймворк мобильной разработки на JS.", "Приложение на React Native."),
    ("Flutter", "Мобильная разработка", "Фреймворк от Google.", "Flutter рисует UI сам."),
    ("Гибрид", "Мобильная разработка", "Приложение на веб-технологиях.", "Гибрид на Cordova."),
    ("IP", "Сети", "Уникальный адрес устройства.", "Сервер на 10.0.0.1."),
    ("DNS", "Сети", "Перевод домена в IP.", "DNS не резолвит домен."),
    ("Порт", "Сети", "Номер сервиса на устройстве.", "Сайт на порту 443."),
    ("Протокол", "Сети", "Правила общения устройств.", "TCP надёжнее UDP."),
    ("Пинг", "Сети", "Задержка отклика в мс.", "Пинг 30 мс."),
    ("Латентность", "Сети", "Задержка запрос-ответ.", "Латентность 500 мс."),
    ("Бэндвидс", "Сети", "Пропускная способность канала.", "Бэндвидс 1 Гбит/с."),
    ("Пакет", "Сети", "Порция данных по сети.", "Потеряли пакет."),
    ("NAT", "Сети", "Преобразование адресов.", "NAT прячет домашние IP."),
    ("VPN", "Сети", "Шифрованный туннель в другую сеть.", "Через VPN IP не виден."),
]


# ---------------- инициализация ----------------
def ensure_admin_exists():
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            username = os.environ.get("ADMIN_USERNAME", "admin")
            password = os.environ.get("ADMIN_PASSWORD", "admin12345")
            db.add(User(username=username,
                        password_hash=hash_password(password),
                        role="admin"))
            db.commit()
            print(f"[init] создан администратор: {username}")
    finally:
        db.close()


def seed_terms_if_empty():
    db = SessionLocal()
    try:
        if db.query(Term).count() > 0:
            return
        admin = db.query(User).filter(User.role == "admin").first()
        admin_id = admin.id if admin else None
        admin_name = admin.username if admin else "system"
        for term, category, definition, example in SEED:
            db.add(Term(term=term, category=category,
                        definition=definition, example=example,
                        created_by_id=admin_id, created_by=admin_name))
        db.commit()
        print(f"[seed] добавлено терминов: {len(SEED)}")
    finally:
        db.close()


ensure_admin_exists()
seed_terms_if_empty()


# ---------------- статика ----------------
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
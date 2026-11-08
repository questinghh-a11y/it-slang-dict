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
import csv
import io
import random
import secrets
import smtplib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from pathlib import Path
from typing import Optional

from fastapi import (FastAPI, HTTPException, Query, Depends, Header,
                     BackgroundTasks, Request)
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import (create_engine, Column, Integer, String, Text,
                        Boolean, DateTime, ForeignKey, func, or_, and_,
                        text, inspect)
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
    username = Column(String(50), nullable=False, index=True)
    action = Column(String(30), nullable=False, index=True)
    target_type = Column(String(20), nullable=False)
    target_id = Column(Integer, nullable=True)
    target_name = Column(String(200), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)
    session_ref = Column(String(12), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        index=True)


# ---------------- миграция ----------------
def migrate():
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        with engine.begin() as conn:
            if "email" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(150)"))

    if "edit_log" in tables:
        cols = {c["name"] for c in inspector.get_columns("edit_log")}
        with engine.begin() as conn:
            if "ip_address" not in cols:
                conn.execute(text("ALTER TABLE edit_log ADD COLUMN ip_address VARCHAR(64)"))
            if "user_agent" not in cols:
                conn.execute(text("ALTER TABLE edit_log ADD COLUMN user_agent VARCHAR(300)"))
            if "session_ref" not in cols:
                conn.execute(text("ALTER TABLE edit_log ADD COLUMN session_ref VARCHAR(12)"))


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
            f"Твой аккаунт создан.\n\n— Словарь ИТ-сленга")
    html = f"""<!doctype html>
<html><body style="font-family:sans-serif;background:#0f1117;color:#e6e9ef;padding:24px">
<div style="max-width:520px;margin:auto;background:#171a23;border-radius:16px;padding:28px;border:1px solid #2a2f3d">
<h2 style="color:#22d3ee;margin:0 0 16px">Привет, {username}!</h2>
<p style="line-height:1.6;color:#cdd3e0">Твой аккаунт создан.</p>
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


def client_info(request: Optional[Request]) -> tuple[Optional[str], Optional[str]]:
    if request is None:
        return None, None
    ip = None
    ua = request.headers.get("user-agent")
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    elif request.client:
        ip = request.client.host
    if ua and len(ua) > 300:
        ua = ua[:297] + "..."
    return ip, ua


def log_action(db: Session, user, action: str, target_type: str,
               target_id: Optional[int] = None,
               target_name: Optional[str] = None,
               details: Optional[str] = None,
               request: Optional[Request] = None,
               session_ref: Optional[str] = None):
    ip, ua = client_info(request)
    db.add(EditLog(
        user_id=user.id if user else None,
        username=user.username if user else "guest",
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        details=details,
        ip_address=ip,
        user_agent=ua,
        session_ref=session_ref,
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


# ---------------- СТАРТОВЫЕ ДАННЫЕ И ИНИЦИАЛИЗАЦИЯ ----------------
# (Твой огромный массив SEED я скрыл для краткости ответа,
#  вставь свой список SEED = [...] прямо сюда!)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код выполняется при запуске сервера
    print("Запуск сервера...")
    Base.metadata.create_all(engine)
    migrate()
    ensure_admin_exists()
    seed_terms_if_empty()
    yield
    # Код выполняется при остановке сервера
    print("Остановка сервера...")


# ---------------- приложение ----------------
app = FastAPI(title="IT Slang Dictionary API", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ---------------- auth ----------------
@app.post("/api/auth/register", response_model=UserOut, status_code=201)
def register(payload: RegisterIn, background: BackgroundTasks,
             request: Request, db: Session = Depends(get_db)):
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

    log_action(db, user, "register", "user", user.id, user.username,
               details=json.dumps({"email": bool(user.email)}, ensure_ascii=False),
               request=request)
    db.commit()

    if user.email and smtp_configured():
        subject, text_body, html = render_welcome(user.username)
        background.add_task(send_email, user.email, subject, text_body, html)

    return user


@app.post("/api/auth/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = (db.query(User)
              .filter(func.lower(User.username) == payload.username.lower())
              .first())

    if not user or not verify_password(payload.password, user.password_hash):
        fake = type("U", (), {"id": None, "username": payload.username})()
        log_action(db, fake, "login_failed", "user", None, payload.username,
                   details="неверное имя или пароль", request=request)
        db.commit()
        raise HTTPException(401, "Неверное имя или пароль")

    token = secrets.token_urlsafe(32)
    db.add(SessionToken(token=token, user_id=user.id))
    log_action(db, user, "login", "user", user.id, user.username,
               session_ref=token[:8], request=request)
    db.commit()
    return {"token": token, "user": UserOut.model_validate(user).model_dump()}


@app.post("/api/auth/logout", status_code=204)
def logout(x_session_token: Optional[str] = Header(None),
           request: Request = None,
           db: Session = Depends(get_db)):
    if x_session_token:
        sess = db.get(SessionToken, x_session_token)
        if sess:
            user = sess.user
            log_action(db, user, "logout", "user", user.id, user.username,
                       session_ref=x_session_token[:8], request=request)
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
                   request: Request,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_user),
                   x_session_token: Optional[str] = Header(None)):
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
                   details=json.dumps(changes, ensure_ascii=False),
                   request=request,
                   session_ref=x_session_token[:8] if x_session_token else None)
        db.commit()

    return user


# ---------------- users (admin) ----------------
@app.get("/api/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).order_by(User.id).all()


@app.put("/api/users/{user_id}/role", response_model=UserOut)
def change_role(user_id: int, payload: RoleIn,
                request: Request,
                db: Session = Depends(get_db),
                admin: User = Depends(require_admin),
                x_session_token: Optional[str] = Header(None)):
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
               details=json.dumps({"from": old, "to": u.role}, ensure_ascii=False),
               request=request,
               session_ref=x_session_token[:8] if x_session_token else None)
    db.commit()
    return u


# ---------------- logs ----------------
@app.get("/api/logs")
def list_logs(
    username: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=300),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    q = db.query(EditLog)

    if user.role != "admin":
        q = q.filter(EditLog.user_id == user.id)
    elif username:
        q = q.filter(EditLog.username == username)

    if action:
        q = q.filter(EditLog.action == action)

    if date_from:
        try:
            dt = datetime.fromisoformat(date_from)
            q = q.filter(EditLog.created_at >= dt)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.fromisoformat(date_to) + timedelta(days=1)
            q = q.filter(EditLog.created_at < dt)
        except ValueError:
            pass

    total = q.count()
    rows = (q.order_by(EditLog.created_at.desc())
              .offset(offset).limit(limit).all())

    items = [{
        "id": r.id,
        "username": r.username,
        "action": r.action,
        "target_type": r.target_type,
        "target_id": r.target_id,
        "target_name": r.target_name,
        "details": r.details,
        "ip_address": r.ip_address,
        "user_agent": r.user_agent,
        "session_ref": r.session_ref,
        "created_at": r.created_at.isoformat(),
    } for r in rows]

    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/api/logs/actions")
def list_log_actions(db: Session = Depends(get_db),
                     _: User = Depends(require_user)):
    rows = db.query(EditLog.action).distinct().all()
    return sorted({r[0] for r in rows})


@app.get("/api/logs/export")
def export_logs(
    username: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    q = db.query(EditLog)

    if user.role != "admin":
        q = q.filter(EditLog.user_id == user.id)
    elif username:
        q = q.filter(EditLog.username == username)

    if action:
        q = q.filter(EditLog.action == action)

    if date_from:
        try:
            dt = datetime.fromisoformat(date_from)
            q = q.filter(EditLog.created_at >= dt)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.fromisoformat(date_to) + timedelta(days=1)
            q = q.filter(EditLog.created_at < dt)
        except ValueError:
            pass

    rows = q.order_by(EditLog.created_at.desc()).all()

    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["id", "дата", "пользователь", "действие",
                "тип объекта", "id объекта", "объект",
                "ip", "браузер", "детали"])
    for r in rows:
        w.writerow([
            r.id,
            r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            r.username,
            r.action,
            r.target_type,
            r.target_id or "",
            r.target_name or "",
            r.ip_address or "",
            r.user_agent or "",
            r.details or "",
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="logs_{datetime.utcnow():%Y%m%d_%H%M}.csv"'},
    )


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
                request: Request,
                db: Session = Depends(get_db),
                admin: User = Depends(require_admin),
                x_session_token: Optional[str] = Header(None)):
    exists = (db.query(Term)
                .filter(func.lower(Term.term) == payload.term.lower())
                .first())
    if exists:
        raise HTTPException(409, "Такой термин уже есть")
    t = Term(term=payload.term, definition=payload.definition,
             example=payload.example, category=payload.category,
             created_by_id=admin.id, created_by=admin.username)
    db.add(t)
    db.commit()
    db.refresh(t)
    log_action(db, admin, "create", "term", t.id, t.term,
               details=json.dumps({"category": t.category}, ensure_ascii=False),
               request=request,
               session_ref=x_session_token[:8] if x_session_token else None)
    db.commit()
    return t


@app.put("/api/terms/{term_id}", response_model=TermOut)
def update_term(term_id: int, payload: TermUpdate,
                request: Request,
                db: Session = Depends(get_db),
                admin: User = Depends(require_admin),
                x_session_token: Optional[str] = Header(None)):
    t = db.get(Term, term_id)
    if not t:
        raise HTTPException(404, "Термин не найден")
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
        log_action(db, admin, "update", "term", t.id, t.term,
                   details=json.dumps(changes, ensure_ascii=False),
                   request=request,
                   session_ref=x_session_token[:8] if x_session_token else None)
        db.commit()
    return t


@app.delete("/api/terms/{term_id}", status_code=204)
def delete_term(term_id: int,
                request: Request,
                db: Session = Depends(get_db),
                admin: User = Depends(require_admin),
                x_session_token: Optional[str] = Header(None)):
    t = db.get(Term, term_id)
    if not t:
        raise HTTPException(404, "Термин не найден")
    name, tid = t.term, t.id
    db.delete(t)
    db.commit()
    log_action(db, admin, "delete", "term", tid, name,
               request=request,
               session_ref=x_session_token[:8] if x_session_token else None)
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


# ---------------- статика ----------------
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
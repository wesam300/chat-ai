import base64
import hashlib
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
import httpx
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "models.db")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
UPLOAD_DIR = BASE_DIR / "uploads"

print(f"--- SERVER STARTING: BASE_DIR={BASE_DIR} ---")
UPLOAD_DIR.mkdir(exist_ok=True)

# المفتاح الأساسي (يُفضّل تعيين OPENROUTER_API_KEY في البيئة بدل تثبيته في الكود)
# تنظيف المفتاح البرمجي بشكل فائق لضمان عمله في Render
raw_key = os.environ.get("OPENROUTER_API_KEY") or "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"
# حذف أي مسافات، علامات تنصيص فردية أو زوجية قد تأتي من إعدادات البيئة
OPENROUTER_API_KEY = raw_key.strip().strip('"').strip("'").strip()

if len(OPENROUTER_API_KEY) < 10:
    print("--- WARNING: OPENROUTER_API_KEY LOOKS INVALID OR TOO SHORT ---")
else:
    print(f"--- API KEY LOADED (Prefix: {OPENROUTER_API_KEY[:10]}...) ---")

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "https://chat-ai-w1u4.onrender.com")
OPENROUTER_SITE_NAME = os.environ.get("OPENROUTER_SITE_NAME", "AI Chat")

SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-change-me-for-production")

# قائمة الموديلات المجانية فائقة الاستقرار (مُحدثة 2026)
M_QWEN_FREE = "qwen/qwen-2.5-72b-instruct:free"
M_GEMINI_LITE = "google/gemini-2.0-flash-lite-preview-02-05:free"
M_GEMINI_FLASH = "google/gemini-2.0-flash-exp:free"
M_DEEPSEEK_FREE = "deepseek/deepseek-r1:free"
M_OPENROUTER_FREE = "openrouter/free" 


def select_openrouter_model(message: str, has_image_attachments: bool, history_text: str) -> str:
    # القوة الضاربة: إذا كانت هناك صور، نستخدم Gemini فوراً لأنه يدعم الرؤية Vision
    if has_image_attachments:
        return M_GEMINI_LITE
    # للدردشة النصية العادية، Qwen 2.5 هو الأفضل والأكثر استقراراً
    return M_QWEN_FREE


def openrouter_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_SITE_URL,
        "X-OpenRouter-Title": OPENROUTER_SITE_NAME,
    }


def call_openrouter_chat(messages: List[Dict[str, Any]], model_id: str) -> requests.Response:
    try:
        return requests.post(
            API_URL,
            headers=openrouter_headers(),
            json={"model": model_id, "messages": messages},
            timeout=120,
            proxies={"http": None, "https": None},
        )
    except Exception as e:
        print(f"DEBUG: OpenRouter Request Failed: {e}")
        raise


def complete_chat_with_fallback(messages: List[Dict[str, Any]], primary_model: str, has_img: bool = False) -> str:
    # محرك "البدائل اللانهائية" لضمان الاستمرارية
    seen = set()
    
    # بناء القائمة الذهبية للبدائل
    if has_img:
        order = [primary_model, M_GEMINI_LITE, M_GEMINI_PRO, "qwen/qwen-vl-plus:free"]
    else:
        order = [
            primary_model,
            M_QWEN_36,
            M_QWEN_PRO,
            M_GEMINI_LITE,
            M_QWEN_TURBO,
            "google/gemma-3-27b-it:free",
            M_MISTRAL_7B
        ]

    last_detail = ""
    for mid in order:
        if not mid or mid in seen:
            continue
        seen.add(mid)
        print(f"--- ATTEMPTING WITH MODEL: {mid} ---")
        try:
            resp = call_openrouter_chat(messages, mid)
        except Exception as e:
            last_detail = f"Exception {mid}: {e}"
            print(f"--- FAILED {mid}: {last_detail} ---")
            continue
            
        if resp.status_code == 200:
            j = resp.json()
            try:
                content = j["choices"][0]["message"]["content"]
                if content and content.strip():
                    return content
                last_detail = f"Empty reply from {mid}"
            except Exception:
                last_detail = f"JSON error from {mid}"
            print(f"--- FAILED {mid}: {last_detail} ---")
            continue
                
        # تحليل الخطأ (401، 429، إلخ) للانتقال الفوري
        try:
            err = resp.json()
            last_detail = f"[{mid}] {resp.status_code}: " + str(err.get("error", err))[:200]
        except Exception:
            last_detail = f"[{mid}] HTTP {resp.status_code}"
            
        print(f"--- FAILED {mid}: {last_detail} ---")
        # لا تتوقف، جرب البديل التالي فوراً
        continue
            
    return (
        "عذراً، جميع خوادم الذكاء الاصطناعي المتاحة تواجه ضغطاً غير مسبوق حالياً.\n\n"
        "يرجى المحاولة مجدداً بعد دقيقة واحدة. شكراً لصبرك.\n\n"
        f"*(ملاحظة للمطور: {last_detail})*"
    )

ALLOWED_UPLOAD = re.compile(r"\.(png|jpe?g|gif|webp|pdf|txt|csv|md)$", re.I)
MAX_UPLOAD_BYTES = 12 * 1024 * 1024


def get_db_connection():
    # إضافة timeout للسماح للقاعدة بالانتظار في حال وجود ضغط
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    # تفعيل وضع WAL للسماح بعمليات متزامنة بكفاءة عالية
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    cur = conn.cursor()
    
    # 1. إنشاء الجداول الأساسية
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider_id TEXT UNIQUE NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'محادثة جديدة',
            model_db_id INTEGER,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY (model_db_id) REFERENCES models(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            image_url TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS account_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    
    # 2. ترقية قاعدة البيانات (Migrations)
    # التأكد من وجود عمود image_url في جدول messages
    cur.execute("PRAGMA table_info(messages)")
    cols = [r['name'] for r in cur.fetchall()]
    if "image_url" not in cols:
        print("--- DB UPGRADE: Adding image_url to messages ---")
        cur.execute("ALTER TABLE messages ADD COLUMN image_url TEXT")
    
    # التأكد من وجود عمود email في جدول users (للتوافق مع جوجل)
    cur.execute("PRAGMA table_info(users)")
    user_cols = [r['name'] for r in cur.fetchall()]
    if "email" not in user_cols:
        print("--- DB UPGRADE: Adding email to users ---")
        cur.execute("ALTER TABLE users ADD COLUMN email TEXT")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_email ON users(email)")

    conn.commit()
    conn.close()
    print("--- DATABASE INITIALIZED & UPGRADED ---")


# --- Pydantic models ---


class ChatRequest(BaseModel):
    message: str = ""
    conversation_id: Optional[int] = None
    history: Optional[List[Dict[str, Any]]] = None
    attachments: Optional[List[Dict[str, str]]] = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: Optional[int] = None


class ConversationOut(BaseModel):
    id: int
    title: str
    model_db_id: Optional[int] = None
    created_at: str
    updated_at: str


class ConversationCreate(BaseModel):
    title: str = "محادثة جديدة"
    model_db_id: Optional[int] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: str


class UserProfileOut(BaseModel):
    name: str
    context: str


class UserProfileUpdate(BaseModel):
    name: str = ""
    context: str = ""


class RegisterBody(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=256)


class LoginBody(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    id: int
    username: str
    email: Optional[str] = None

class GoogleAuthBody(BaseModel):
    idToken: str
    username: Optional[str] = ""
    email: str

class AdminStats(BaseModel):
    total_users: int
    total_conversations: int
    total_messages: int
    successful_chats: int
    failed_chats: int


app = FastAPI(title="OpenRouter Web Chat")

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=14 * 24 * 3600, same_site="lax")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
# خدمت ملفات الـ JS والـ CSS من المجلد الرئيسي
app.mount("/static", StaticFiles(directory=str(BASE_DIR)), name="static")
# ملاحظة: سنقوم بتعديل الروابط في HTML لتشمل /static/ أو سنقدم حلاً بديلاً للمسارات النسبية


# تشغيل تهيئة قاعدة البيانات مباشرة عند تحميل الملف لضمان الجاهزية فوراً
init_db()
print("--- DATABASE INITIALIZED ---")


def get_session_user_id(request: Request) -> Optional[int]:
    uid = request.session.get("user_id")
    return int(uid) if uid is not None else None


def hash_password(p: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", p.encode("utf-8"), salt.encode("ascii"), 210_000)
    return f"{salt}${h.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        salt, hexh = stored.split("$", 1)
        h = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt.encode("ascii"), 210_000)
        return h.hex() == hexh
    except (ValueError, AttributeError):
        return False


def get_user_by_username(username: str) -> Optional[Tuple[int, str, str]]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username.strip().lower(),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return row[0], row[1], row[2]


def create_user(username: str, password: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    ph = hash_password(password)
    # تنظيف اسم المستخدم
    uname = username.strip().lower()
    # إذا كان اسم المستخدم بريداً إلكترونياً، نضعه في عمود الإيميل أيضاً
    email = uname if "@" in uname else None
    
    try:
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (uname, email, ph),
        )
        uid = cur.lastrowid
        cur.execute("INSERT OR IGNORE INTO account_profiles (user_id, name, context) VALUES (?, '', '')", (uid,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="اسم المستخدم أو البريد موجود مسبقاً")
    conn.close()
    return uid


def get_account_profile(user_id: int) -> UserProfileOut:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name, context FROM account_profiles WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return UserProfileOut(name="", context="")
    return UserProfileOut(name=row[0] or "", context=row[1] or "")


def update_account_profile(user_id: int, name: str, context: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO account_profiles (user_id, name, context, updated_at) VALUES (?, ?, ?, datetime('now')) "
        "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, context=excluded.context, updated_at=datetime('now')",
        (user_id, name.strip(), context.strip()),
    )
    conn.commit()
    conn.close()


def get_conversations(user_id: int) -> List[ConversationOut]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, model_db_id, created_at, updated_at FROM conversations "
        "WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        ConversationOut(id=r[0], title=r[1], model_db_id=r[2], created_at=r[3], updated_at=r[4]) for r in rows
    ]


def get_conversation_with_messages(conv_id: int, user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, model_db_id, created_at, updated_at, user_id FROM conversations WHERE id = ?",
        (conv_id,),
    )
    row = cur.fetchone()
    if not row or row[5] != user_id:
        conn.close()
        return None, []
    conv = ConversationOut(id=row[0], title=row[1], model_db_id=row[2], created_at=row[3], updated_at=row[4])
    cur.execute(
        "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conv_id,),
    )
    msgs = [MessageOut(id=r[0], role=r[1], content=r[2], created_at=r[3]) for r in cur.fetchall()]
    conn.close()
    return conv, msgs


def create_conversation(user_id: int, title: str = "محادثة جديدة", model_db_id: Optional[int] = None) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO conversations (title, model_db_id, user_id) VALUES (?, ?, ?)",
        (title, model_db_id, user_id),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def add_message(conversation_id, role, content, image_url=None):
    if conversation_id is None:
        print(f"--- DB ERROR: ATTEMPTED TO ADD MESSAGE TO NULL CONVERSATION (Role: {role}) ---")
        return None
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content, image_url) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, image_url),
        )
        cur.execute("UPDATE conversations SET updated_at = datetime('now') WHERE id = ?", (conversation_id,))
        conn.commit()
    except Exception as e:
        print(f"--- DB ERROR IN add_message: {e} ---")
    finally:
        conn.close()


def update_conversation_title(conv_id: int, title: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE conversations SET title = ?, updated_at = datetime('now') WHERE id = ?", (title, conv_id))
    conn.commit()
    conn.close()


def delete_conversation(conv_id: int, user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM conversations WHERE id = ?", (conv_id,))
    row = cur.fetchone()
    if not row or row[0] != user_id:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found")
    cur.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    cur.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()


def store_user_content(text: str, attachments: Optional[List[Dict[str, str]]]) -> str:
    if not attachments:
        return text
    return json.dumps({"type": "multipart", "text": text, "attachments": attachments}, ensure_ascii=False)


def ensure_data_uri(url: str) -> str:
    # تحويل روابط الصور المحلية إلى Base64 ليتمكن OpenRouter من قراءتها.
    if not url.startswith("http") or "/uploads/" not in url:
        return url
    try:
        # استخراج اسم الملف من الرابط
        fname = url.split("/uploads/")[-1].split("?")[0]
        path = UPLOAD_DIR / fname
        if path.exists():
            mime, _ = mimetypes.guess_type(str(path))
            if not mime:
                mime = "image/jpeg"
            b64_data = base64.b64encode(path.read_bytes()).decode("utf-8")
            return f"data:{mime};base64,{b64_data}"
    except Exception:
        pass
    return url


def content_to_api_format(content: str) -> Union[str, List[Dict[str, Any]]]:
    s = content.strip()
    if s.startswith("{") and '"type"' in s:
        try:
            j = json.loads(s)
            if j.get("type") == "multipart":
                parts: List[Dict[str, Any]] = []
                if j.get("text", "").strip():
                    parts.append({"type": "text", "text": j["text"].strip()})
                for att in j.get("attachments") or []:
                    if att.get("type") == "image_url" and att.get("url"):
                        parts.append({"type": "image_url", "image_url": {"url": ensure_data_uri(att["url"])}})
                if not parts:
                    return ""
                if len(parts) == 1 and parts[0]["type"] == "text":
                    return parts[0]["text"]
                return parts
        except json.JSONDecodeError:
            pass
    return content


def build_fresh_user_content(text: str, attachments: Optional[List[Dict[str, str]]]) -> Union[str, List[Dict[str, Any]]]:
    parts: List[Dict[str, Any]] = []
    if text.strip():
        parts.append({"type": "text", "text": text.strip()})
    for att in attachments or []:
        if att.get("type") == "image_url" and att.get("url"):
            parts.append({"type": "image_url", "image_url": {"url": ensure_data_uri(att["url"])}})
    if not parts:
        raise HTTPException(status_code=400, detail="أرسل نصاً أو صورة/ملفاً")
    if len(parts) == 1 and parts[0]["type"] == "text":
        return parts[0]["text"]
    return parts


def history_item_to_api(msg: Dict[str, Any]) -> Dict[str, Any]:
    role = msg.get("role", "user")
    c = msg.get("content", "")
    if isinstance(c, dict) and c.get("type") == "multipart":
        body = content_to_api_format(json.dumps(c))
        return {"role": role, "content": body}
    if isinstance(c, str):
        body = content_to_api_format(c)
        return {"role": role, "content": body}
    return {"role": role, "content": str(c)}


# --- Auth ---


@app.post("/api/auth/register")
def api_register(request: Request, data: RegisterBody):
    uid = create_user(data.username, data.password)
    request.session["user_id"] = uid
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE id = ?", (uid,))
    uname = cur.fetchone()[0]
    conn.close()
    return {"ok": True, "user": UserPublic(id=uid, username=uname)}


@app.post("/api/auth/login")
def api_login(request: Request, data: LoginBody):
    row = get_user_by_username(data.username)
    if not row or not verify_password(data.password, row[2]):
        raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة")
    uid, uname, _ = row
    request.session["user_id"] = uid
    return {"ok": True, "user": UserPublic(id=uid, username=uname)}


@app.post("/api/auth/logout")
def api_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/me")
def api_me(request: Request):
    uid = get_session_user_id(request)
    print(f"--- FETCHING SESSION USER: {uid} ---")
    if not uid:
        return {"user": None}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, username, email FROM users WHERE id = ?", (uid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        request.session.clear()
        return {"user": None}
    return {"user": UserPublic(id=row[0], username=row[1], email=row[2])}

@app.post("/api/auth/google")
async def api_google_auth(request: Request, data: GoogleAuthBody):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    email_clean = data.email.strip().lower()
    
    cur.execute("SELECT id FROM users WHERE email = ?", (email_clean,))
    row = cur.fetchone()
    
    if row:
        uid = row[0]
    else:
        # محاولة إنشاء اسم مستخدم فريد
        base_uname = data.username or email_clean.split('@')[0]
        uname = base_uname
        counter = 1
        while True:
            try:
                cur.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (uname, email_clean, "GOOGLE_OAUTH_USER"),
                )
                uid = cur.lastrowid
                break
            except sqlite3.IntegrityError:
                uname = f"{base_uname}{counter}"
                counter += 1
                if counter > 100: # حماية من الحلقات اللانهائية
                    raise HTTPException(status_code=500, detail="فشل إنشاء حساب فريد")
                    
        cur.execute("INSERT OR IGNORE INTO account_profiles (user_id, name, context) VALUES (?, ?, '')", (uid, data.username or uname))
    
    conn.commit()
    conn.close()
    request.session["user_id"] = uid
    print(f"--- GOOGLE LOGIN SUCCESSFUL: UID={uid}, EMAIL={email_clean} ---")
    return {"ok": True, "uid": uid}


# --- Conversations ---


@app.get("/api/conversations", response_model=List[ConversationOut])
def list_conversations(request: Request):
    uid = get_session_user_id(request)
    if not uid:
        return []
    return get_conversations(uid)


@app.get("/api/conversations/{conv_id}")
def get_conversation(request: Request, conv_id: int):
    uid = get_session_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="سجّل الدخول لعرض المحادثات المحفوظة")
    conv, msgs = get_conversation_with_messages(conv_id, uid)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": conv, "messages": msgs}


@app.post("/api/conversations", response_model=ConversationOut)
def create_conv(request: Request, data: ConversationCreate):
    uid = get_session_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="سجّل الدخول لإنشاء محادثة محفوظة")
    cid = create_conversation(uid, title=data.title, model_db_id=data.model_db_id)
    conv, _ = get_conversation_with_messages(cid, uid)
    return conv


class ConversationUpdate(BaseModel):
    title: str


@app.patch("/api/conversations/{conv_id}")
def patch_conversation(request: Request, conv_id: int, data: ConversationUpdate):
    uid = get_session_user_id(request)
    if not uid:
        raise HTTPException(status_code=401)
    conv, _ = get_conversation_with_messages(conv_id, uid)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    update_conversation_title(conv_id, data.title)
    return {"ok": True}


@app.delete("/api/conversations/{conv_id}")
def delete_conv(request: Request, conv_id: int):
    uid = get_session_user_id(request)
    if not uid:
        raise HTTPException(status_code=401)
    delete_conversation(conv_id, uid)
    return {"ok": True}


# --- Admin Panel API ---
ADMIN_EMAIL_RESTRICT = "wemu20@gmail.com"

@app.get("/api/admin/stats", response_model=AdminStats)
def get_admin_stats(request: Request):
    # التحقق من صلاحية الأدمن
    uid = get_session_user_id(request)
    if not uid: raise HTTPException(status_code=401)
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT email FROM users WHERE id = ?", (uid,))
    email = cur.fetchone()[0]
    if email != ADMIN_EMAIL_RESTRICT:
        conn.close()
        raise HTTPException(status_code=403, detail="غير مسموح لك")
    
    cur.execute("SELECT COUNT(*) FROM users")
    u_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM conversations")
    c_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM messages")
    m_count = cur.fetchone()[0]
    conn.close()
    
    return AdminStats(
        total_users=u_count,
        total_conversations=c_count,
        total_messages=m_count,
        successful_chats=m_count, # تمثيلي حالياً
        failed_chats=0
    )

@app.get("/api/admin/users")
def get_admin_users(request: Request):
    uid = get_session_user_id(request)
    if not uid: raise HTTPException(status_code=401)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, username, email, created_at FROM users ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    return [{"id": r[0], "username": r[1], "email": r[2], "date": r[3]} for r in rows]


# --- Upload ---


@app.post("/api/upload")
async def api_upload(request: Request, file: UploadFile = File(...)):
    name = file.filename or "file"
    if not ALLOWED_UPLOAD.search(name):
        raise HTTPException(status_code=400, detail="نوع الملف غير مدعوم")
    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="الملف كبير جداً (الحد 12 ميجابايت)")
    ext = Path(name).suffix.lower() or ".bin"
    safe = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / safe
    dest.write_bytes(body)
    base = str(request.base_url).rstrip("/")
    url = f"{base}/uploads/{safe}"
    return {"url": url, "name": name, "mime": file.content_type or "application/octet-stream"}


# --- Chat ---


@app.post("/api/chat")
async def chat(request: Request, data: ChatRequest):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="يرجى تسجيل الدخول أولاً")

    conversation_id = data.conversation_id
    if not conversation_id:
        conversation_id = create_conversation(user_id)

    conv, existing_msgs = get_conversation_with_messages(conversation_id, user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="المحادثة غير موجودة")

    has_img = bool(data.attachments)
    hist_txt = ""
    if data.history:
        hist_txt += " ".join(str(h.get("content", "")) for h in data.history[-12:] if h.get("role") == "user")
    if existing_msgs:
        hist_txt += " " + " ".join((m.content[:800] for m in existing_msgs if m.role == "user"))

    primary_model = select_openrouter_model(data.message or "", has_img, hist_txt)
    messages_for_api: List[Dict[str, Any]] = []

    base_system_prompt = (
        "You are an elite, highly logical, and analytical AI assistant, acting as a Senior Expert Software Engineer. "
        "Guidelines:\n"
        "1. NO CHITCHAT: Never use conversational fillers (e.g., 'Hello', 'Here is your code', 'Hope this helps').\n"
        "2. DIRECT ANSWERS: If asked for code, output ONLY the code enclosed in proper markdown blocks, followed by a concise, highly technical bulleted list of changes if necessary.\n"
        "3. HIGH QUALITY: Write production-ready, highly optimized, and clean code.\n"
        "4. LANGUAGE: Always respond in professional Arabic, unless explicitly asked to use English or when writing code syntax.\n"
        "5. TONE: Professional, objective, direct, and brilliant. Do not flatter the user."
    )

    profile = get_account_profile(user_id)
    if profile.name.strip() or profile.context.strip():
        parts = []
        if profile.name.strip(): parts.append(f"User Name: {profile.name.strip()}.")
        if profile.context.strip(): parts.append(f"User Context: {profile.context.strip()}")
        messages_for_api.append({"role": "system", "content": f"{base_system_prompt}\n\nContext to consider silently:\n{' '.join(parts)}"})
    else:
        messages_for_api.append({"role": "system", "content": base_system_prompt})

    for m in existing_msgs:
        messages_for_api.append({"role": m.role, "content": content_to_api_format(m.content)})
    
    user_body = build_fresh_user_content(data.message, data.attachments)
    messages_for_api.append({"role": "user", "content": user_body})

    # حفظ رسالة المستخدم في القاعدة لأننا سنبث الرد
    ustore = store_user_content(data.message, data.attachments)
    add_message(conversation_id, "user", ustore)

    # تحديث عنوان المحادثة تلقائياً إذا كانت جديدة
    if not data.conversation_id:
        title = (data.message[:50] + "…") if len(data.message) > 50 else data.message
        title = title.replace("\n", " ").strip() or "محادثة جديدة"
        update_conversation_title(conversation_id, title)

    async def event_stream():
        headers = openrouter_headers()
        url = "https://openrouter.ai/api/v1/chat/completions"
        
        # حلقة نجاة ذكية: تجربة أفضل الموديلات المجانية بترتيب التوفر
        candidate_models = [
            primary_model,
            M_GEMINI_FLASH,
            M_QWEN_FREE,
            M_OPENROUTER_FREE  # هذا الموديل يحولك تلقائياً لأي موديل مجاني متاح حالياً
        ]
        
        # إزالة التكرار مع الحفاظ على الترتيب
        models_to_try = []
        for m in candidate_models:
            if m not in models_to_try:
                models_to_try.append(m)
        
        success = False
        full_reply = ""
        
        for model in models_to_try:
            payload = {"model": model, "messages": messages_for_api, "stream": True}
            try:
                async with httpx.AsyncClient(timeout=25.0) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as resp:
                        if resp.status_code == 200:
                            success = True
                            yield f"data: {json.dumps({'event': 'init', 'conversation_id': conversation_id, 'reply': ''})}\n\n"
                            
                            async for chunk in resp.aiter_lines():
                                if chunk.startswith("data: "):
                                    d = chunk[6:]
                                    if d == "[DONE]": break
                                    try:
                                        j = json.loads(d)
                                        content = j["choices"][0].get("delta", {}).get("content")
                                        if content:
                                            full_reply += content
                                            yield f"data: {json.dumps({'event': 'chunk', 'content': content})}\n\n"
                                    except Exception:
                                        pass
                            break
                        else:
                            print(f"--- STREAM HTTP {resp.status_code} with {model} ---")
            except Exception as e:
                print(f"--- STREAM ERROR with {model}: {e} ---")
                continue
                
        if not success:
            full_reply = "عذراً، الخوادم تواجه ضغطاً كبيراً. قد يكون حساب OpenRouter استهلك حزمة المجانيات. يرجى المحاولة لاحقاً."
            yield f"data: {json.dumps({'event': 'error', 'content': full_reply, 'conversation_id': conversation_id})}\n\n"

            
        add_message(conversation_id, "assistant", full_reply)
        yield f"data: {json.dumps({'event': 'done', 'reply': full_reply})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
def index():
    # الواجهة الرئيسية الجديدة (التصميم الجديد)
    html_path = BASE_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    # لوحة الإدارة
    html_path = BASE_DIR / "admin.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))

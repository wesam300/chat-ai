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
from fastapi.responses import HTMLResponse
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
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY or OPENROUTER_API_KEY.strip() == "":
    OPENROUTER_API_KEY = "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"
OPENROUTER_API_KEY = OPENROUTER_API_KEY.strip(' "\'')

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "http://localhost:8000")
OPENROUTER_SITE_NAME = os.environ.get("OPENROUTER_SITE_NAME", "AI Chat")

SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-change-me-for-production")

# مجموعة الموديلات للاختيار الداخلي فقط (لا تُعرض للمستخدم)
M_QWEN = "qwen/qwen3.6-plus:free"
M_LYRIA_PRO = "google/lyria-3-pro-preview"
M_LYRIA_CLIP = "google/lyria-3-clip-preview"
M_WAN = "alibaba/wan-2.6"
M_VEO = "google/veo-3.1"
M_EMBED = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
M_RIVER = "sourceful/riverflow-v2-pro"
M_GEMMA_4 = "google/gemma-3-4b-it:free"
M_GEMMA_12 = "google/gemma-3-12b-it:free"
M_GEMMA_27 = "google/gemma-3-27b-it:free"

# ترقية الموديل المسؤول عن الصور ليكون أذكى بكثير ويدعم العربية جيداً
M_NANO_VL = "google/gemini-2.0-flash-lite-preview-02-05:free"


def select_openrouter_model(message: str, has_image_attachments: bool, history_text: str) -> str:
    # يختار موديل OpenRouter حسب نص الطلب والمرفقات (بدون عرض للمستخدم).
    if has_image_attachments:
        return M_NANO_VL
    combined = f"{history_text[-4000:]} {message}".strip()
    t = combined.lower()
    # تضمين / تشابه / متجهات
    embed_kw = (
        "embed",
        "embedding",
        "vector",
        "similarity",
        "cosine",
        "تضمين",
        "تشابه",
        "متجه",
    )
    if any(k in t for k in embed_kw):
        return M_EMBED
    # فيديو / أنيميشن
    video_kw = (
        "video",
        "veo",
        "wan",
        "animation",
        "animated",
        "فيديو",
        "توليد فيديو",
        "أنيميشن",
        "موشن",
    )
    if any(k in t for k in video_kw):
        return M_VEO if (len(message) % 2 == 0) else M_WAN
    # موسيقى / صوت
    music_kw = ("music", "lyria", "song", "audio", "موسيقى", "أغنية", "لحن", "soundtrack")
    if any(k in t for k in music_kw):
        if "clip" in t or "مقطع" in message:
            return M_LYRIA_CLIP
        return M_LYRIA_PRO
    # تفكير معمّق / كود / برهان
    reason_kw = (
        "proof",
        "theorem",
        "reasoning",
        "code review",
        "step by step",
        "تحليل معمق",
        "خطوة بخطوة",
        "برهان",
        "البرمجة المعقدة",
    )
    if any(k in t for k in reason_kw):
        return M_RIVER
    n = len(message.strip())
    if 0 < n < 40:
        return M_GEMMA_4
    if n > 2200:
        return M_GEMMA_27
    if n > 900:
        return M_GEMMA_12
    return M_QWEN


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
    # محرك احترافي لاختيار النماذج مع دعم الطوارئ المتعدد للصور والنصوص.
    seen = set()
    
    # قائمة موديلات احترافية كطوارئ
    if has_img:
        # موديلات تدعم الصور مجانية
        order = [
            primary_model,
            "google/gemini-2.0-pro-exp-02-05:free",
            "qwen/qwen-vl-plus:free",
            "nvidia/nemotron-nano-12b-v2-vl:free",
        ]
    else:
        # موديلات نصوص
        order = [
            primary_model,
            M_QWEN,
            M_GEMMA_27,
            "google/gemini-2.0-flash-lite-preview-02-05:free",
        ]

    last_detail = ""
    for mid in order:
        if mid in seen:
            continue
        seen.add(mid)
        try:
            resp = call_openrouter_chat(messages, mid)
        except Exception as e:
            last_detail = str(e)
            continue
            
        if resp.status_code == 200:
            j = resp.json()
            try:
                return j["choices"][0]["message"]["content"]
            except Exception:
                last_detail = f"استجابة غير صالحة من {mid}"
                continue
                
        try:
            err = resp.json()
            last_detail = f"[{mid}] " + str(err.get("error", err))[:300]
        except Exception:
            last_detail = f"[{mid}] HTTP {resp.status_code}: {resp.text[:200]}"
            
    # إذا فشلت كل الموديلات بسبب زحام (Too Many Requests) أو خطأ آخر
    return (
        "عذراً، أواجه ضغطاً كبيراً في الطلبات (Too Many Requests) أو هناك عطل مؤقت في الخوادم ولا يمكنني الرد حالياً.\n\n"
        "يرجى المحاولة بعد قليل. شكراً لتفهمك.\n\n"
        f"*(تفاصيل تقنية للتصحيح: {last_detail})*"
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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider_id TEXT UNIQUE NOT NULL
        )
        """
    )
    cur.execute(
        """
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
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            image_url TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
        """
    )
    
    # ترقية قاعدة البيانات الحالية إذا لم تكن تحتوي على عمود image_url
    try:
        cur.execute("ALTER TABLE messages ADD COLUMN image_url TEXT")
    except sqlite3.OperationalError:
        # العمود موجود مسبقاً، نتجاهل الخطأ
        pass
        
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS account_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    
    # ترقية قاعدة البيانات الحالية إذا لم تكن تحتوي على عمود image_url
    cur.execute("PRAGMA table_info(messages)")
    columns = [row['name'] for row in cur.fetchall()]
    if "image_url" not in columns:
        cur.execute("ALTER TABLE messages ADD COLUMN image_url TEXT")
        
    conn.commit()
    conn.close()


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
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username.strip().lower(), ph),
        )
        uid = cur.lastrowid
        cur.execute("INSERT OR IGNORE INTO account_profiles (user_id, name, context) VALUES (?, '', '')", (uid,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="اسم المستخدم موجود مسبقاً")
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
    if not uid:
        return {"user": None}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE id = ?", (uid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        request.session.clear()
        return {"user": None}
    return {"user": UserPublic(id=row[0], username=row[1])}


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


# --- Profile (logged-in only) ---


@app.get("/api/user-profile", response_model=UserProfileOut)
def api_get_user_profile(request: Request):
    uid = get_session_user_id(request)
    if uid:
        return get_account_profile(uid)
    return UserProfileOut(name="", context="")


@app.patch("/api/user-profile", response_model=UserProfileOut)
def api_update_user_profile(request: Request, data: UserProfileUpdate):
    uid = get_session_user_id(request)
    if uid:
        update_account_profile(uid, data.name, data.context)
        return get_account_profile(uid)
    return UserProfileOut(name="", context="")


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


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: Request, data: ChatRequest):
    user_id = get_session_user_id(request)
    if not user_id:
        print("--- CHAT ERROR: UNAUTHORIZED ACCESS ATTEMPT ---")
        raise HTTPException(status_code=401, detail="يرجى تسجيل الدخول أولاً")

    # تحديد أو إنشاء المحادثة
    conversation_id = data.conversation_id
    if not conversation_id:
        try:
            conversation_id = create_conversation(user_id)
            print(f"--- CREATED NEW CONVERSATION: {conversation_id} ---")
        except Exception as e:
            print(f"--- ERROR CREATING CONVERSATION: {e} ---")
            raise HTTPException(status_code=500, detail="فشل في إنشاء محادثة جديدة")

    # جلب المحادثة للتأكد من ملكيتها
    conv, existing_msgs = get_conversation_with_messages(conversation_id, user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="المحادثة غير موجودة أو لا تملك صلاحية الوصول")

    has_img = bool(data.attachments)
    
    # بناء سياق الدردشة
    hist_txt = ""
    if data.history:
        hist_txt += " ".join(str(h.get("content", "")) for h in data.history[-12:] if h.get("role") == "user")
    if existing_msgs:
        hist_txt += " " + " ".join((m.content[:800] for m in existing_msgs if m.role == "user"))

    primary_model = select_openrouter_model(data.message or "", has_img, hist_txt)

    messages_for_api: List[Dict[str, Any]] = []

    # أوامر نظامية للرد بالعربية
    base_system_prompt = (
        "أنت مساعد ذكاء اصطناعي متقدم وذكي جداً. "
        "يجب عليك دائماً الرد باللغة العربية الواضحة والسليمة، إلا إذا طلب منك المستخدم غير ذلك. "
        "تجنب تكرار الكلام، وكن دقيقاً واحترافياً."
    )

    profile = get_account_profile(user_id)
    if profile.name.strip() or profile.context.strip():
        parts = []
        if profile.name.strip():
            parts.append(f"المستخدم الذي تتحدث معه اسمه: {profile.name.strip()}.")
        if profile.context.strip():
            parts.append(f"معلومات عنه/عنها: {profile.context.strip()}")
        messages_for_api.append(
            {"role": "system", "content": f"{base_system_prompt} { ' '.join(parts) } خاطبه باسمه عند الحاجة."}
        )
    else:
        messages_for_api.append({"role": "system", "content": base_system_prompt})

    # إضافة الرسائل السابقة والحالية
    for m in existing_msgs:
        messages_for_api.append({"role": m.role, "content": content_to_api_format(m.content)})
    
    user_body = build_fresh_user_content(data.message, data.attachments)
    messages_for_api.append({"role": "user", "content": user_body})

    # الحصول على رد الذكاء الاصطناعي
    reply = complete_chat_with_fallback(messages_for_api, primary_model, has_img)

    # حفظ الرسائل في القاعدة
    ustore = store_user_content(data.message, data.attachments)
    add_message(conversation_id, "user", ustore)
    add_message(conversation_id, "assistant", reply)

    # تحديث عنوان المحادثة تلقائياً إذا كانت جديدة
    if not data.conversation_id:
        title = (data.message[:50] + "…") if len(data.message) > 50 else data.message
        title = title.replace("\n", " ").strip() or "محادثة جديدة"
        update_conversation_title(conversation_id, title)

    return ChatResponse(reply=reply, conversation_id=conversation_id)


@app.get("/", response_class=HTMLResponse)
def index():
    # قراءة الملف في كل مرة أو عند الطلب لضمان عدم تعطل السيرفر عند البدء
    html_path = BASE_DIR / "chat_ui.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))

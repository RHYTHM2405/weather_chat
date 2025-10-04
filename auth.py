# auth.py
import os, time, json, datetime
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, g, current_app
from werkzeug.security import generate_password_hash, check_password_hash

# SQLAlchemy
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

# JWT
import jwt

# ----- Config (read from env or fallback)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///weatherchat.db")
JWT_SECRET = os.getenv("JWT_SECRET", "change_this_for_prod")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXP_SECONDS = int(os.getenv("JWT_EXP_SECONDS", 60 * 60 * 24 * 7))

# ----- SQLAlchemy setup (scoped session to safely share)
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(bind=engine, autocommit=False, autoflush=False))

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class ChatStore(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    name = Column(String(200), default="default")
    chat_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

def create_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ----- JWT helpers
def create_token(user_id):
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + JWT_EXP_SECONDS}
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token

def decode_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = None
        if auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1]
        if not token:
            return jsonify({"error": "authorization_required"}), 401
        payload = decode_token(token)
        if not payload:
            return jsonify({"error": "invalid_or_expired_token"}), 401
        user_id = payload.get("sub")
        db = next(get_db())
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return jsonify({"error": "user_not_found"}), 404
        # attach user object to flask.g
        g.current_user = user
        return func(*args, **kwargs)
    return wrapper

# ----- Blueprint -----
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

@auth_bp.route("/register", methods=["POST"])
def register():
    body = request.get_json(force=True)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return jsonify({"error": "username_password_required"}), 400
    db = next(get_db())
    if db.query(User).filter(User.username == username).first():
        return jsonify({"error": "username_taken"}), 400
    hashpw = generate_password_hash(password)
    user = User(username=username, password_hash=hashpw)
    db.add(user); db.commit(); db.refresh(user)
    token = create_token(user.id)
    return jsonify({"token": token, "user": {"id": user.id, "username": user.username}}), 201

@auth_bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(force=True)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return jsonify({"error": "username_password_required"}), 400
    db = next(get_db())
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "invalid_credentials"}), 401
    token = create_token(user.id)
    # return latest chat if exists
    chat = db.query(ChatStore).filter(ChatStore.user_id == user.id).order_by(ChatStore.updated_at.desc()).first()
    chat_json = chat.chat_json if chat else None
    return jsonify({"token": token, "user": {"id": user.id, "username": user.username}, "chat": chat_json}), 200

@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    # JWT is stateless; instruct client to remove token
    return jsonify({"ok": True})

@auth_bp.route("/save_chat", methods=["POST"])
@login_required
def save_chat():
    body = request.get_json(force=True)
    chat_obj = body.get("chat")
    if chat_obj is None:
        return jsonify({"error": "chat_required"}), 400
    db = next(get_db())
    user = g.current_user
    existing = db.query(ChatStore).filter(ChatStore.user_id == user.id, ChatStore.name == "default").first()
    if existing:
        existing.chat_json = json.dumps(chat_obj)
        db.add(existing)
    else:
        new = ChatStore(user_id=user.id, name="default", chat_json=json.dumps(chat_obj))
        db.add(new)
    db.commit()
    return jsonify({"ok": True})

@auth_bp.route("/get_chat", methods=["GET"])
@login_required
def get_chat():
    db = next(get_db())
    user = g.current_user
    existing = db.query(ChatStore).filter(ChatStore.user_id == user.id, ChatStore.name == "default").first()
    if existing:
        return jsonify({"chat": json.loads(existing.chat_json)})
    return jsonify({"chat": None})

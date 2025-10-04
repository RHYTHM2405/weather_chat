# auth_server.py  (merge parts into your existing server file if you prefer)
import os, json, time, datetime
from functools import wraps
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import jwt

# ---- Config ----
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///weatherchat.db")
JWT_SECRET = os.getenv("JWT_SECRET", "change_this_to_a_random_secret")  # change in production
JWT_ALGORITHM = "HS256"
JWT_EXP_SECONDS = 60 * 60 * 24 * 7  # 7 days token expiry

# Optionally set by env for Google OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# ---- Flask + CORS ----
app = Flask(__name__)
CORS(app)  # if frontend served from different origin; remove if same origin

# ---- SQLAlchemy models ----
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(300), nullable=True)  # nullable for OAuth users
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class ChatStore(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    name = Column(String(200), default="default")  # allow multiple chat streams if desired
    chat_json = Column(Text, nullable=False)  # store JSON text of the conversation
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

# Create DB tables (call create_db() once)
def create_db():
    Base.metadata.create_all(bind=engine)

# ---- Helper: DB session context ----
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---- JWT helpers ----
def create_token(user_id):
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + JWT_EXP_SECONDS
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token

def decode_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception as e:
        return None

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1]
        else:
            token = None
        if not token:
            return jsonify({"error": "authorization_required"}), 401
        payload = decode_token(token)
        if not payload:
            return jsonify({"error": "invalid_or_expired_token"}), 401
        user_id = payload.get("sub")
        # Attach user to request context
        db = next(get_db())
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return jsonify({"error": "user_not_found"}), 404
        g.current_user = user
        return fn(*args, **kwargs)
    return wrapper

# ---- Auth endpoints ----
@app.route("/api/register", methods=["POST"])
def api_register():
    body = request.get_json(force=True)
    username = body.get("username", "").strip()
    password = body.get("password", "")
    if not username or not password:
        return jsonify({"error": "username_password_required"}), 400
    db = next(get_db())
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        return jsonify({"error": "username_taken"}), 400
    hashpw = generate_password_hash(password)
    user = User(username=username, password_hash=hashpw)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id)
    return jsonify({"token": token, "user": {"id": user.id, "username": user.username}}), 201

@app.route("/api/login", methods=["POST"])
def api_login():
    body = request.get_json(force=True)
    username = body.get("username", "").strip()
    password = body.get("password", "")
    if not username or not password:
        return jsonify({"error": "username_password_required"}), 400
    db = next(get_db())
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.password_hash:
        return jsonify({"error": "invalid_credentials"}), 401
    if not check_password_hash(user.password_hash, password):
        return jsonify({"error": "invalid_credentials"}), 401
    token = create_token(user.id)
    # return latest chat if exists
    chat = db.query(ChatStore).filter(ChatStore.user_id == user.id).order_by(ChatStore.updated_at.desc()).first()
    chat_json = chat.chat_json if chat else None
    return jsonify({"token": token, "user": {"id": user.id, "username": user.username}, "chat": chat_json}), 200

@app.route("/api/logout", methods=["POST"])
@login_required
def api_logout():
    # For JWT stateless, logout is handled client-side by deleting token.
    return jsonify({"ok": True}), 200

# ---- Chat endpoints ----
@app.route("/api/save_chat", methods=["POST"])
@login_required
def api_save_chat():
    body = request.get_json(force=True)
    chat_json = body.get("chat")
    if chat_json is None:
        return jsonify({"error": "chat_required"}), 400
    db = next(get_db())
    # save or update single chat row (default name)
    existing = db.query(ChatStore).filter(ChatStore.user_id == g.current_user.id, ChatStore.name == "default").first()
    if existing:
        existing.chat_json = json.dumps(chat_json)
        db.add(existing)
    else:
        new = ChatStore(user_id=g.current_user.id, name="default", chat_json=json.dumps(chat_json))
        db.add(new)
    db.commit()
    return jsonify({"ok": True}), 200

@app.route("/api/get_chat", methods=["GET"])
@login_required
def api_get_chat():
    db = next(get_db())
    existing = db.query(ChatStore).filter(ChatStore.user_id == g.current_user.id, ChatStore.name == "default").first()
    if existing:
        return jsonify({"chat": json.loads(existing.chat_json)}), 200
    return jsonify({"chat": None}), 200

# ---- Optional: Google OAuth (sketch) ----
# For a full Google OAuth flow you'll need to setup credentials in Google Cloud and redirect URIs.
# Using Authlib you can implement a /api/oauth/google route. For brevity I provide a pointer rather than full code.
# If you want the full Google OAuth code I can add it too.

# ---- run helper ----
if __name__ == "__main__":
    create_db()
    print("DB created (if not exists). Run app with flask or python auth_server.py")
    app.run(port=5001, debug=True)

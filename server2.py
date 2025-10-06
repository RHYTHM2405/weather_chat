# server.py
# Flask server for WeatherChat: Deepgram STT, Open-Meteo weather, OpenRouter LLM
# Adds /api/process (sync) and /api/stream_process (streaming chunked response)
# NOTE: Replace OPENROUTER_API_KEY and DEEPGRAM_API_KEY with your keys or set env vars.

import os
import re
import json
import time
import requests
import shelve
import traceback
from flask import Flask, request, jsonify, render_template, Response, session
from urllib.parse import quote_plus

# ---------- Database and auth imports ----------
try:
    import psycopg2
    import psycopg2.extras
except Exception as e:
    psycopg2 = None  # we'll raise an error at runtime if DB is needed but driver missing

from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# Ensure Flask app exists
app = Flask(__name__, static_folder="static", template_folder="templates")
# session secret
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24)

# -------------------------
# CONFIG - put your keys here or use env vars
# -------------------------
# If you'd like to load a .env file uncomment/load dotenv; originally code used load_dotenv() but
# load_dotenv wasn't imported earlier. If you want to use it, add: from dotenv import load_dotenv
try:
    from dotenv import load_dotenv as _ld
    _ld()
except Exception:
    pass

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat-v3.1:free")
SITE_URL = os.getenv("SITE_URL", "http://localhost:5000")
SITE_TITLE = os.getenv("SITE_TITLE", "WeatherBot")
FIXED_CONTEXT = os.getenv("FIXED_CONTEXT", "")

DEEPGRAM_BASE_URL = "https://api.deepgram.com/v1/listen"

UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
UNSPLASH_SEARCH_URL = os.getenv("UNSPLASH_SEARCH_URL", "https://api.unsplash.com/search/photos")
UNSPLASH_MIN_DELAY = float(os.getenv("UNSPLASH_MIN_DELAY", 0.12))
UNSPLASH_CACHE_FILE = os.path.join(os.path.dirname(__file__), "unsplash_cache.db")
_last_unsplash_call = 0.0

# ---------- Postgres helper functions / initialization ----------
# Accept either DATABASE_URL (heroku style) or PGHOST/PGDATABASE/PGUSER/PGPASSWORD/PGPORT
DATABASE_URL = os.getenv("DATABASE_URL")
PG_HOST = os.getenv("PGHOST")
PG_DATABASE = os.getenv("PGDATABASE")
PG_USER = os.getenv("PGUSER")
PG_PASSWORD = os.getenv("PGPASSWORD")
PG_PORT = os.getenv("PGPORT", "5432")

def get_conn_params():
    """
    Return connection parameters / dsn string for psycopg2.
    Priority: DATABASE_URL env var (if provided) else PG_ variables.
    """
    if DATABASE_URL:
        return DATABASE_URL
    # build dsn
    if PG_HOST and PG_DATABASE and PG_USER:
        # user provided pieces
        return {
            "host": PG_HOST,
            "dbname": PG_DATABASE,
            "user": PG_USER,
            "password": PG_PASSWORD,
            "port": PG_PORT
        }
    # fallback to localhost sqlite-like? We'll return None to indicate DB disabled
    return None

def get_db_conn():
    """
    Returns a new psycopg2 connection. Caller should close it.
    Raises RuntimeError if psycopg2 not available or connection info missing.
    """
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed. Install with: pip install psycopg2-binary")

    params = get_conn_params()
    if not params:
        raise RuntimeError("Postgres connection not configured. Set DATABASE_URL or PGHOST/PGDATABASE/PGUSER/PGPASSWORD.")

    if isinstance(params, str):
        # params is a DSN string
        return psycopg2.connect(params, cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        # dict
        return psycopg2.connect(cursor_factory=psycopg2.extras.RealDictCursor, **params)

def init_db():
    """
    Ensure users table exists. Called at startup.
    """
    try:
        conn = get_db_conn()
    except Exception as e:
        # If DB not configured, skip initialization silently (endpoints will error with clear message)
        print("Postgres init skipped/failed:", str(e))
        return

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                );
                """)
                conn.commit()
                print("Postgres init: users table ensured.")
    except Exception as e:
        print("Error creating users table:", str(e))
    finally:
        try:
            conn.close()
        except:
            pass

# initialize DB at startup (best-effort)
init_db()

# ---------- Auth helper utilities ----------
def create_user(username, email, password):
    """
    Insert a new user (username, email, password). Password will be hashed.
    Returns user record dict on success.
    Raises RuntimeError on error (or returns None).
    """
    if not username or not email or not password:
        raise ValueError("username, email and password required")

    try:
        conn = get_db_conn()
    except Exception as e:
        raise RuntimeError(f"Database error: {str(e)}")

    password_hash = generate_password_hash(password)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING id, username, email, created_at;",
                    (username, email, password_hash)
                )
                user = cur.fetchone()
                conn.commit()
                return dict(user) if user else None
    except psycopg2.errors.UniqueViolation:
        # UniqueViolation may be raised; psycopg2 will wrap; give friendly message
        raise RuntimeError("username_or_email_taken")
    except Exception as e:
        raise RuntimeError(f"create_user_failed: {str(e)}")
    finally:
        try:
            conn.close()
        except:
            pass

def find_user_by_username_or_email(username_or_email):
    try:
        conn = get_db_conn()
    except Exception as e:
        raise RuntimeError(f"Database error: {str(e)}")

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, email, password_hash, created_at FROM users WHERE username = %s OR email = %s LIMIT 1",
                    (username_or_email, username_or_email)
                )
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception as e:
        raise RuntimeError(f"find_user_failed: {str(e)}")
    finally:
        try:
            conn.close()
        except:
            pass

def find_user_by_id(user_id):
    try:
        conn = get_db_conn()
    except Exception as e:
        raise RuntimeError(f"Database error: {str(e)}")
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, email, created_at FROM users WHERE id = %s LIMIT 1",
                    (user_id,)
                )
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception as e:
        raise RuntimeError(f"find_user_by_id_failed: {str(e)}")
    finally:
        try:
            conn.close()
        except:
            pass

# ---------- New endpoints for auth ----------
@app.route("/api/register", methods=["POST"])
def api_register():
    """
    JSON body: { "username": "...", "email": "...", "password": "..." }
    Returns 201 created with user info (no password).
    """
    try:
        data = request.get_json(force=True)
        username = (data.get("username") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""

        if not username or not email or not password:
            return jsonify({"error": "username, email and password are required"}), 400

        try:
            user = create_user(username, email, password)
        except RuntimeError as rexc:
            msg = str(rexc)
            if msg == "username_or_email_taken":
                return jsonify({"error": "username_or_email_taken"}), 409
            return jsonify({"error": "create_user_failed", "details": msg}), 500

        # auto-login after registration
        session['user_id'] = user['id']
        return jsonify({"ok": True, "user": {"id": user['id'], "username": user['username'], "email": user['email'], "created_at": user['created_at'].isoformat() if isinstance(user.get('created_at'), datetime) else user.get('created_at')} }), 201

    except Exception as exc:
        tb = traceback.format_exc()
        print("Exception in /api/register:\n", tb)
        return jsonify({"error": "internal_exception", "details": str(exc)}), 500

@app.route("/api/login", methods=["POST"])
def api_login():
    """
    JSON body: { "username_or_email": "...", "password": "..." }
    Returns user's basic info and sets a session cookie on success.
    """
    try:
        data = request.get_json(force=True)
        username_or_email = (data.get("username_or_email") or "").strip()
        password = data.get("password") or ""
        if not username_or_email or not password:
            return jsonify({"error": "username_or_email and password required"}), 400

        try:
            user = find_user_by_username_or_email(username_or_email)
        except RuntimeError as rexc:
            return jsonify({"error": "db_error", "details": str(rexc)}), 500

        if not user:
            return jsonify({"error": "invalid_credentials"}), 401

        stored_hash = user.get("password_hash")
        if not stored_hash or not check_password_hash(stored_hash, password):
            return jsonify({"error": "invalid_credentials"}), 401

        # set session
        session['user_id'] = user['id']
        return jsonify({"ok": True, "user": {"id": user['id'], "username": user['username'], "email": user['email'], "created_at": user.get('created_at').isoformat() if isinstance(user.get('created_at'), datetime) else user.get('created_at')} }), 200

    except Exception as exc:
        tb = traceback.format_exc()
        print("Exception in /api/login:\n", tb)
        return jsonify({"error": "internal_exception", "details": str(exc)}), 500

@app.route("/api/logout", methods=["POST"])
def api_logout():
    try:
        session.pop("user_id", None)
        return jsonify({"ok": True}), 200
    except Exception as exc:
        return jsonify({"error": "logout_failed", "details": str(exc)}), 500

@app.route("/api/me", methods=["GET"])
def api_me():
    """
    Returns current user info if logged in via session cookie.
    """
    try:
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"user": None}), 200
        try:
            user = find_user_by_id(user_id)
        except RuntimeError as rexc:
            return jsonify({"error": "db_error", "details": str(rexc)}), 500
        if not user:
            # session refers to missing user
            session.pop("user_id", None)
            return jsonify({"user": None}), 200
        return jsonify({"user": user}), 200
    except Exception as exc:
        tb = traceback.format_exc()
        print("Exception in /api/me:\n", tb)
        return jsonify({"error": "internal_exception", "details": str(exc)}), 500

# -------------------------
# (existing code below is preserved; I only added DB & auth above)
# -------------------------

def get_unsplash_image(place_name, city_context=None, max_results=1, timeout=8):
    """
    Query Unsplash and return a normalized image dict or None.
    Normalized dict keys: { thumbnail, url, source_page, attribution }
    """
    if not place_name:
        return None
    q_candidates = [place_name]
    if city_context:
        q_candidates.insert(0, f"{place_name} {city_context}")   # try "Place City" first
        q_candidates.append(f"{place_name}, {city_context}")
    # also try plain place (already in list)

    headers = {"Authorization": f"Client-ID {UNSPLASH_KEY}"} if UNSPLASH_KEY else {}
    for q in q_candidates:
        try:
            print(f"DEBUG Unsplash: searching for q={q!r}")
            params = {"query": q, "per_page": max_results, "orientation": "landscape"}
            resp = requests.get(UNSPLASH_SEARCH_URL, headers=headers, params=params, timeout=timeout)
            print("DEBUG Unsplash status:", resp.status_code)
            try:
                j = resp.json()
            except Exception as je:
                print("DEBUG Unsplash JSON parse error:", je, resp.text[:250])
                j = None
            if resp.status_code != 200 or not j:
                # try next candidate
                continue
            total = j.get("total", 0)
            print("DEBUG Unsplash total:", total)
            results = j.get("results") or []
            if not results:
                # no result for this query, try next variant
                continue
            # pick first result
            r = results[0]
            urls = r.get("urls") or {}
            # normalize fields
            thumb = urls.get("thumb") or urls.get("small") or urls.get("regular")
            regular = urls.get("regular") or urls.get("full") or urls.get("raw")
            if not (thumb or regular):
                print("DEBUG Unsplash: result missing url fields, skipping")
                continue
            # build source page and attribution
            img_id = r.get("id")
            source_page = f"https://unsplash.com/photos/{img_id}" if img_id else r.get("links", {}).get("html")
            user = r.get("user", {})
            attribution = None
            if user:
                name = user.get("name")
                username = user.get("username")
                if name:
                    attribution = f"{name} (Unsplash)"
                elif username:
                    attribution = f"@{username} (Unsplash)"

            image_obj = {
                "thumbnail": thumb,
                "url": regular,
                "source_page": source_page,
                "attribution": attribution
            }
            print(f"DEBUG Unsplash: matched q={q!r} -> thumb={thumb} regular={regular}")
            # small pause to be polite
            time.sleep(0.06)
            return image_obj
        except Exception as e:
            print("DEBUG Unsplash exception for q=", q, str(e))
            # continue to next candidate
            continue

    # nothing found
    return None


# map weather code -> condition label
def map_weather_to_condition(weathercode, windspeed):
    sunny_codes = {0}
    cloudy_codes = {1,2,3}
    fog_codes = {45,48}
    drizzle_codes = {51,53,55,56,57}
    rain_codes = {61,63,65,80,81,82}
    freezing_rain_codes = {66,67}
    snow_codes = {71,73,75,77,85,86}
    thunder_codes = {95,96,99}
    try:
        ws = float(windspeed) if windspeed is not None else 0.0
        if ws >= 10:
            return "windy"
    except Exception:
        pass
    if weathercode in sunny_codes:
        return "sunny"
    if weathercode in cloudy_codes:
        return "cloudy"
    if weathercode in fog_codes:
        return "fog"
    if weathercode in drizzle_codes:
        return "drizzle"
    if weathercode in rain_codes or weathercode in freezing_rain_codes:
        return "rainy"
    if weathercode in snow_codes:
        return "snowy"
    if weathercode in thunder_codes:
        return "thunderstorm"
    return "other"

# ---------- helper: OpenRouter call with graceful errors ----------
def openrouter_chat_get_content(messages, max_tokens=512, temperature=0.7, top_p=0.95):
    if not OPENROUTER_API_KEY or "YOUR_OPENROUTER_KEY_HERE" in OPENROUTER_API_KEY:
        return None, {"error": "OPENROUTER_API_KEY not set"}
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": SITE_URL,
        "X-Title": SITE_TITLE,
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p
    }
    try:
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, data=json.dumps(payload), timeout=60)
        if resp.status_code == 404:
            # try to list models to help debugging
            try:
                models_resp = requests.get("https://openrouter.ai/api/v1/models", headers=headers, timeout=20)
                models_list = models_resp.json() if models_resp.ok else {"error": f"models list failed: {models_resp.status_code}"}
            except Exception as e:
                models_list = {"error": f"models list exception: {str(e)}"}
            return None, {"error": "model_not_found", "status_code": resp.status_code, "openrouter_body": resp.text, "available_models_sample": models_list}
        resp.raise_for_status()
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
            return text, data
        except Exception:
            return None, {"raw": data}
    except requests.HTTPError as e:
        try:
            detail = resp.text
        except Exception:
            detail = str(e)
        return None, {"error": "http_error", "details": detail, "status_code": getattr(resp, "status_code", None)}
    except Exception as e:
        return None, {"error": "exception", "details": str(e)}

# ---------- Transcribe endpoint (Deepgram) ----------
@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    """
    Accepts multipart/form-data with 'file' and optional 'language' field.
    language values:
      - 'auto' or missing -> detect_language=true
      - 'ja' -> language=ja
      - 'en' or 'en-US' -> language=en-US
    """
    if "file" not in request.files:
        return jsonify({"error":"file field is required"}), 400
    if not DEEPGRAM_API_KEY or "YOUR_DEEPGRAM_KEY_HERE" in DEEPGRAM_API_KEY:
        return jsonify({"error":"DEEPGRAM_API_KEY not configured"}), 500

    lang = request.form.get("language", "").strip().lower()  # from frontend
    # building params carefully
    params = {"model":"general", "punctuate":"true"}
    if not lang or lang == "auto":
        params["detect_language"] = "true"
    else:
        # use explicit language code (Deepgram expects 'ja' or 'en-US' etc.)
        params["language"] = "ja" if lang.startswith("ja") else "en-US"

    f = request.files["file"]
    audio_bytes = f.read()
    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": "application/octet-stream"}
    try:
        resp = requests.post(DEEPGRAM_BASE_URL, params=params, headers=headers, data=audio_bytes, timeout=120)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            try:
                return jsonify({"error":"Deepgram error", "details": resp.json()}), resp.status_code
            except Exception:
                return jsonify({"error":"Deepgram error", "details": resp.text}), resp.status_code
        out = resp.json()
        transcript = None
        detected_language = None
        results = out.get("results")
        if results:
            channels = results.get("channels")
            if channels and isinstance(channels, list) and len(channels)>0:
                alts = channels[0].get("alternatives")
                if alts and len(alts)>0:
                    transcript = alts[0].get("transcript")
                    detected_language = alts[0].get("language") or results.get("language")
        if not transcript:
            transcript = out.get("text") or out.get("transcript") or ""
        return jsonify({"text": transcript, "language": detected_language, "raw": out})
    except Exception as e:
        return jsonify({"error":"transcription_failed", "details": str(e)}), 500

# ---------- helper to perform the full process synchronously ----------
def process_message_sync(user_text):
    """
    Performs city extraction, weather lookup (if city found), and final LLM generation.
    Returns a dict with keys: city, weather (or None), answer or answer_structured, raw_llm (the final LLM raw payload)
    This reuses the same variable names used previously.
    """
    # 1) extract city
    extract_system = {"role": "system", "content": "You are a parser. From the user's message, extract the name of the city mentioned. If no city is present, respond with NONE."}
    extract_user = {"role": "user", "content": f"User message: {user_text}\n\nRespond with only the city name (single word or multi-word), or NONE if no city is found."}
    city_text, raw = openrouter_chat_get_content([extract_system, extract_user], max_tokens=40, temperature=0.0)
    if city_text is None:
        return {"error": "city extraction failed", "details": raw}

    city = city_text.strip().strip('"').strip("'")
    if city.upper() == "NONE" or city == "":
        # fallback: generate answer without city/weather
        messages = []
        messages.append({"role": "system", "content": "You are a travel assistant. Use the user's prompt to produce a helpful travel-related response even without specific city/weather data."})
        user_combined_no_city = (
            f"Original user prompt: {user_text}\n\n"
            "No city was detected in the user's message. Produce a helpful travel-oriented answer based only on the user's prompt. "
            "If the prompt asks for location-specific advice, explain you do not have a city and give general suggestions or ask for clarification."
        )
        messages.append({"role":"user","content": user_combined_no_city})
        final_text, raw_final = openrouter_chat_get_content(messages, max_tokens=600, temperature=0.7)
        if final_text is None:
            return {"error":"final_generation_failed_no_city", "details": raw_final}
        return {"city": None, "weather": None, "answer": final_text, "raw_llm": raw_final}

    # sanitize
    if city.lower().startswith("city:"):
        city = city.split(":",1)[1].strip()
    m = re.search(r"[A-Za-z\u00C0-\u017F\u3040-\u30FF\u4E00-\u9FFF \-]+", city)
    if m:
        city = m.group(0).strip()

    # 2) geocode + weather via Open-Meteo
    try:
        gresp = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count":1}, timeout=8)
        gresp.raise_for_status()
        gdata = gresp.json()
        results = gdata.get("results")
        if not results:
            return {"error":"city_not_found_in_geocoding", "city": city}
        place = results[0]
        lat = place["latitude"]
        lon = place["longitude"]

        fresp = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "current_weather": True, "timezone": "auto"
        }, timeout=8)
        fresp.raise_for_status()
        w = fresp.json()
        cur = w.get("current_weather", {})
        weathercode = cur.get("weathercode")
        temperature = cur.get("temperature")
        windspeed = cur.get("windspeed")
        condition = map_weather_to_condition(weathercode, windspeed)
        short_forecast = f"Condition: {condition}; Temp: {temperature}°C; wind: {windspeed} m/s."
    except Exception as e:
        return {"error":"weather_fetch_failed", "details": str(e)}

    # 3) final LLM generation
    messages = []
    messages.append({"role":"system","content":"You are a travel assistant. Use the provided weather facts and the user's request to produce a helpful response."})
    user_combined = (
        f"Original user prompt: {user_text}\n\n"
        f"Weather facts for {city}: {short_forecast}\n\n"
        "Now produce an answer that addresses the user's prompt, using the weather facts above. Be clear and useful."
    )
    messages.append({"role":"user","content": user_combined})
    final_text, raw_final = openrouter_chat_get_content(messages, max_tokens=900, temperature=0.7)
    if final_text is None:
        return {"error":"final_generation_failed", "details": raw_final}

    # Try to parse final_text as JSON (structured answer). If not JSON, keep as plain text.
    parsed = None
    try:
        parsed = json.loads(final_text)
    except Exception:
        parsed = None

    # If parsed looks structured (has 'sections'), attach images; otherwise return plain text
    if parsed and isinstance(parsed, dict) and parsed.get("sections"):
        try:
            structured_with_images = attach_unsplash_images_to_struct(parsed)
            return {
                "city": city,
                "weather": {"condition": condition, "temperature": temperature, "windspeed": windspeed},
                "answer_structured": structured_with_images,
                "answer": None,
                "raw_llm": raw_final
            }
        except Exception as e:
            # If image attachment fails, log and fall back to returning parsed without images
            print("attach_unsplash_images_to_struct error:", str(e))
            return {
                "city": city,
                "weather": {"condition": condition, "temperature": temperature, "windspeed": windspeed},
                "answer_structured": parsed,
                "answer": None,
                "raw_llm": raw_final
            }

    # Default fallback: return plain text answer (not structured)
    return {
        "city": city,
        "weather": {"condition": condition, "temperature": temperature, "windspeed": windspeed},
        "answer": final_text,
        "raw_llm": raw_final
    }

def attach_unsplash_images_to_struct(structured, city_context=None):
    """
    Walk the structured dict (expected: {'sections':[{'items':[{'title':...}, ...]}]})
    and attach image metadata into each item as item['image'] = {thumbnail,url,source_page,attribution}
    Returns the modified structured object.
    """
    print("DEBUG: attach_unsplash_images_to_struct called")
    if not structured or not isinstance(structured, dict):
        print("DEBUG: structured is empty or wrong type")
        return structured

    # open shelve cache if you use it
    try:
        cache = shelve.open("unsplash_cache.db")
    except Exception as e:
        cache = None
        print("DEBUG: could not open shelve cache:", e)

    try:
        for sec in structured.get("sections", []):
            for item in sec.get("items", []):
                # candidate fields that may contain place name
                place = None
                for key in ("title", "name", "place", "text"):
                    v = item.get(key)
                    if v and isinstance(v, str) and len(v.strip()) > 1:
                        place = v.strip()
                        break
                if not place:
                    # nothing to search for
                    print("DEBUG: no place field in item:", item)
                    continue

                # skip if image already exists
                if item.get("image"):
                    print("DEBUG: item already has image, skipping:", place)
                    continue

                cache_key = f"unsplash::{place.lower()}::{(city_context or '').lower()}"
                # check cache
                img = None
                if cache is not None:
                    try:
                        img = cache.get(cache_key)
                        if img:
                            print("DEBUG: cache hit for", cache_key)
                    except Exception as e:
                        print("DEBUG: cache read error", e)

                # if no cache hit, ask Unsplash
                if not img:
                    print("DEBUG: attempting unsplash lookup for:", place)
                    img = get_unsplash_image(place, city_context=city_context)
                    if img:
                        # store in cache
                        if cache is not None:
                            try:
                                cache[cache_key] = img
                                cache.sync()
                            except Exception as e:
                                print("DEBUG: cache write error", e)
                        item['image'] = img
                        print("DEBUG: attached image for", place, "->", img.get('thumbnail') or img.get('url'))
                    else:
                        print("DEBUG: no image found for", place)
                else:
                    # cache hit assigned above
                    item['image'] = img
    finally:
        try:
            if cache is not None:
                cache.close()
        except:
            pass

    return structured

# ---------- /api/process (synchronous) ----------
@app.route("/api/process", methods=["POST"])
def api_process():
    try:
        body = request.get_json(force=True)
        user_text = body.get("userText", "").strip()
        if not user_text:
            return jsonify({"error":"userText required"}), 400

        result = process_message_sync(user_text)
        # if an error object returned, propagate with 500 or 200 depending on semantics
        if result.get("error"):
            # if it's city_not_found_in_geocoding, return 200 with that info (client handles)
            if result["error"] == "city_not_found_in_geocoding":
                return jsonify(result), 200
            return jsonify({"error": result["error"], "details": result.get("details")}), 500

        return jsonify(result), 200

    except Exception as exc:
        tb = traceback.format_exc()
        print("Exception in /api/process:\n", tb)
        return jsonify({"error":"internal_exception","details": str(exc), "traceback": tb}), 500

# ---------- /api/stream_process (streaming simulated) ----------
@app.route("/api/stream_process", methods=["POST"])
def api_stream_process():
    """
    Streams back the final answer in small chunks using text/event-stream.
    Implementation note: we compute the full answer server-side (process_message_sync),
    then stream it piece-by-piece to simulate token streaming (works reliably for demo).
    """
    try:
        body = request.get_json(force=True)
        user_text = body.get("userText", "").strip()
        if not user_text:
            return jsonify({"error":"userText required"}), 400

        result = process_message_sync(user_text)
        if result.get("error"):
            # send a single chunk with JSON error object
            def single_err():
                yield f"data: {json.dumps({'error': result})}\n\n"
            return Response(single_err(), content_type="text/event-stream")

        answer = result.get("answer","")
        # split into chunks (by sentences and small pieces)
        import itertools
        # naive chunk: sentences first
        chunks = []
        # split by sentence punctuation, but keep short pieces
        pieces = re.split(r'(?<=[.?!])\s+', answer)
        for p in pieces:
            if not p:
                continue
            # further split long sentences into ~60-char pieces
            if len(p) <= 80:
                chunks.append(p)
            else:
                for i in range(0, len(p), 60):
                    chunks.append(p[i:i+60])

        def generate():
            # initial meta: weather + city
            meta = {"type":"meta","city": result.get("city"), "weather": result.get("weather")}
            yield f"data: {json.dumps(meta)}\n\n"
            # now stream each chunk with small delay
            for i, chunk in enumerate(chunks):
                payload = {"type":"chunk","index": i, "text": chunk}
                yield f"data: {json.dumps(payload)}\n\n"
                time.sleep(0.06)  # small delay to simulate streaming (60ms)
            # final event
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        return Response(generate(), content_type="text/event-stream")
    except Exception as exc:
        tb = traceback.format_exc()
        print("Exception in /api/stream_process:\n", tb)
        def single_exc():
            yield f"data: {json.dumps({'error': str(exc), 'traceback': tb})}\n\n"
        return Response(single_exc(), content_type="text/event-stream")

# ---------- Serve frontend ----------
@app.route("/")
def index():
    return render_template("index8.html")

# ---------- health ----------
@app.route("/api/health")
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    print("Starting server. OpenRouter key present:", bool(OPENROUTER_API_KEY and "YOUR_OPENROUTER_KEY_HERE" not in OPENROUTER_API_KEY))
    print("Starting server. Deepgram key present:", bool(DEEPGRAM_API_KEY and "YOUR_DEEPGRAM_KEY_HERE" not in DEEPGRAM_API_KEY))
    print("Postgres configured:", bool(get_conn_params()))
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)), debug=False, use_reloader=False)

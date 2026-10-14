import io
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parking")
OPTIONS = json.loads(Path("/data/options.json").read_text())
TOKEN = OPTIONS["bot_token"].strip()
ADMIN = int(OPTIONS["admin_chat_id"])
CAMERA = OPTIONS["camera_entity_id"]
START = int(OPTIONS["start_hour"])
END = int(OPTIONS["end_hour"])
TTL = int(OPTIONS["cache_seconds"])
TZ = ZoneInfo("Europe/Kyiv")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
DATA = Path("/data/people.json")
API = "https://api.telegram.org/bot" + TOKEN + "/"
session = requests.Session()
cache_lock = Lock()
cache = {"time": 0.0, "data": None}
last_message = {}
BUTTON = {"keyboard": [[{"text": "📸 Що там парковка?"}]], "resize_keyboard": True}


def read_people():
    if DATA.exists():
        try:
            obj = json.loads(DATA.read_text())
            return {"approved": set(map(int, obj.get("approved", []))),
                    "pending": {str(k): v for k, v in obj.get("pending", {}).items()}}
        except (ValueError, OSError) as e:
            raise RuntimeError("Cannot read access list; refusing to reset permissions") from e
    return {"approved": set(), "pending": {}}


people = read_people()
people["approved"].add(ADMIN)


def persist():
    tmp = DATA.with_suffix(".tmp")
    tmp.write_text(json.dumps({"approved": sorted(people["approved"]),
                               "pending": people["pending"]}, ensure_ascii=False))
    os.replace(tmp, DATA)


def telegram(method, **kwargs):
    result = session.post(API + method, timeout=40, **kwargs)
    result.raise_for_status()
    payload = result.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram {method}: {payload.get('description')}")
    return payload.get("result")


def say(chat_id, text, markup=None):
    data = {"chat_id": chat_id, "text": text}
    if markup is not None:
        data["reply_markup"] = json.dumps(markup, ensure_ascii=False)
    return telegram("sendMessage", data=data)


def open_now():
    hour = datetime.now(TZ).hour
    return START <= hour < END if START < END else (hour >= START or hour < END)


def snapshot():
    if not SUPERVISOR_TOKEN:
        raise RuntimeError("Supervisor API token missing")
    with cache_lock:
        now = time.monotonic()
        if cache["data"] is not None and now - cache["time"] < TTL:
            return cache["data"]
        url = "http://supervisor/core/api/camera_proxy/" + CAMERA
        response = session.get(url, headers={"Authorization": "Bearer " + SUPERVISOR_TOKEN}, timeout=25)
        response.raise_for_status()
        if not response.headers.get("Content-Type", "").lower().startswith("image/") or not response.content:
            raise RuntimeError("Camera did not return an image")
        cache["data"] = response.content
        cache["time"] = time.monotonic()
        return cache["data"]


def photo(chat_id):
    data = snapshot()
    telegram("sendPhoto", data={"chat_id": chat_id}, files={"photo": ("parking.jpg", io.BytesIO(data), "image/jpeg")})


def welcome(chat_id):
    say(chat_id, "Натисни кнопку, щоб отримати знімок парковки.", BUTTON)


def new_request(user, chat_id):
    key = str(user["id"])
    if key not in people["pending"]:
        name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
        people["pending"][key] = {"name": name[:100], "username": (user.get("username") or "")[:60]}
        persist()
        label = name + (" @" + user["username"] if user.get("username") else "")
        say(ADMIN, "🔐 Запит на доступ до парковки\n" + label + "\nTelegram ID: " + key,
            {"inline_keyboard": [[
                {"text": "✅ Дозволити", "callback_data": "allow:" + key},
                {"text": "❌ Відхилити", "callback_data": "deny:" + key}
            ]]})
    say(chat_id, "Запит надіслано адміністратору. Очікуй підтвердження.")


def message(msg):
    chat = msg.get("chat", {})
    if chat.get("type") != "private":
        return
    uid = int(chat["id"])
    txt = (msg.get("text") or "").strip()
    if uid != ADMIN and uid not in people["approved"]:
        new_request(msg.get("from", {"id": uid}), uid)
        return
    if txt.startswith("/revoke") and uid == ADMIN:
        parts = txt.split()
        if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) == ADMIN:
            say(uid, "Використання: /revoke TELEGRAM_ID")
            return
        target = int(parts[1])
        people["approved"].discard(target)
        people["pending"].pop(str(target), None)
        persist()
        say(uid, f"Доступ відкликано: {target}")
        return
    if txt.startswith("/users") and uid == ADMIN:
        say(uid, "Схвалені ID:\n" + "\n".join(map(str, sorted(people["approved"]))))
        return
    if txt.startswith("/start") or txt.startswith("/help"):
        welcome(uid)
        return
    if txt != "📸 Що там парковка?":
        welcome(uid)
        return
    if not open_now():
        say(uid, "🌙 Знімки доступні з 06:00 до 22:00 за Києвом.")
        return
    now = time.monotonic()
    if now - last_message.get(uid, -9999) < 3:
        return
    last_message[uid] = now
    try:
        photo(uid)
    except Exception:
        log.exception("Snapshot delivery failed")
        say(uid, "⚠️ Не вдалося отримати знімок. Спробуй пізніше.")


def callback(cb):
    uid = int(cb.get("from", {}).get("id", 0))
    callback_id = cb["id"]
    value = cb.get("data", "")
    if uid != ADMIN or not value.startswith(("allow:", "deny:")):
        telegram("answerCallbackQuery", data={"callback_query_id": callback_id, "text": "Немає прав"})
        return
    action, key = value.split(":", 1)
    if not key.isdigit() or key not in people["pending"]:
        telegram("answerCallbackQuery", data={"callback_query_id": callback_id, "text": "Запит уже оброблений"})
        return
    people["pending"].pop(key)
    target = int(key)
    if action == "allow":
        people["approved"].add(target)
    persist()
    telegram("answerCallbackQuery", data={"callback_query_id": callback_id,
                                         "text": "Доступ надано" if action == "allow" else "Відхилено"})
    original = cb.get("message", {})
    if original:
        telegram("editMessageReplyMarkup", data={"chat_id": original["chat"]["id"],
                                                "message_id": original["message_id"],
                                                "reply_markup": json.dumps({"inline_keyboard": []})})
    if action == "allow":
        say(target, "✅ Доступ відкрито.", BUTTON)
    else:
        say(target, "❌ Запит на доступ відхилено.")


def main():
    if not TOKEN or not SUPERVISOR_TOKEN:
        raise RuntimeError("Configure bot_token and enable homeassistant_api")
    log.info("Parking Telegram Bot started; hours %02d:00-%02d:00, cache %ds", START, END, TTL)
    telegram("deleteWebhook", data={"drop_pending_updates": "false"})
    offset = None
    while True:
        try:
            params = {"timeout": 25, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset is not None:
                params["offset"] = offset
            updates = telegram("getUpdates", data=params)
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    if "message" in u:
                        message(u["message"])
                    elif "callback_query" in u:
                        callback(u["callback_query"])
                except Exception:
                    log.exception("Failed to process update %s", u["update_id"])
        except Exception:
            log.exception("Polling failed")
            time.sleep(5)


if __name__ == "__main__":
    main()

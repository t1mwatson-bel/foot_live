
import requests
from config import API, CHAT_ID


def send_telegram(text):
    try:
        r = requests.post(
            API + "/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=15,
        )

        try:
            data = r.json()
        except ValueError:
            print(
                f"❌ TG send: HTTP {r.status_code}, "
                f"ответ: {r.text[:500]}",
                flush=True,
            )
            return None

        if r.status_code == 200 and data.get("ok"):
            return data["result"]["message_id"]

        print(
            f"❌ TG send: HTTP {r.status_code}, "
            f"ошибка: {data.get('description', data)}",
            flush=True,
        )

    except Exception as e:
        print(f"❌ TG send: {e}", flush=True)

    return None


def edit_telegram(message_id, text):
    try:
        r = requests.post(
            API + "/editMessageText",
            json={
                "chat_id": CHAT_ID,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=15,
        )

        try:
            data = r.json()
        except ValueError:
            print(
                f"❌ TG edit: HTTP {r.status_code}, "
                f"ответ: {r.text[:500]}",
                flush=True,
            )
            return False

        if r.status_code == 200 and data.get("ok"):
            print(
                f"✏️ TG: сообщение {message_id} обновлено",
                flush=True,
            )
            return True

        description = str(data.get("description", data))

        # Telegram сообщает это, если текст уже такой же.
        if "message is not modified" in description.lower():
            print(
                f"ℹ️ TG: сообщение {message_id} уже содержит этот текст",
                flush=True,
            )
            return True

        print(
            f"❌ TG edit: сообщение {message_id}; "
            f"HTTP {r.status_code}; ошибка: {description}",
            flush=True,
        )
        return False

    except Exception as e:
        print(f"❌ TG edit: {e}", flush=True)
        return False


def format_with_result(base_text, result_line):
    return f"{base_text}\n\n{result_line}"
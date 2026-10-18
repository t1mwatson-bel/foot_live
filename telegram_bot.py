```python
import requests

from config import API, CHAT_ID


REQUEST_TIMEOUT = 15


def _telegram_request(method, payload):
    """Отправляет запрос в Telegram API и проверяет результат."""
    url = f"{API.rstrip('/')}/{method}"

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        try:
            data = response.json()
        except ValueError:
            print(
                f"❌ Telegram {method}: сервер вернул не JSON. "
                f"HTTP {response.status_code}: {response.text[:500]}",
                flush=True,
            )
            return False, None

        if not response.ok or not data.get("ok"):
            description = data.get("description", response.text[:500])

            # Telegram возвращает эту ошибку, если текст уже такой же.
            # Это означает, что сообщение уже находится в нужном состоянии.
            if (
                method == "editMessageText"
                and "message is not modified" in str(description).lower()
            ):
                return True, data.get("result")

            print(
                f"❌ Telegram {method}: HTTP {response.status_code}; "
                f"ошибка: {description}",
                flush=True,
            )
            return False, None

        return True, data.get("result")

    except requests.RequestException as exc:
        print(
            f"❌ Telegram {method}: ошибка соединения: {exc}",
            flush=True,
        )
        return False, None

    except Exception as exc:
        print(
            f"❌ Telegram {method}: неожиданная ошибка: {exc}",
            flush=True,
        )
        return False, None


def send_telegram(text):
    """Отправляет новое сообщение и возвращает его message_id."""
    success, result = _telegram_request(
        "sendMessage",
        {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        },
    )

    if not success or not isinstance(result, dict):
        return None

    message_id = result.get("message_id")

    if message_id is None:
        print(
            "❌ Telegram sendMessage: в ответе отсутствует message_id",
            flush=True,
        )
        return None

    return message_id


def edit_telegram(message_id, text):
    """Редактирует ранее отправленное сообщение."""
    if message_id is None:
        print(
            "❌ Telegram editMessageText: отсутствует message_id",
            flush=True,
        )
        return False

    success, _ = _telegram_request(
        "editMessageText",
        {
            "chat_id": CHAT_ID,
            "message_id": int(message_id),
            "text": text,
            "parse_mode": "HTML",
        },
    )

    if success:
        print(
            f"✅ Telegram: сообщение {message_id} обновлено",
            flush=True,
        )

    return success


def format_with_result(base_text, result_line):
    """Добавляет результат к исходному тексту прогноза."""
    base_text = (base_text or "").rstrip()
    result_line = (result_line or "").strip()

    if not base_text:
        return result_line

    if not result_line:
        return base_text

    return f"{base_text}\n\n{result_line}"
```

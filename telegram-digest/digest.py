"""Telegram digest: reads new messages from your chats/channels, lets Claude
pick the important ones, and sends a short digest to your Saved Messages.

Run once:      python digest.py
Run in a loop: python digest.py --loop
"""

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION_NAME = str(BASE_DIR / os.getenv("TG_SESSION", "digest"))

MODEL = os.getenv("DIGEST_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("DIGEST_EFFORT", "low")

LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "24"))
MAX_PER_CHAT = int(os.getenv("MAX_PER_CHAT", "100"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "150"))
MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "3000"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "6"))
LOOP_MINUTES = int(os.getenv("LOOP_MINUTES", "60"))

# Comma-separated chat usernames/titles. Empty INCLUDE = all chats.
INCLUDE = [s.strip().lower() for s in os.getenv("INCLUDE_CHATS", "").split(",") if s.strip()]
EXCLUDE = [s.strip().lower() for s in os.getenv("EXCLUDE_CHATS", "").split(",") if s.strip()]
SKIP_BOTS = os.getenv("SKIP_BOTS", "1") == "1"

STATE_FILE = BASE_DIR / "state.json"
INTERESTS_FILE = BASE_DIR / "interests.md"

TG_MESSAGE_LIMIT = 4000

log = logging.getLogger("digest")

SYSTEM_PROMPT = """Sen foydalanuvchining shaxsiy Telegram yordamchisisan.
Senga bir nechta chat va kanallardan kelgan yangi xabarlar ro'yxati beriladi.
Vazifang: foydalanuvchi uchun haqiqatan muhim yoki foydali bo'lgan xabarlarni tanlash.

Har bir tanlangan xabar uchun:
- id: xabarning ro'yxatdagi id raqami (o'zgartirmasdan)
- score: 1-10 (10 = darhol ko'rish kerak)
- category: qisqa toifa (masalan: "Shaxsiy", "Ish", "Imkoniyat", "Yangilik", "YouTube", "AI")
- summary: o'zbek tilida 1-2 gaplik qisqa mazmun

Reklama, spam, takroriy postlar, "salom"/stiker kabi bo'sh xabarlarni tanlama.
Muhim narsa bo'lmasa, bo'sh ro'yxat qaytar.

Foydalanuvchining qiziqishlari va qoidalari:
"""

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "score": {"type": "integer"},
                    "category": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["id", "score", "category", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def chat_matches(names: list[str], dialog) -> bool:
    entity = dialog.entity
    candidates = {(dialog.name or "").lower()}
    if getattr(entity, "username", None):
        candidates.add(entity.username.lower())
        candidates.add("@" + entity.username.lower())
    return any(n in candidates for n in names)


def message_link(entity, msg_id: int) -> str | None:
    if isinstance(entity, Channel):
        if entity.username:
            return f"https://t.me/{entity.username}/{msg_id}"
        return f"https://t.me/c/{entity.id}/{msg_id}"
    return None


def chat_kind(entity) -> str:
    if isinstance(entity, User):
        return "bot" if entity.bot else "private"
    if isinstance(entity, Chat):
        return "group"
    if isinstance(entity, Channel):
        return "group" if entity.megagroup else "channel"
    return "other"


async def collect_messages(client: TelegramClient, state: dict) -> tuple[list[dict], dict]:
    """Return new messages since last run and the updated per-chat state."""
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    me = await client.get_me()
    collected: list[dict] = []
    new_state = dict(state)

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, User) and entity.id == me.id:
            continue  # Saved Messages - that's where the digest goes
        kind = chat_kind(entity)
        if kind == "bot" and SKIP_BOTS:
            continue
        if INCLUDE and not chat_matches(INCLUDE, dialog):
            continue
        if EXCLUDE and chat_matches(EXCLUDE, dialog):
            continue

        key = str(dialog.id)
        last_id = state.get(key, 0)
        if last_id == 0 and (dialog.date is None or dialog.date < since):
            continue  # no activity inside the lookback window

        kwargs = {"limit": MAX_PER_CHAT}
        if last_id:
            kwargs["min_id"] = last_id

        max_seen = last_id
        async for msg in client.iter_messages(entity, **kwargs):
            max_seen = max(max_seen, msg.id)
            if not last_id and msg.date < since:
                break
            text = (msg.message or "").strip()
            if not text:
                continue
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS] + " …[qisqartirildi]"
            sender = ""
            if kind == "group" and msg.sender:
                sender = getattr(msg.sender, "first_name", None) or getattr(msg.sender, "title", "") or ""
            collected.append(
                {
                    "chat": dialog.name,
                    "kind": kind,
                    "sender": sender,
                    "date": msg.date.astimezone().strftime("%d.%m %H:%M"),
                    "text": text,
                    "link": message_link(entity, msg.id),
                }
            )
        if max_seen:
            new_state[key] = max_seen

    log.info("Collected %d new messages", len(collected))
    return collected, new_state


def rank_batch(claude: anthropic.Anthropic, batch: list[dict], interests: str) -> list[dict]:
    lines = []
    for i, m in enumerate(batch):
        who = f" | {m['sender']}" if m["sender"] else ""
        lines.append(f"[id={i}] ({m['kind']}) {m['chat']}{who} | {m['date']}\n{m['text']}")
    user_content = "Yangi xabarlar:\n\n" + "\n\n---\n\n".join(lines)

    response = claude.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT + interests,
        messages=[{"role": "user", "content": user_content}],
        output_config={
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": RESULT_SCHEMA},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        log.warning("Claude declined this batch (%s)", response.stop_details)
        return []
    if response.stop_reason == "max_tokens":
        log.warning("Response hit max_tokens; lower BATCH_SIZE")
        return []

    text = next((b.text for b in response.content if b.type == "text"), "")
    picked = []
    for item in json.loads(text)["items"]:
        idx = item["id"]
        if 0 <= idx < len(batch) and item["score"] >= MIN_SCORE:
            picked.append({**batch[idx], **item})
    return picked


def format_digest(items: list[dict]) -> list[str]:
    """Build the digest and split it into Telegram-sized chunks."""
    items.sort(key=lambda x: x["score"], reverse=True)
    header = f"📌 Digest — {datetime.now().strftime('%d.%m.%Y %H:%M')}\nMuhim xabarlar: {len(items)}\n"
    blocks = []
    for it in items:
        fire = "🔥" if it["score"] >= 9 else "⭐" if it["score"] >= 7 else "•"
        block = f"{fire} [{it['category']}] {it['chat']} ({it['date']})\n{it['summary']}"
        if it["link"]:
            block += f"\n{it['link']}"
        blocks.append(block)

    chunks, current = [], header
    for block in blocks:
        if len(current) + len(block) + 2 > TG_MESSAGE_LIMIT:
            chunks.append(current)
            current = ""
        current += "\n" + block + "\n"
    chunks.append(current)
    return chunks


async def run_once(client: TelegramClient, claude: anthropic.Anthropic) -> None:
    interests = INTERESTS_FILE.read_text(encoding="utf-8") if INTERESTS_FILE.exists() else ""
    state = load_state()
    messages, new_state = await collect_messages(client, state)

    if not messages:
        log.info("Nothing new")
        save_state(new_state)
        return

    picked: list[dict] = []
    for start in range(0, len(messages), BATCH_SIZE):
        batch = messages[start : start + BATCH_SIZE]
        try:
            picked.extend(rank_batch(claude, batch, interests))
        except anthropic.RateLimitError:
            log.error("Rate limited by Claude API; will retry next run")
            return  # keep old state so these messages are re-checked
        except anthropic.APIStatusError as e:
            log.error("Claude API error %s: %s", e.status_code, e.message)
            return
        except anthropic.APIConnectionError:
            log.error("Could not reach Claude API; will retry next run")
            return

    if picked:
        for chunk in format_digest(picked):
            await client.send_message("me", chunk, link_preview=False)
        log.info("Sent digest with %d items", len(picked))
    else:
        log.info("No important messages this time")
    save_state(new_state)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram -> Claude digest")
    parser.add_argument("--loop", action="store_true", help=f"repeat every LOOP_MINUTES ({LOOP_MINUTES})")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    claude = anthropic.Anthropic()

    async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
        while True:
            started = time.monotonic()
            await run_once(client, claude)
            if not args.loop:
                break
            await asyncio.sleep(max(0, LOOP_MINUTES * 60 - (time.monotonic() - started)))


if __name__ == "__main__":
    asyncio.run(main())

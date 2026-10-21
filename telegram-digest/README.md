# Telegram Digest

Telegram'dagi chat, guruh va kanallaringizdan yangi xabarlarni o'qiydi,
Claude yordamida eng muhimlarini saralaydi va qisqa digestni
**Saved Messages** (Избранное) ga yuboradi.

```
📌 Digest — 21.10.2026 09:00
Muhim xabarlar: 3

🔥 [Shaxsiy] Akmal (21.10 08:12)
Ertangi uchrashuv vaqtini tasdiqlashingizni so'ramoqda.

⭐ [AI] AI News kanal (21.10 07:40)
Yangi rasm generatsiya modeli chiqdi, bepul tarif bor.
https://t.me/ainews/1234
```

## Qanday ishlaydi

1. **Telethon** orqali sizning akkauntingizdan kiradi (bot emas — oddiy bot
   siz a'zo bo'lgan kanallar va shaxsiy chatlarni o'qiy olmaydi).
2. Oxirgi ishga tushirishdan beri kelgan xabarlarni yig'adi
   (`state.json` da har chat uchun oxirgi o'qilgan xabar saqlanadi).
3. Xabarlarni `interests.md` dagi qiziqishlaringiz bilan birga Claude'ga
   yuboradi, u har biriga 1–10 ball beradi.
4. `MIN_SCORE` dan yuqori ballilarini qisqa mazmun va havola bilan
   Saved Messages'ga yuboradi.

Bot xabarlarni **o'qilgan deb belgilamaydi**.

## O'rnatish

```bash
cd telegram-digest
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` ni to'ldiring:

- `TG_API_ID`, `TG_API_HASH` — https://my.telegram.org → *API development tools*
- `ANTHROPIC_API_KEY` — https://console.anthropic.com → *API Keys*

`interests.md` ni o'zingizga moslang — saralash sifati asosan shunga bog'liq.

## Ishga tushirish

```bash
python digest.py          # bir marta
python digest.py --loop   # har LOOP_MINUTES daqiqada
```

Birinchi marta telefon raqamingiz va Telegram yuborgan kodni so'raydi.
Shundan keyin `digest.session` fayli yaratiladi.

> ⚠️ `digest.session` va `.env` — akkauntingiz kaliti. Hech kimga bermang,
> git'ga qo'shmang (`.gitignore` da bor).

## Sozlamalar (`.env`)

| O'zgaruvchi | Default | Ma'nosi |
|---|---|---|
| `DIGEST_MODEL` | `claude-opus-5-5` | Arzonroq: `claude-haiku-5-5` |
| `DIGEST_EFFORT` | `low` | `low` / `medium` / `high` |
| `LOOKBACK_HOURS` | `24` | Birinchi ishga tushirishda necha soatlik xabar |
| `MAX_PER_CHAT` | `100` | Bitta chatdan bir martada maksimal xabar |
| `MIN_SCORE` | `6` | Digestga kirish uchun minimal ball |
| `LOOP_MINUTES` | `60` | `--loop` oralig'i |
| `INCLUDE_CHATS` | bo'sh | Faqat shu chatlar (username yoki nom, vergul bilan) |
| `EXCLUDE_CHATS` | bo'sh | Bu chatlarni o'tkazib yuborish |
| `SKIP_BOTS` | `1` | Botlar bilan chatlarni o'tkazib yuborish |

## Instagram haqida

Instagram Telegram'dek ochiq emas:

- Rasmiy **Instagram Graph API** faqat **Business/Creator** akkauntlar uchun
  ishlaydi va DM'larni faqat Meta app review'dan o'tgandan keyin beradi.
- Shaxsiy akkauntni scraping/unofficial API bilan o'qish Instagram qoidalariga
  zid va akkaunt bloklanish xavfi yuqori.

Shuning uchun keyingi bosqich sifatida: Creator akkauntga o'tib, Graph API
orqali DM va kommentlarni shu digestga qo'shish mumkin.

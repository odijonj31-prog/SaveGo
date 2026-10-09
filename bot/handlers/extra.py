import json
import logging
import time
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InlineQuery,
                           InlineQueryResultCachedAudio, InlineQueryResultCachedPhoto,
                           InlineQueryResultCachedVideo, InlineQueryResultsButton, LabeledPrice,
                           Message, PreCheckoutQuery)

from .. import config, db
from ..i18n import t
from .user import URL_RE, extract_url, handle_link, is_link, norm_url

log = logging.getLogger(__name__)
router = Router()          # private: /ref, /premium, to'lov, inline
group = Router()           # guruhlar: faqat linklar
group.message.filter(F.chat.type.in_({"group", "supergroup"}))


def fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


# ---------------- guruhlarda ----------------
@group.message(is_link)
async def on_group_link(m: Message, bot: Bot, lang: str = "uz"):
    if m.from_user is None:
        return
    await handle_link(m, bot, lang, extract_url(m), 720, m.from_user.id)


# ---------------- referal ----------------
@router.message(Command("ref"), F.chat.type == "private")
async def cmd_ref(m: Message, bot: Bot, u, lang: str):
    uname = (await bot.me()).username
    link = f"https://t.me/{uname}?start=ref_{m.from_user.id}"
    n = await db.ref_count(m.from_user.id)
    await m.answer(t(lang, "ref_text", b=config.REF_BONUS, link=link, n=n, bonus=n * config.REF_BONUS))


# ---------------- premium (Telegram Stars) ----------------
@router.message(Command("premium"), F.chat.type == "private")
async def cmd_premium(m: Message, u, lang: str):
    row = await db.get_user(m.from_user.id)
    text = t(lang, "premium_info", d=config.PREMIUM_DAYS, stars=config.PREMIUM_STARS)
    if (row["premium_until"] or 0) > time.time():
        text += "\n\n" + t(lang, "premium_active", until=fmt_date(row["premium_until"]))
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_buy", stars=config.PREMIUM_STARS), callback_data="buy")]])
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "buy")
async def buy(call: CallbackQuery, bot: Bot, lang: str):
    await call.answer()
    await bot.send_invoice(
        chat_id=call.from_user.id, title="💎 Premium",
        description=t(lang, "premium_info", d=config.PREMIUM_DAYS, stars=config.PREMIUM_STARS).replace("<b>", "").replace("</b>", ""),
        payload=f"premium:{config.PREMIUM_DAYS}", currency="XTR",
        prices=[LabeledPrice(label="Premium", amount=config.PREMIUM_STARS)])


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def paid(m: Message, bot: Bot, lang: str):
    until = await db.extend_premium(m.from_user.id, config.PREMIUM_DAYS)
    await db.incr("stars", m.successful_payment.total_amount)
    await m.answer(t(lang, "premium_thanks", until=fmt_date(until)))
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid, f"⭐ To'lov: {m.successful_payment.total_amount} Stars — "
                                        f"<code>{m.from_user.id}</code> (@{m.from_user.username or '-'})")
        except Exception:
            pass


# ---------------- inline rejim ----------------
@router.inline_query()
async def inline(q: InlineQuery, bot: Bot):
    text = (q.query or "").strip()
    results = []
    mt = URL_RE.search(text)
    if mt:
        row = await db.cache_get(norm_url(mt.group(0)))
        if row:
            for i, (kind, fid) in enumerate(json.loads(row["payload"])[:5]):
                rid = f"c{i}"
                if kind == "video":
                    results.append(InlineQueryResultCachedVideo(id=rid, video_file_id=fid, title=(row["title"] or "Video")[:60]))
                elif kind == "photo":
                    results.append(InlineQueryResultCachedPhoto(id=rid, photo_file_id=fid))
                elif kind == "audio":
                    results.append(InlineQueryResultCachedAudio(id=rid, audio_file_id=fid))
    await q.answer(results, cache_time=5, is_personal=False,
                   button=InlineQueryResultsButton(text="📥 Botda yuklash / Open bot", start_parameter="inline"))

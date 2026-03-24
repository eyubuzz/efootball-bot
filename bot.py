import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import ADMIN_ID, BOT_TOKEN, CHANNEL_ID
from database import (
    get_comment_count,
    get_comments_page,
    get_question,
    get_stats,
    get_user_aura,
    get_user_stats,
    init_db,
    save_comment,
    save_question,
    set_channel_msg_id,
    update_status,
    vote_comment,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
WAITING_QUESTION = 1
WAITING_COMMENT  = 2

# ── Constants ─────────────────────────────────────────────────────────────────
COMMENTS_PER_PAGE = 3

TAGS = {
    "teambuildup": "🏗️ Team Build-up",
    "formation":   "📐 Formation",
    "packs":       "🎁 Opening Packs",
    "tactics":     "🎯 Tactics",
    "player":      "⭐ Player Review",
    "budget":      "💰 Budget Build",
    "general":     "🔧 General",
}

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["✏️ Ask Question"], ["👤 Profile", "ℹ️ Help"]],
    resize_keyboard=True,
    input_field_placeholder="Choose an option…",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def tag_selection_keyboard(question_id: int) -> InlineKeyboardMarkup:
    buttons, row = [], []
    for key, label in TAGS.items():
        row.append(InlineKeyboardButton(label, callback_data=f"settag_{question_id}_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Reject Instead", callback_data=f"reject_{question_id}")])
    return InlineKeyboardMarkup(buttons)


def review_keyboard(question_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏷️ Tag & Approve", callback_data=f"tag_{question_id}"),
        InlineKeyboardButton("❌ Reject",         callback_data=f"reject_{question_id}"),
    ]])


def build_comments_view(question_id: int, page: int, bot_username: str):
    """Return (text, keyboard) for the given comments page."""
    row = get_question(question_id)
    if not row:
        return "⚠️ Question not found.", InlineKeyboardMarkup([])

    tag_label  = TAGS.get(row["tag"] or "", "")
    comments, total = get_comments_page(question_id, page, COMMENTS_PER_PAGE)
    total_pages = max(1, (total + COMMENTS_PER_PAGE - 1) // COMMENTS_PER_PAGE)
    page = max(1, min(page, total_pages))

    lines = [
        f"💬 *eFootball Question #{question_id}*",
    ]
    if tag_label:
        lines.append(f"_{tag_label}_")
    lines.append(f"Displaying page {page}/{total_pages}. Total {total} Comment{'s' if total != 1 else ''}")
    lines.append("─" * 24)

    if not comments:
        lines.append("\n_No comments yet — be the first!_")
    else:
        for i, c in enumerate(comments, 1):
            aura = get_user_aura(c["user_id"])
            name = c["full_name"] or "Anonymous"
            lines.append(f"\n*[{i}]* 👤 *{name}* ⚡{aura} Aura")
            lines.append(c["comment"])

    lines.append("─" * 24)
    text = "\n".join(lines)

    buttons = []

    # Vote row per comment
    for i, c in enumerate(comments, 1):
        buttons.append([
            InlineKeyboardButton(f"👍 {c['likes']}",  callback_data=f"up_{c['id']}_{question_id}_{page}"),
            InlineKeyboardButton(f"👎 {c['dislikes']}", callback_data=f"dn_{c['id']}_{question_id}_{page}"),
            InlineKeyboardButton(f"↩️ Reply #{i}",    callback_data=f"rp_{c['id']}_{question_id}_{page}"),
        ])

    # Navigation row
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"vc_{question_id}_{page - 1}"))
    nav.append(InlineKeyboardButton(f"Page {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"vc_{question_id}_{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("➕ Add Comment", callback_data=f"ac_{question_id}")])

    return text, InlineKeyboardMarkup(buttons)


async def update_channel_button(context: ContextTypes.DEFAULT_TYPE, question_id: int):
    """Edit the channel post to show the updated comment count."""
    row = get_question(question_id)
    if not row:
        return
    channel_msg_id = row["channel_msg_id"]
    if not channel_msg_id:
        return
    count    = get_comment_count(question_id)
    bot_link = f"https://t.me/{context.bot.username}?start=c_{question_id}"
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=CHANNEL_ID,
            message_id=channel_msg_id,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"💬 View / Add Comments ({count})", url=bot_link)
            ]]),
        )
    except Exception as e:
        logger.warning("Could not update channel button: %s", e)


# ── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    # Deep-link: /start c_<question_id>
    if args and args[0].startswith("c_"):
        try:
            question_id = int(args[0][2:])
        except ValueError:
            question_id = None
        if question_id:
            text, keyboard = build_comments_view(question_id, 1, context.bot.username)
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
            return

    await update.message.reply_text(
        "👋 *Welcome to the eFootball Q&A Bot!*\n\n"
        "Ask questions about team building, formations, packs & more.\n\n"
        "Use the menu below to get started 👇",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


# ── Help ──────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use this bot:*\n\n"
        "✏️ *Ask Question* — tap the menu button and type your eFootball question.\n"
        "💬 *Comments* — tap the button under any channel post to view and add comments.\n"
        "👍 / 👎 — vote on comments to earn / give *Aura* points.\n"
        "👤 *Profile* — see your stats and Aura.\n\n"
        "*Topic tags used in the channel:*\n"
        "🏗️ Team Build-up  |  📐 Formation  |  🎁 Opening Packs\n"
        "🎯 Tactics  |  ⭐ Player Review  |  💰 Budget Build  |  🔧 General",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


# ── Profile ───────────────────────────────────────────────────────────────────

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    stats = get_user_stats(user.id)
    name  = user.full_name or "Unknown"
    await update.message.reply_text(
        f"👤 *{name}*\n"
        f"──────────────────\n"
        f"⚡ Aura:           *{stats['aura']}*\n"
        f"❓ Questions posted: *{stats['questions']}*\n"
        f"💬 Comments made:   *{stats['comments']}*\n\n"
        f"_Aura is earned when others upvote your comments._",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


# ── Ask Question (conversation) ───────────────────────────────────────────────

async def ask_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✏️ *What's your eFootball question?*\n\n"
        "Type it below (10–600 characters).\n"
        "Send /cancel to go back.",
        parse_mode="Markdown",
    )
    return WAITING_QUESTION


async def ask_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if len(text) < 10:
        await update.message.reply_text("⚠️ Too short — add more detail and try again.")
        return WAITING_QUESTION

    if len(text) > 600:
        await update.message.reply_text("⚠️ Too long (max 600 chars). Please shorten your question.")
        return WAITING_QUESTION

    user = update.effective_user
    qid  = save_question(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "Unknown",
        question=text,
    )

    await update.message.reply_text(
        f"✅ *Question submitted!*\n\n"
        f"🆔 ID: `#{qid}`\n"
        f"⏳ Pending admin review — you'll be notified once it's posted.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )

    # Notify admin
    user_tag = f" (@{user.username})" if user.username else ""
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🔔 *New Question — #{qid}*\n\n"
            f"👤 *From:* {user.full_name}{user_tag}\n"
            f"🆔 *User ID:* `{user.id}`\n\n"
            f"❓ *Question:*\n{text}"
        ),
        reply_markup=review_keyboard(qid),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── Add Comment (conversation) ────────────────────────────────────────────────

async def comment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    question_id = int(query.data.split("_", 1)[1])
    row = get_question(question_id)
    if not row or row["status"] != "approved":
        await query.answer("⚠️ Question not found or not approved.", show_alert=True)
        return ConversationHandler.END

    context.user_data["comment_qid"] = question_id
    await query.message.reply_text(
        f"💬 *Adding comment to Question #{question_id}*\n\n"
        f"Type your comment below (3–500 characters).\n"
        f"Send /cancel to go back.",
        parse_mode="Markdown",
    )
    return WAITING_COMMENT


async def reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply to a specific comment — treated as a regular comment for simplicity."""
    query = update.callback_query
    await query.answer()

    _, cid, qid, page = query.data.split("_")
    question_id = int(qid)
    row = get_question(question_id)
    if not row or row["status"] != "approved":
        await query.answer("⚠️ Question not found.", show_alert=True)
        return ConversationHandler.END

    context.user_data["comment_qid"] = question_id
    await query.message.reply_text(
        f"↩️ *Replying to a comment on Question #{question_id}*\n\n"
        f"Type your reply below (3–500 characters).\n"
        f"Send /cancel to go back.",
        parse_mode="Markdown",
    )
    return WAITING_COMMENT


async def comment_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text        = update.message.text.strip()
    question_id = context.user_data.get("comment_qid")

    if not question_id:
        await update.message.reply_text("⚠️ Something went wrong. Please try again.", reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    if len(text) < 3:
        await update.message.reply_text("⚠️ Too short. Try again.")
        return WAITING_COMMENT

    if len(text) > 500:
        await update.message.reply_text("⚠️ Too long (max 500 chars). Please shorten.")
        return WAITING_COMMENT

    user = update.effective_user
    save_comment(
        question_id=question_id,
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "Unknown",
        comment=text,
    )

    # Update the channel post button count
    await update_channel_button(context, question_id)

    # Notify question author
    row = get_question(question_id)
    if row and row["user_id"] != user.id:
        try:
            await context.bot.send_message(
                chat_id=row["user_id"],
                text=(
                    f"💬 *New comment on your Question #{question_id}!*\n\n"
                    f"❓ {row['question']}\n\n"
                    f"👤 {user.full_name}: {text}"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    count = get_comment_count(question_id)
    bot_link = f"https://t.me/{context.bot.username}?start=c_{question_id}"
    await update.message.reply_text(
        f"✅ *Comment posted!*\n\n"
        f"[View all {count} comment{'s' if count != 1 else ''}]({bot_link})",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


# ── Inline callbacks ──────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    # No-op button (page indicator)
    if data == "noop":
        await query.answer()
        return

    # ── View / navigate comments ──
    if data.startswith("vc_"):
        await query.answer()
        _, qid, page = data.split("_")
        text, keyboard = build_comments_view(int(qid), int(page), context.bot.username)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        return

    # ── Vote up ──
    if data.startswith("up_"):
        _, cid, qid, page = data.split("_")
        likes, dislikes = vote_comment(int(cid), query.from_user.id, "up")
        await query.answer(f"👍 {likes}")
        text, keyboard = build_comments_view(int(qid), int(page), context.bot.username)
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            pass
        return

    # ── Vote down ──
    if data.startswith("dn_"):
        _, cid, qid, page = data.split("_")
        likes, dislikes = vote_comment(int(cid), query.from_user.id, "down")
        await query.answer(f"👎 {dislikes}")
        text, keyboard = build_comments_view(int(qid), int(page), context.bot.username)
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            pass
        return

    # ── Admin: show tag picker ──
    if data.startswith("tag_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("⛔ Not authorized.", show_alert=True)
            return
        await query.answer()
        question_id = int(data.split("_", 1)[1])
        row = get_question(question_id)
        if not row:
            await query.edit_message_text("⚠️ Question not found.")
            return
        if row["status"] != "pending":
            await query.edit_message_text(f"⚠️ Already {row['status']}.")
            return
        await query.edit_message_text(
            f"🏷️ *Select tag for Question #{question_id}*\n\n"
            f"👤 {row['full_name']}\n"
            f"❓ {row['question']}\n\n"
            f"Choose the best topic:",
            reply_markup=tag_selection_keyboard(question_id),
            parse_mode="Markdown",
        )
        return

    # ── Admin: set tag & approve ──
    if data.startswith("settag_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("⛔ Not authorized.", show_alert=True)
            return
        await query.answer()
        _, question_id, tag_key = data.split("_", 2)
        question_id = int(question_id)
        row = get_question(question_id)
        if not row:
            await query.edit_message_text("⚠️ Question not found.")
            return
        if row["status"] != "pending":
            await query.edit_message_text(f"⚠️ Already {row['status']}.")
            return

        tag_label   = TAGS.get(tag_key, "🔧 General")
        tag_hashtag = "#" + tag_key
        update_status(question_id, "approved", tag_key)

        # Post to channel
        channel_text = (
            f"{tag_label}\n\n"
            f"❓ *eFootball Question #{question_id}*\n\n"
            f"{row['question']}\n\n"
            f"{tag_hashtag}"
        )
        bot_link = f"https://t.me/{context.bot.username}?start=c_{question_id}"
        msg = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=channel_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 View / Add Comments (0)", url=bot_link)
            ]]),
        )
        set_channel_msg_id(question_id, msg.message_id)

        # Notify question author
        try:
            await context.bot.send_message(
                chat_id=row["user_id"],
                text=(
                    f"🎉 *Your question was approved and posted!*\n\n"
                    f"🏷️ Tag: {tag_label}\n"
                    f"❓ {row['question']}\n\n"
                    f"[View comments]({bot_link})"
                ),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception:
            pass

        await query.edit_message_text(
            f"✅ *Approved & Posted — #{question_id}*\n\n"
            f"🏷️ {tag_label}\n"
            f"👤 {row['full_name']}\n"
            f"❓ {row['question']}\n\n"
            f"📢 Posted to channel.",
            parse_mode="Markdown",
        )
        return

    # ── Admin: reject ──
    if data.startswith("reject_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("⛔ Not authorized.", show_alert=True)
            return
        await query.answer()
        question_id = int(data.split("_", 1)[1])
        row = get_question(question_id)
        if not row:
            await query.edit_message_text("⚠️ Question not found.")
            return
        if row["status"] != "pending":
            await query.edit_message_text(f"⚠️ Already {row['status']}.")
            return
        update_status(question_id, "rejected")
        try:
            await context.bot.send_message(
                chat_id=row["user_id"],
                text=(
                    f"❌ *Your question wasn't approved this time.*\n\n"
                    f"❓ {row['question']}\n\n"
                    f"Feel free to rephrase and submit again!"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await query.edit_message_text(
            f"❌ *Rejected — #{question_id}*\n\n"
            f"👤 {row['full_name']}\n"
            f"❓ {row['question']}",
            parse_mode="Markdown",
        )
        return

    await query.answer()


# ── Admin: stats ──────────────────────────────────────────────────────────────

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    data     = get_stats()
    pending  = data.get("pending",  0)
    approved = data.get("approved", 0)
    rejected = data.get("rejected", 0)
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"⏳ Pending:  {pending}\n"
        f"✅ Approved: {approved}\n"
        f"❌ Rejected: {rejected}\n"
        f"──────────────\n"
        f"📝 Total:    {pending + approved + rejected}",
        parse_mode="Markdown",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler (question submission + comment submission)
    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text(["✏️ Ask Question"]), ask_start),
            CallbackQueryHandler(comment_start, pattern=r"^ac_\d+$"),
            CallbackQueryHandler(reply_start,   pattern=r"^rp_\d+_\d+_\d+$"),
        ],
        states={
            WAITING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_receive)],
            WAITING_COMMENT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, comment_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("stats",   stats))

    # Reply keyboard shortcuts
    app.add_handler(MessageHandler(filters.Text(["👤 Profile"]),  profile_command))
    app.add_handler(MessageHandler(filters.Text(["ℹ️ Help"]),     help_command))

    # Inline callback (view, vote, admin approve/reject)
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("eFootball bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

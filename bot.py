import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import ADMIN_ID, BOT_TOKEN, CHANNEL_ID
from database import (
    get_comments,
    get_question,
    get_stats,
    init_db,
    save_comment,
    save_question,
    update_status,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tags the admin can assign when approving a question
# ---------------------------------------------------------------------------
TAGS = {
    "teambuildup": "🏗️ Team Build-up",
    "formation":   "📐 Formation",
    "packs":       "🎁 Opening Packs",
    "tactics":     "🎯 Tactics",
    "player":      "⭐ Player Review",
    "budget":      "💰 Budget Build",
    "general":     "🔧 General",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def tag_selection_keyboard(question_id: int) -> InlineKeyboardMarkup:
    """Build the tag selection keyboard shown to the admin."""
    buttons = []
    row = []
    for key, label in TAGS.items():
        row.append(InlineKeyboardButton(label, callback_data=f"settag_{question_id}_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # Cancel / back to reject
    buttons.append([InlineKeyboardButton("❌ Reject Instead", callback_data=f"reject_{question_id}")])
    return InlineKeyboardMarkup(buttons)


def review_keyboard(question_id: int) -> InlineKeyboardMarkup:
    """Initial keyboard shown to admin for a new question."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏷️ Tag & Approve", callback_data=f"tag_{question_id}"),
        InlineKeyboardButton("❌ Reject",         callback_data=f"reject_{question_id}"),
    ]])


# ---------------------------------------------------------------------------
# User commands
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to the eFootball Q&A Bot!*\n\n"
        "Ask anything about eFootball — team building, formations, packs, and more.\n\n"
        "📌 *Commands:*\n"
        "/ask <your question> — submit a question\n"
        "/comment <question ID> <your comment> — comment on a question\n"
        "/comments <question ID> — view all comments on a question\n"
        "/help — show this guide",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use this bot:*\n\n"
        "*Submit a question:*\n"
        "`/ask What's the best formation for counter-attack?`\n\n"
        "*Comment on a question:*\n"
        "`/comment 5 I use 4-3-3 and it works great!`\n\n"
        "*See comments on a question:*\n"
        "`/comments 5`\n\n"
        "✅ Approved questions are posted to the channel with a topic tag.\n"
        "💬 Anyone can comment on any approved question.\n\n"
        "*Tags used in the channel:*\n"
        "🏗️ Team Build-up  |  📐 Formation\n"
        "🎁 Opening Packs  |  🎯 Tactics\n"
        "⭐ Player Review   |  💰 Budget Build  |  🔧 General",
        parse_mode="Markdown",
    )


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❓ Write your question after /ask\n\n"
            "Example:\n`/ask What's the best 4-3-3 pressing setup in eFootball 2025?`",
            parse_mode="Markdown",
        )
        return

    question_text = " ".join(context.args).strip()

    if len(question_text) < 10:
        await update.message.reply_text("⚠️ Your question is too short. Please add more detail.")
        return

    if len(question_text) > 600:
        await update.message.reply_text("⚠️ Max 600 characters. Please shorten your question.")
        return

    user = update.effective_user
    question_id = save_question(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "Unknown",
        question=question_text,
    )

    await update.message.reply_text(
        f"✅ *Question submitted!*\n\n"
        f"🆔 Question ID: `#{question_id}`\n"
        f"⏳ Pending admin review — you'll be notified once it's posted.",
        parse_mode="Markdown",
    )

    # Notify admin
    user_tag = f" (@{user.username})" if user.username else ""
    admin_text = (
        f"🔔 *New Question — #{question_id}*\n\n"
        f"👤 *From:* {user.full_name}{user_tag}\n"
        f"🆔 *User ID:* `{user.id}`\n\n"
        f"❓ *Question:*\n{question_text}"
    )
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_text,
        reply_markup=review_keyboard(question_id),
        parse_mode="Markdown",
    )


async def comment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /comment <question_id> <your comment>"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "💬 Usage: `/comment <question ID> <your comment>`\n\n"
            "Example: `/comment 3 I use 4-2-3-1 and it works!`",
            parse_mode="Markdown",
        )
        return

    raw_id = context.args[0]
    if not raw_id.isdigit():
        await update.message.reply_text("⚠️ The question ID must be a number. Example: `/comment 3 your text`", parse_mode="Markdown")
        return

    question_id = int(raw_id)
    comment_text = " ".join(context.args[1:]).strip()

    if len(comment_text) < 3:
        await update.message.reply_text("⚠️ Comment is too short.")
        return

    if len(comment_text) > 500:
        await update.message.reply_text("⚠️ Comment is too long (max 500 characters).")
        return

    row = get_question(question_id)
    if not row:
        await update.message.reply_text(f"⚠️ Question #{question_id} does not exist.")
        return

    # row: (id, user_id, username, full_name, question, status, tag, created_at, answered_at)
    _, q_user_id, _, _, question_text, status, tag, *_ = row

    if status != "approved":
        await update.message.reply_text(
            f"⚠️ You can only comment on approved questions. Question #{question_id} has not been approved yet."
        )
        return

    user = update.effective_user
    save_comment(
        question_id=question_id,
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "Unknown",
        comment=comment_text,
    )

    await update.message.reply_text(
        f"✅ *Comment posted on Question #{question_id}!*\n\n"
        f"Use /comments {question_id} to see all comments.",
        parse_mode="Markdown",
    )

    # Notify the question author (if not commenting on their own question)
    if user.id != q_user_id:
        try:
            await context.bot.send_message(
                chat_id=q_user_id,
                text=(
                    f"💬 *Someone commented on your question #{question_id}!*\n\n"
                    f"❓ *Question:* {question_text}\n\n"
                    f"💬 *Comment by {user.full_name}:*\n{comment_text}\n\n"
                    f"Use /comments {question_id} to see all comments."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass  # user may have blocked the bot

    # Also notify admin of the comment
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"💬 *New comment on Question #{question_id}*\n\n"
                f"👤 By: {user.full_name}{' (@' + user.username + ')' if user.username else ''}\n"
                f"❓ Question: {question_text}\n\n"
                f"💬 {comment_text}"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def comments_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /comments <question_id>"""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "💬 Usage: `/comments <question ID>`\n\nExample: `/comments 3`",
            parse_mode="Markdown",
        )
        return

    question_id = int(context.args[0])
    row = get_question(question_id)
    if not row:
        await update.message.reply_text(f"⚠️ Question #{question_id} not found.")
        return

    _, _, _, _, question_text, status, tag, *_ = row

    if status != "approved":
        await update.message.reply_text(f"⚠️ Question #{question_id} has not been approved yet.")
        return

    comments = get_comments(question_id)
    tag_label = TAGS.get(tag, "")

    header = (
        f"❓ *Question #{question_id}*"
        + (f"  {tag_label}" if tag_label else "")
        + f"\n{question_text}\n"
        + "─" * 30
    )

    if not comments:
        await update.message.reply_text(
            header + "\n\n💬 No comments yet. Be the first!\n\n"
            f"Use: `/comment {question_id} your comment`",
            parse_mode="Markdown",
        )
        return

    lines = [header, ""]
    for i, (full_name, username, comment, created_at) in enumerate(comments, 1):
        name_tag = f" (@{username})" if username else ""
        lines.append(f"*{i}. {full_name}{name_tag}*\n{comment}\n")

    lines.append(f"─" * 30)
    lines.append(f"💬 To comment: `/comment {question_id} your text`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Admin: approve/reject + tag selection callbacks
# ---------------------------------------------------------------------------

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ You are not authorized.", show_alert=True)
        return

    await query.answer()
    data = query.data

    # ── Step 1: admin clicks "Tag & Approve" → show tag menu ──
    if data.startswith("tag_"):
        question_id = int(data.split("_", 1)[1])
        row = get_question(question_id)
        if not row:
            await query.edit_message_text("⚠️ Question not found.")
            return

        _, _, _, full_name, question_text, status, *_ = row
        if status != "pending":
            await query.edit_message_text(f"⚠️ Question #{question_id} already {status}.")
            return

        await query.edit_message_text(
            f"🏷️ *Select a tag for Question #{question_id}*\n\n"
            f"👤 {full_name}\n"
            f"❓ {question_text}\n\n"
            f"Choose the topic that best fits this question:",
            reply_markup=tag_selection_keyboard(question_id),
            parse_mode="Markdown",
        )

    # ── Step 2: admin picks a tag → approve + post to channel ──
    elif data.startswith("settag_"):
        parts = data.split("_", 2)
        question_id = int(parts[1])
        tag_key = parts[2]

        row = get_question(question_id)
        if not row:
            await query.edit_message_text("⚠️ Question not found.")
            return

        _, user_id, _, full_name, question_text, status, *_ = row
        if status != "pending":
            await query.edit_message_text(f"⚠️ Question #{question_id} already {status}.")
            return

        tag_label = TAGS.get(tag_key, "🔧 General")
        update_status(question_id, "approved", tag_key)

        # Post to channel
        channel_post = (
            f"{tag_label}\n\n"
            f"❓ *eFootball Question #{question_id}*\n\n"
            f"{question_text}\n\n"
            f"💬 Comment via the bot: /comment {question_id} your answer"
        )
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=channel_post,
            parse_mode="Markdown",
        )

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 *Your question was approved and posted!*\n\n"
                    f"🏷️ Tag: {tag_label}\n"
                    f"❓ {question_text}\n\n"
                    f"People can now comment on it using:\n"
                    f"`/comment {question_id} their answer`"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

        await query.edit_message_text(
            f"✅ *Approved & Posted — #{question_id}*\n\n"
            f"🏷️ Tag: {tag_label}\n"
            f"👤 {full_name}\n"
            f"❓ {question_text}\n\n"
            f"📢 Posted to channel!",
            parse_mode="Markdown",
        )

    # ── Reject ──
    elif data.startswith("reject_"):
        question_id = int(data.split("_", 1)[1])
        row = get_question(question_id)
        if not row:
            await query.edit_message_text("⚠️ Question not found.")
            return

        _, user_id, _, full_name, question_text, status, *_ = row
        if status != "pending":
            await query.edit_message_text(f"⚠️ Question #{question_id} already {status}.")
            return

        update_status(question_id, "rejected")

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"❌ *Your question was not approved this time.*\n\n"
                    f"❓ {question_text}\n\n"
                    f"Feel free to rephrase and submit again!"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

        await query.edit_message_text(
            f"❌ *Rejected — #{question_id}*\n\n"
            f"👤 {full_name}\n"
            f"❓ {question_text}",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Admin: stats
# ---------------------------------------------------------------------------

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    data = get_stats()
    pending  = data.get("pending", 0)
    approved = data.get("approved", 0)
    rejected = data.get("rejected", 0)
    total    = pending + approved + rejected

    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"⏳ Pending:  {pending}\n"
        f"✅ Approved: {approved}\n"
        f"❌ Rejected: {rejected}\n"
        f"──────────────\n"
        f"📝 Total:    {total}",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_command))
    app.add_handler(CommandHandler("ask",      ask))
    app.add_handler(CommandHandler("comment",  comment_command))
    app.add_handler(CommandHandler("comments", comments_command))
    app.add_handler(CommandHandler("stats",    stats))
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("eFootball bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

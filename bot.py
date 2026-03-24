import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import ADMIN_ID, BOT_TOKEN, CHANNEL_ID
from database import get_question, get_stats, init_db, save_question, update_status

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# User commands
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to the eFootball Team Building Bot!*\n\n"
        "Got a question about squad building, formations, player picks, or tactics?\n"
        "Submit it with /ask and the admin will review it.\n\n"
        "✅ Approved questions get posted to the channel!\n\n"
        "📌 Commands:\n"
        "/ask <your question> — submit a question\n"
        "/help — show usage guide",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How it works:*\n\n"
        "1️⃣ Send /ask followed by your question\n"
        "2️⃣ The admin reviews it\n"
        "3️⃣ If approved, it's posted to the channel automatically\n\n"
        "*Topics we love:*\n"
        "⚽ Team building & squad tips\n"
        "🏆 Best formations & roles\n"
        "💡 Player recommendations\n"
        "🎯 Skill moves & manager tactics\n"
        "📊 Coin & GP management\n\n"
        "*Example:*\n"
        "`/ask What's the best 4-3-3 pressing setup in eFootball 2025?`",
        parse_mode="Markdown",
    )


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❓ Please write your question after /ask\n\n"
            "Example:\n`/ask What's the best budget team for Division 1?`",
            parse_mode="Markdown",
        )
        return

    question_text = " ".join(context.args).strip()

    if len(question_text) < 10:
        await update.message.reply_text(
            "⚠️ Your question is too short. Please add more detail."
        )
        return

    if len(question_text) > 600:
        await update.message.reply_text(
            "⚠️ Your question is too long (max 600 characters). Please shorten it."
        )
        return

    user = update.effective_user
    question_id = save_question(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "Unknown",
        question=question_text,
    )

    # Confirm to user
    await update.message.reply_text(
        f"✅ *Question submitted!*\n\n"
        f"🆔 Question ID: `#{question_id}`\n"
        f"⏳ Pending admin review — you'll be notified once it's approved or rejected.",
        parse_mode="Markdown",
    )

    # Notify admin with approve/reject buttons
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{question_id}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{question_id}"),
        ]
    ])

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
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Admin: approve / reject callback
# ---------------------------------------------------------------------------

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ You are not authorized.", show_alert=True)
        return

    await query.answer()

    action, raw_id = query.data.split("_", 1)
    question_id = int(raw_id)

    row = get_question(question_id)
    if not row:
        await query.edit_message_text("⚠️ Question not found in database.")
        return

    # row: (id, user_id, username, full_name, question, status, created_at, answered_at)
    _, user_id, _, full_name, question_text, status, *_ = row

    if status != "pending":
        await query.edit_message_text(
            f"⚠️ Question #{question_id} was already *{status}*.",
            parse_mode="Markdown",
        )
        return

    if action == "approve":
        update_status(question_id, "approved")

        # Post to channel
        channel_post = (
            f"❓ *eFootball Team Building Q&A*\n\n"
            f"{question_text}\n\n"
            f"💬 Drop your tips and strategies in the comments!"
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
                    f"🎉 *Your question was approved and posted to the channel!*\n\n"
                    f"❓ {question_text}"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass  # user may have blocked the bot

        await query.edit_message_text(
            f"✅ *Approved & posted — #{question_id}*\n\n"
            f"👤 {full_name}\n"
            f"❓ {question_text}",
            parse_mode="Markdown",
        )

    elif action == "reject":
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
# Admin: stats command
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_command))
    app.add_handler(CommandHandler("ask",   ask))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("eFootball bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

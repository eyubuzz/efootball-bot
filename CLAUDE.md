# eFootball Q&A Telegram Bot

## Project Overview
This is an eFootball Q&A Telegram bot that allows users to submit questions which get reviewed and posted to a Telegram channel.

## Tech Stack
- **Runtime:** Node.js
- **Telegram library:** node-telegram-bot-api
- **Database:** Supabase
- **Hosting:** Railway (bot), Netlify (admin panel)

## Database
**Supabase** — table: `questions`

| Column | Description |
|--------|-------------|
| `id` | Primary key |
| `user_id` | Telegram user ID |
| `username` | Telegram username |
| `question` | Question text |
| `tag` | Topic tag |
| `status` | Moderation status |
| `answer` | Admin answer |
| `created_at` | Submission timestamp |

## Tags
- `tactics`
- `myclub`
- `gameplay`

## Status Values
- `pending` — awaiting admin review
- `approved` — approved and posted to channel
- `denied` — rejected by admin

## Environment Variables
| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/service key |
| `CHANNEL_ID` | Telegram channel ID to post approved answers |
| `ADMIN_CHAT_ID` | Admin's Telegram chat ID for alerts |

## Architecture
- **Bot** — hosted on Railway, handles all Telegram interactions
- **Admin panel** — HTML file hosted on Netlify, allows admin to approve/deny/AI-draft answers
- Approved answers are posted automatically to the Telegram channel

## Features Already Built
- `/start` with tag picker
- Question submission saved to Supabase
- Admin approve / deny / AI-draft answers on Netlify panel
- Approved answers posted to Telegram channel
- 3 topic tags: tactics, myclub, gameplay

## Features Still To Add
1. Notify user when their question is approved
2. Alert admin via DM when a new question arrives
3. Daily limit of 3 questions per user
4. Spam and duplicate question protection
5. `/mystatus` command — user views their submitted questions and statuses
6. `/search` command — search approved Q&As by keyword
7. `/cancel` command — cancel mid-submission flow
8. Weekly Sunday digest — auto-post top Q&As to channel
9. Amharic and English language support — detect language and respond accordingly

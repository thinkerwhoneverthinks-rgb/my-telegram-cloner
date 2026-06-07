import os
import re
import json
import asyncio
import logging
import random
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
from aiohttp import web

# --- CONFIGURATION FROM ENVIRONMENT VARIABLES ---
API_ID_RAW = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

if not API_ID_RAW or not API_HASH:
    raise ValueError(
        "❌ CRITICAL CONFIGURATION ERROR:\n"
        "API_ID or API_HASH environment variables are missing.\n"
        "Please add them under the 'Environment' tab in your Render service dashboard."
    )

API_ID = int(API_ID_RAW)
API_HASH = str(API_HASH)

CONFIG_FILE = 'bot_config.json'
PROGRESS_FILE = 'clone_progress.json'
MAX_RETRIES = 3
BASE_DELAY_MIN = 2.5
BASE_DELAY_MAX = 5.5

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('history_cloner_session', API_ID, API_HASH)

bot_data = {
    "dest_link": None,
    "tasks": {},
    "is_running": False
}

# --- PERSISTENCE UTILITIES ---
def load_config():
    global bot_data
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                bot_data["dest_link"] = saved.get("dest_link")
                saved_tasks = saved.get("tasks", {})
                bot_data["tasks"] = {int(k): v for k, v in saved_tasks.items()}
                logger.info("Configuration loaded from file storage successfully.")
        except Exception as e:
            logger.error(f"Error loading persistent configuration: {e}")

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"dest_link": bot_data["dest_link"], "tasks": bot_data["tasks"]}, f)
    except Exception as e:
        logger.error(f"Error saving updated configuration: {e}")

def parse_telegram_link(link, is_destination=False):
    if not link: return None, None, None
    match = re.search(r't\.me/(?:c/)?([^/]+)/(\d+)(?:/(\d+))?', link)
    if not match: return None, None, None
    chat_identifier = match.group(1)
    val1 = int(match.group(2))
    val2 = int(match.group(3)) if match.group(3) else None

    if 't.me/c/' in link and not chat_identifier.startswith('-100'):
        try: chat_id = int('-100' + chat_identifier)
        except ValueError: chat_id = chat_identifier
    else:
        try: chat_id = int(chat_identifier)
        except ValueError: chat_id = chat_identifier

    if is_destination:
        return (chat_id, val1, val2) if val2 is not None else (chat_id, val1, None)
    else:
        return (chat_id, val1, val2) if val2 is not None else (chat_id, None, val1)

async def copy_with_retry(message, dest, dest_topic_id=None):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if dest_topic_id: 
                await client.send_message(dest, message, reply_to=dest_topic_id)
            else: 
                await client.send_message(dest, message)
            return True
        except errors.FloodWaitError as e:
            logger.warning(f"FloodWait limits hit: Sleeping for {e.seconds}s")
            await asyncio.sleep(e.seconds + 2)
        except Exception as e:
            logger.error(f"Error transferring message ID {message.id}: {e}")
            if attempt < MAX_RETRIES: await asyncio.sleep(4)
    return False

# --- TELEGRAM COMMANDS INTERFACE ---

@client.on(events.NewMessage(pattern=r'^/start$', outgoing=True))
async def start_handler(event):
    status = "🟢 **Cloud Userbot Active & Online**\n\n"
    status += f"🎯 **Destination:** {bot_data['dest_link'] or '❌ Not Set'}\n\n"
    status += "📋 **Current Queue Mapping:**\n"
    
    for i in range(1, 6):
        task = bot_data["tasks"].get(i, {})
        t_status = "Ready" if "start" in task and "end" in task else "Not configured"
        m_status = "With header message" if task.get("msg") else "No custom message"
        status += f"▪️ **Task {i}:** {t_status} ({m_status})\n"
        
    status += "\n💡 *Commands available: /setdest, /task1-5, /mes1-5, /clear, and /done.*"
    await event.reply(status)

@client.on(events.NewMessage(pattern=r'^/setdest\s+(.+)$', outgoing=True))
async def set_dest_handler(event):
    link = event.pattern_match.group(1).strip()
    bot_data["dest_link"] = link
    save_config()
    await event.reply(f"🎯 **Destination target mapped & saved:**\n{link}")

@client.on(events.NewMessage(pattern=r'^/task([1-5])(?:\s+(.+))?$', outgoing=True))
async def tasks_handler(event):
    task_num = int(event.pattern_match.group(1))
    args = event.pattern_match.group(2)
    
    if not args:
        await event.reply(f"⚠️ **Usage:** `/task{task_num} [link/start-end]`\nExample: `/task1 https://t.me/c/3935930009/3-15`")
        return
        
    # Regex to capture the base URL and the start/end numbers
    match = re.search(r'^(.*(?:/))(\d+)-(\d+)$', args.strip())
    if not match:
        await event.reply(f"❌ **Error:** Invalid format. Provide link like `https://t.me/c/3935930009/3-15`.")
        return
        
    base_url = match.group(1)
    
    # Sort them just in case you accidentally write 15-3 instead of 3-15
    ids = sorted([int(match.group(2)), int(match.group(3))])
    
    start_link = f"{base_url}{ids[0]}"
    end_link = f"{base_url}{ids[1]}"
        
    if task_num not in bot_data["tasks"]:
        bot_data["tasks"][task_num] = {}
        
    bot_data["tasks"][task_num]["start"] = start_link
    bot_data["tasks"][task_num]["end"] = end_link
    save_config()
    await event.reply(f"✅ **Task {task_num} Configured:**\n🛫 Start: {start_link}\n🛬 End: {end_link}")

@client.on(events.NewMessage(pattern=r'^/mes([1-5])(?:\s+(.+))?$', outgoing=True))
async def message_handler(event):
    task_num = int(event.pattern_match.group(1))
    msg_text = event.pattern_match.group(2)
    
    if not msg_text:
        if task_num in bot_data["tasks"] and "msg" in bot_data["tasks"][task_num]:
            del bot_data["tasks"][task_num]["msg"]
            save_config()
            await event.reply(f"🗑️ Removed pre-task header message for **Task {task_num}**.")
        else:
            await event.reply(f"⚠️ **Usage:** `/mes{task_num} [Your custom header message text]`")
        return

    if task_num not in bot_data["tasks"]:
        bot_data["tasks"][task_num] = {}
        
    bot_data["tasks"][task_num]["msg"] = msg_text.strip()
    save_config()
    await event.reply(f"💬 **Header message linked to Task {task_num} (Sends BEFORE task):**\n\"{msg_text.strip()}\"")

@client.on(events.NewMessage(pattern=r'^/clear$', outgoing=True))
async def clear_handler(event):
    bot_data["tasks"] = {}
    save_config()
    await event.reply("🗑️ Queue wiped completely clean. Destination parameter remains locked and saved.")

@client.on(events.NewMessage(pattern=r'^/done$', outgoing=True))
async def done_handler(event):
    if bot_data["is_running"]:
        await event.reply("⚠️ A batch execution sequence is currently processing in the cloud container!")
        return

    if not bot_data["dest_link"]:
        await event.reply("❌ **Error:** No destination target configured. Use `/setdest [link]` first.")
        return

    active_tasks = {k: v for k, v in bot_data["tasks"].items() if "start" in v and "end" in v}
    if not active_tasks:
        await event.reply("❌ **Error:** No valid tasks configured in your deployment queue.")
        return

    bot_data["is_running"] = True
    status_msg = await event.reply("🚀 **Processing Queue Batch Sequence...** You can safely turn off your connection now.")
    
    dest_chat, dest_topic_id, _ = parse_telegram_link(bot_data["dest_link"], is_destination=True)
    task_summaries = []  # List to store our final output summaries
    
    try:
        for sorted_id in sorted(active_tasks.keys()):
            task = active_tasks[sorted_id]
            await status_msg.edit(f"⏳ **Executing Process Sequence {sorted_id}/{max(active_tasks.keys())}...**")
            
            src_chat, src_topic_id, start_id = parse_telegram_link(task["start"], is_destination=False)
            _, _, end_id = parse_telegram_link(task["end"], is_destination=False)
            
            if not src_chat or not start_id or not end_id or not dest_chat:
                await event.reply(f"❌ Core link parsing exception on **Task {sorted_id}**. Skipping partition.")
                continue

            # --- SENDS MESSAGE BEFORE THE TASK STARTS ---
            if "msg" in task:
                if dest_topic_id:
                    await client.send_message(dest_chat, task["msg"], reply_to=dest_topic_id)
                else:
                    await client.send_message(dest_chat, task["msg"])
                await asyncio.sleep(random.uniform(2.0, 4.0))

            iter_kwargs = {'entity': src_chat, 'min_id': start_id - 1, 'max_id': end_id + 1, 'reverse': True}
            if src_topic_id: iter_kwargs['reply_to'] = src_topic_id

            success_count, skip_count = 0, 0
            vid_count, file_count = 0, 0
            
            async for message in client.iter_messages(**iter_kwargs):
                if message is None or getattr(message, 'action', None) or getattr(message, '_empty', False) or (not message.text and not getattr(message, 'media', None)):
                    skip_count += 1
                    continue
                    
                if await copy_with_retry(message, dest_chat, dest_topic_id=dest_topic_id):
                    success_count += 1
                    
                    # --- COUNT VIDEOS AND FILES ---
                    # In Telethon, if it's a video, message.video is truthy.
                    if message.video:
                        vid_count += 1
                    # If it's a document (PDF, zip, etc.) but NOT a video
                    elif message.document:
                        file_count += 1
                        
                    await asyncio.sleep(random.uniform(BASE_DELAY_MIN, BASE_DELAY_MAX))
                else:
                    await event.reply(f"🛑 Execution structural failure. Target protection triggered at message: {message.id}")
                    bot_data["is_running"] = False
                    return
            
            await event.reply(f"✅ **Task {sorted_id} Sequence Concluded!**\nTransferred: {success_count}\nSkipped: {skip_count}")
            
            # --- BUILD SUMMARY FOR THIS TASK ---
            summary_chunk = ""
            if "msg" in task:
                summary_chunk += f"{task['msg']}\n"
            summary_chunk += f"{vid_count} vid {file_count} file"
            task_summaries.append(summary_chunk)
            
            # Substantial interval padding buffer between autonomous pipeline tasks
            await asyncio.sleep(random.uniform(10.0, 20.0))
            
        # --- SEND FINAL INDEX REPORT ONCE EVERYTHING IS DONE ---
        if task_summaries:
            final_report = "\n\n".join(task_summaries)
            if dest_topic_id:
                await client.send_message(dest_chat, final_report, reply_to=dest_topic_id)
            else:
                await client.send_message(dest_chat, final_report)

        await status_msg.edit("🏆 **Queue executed successfully!** Tasks cleared out.")
        bot_data["tasks"] = {}
        save_config()

    except Exception as e:
        await event.reply(f"⚠️ Thread error caught: `{e}`")
    finally:
        bot_data["is_running"] = False

# --- DUMMY RENDER APP PING SERVER ---
async def handle_health_check(request):
    return web.Response(text="Render Userbot container instance actively running.")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    load_config()
    await start_web_server()
    await client.start()
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

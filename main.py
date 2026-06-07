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
    "slots": {},
    "is_running": False,
    "is_paused": False
}

# --- PERSISTENCE UTILITIES ---
def load_config():
    global bot_data
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                bot_data["dest_link"] = saved.get("dest_link")
                saved_slots = saved.get("slots", {})
                # Ensure integer keys are maintained upon reading
                bot_data["slots"] = {int(k): v for k, v in saved_slots.items()}
                logger.info("Configuration loaded from file storage successfully.")
        except Exception as e:
            logger.error(f"Error loading persistent configuration: {e}")

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"dest_link": bot_data["dest_link"], "slots": bot_data["slots"]}, f)
    except Exception as e:
        logger.error(f"Error saving updated configuration: {e}")

def get_next_free_slot():
    slot = 1
    while slot in bot_data["slots"]:
        slot += 1
    return slot

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
                sent = await client.send_message(dest, message, reply_to=dest_topic_id)
            else: 
                sent = await client.send_message(dest, message)
            return sent
        except errors.FloodWaitError as e:
            logger.warning(f"FloodWait limits hit: Sleeping for {e.seconds}s")
            await asyncio.sleep(e.seconds + 2)
        except Exception as e:
            logger.error(f"Error transferring message ID {message.id}: {e}")
            if attempt < MAX_RETRIES: await asyncio.sleep(4)
    return None

# --- TELEGRAM COMMANDS INTERFACE ---

@client.on(events.NewMessage(pattern=r'^/start$', outgoing=True))
async def start_handler(event):
    status = "🟢 **Cloud Userbot Active & Online**\n\n"
    status += f"🎯 **Destination:** {bot_data['dest_link'] or '❌ Not Set'}\n\n"
    status += "📋 **Current Queue Mapping:**\n"
    
    if not bot_data["slots"]:
        status += "▪️ *No tasks or batches configured yet.*\n"
    else:
        for choice_id in sorted(bot_data["slots"].keys()):
            slot = bot_data["slots"][choice_id]
            s_type = slot.get("type", "Unknown").upper()
            m_status = "With header" if slot.get("msg") else "No custom header"
            status += f"▪️ **Slot {choice_id} [{s_type}]:** Configured ({m_status})\n"
            
    status += "\n💡 *Commands: /setdest, /task, /batch, /mesX, /mebX, /preview, /removeX, /pause, /resume, /delete taskX, /clear, and /done.*"
    await event.reply(status)

@client.on(events.NewMessage(pattern=r'^/setdest\s+(.+)$', outgoing=True))
async def set_dest_handler(event):
    link = event.pattern_match.group(1).strip()
    bot_data["dest_link"] = link
    save_config()
    await event.reply(f"🎯 **Destination target mapped & saved:**\n{link}")

@client.on(events.NewMessage(pattern=r'^/task(\d+)?(?:\s+(.+))?$', outgoing=True))
async def tasks_handler(event):
    slot_raw = event.pattern_match.group(1)
    args = event.pattern_match.group(2)
    
    is_auto = slot_raw is None
    slot_num = get_next_free_slot() if is_auto else int(slot_raw)
    
    if not args:
        await event.reply(f"⚠️ **Usage:** `/task{slot_raw or ''} [link/start-end]`")
        return
        
    match = re.search(r'^(.*(?:/))(\d+)-(\d+)$', args.strip())
    if not match:
        await event.reply(f"❌ **Error:** Invalid format. Provide range link like `.../3-15`.")
        return
        
    base_url = match.group(1)
    ids = sorted([int(match.group(2)), int(match.group(3))])
    
    # Initialize or clean slot tracking container
    bot_data["slots"][slot_num] = bot_data["slots"].get(slot_num, {})
    bot_data["slots"][slot_num].update({
        "type": "task",
        "start": f"{base_url}{ids[0]}",
        "end": f"{base_url}{ids[1]}",
        "sent_ids": bot_data["slots"][slot_num].get("sent_ids", [])
    })
    
    save_config()
    prefix = "✅ Auto-assigned to" if is_auto else "✅ Configured"
    await event.reply(f"{prefix} **Slot {slot_num} [BOUNDED TASK]**.")

@client.on(events.NewMessage(pattern=r'^/batch(\d+)?(?:\s+(.+))?$', outgoing=True))
async def batch_handler(event):
    slot_raw = event.pattern_match.group(1)
    args = event.pattern_match.group(2)
    
    is_auto = slot_raw is None
    slot_num = get_next_free_slot() if is_auto else int(slot_raw)
    
    if not args:
        await event.reply(f"⚠️ **Usage:** `/batch{slot_raw or ''} [starting-link]`")
        return
        
    bot_data["slots"][slot_num] = bot_data["slots"].get(slot_num, {})
    bot_data["slots"][slot_num].update({
        "type": "batch",
        "start": args.strip(),
        "sent_ids": bot_data["slots"][slot_num].get("sent_ids", [])
    })
    if "end" in bot_data["slots"][slot_num]:
        del bot_data["slots"][slot_num]["end"]
        
    save_config()
    prefix = "✅ Auto-assigned to" if is_auto else "✅ Configured"
    await event.reply(f"{prefix} **Slot {slot_num} [OPEN-ENDED BATCH]**.")

@client.on(events.NewMessage(pattern=r'^/(?:mes|meb)(\d+)(?:\s+(.+))?$', outgoing=True))
async def message_handler(event):
    slot_num = int(event.pattern_match.group(1))
    msg_text = event.pattern_match.group(2)
    
    if not msg_text:
        if slot_num in bot_data["slots"] and "msg" in bot_data["slots"][slot_num]:
            del bot_data["slots"][slot_num]["msg"]
            save_config()
            await event.reply(f"🗑️ Removed header message for **Slot {slot_num}**.")
        return

    if slot_num not in bot_data["slots"]:
        bot_data["slots"][slot_num] = {"sent_ids": []}
        
    bot_data["slots"][slot_num]["msg"] = msg_text.strip()
    save_config()
    await event.reply(f"💬 **Header linked to Slot {slot_num}.**")

@client.on(events.NewMessage(pattern=r'^/preview$', outgoing=True))
async def preview_handler(event):
    if not bot_data["slots"]:
        await event.reply("📋 **Queue Pipeline Preview:**\n*The operation deployment queue is currently completely empty.*")
        return
        
    preview_text = "👀 **Current Queue Pipeline Preview:**\n\n"
    for choice_id in sorted(bot_data["slots"].keys()):
        slot = bot_data["slots"][choice_id]
        s_type = slot.get("type", "unknown").upper()
        header = slot.get("msg", "*No header set for this slot*")
        
        preview_text += f"💬 Header {choice_id}: \"{header}\"\n"
        if s_type == "TASK":
            preview_text += f"▪️ Slot {choice_id} [{s_type}]:\n    🛫 Start: {slot.get('start')}\n    🛬 End: {slot.get('end')}\n\n"
        else:
            preview_text += f"▪️ Slot {choice_id} [{s_type}]: {slot.get('start')}\n\n"
            
    preview_text += "---\n🚀 *Ready to deploy? Send /done to start processing.*"
    await event.reply(preview_text)

@client.on(events.NewMessage(pattern=r'^/remove\s+(\d+)$', outgoing=True))
async def remove_handler(event):
    slot_num = int(event.pattern_match.group(1))
    if slot_num in bot_data["slots"]:
        del bot_data["slots"][slot_num]
        save_config()
        await event.reply(f"🗑️ **Slot {slot_num} Removed from Queue.** Links and headers deleted.")
    else:
        await event.reply(f"⚠️ **Error:** Slot {slot_num} is not present in the current local setup queue.")

@client.on(events.NewMessage(pattern=r'^/pause$', outgoing=True))
async def pause_handler(event):
    bot_data["is_paused"] = True
    await event.reply("⏸️ **Queue Paused.** The processing loop will freeze at the next element check.")

@client.on(events.NewMessage(pattern=r'^/resume$', outgoing=True))
async def resume_handler(event):
    bot_data["is_paused"] = False
    await event.reply("▶️ **Queue Resumed.** Continuing pipeline execution.")

@client.on(events.NewMessage(pattern=r'^/delete\s+(?:task|batch)(\d+)$', outgoing=True))
async def delete_handler(event):
    slot_num = int(event.pattern_match.group(1))
    if slot_num not in bot_data["slots"]:
        await event.reply(f"❌ **Error:** Slot {slot_num} is not configured or lacks cache history tracking tokens.")
        return
        
    slot = bot_data["slots"][slot_num]
    sent_ids = slot.get("sent_ids", [])
    
    if not sent_ids:
        del bot_data["slots"][slot_num]
        save_config()
        await event.reply(f"🗑️ Slot {slot_num} had no history footprint. Local parameters wiped clean.")
        return
        
    dest_chat, _, _ = parse_telegram_link(bot_data["dest_link"], is_destination=True)
    if not dest_chat:
        await event.reply("❌ **Error:** Destination target missing or completely unparseable.")
        return
        
    progress_wipe = await event.reply(f"🗑️ **Bulk Deleting Slot {slot_num} elements from target destination...**")
    
    deleted_count = 0
    # Process deletions efficiently via optimized array grouping (100 IDs per frame limit)
    for i in range(0, len(sent_ids), 100):
        chunk = sent_ids[i:i+100]
        try:
            await client.delete_messages(dest_chat, chunk)
            deleted_count += len(chunk)
        except Exception as e:
            logger.error(f"Error executing bulk deletion chunk payload: {e}")

    del bot_data["slots"][slot_num]
    save_config()
    await progress_wipe.edit(f"✅ **Wipe Concluded Successfully!** Removed {deleted_count} messages. Slot {slot_num} completely reset.")

@client.on(events.NewMessage(pattern=r'^/clear$', outgoing=True))
async def clear_handler(event):
    bot_data["slots"] = {}
    save_config()
    await event.reply("🗑️ Queue wiped completely clean. Destination parameters remain untouched.")

@client.on(events.NewMessage(pattern=r'^/done$', outgoing=True))
async def done_handler(event):
    if bot_data["is_running"]:
        await event.reply("⚠️ An execution sequence is actively processing in the cloud container container!")
        return

    if not bot_data["dest_link"]:
        await event.reply("❌ **Error:** Set target destination before triggering execution route.")
        return

    # Check for presence of any valid un-executed tasks
    active_initial_check = {k: v for k, v in bot_data["slots"].items() if "start" in v}
    if not active_initial_check:
        await event.reply("❌ **Error:** No active configuration payloads located inside the queue slots.")
        return

    bot_data["is_running"] = True
    bot_data["is_paused"] = False
    status_msg = await event.reply("🚀 **Initializing Queue Layout...** Running sequence operations.")
    
    dest_chat, dest_topic_id, _ = parse_telegram_link(bot_data["dest_link"], is_destination=True)
    task_summaries = []
    processed_slots = set()
    
    try:
        while True:
            # Re-scans configurations on-the-fly to allow real-time additions mid-run
            current_active_slots = {k: v for k, v in bot_data["slots"].items() if "start" in v and k not in processed_slots}
            if not current_active_slots:
                break # Exit when all sequential slots have concluded processing completely
                
            sorted_keys = sorted(current_active_slots.keys())
            sorted_id = sorted_keys[0]
            max_key = max(sorted(bot_data["slots"].keys()))
            
            slot = bot_data["slots"][sorted_id]
            slot_type = slot.get("type", "task")
            slot.setdefault("sent_ids", [])
            
            src_chat, src_topic_id, start_id = parse_telegram_link(slot["start"], is_destination=False)
            
            if slot_type == "task":
                _, _, end_id = parse_telegram_link(slot["end"], is_destination=False)
                iter_kwargs = {'entity': src_chat, 'min_id': start_id - 1, 'max_id': end_id + 1, 'reverse': True}
            else:
                end_id = None
                iter_kwargs = {'entity': src_chat, 'min_id': start_id - 1, 'reverse': True}
                
            if src_topic_id: iter_kwargs['reply_to'] = src_topic_id

            if not src_chat or not start_id or (slot_type == "task" and not end_id) or not dest_chat:
                await event.reply(f"❌ Core parsing failure on Slot {sorted_id}. Skipping sequence.")
                processed_slots.add(sorted_id)
                continue

            if "msg" in slot:
                header_msg = await client.send_message(dest_chat, slot["msg"], reply_to=dest_topic_id) if dest_topic_id else await client.send_message(dest_chat, slot["msg"])
                if header_msg:
                    slot["sent_ids"].append(header_msg.id)
                await asyncio.sleep(random.uniform(2.0, 4.0))

            success_count, skip_count = 0, 0
            vid_count, file_count = 0, 0
            
            async for message in client.iter_messages(**iter_kwargs):
                # --- LIVE PAUSE INTERCEPTOR CHECKPOINT ---
                if bot_data.get("is_paused", False):
                    await status_msg.edit(f"⏸️ **Pipeline Interrupted (Paused).**\n📍 Holding state at Message ID: `{message.id}`.")
                    while bot_data.get("is_paused", False):
                        await asyncio.sleep(1)
                        if sorted_id not in bot_data["slots"]: break
                        
                # Direct breakout safeguard if user deleted/removed the slot mid-run
                if sorted_id not in bot_data["slots"]:
                    await event.reply(f"🛑 Active Slot {sorted_id} configuration deleted. Killing stream loop execution.")
                    break

                if message is None or getattr(message, 'action', None) or getattr(message, '_empty', False) or (not message.text and not getattr(message, 'media', None)):
                    skip_count += 1
                    continue
                
                if slot_type == "task":
                    total_ids = max(1, end_id - start_id)
                    progress_pct = min(100, int(((message.id - start_id) / total_ids) * 100))
                    bar_filled = int(progress_pct / 10)
                    progress_bar = "█" * bar_filled + "░" * (10 - bar_filled)
                    
                    await status_msg.edit(
                        f"⏳ **Executing Slot Sequence {sorted_id}/{max_key}...** [Task]\n"
                        f"💬 Header: *\"{slot.get('msg', 'None')}\"*\n"
                        f"📊 Progress: `[{progress_bar}]` **{progress_pct}%**\n"
                        f"📍 Processing Message ID: `{message.id}` of `{end_id}`\n"
                        f"📈 Collected: {vid_count} Videos | {file_count} Files"
                    )
                else:
                    await status_msg.edit(
                        f"⏳ **Executing Slot Sequence {sorted_id}/{max_key}...** [Batch]\n"
                        f"💬 Header: *\"{slot.get('msg', 'None')}\"*\n"
                        f"📍 Scanning Open Forward ➡️ Currently at ID: `{message.id}`\n"
                        f"📈 Collected: {vid_count} Videos | {file_count} Files"
                    )
                    
                sent_node = await copy_with_retry(message, dest_chat, dest_topic_id=dest_topic_id)
                if sent_node:
                    slot["sent_ids"].append(sent_node.id)
                    save_config()
                    success_count += 1
                    if message.video: vid_count += 1
                    elif message.document: file_count += 1
                        
                    await asyncio.sleep(random.uniform(BASE_DELAY_MIN, BASE_DELAY_MAX))
                else:
                    await event.reply(f"🛑 Structural exception. Flow target protection triggered at ID: {message.id}")
                    bot_data["is_running"] = False
                    return
            
            # Post-slot processing check to ensure tracking metrics remain accurate
            if sorted_id in bot_data["slots"]:
                slot_title = f"Slot {sorted_id} ({slot_type.upper()})"
                await event.reply(
                    f"✅ **{slot_title} Concluded!**\n"
                    f"Transferred: {success_count} items\n"
                    f"Breakdown: {vid_count} videos, {file_count} files"
                )
                summary_chunk = f"**{slot.get('msg', f'Slot {sorted_id} Stream')}**\n{vid_count} vid {file_count} file"
                task_summaries.append(summary_chunk)
                await asyncio.sleep(random.uniform(10.0, 20.0))
            
            processed_slots.add(sorted_id)
            
        if task_summaries:
            final_report = "\n\n".join(task_summaries)
            await event.reply(f"📊 **Grand Final Execution Report:**\n\n{final_report}")

        await status_msg.edit("🏆 **Queue executed successfully!** All available operational blocks processed completely.")
        bot_data["slots"] = {}
        save_config()

    except Exception as e:
        await event.reply(f"⚠️ Critical framework exception caught: `{e}`")
    finally:
        bot_data["is_running"] = False
        bot_data["is_paused"] = False

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

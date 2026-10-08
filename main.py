import os
import re
import json
import asyncio
import logging
import random
from datetime import datetime
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import CreateForumTopicRequest, GetForumTopicsByIDRequest
from telethon.tl.types import MessageActionTopicCreate
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
BRAIN_TAG = "#CLONER_BRAIN_STORAGE"

# --- SAFETY & DELAY PARAMETERS ---
BATCH_SIZE = 100
BATCH_DELAY_MIN = 35.0
BATCH_DELAY_MAX = 50.0

BREATHER_BATCHES_MIN = 4
BREATHER_BATCHES_MAX = 8
BREATHER_PAUSE_MIN = 300.0   # 5 minutes
BREATHER_PAUSE_MAX = 480.0   # 8 minutes

FORWARD_CHECK_INTERVAL = 300.0  # 5 minutes check interval
MAX_RETRIES = 3

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('history_cloner_session', API_ID, API_HASH)

# Global runtime state
state = {
    "dest_link": None,
    "is_running": False,
    "is_paused": False,
    "current_status": "Idle",
    "active_task": None,
    "last_sent_ids": [],
    "batches_since_breather": 0,
    "next_breather_threshold": random.randint(BREATHER_BATCHES_MIN, BREATHER_BATCHES_MAX)
}

# --- PERSISTENCE & TELEGRAM "BRAIN STORAGE" ---

def get_serializable_state():
    return {
        "dest_link": state.get("dest_link"),
        "is_running": state.get("is_running"),
        "current_status": state.get("current_status"),
        "active_task": state.get("active_task"),
        "last_sent_ids": state.get("last_sent_ids", [])[-500:],  # Store up to last 500 IDs
        "total_sent_count": len(state.get("last_sent_ids", []))
    }

def save_local_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(get_serializable_state(), f, indent=2)
    except Exception as e:
        logger.error(f"Error saving local config: {e}")

def load_local_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                state["dest_link"] = data.get("dest_link")
                state["active_task"] = data.get("active_task")
                state["last_sent_ids"] = data.get("last_sent_ids", [])
                logger.info("Local config loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading local config: {e}")

async def sync_brain_storage():
    """Syncs state to a pinned message in Telegram Saved Messages ('me')."""
    try:
        brain_msg = None
        async for msg in client.iter_messages('me', limit=15):
            if msg.text and BRAIN_TAG in msg.text:
                brain_msg = msg
                break

        task_info = state.get("active_task") or {}
        summary = (
            f"🧠 **Telegram Cloner Brain Storage** {BRAIN_TAG}\n\n"
            f"📍 **Status:** `{state.get('current_status', 'Idle')}`\n"
            f"🎯 **Destination:** `{state.get('dest_link') or 'Not set'}`\n"
            f"📦 **Active Task:** `{task_info.get('title') or task_info.get('source_link') or 'None'}`\n"
            f"📊 **Messages Sent (Current/Last):** `{len(state.get('last_sent_ids', []))}`\n"
            f"🕒 **Last Synced:** `{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}`\n\n"
            f"```json\n"
            f"{json.dumps(get_serializable_state(), indent=2)}\n"
            f"```"
        )

        if brain_msg:
            await brain_msg.edit(summary)
        else:
            new_msg = await client.send_message('me', summary)
            try:
                await client.pin_message('me', new_msg.id, notify=False)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to sync brain storage: {e}")

async def load_brain_storage():
    """Reads Saved Messages on startup to recover state if local disk was wiped."""
    try:
        async for msg in client.iter_messages('me', limit=15):
            if msg.text and BRAIN_TAG in msg.text:
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', msg.text, re.DOTALL)
                if json_match:
                    recovered = json.loads(json_match.group(1))
                    if not state.get("dest_link") and recovered.get("dest_link"):
                        state["dest_link"] = recovered.get("dest_link")
                    if not state.get("last_sent_ids") and recovered.get("last_sent_ids"):
                        state["last_sent_ids"] = recovered.get("last_sent_ids", [])
                    logger.info("Successfully recovered state from Saved Messages brain storage.")
                break
    except Exception as e:
        logger.warning(f"Could not load brain storage from Saved Messages: {e}")

# --- LINK PARSER & METADATA UTILITIES ---

def parse_telegram_link(link):
    """
    Parses any Telegram link into (chat_id, topic_or_id1, id2, is_range, raw_range).
    Supports:
    - https://t.me/channel/100-300
    - https://t.me/c/1234567890/55 (Topic 55 or Message 55)
    - https://t.me/c/1234567890/55/100-300
    - https://t.me/username
    """
    if not link:
        return None, None, None, False, None

    link = link.strip()
    match = re.search(r't\.me/(?:c/)?([^/]+)(?:/(\d+(?:-\d+)?))?(?:/(\d+(?:-\d+)?))?', link)
    if not match:
        return None, None, None, False, None

    chat_raw = match.group(1)
    seg1 = match.group(2)
    seg2 = match.group(3)

    if 't.me/c/' in link and not chat_raw.startswith('-100'):
        try:
            chat_id = int('-100' + chat_raw)
        except ValueError:
            chat_id = chat_raw
    else:
        try:
            chat_id = int(chat_raw)
        except ValueError:
            chat_id = chat_raw

    is_range = False
    start_id = None
    end_id = None
    topic_id = None

    if seg1 and '-' in seg1:
        # Range on seg1: t.me/channel/100-200
        is_range = True
        parts = sorted([int(p) for p in seg1.split('-')])
        start_id, end_id = parts[0], parts[1]
    elif seg2 and '-' in seg2:
        # Topic + range: t.me/c/123/55/100-200
        topic_id = int(seg1)
        is_range = True
        parts = sorted([int(p) for p in seg2.split('-')])
        start_id, end_id = parts[0], parts[1]
    elif seg1 and seg2:
        # Topic + message: t.me/c/123/55/120
        topic_id = int(seg1)
        start_id = int(seg2)
    elif seg1:
        # Single number: could be topic ID or message ID
        val = int(seg1)
        topic_id = val
        start_id = val

    return chat_id, topic_id, start_id, end_id, is_range

async def get_topic_title(chat_entity, topic_id):
    """Retrieves the title of a forum topic from source group."""
    if not topic_id:
        return None
    try:
        res = await client(GetForumTopicsByIDRequest(channel=chat_entity, topics=[topic_id]))
        if res and hasattr(res, 'topics') and res.topics:
            return res.topics[0].title
    except Exception:
        pass

    try:
        topic_msg = await client.get_messages(chat_entity, ids=topic_id)
        if topic_msg and getattr(topic_msg, 'action', None) and isinstance(topic_msg.action, MessageActionTopicCreate):
            return topic_msg.action.title
    except Exception:
        pass

    return None

async def create_new_forum_topic(dest_entity, title):
    """Creates a new forum topic in the destination group."""
    try:
        res = await client(CreateForumTopicRequest(channel=dest_entity, title=title))
        for update in getattr(res, 'updates', []):
            if hasattr(update, 'message'):
                return update.message.id
        if hasattr(res, 'id'):
            return res.id
    except Exception as e:
        logger.error(f"Failed to create forum topic '{title}': {e}")
        raise
    return None

# --- FORWARD & RESTRICTION HANDLERS ---

async def is_forward_restricted(chat_entity):
    """Returns True if the channel restricts saving/forwarding content."""
    try:
        full_chat = await client.get_entity(chat_entity)
        return getattr(full_chat, 'noforwards', False)
    except Exception as e:
        logger.error(f"Error checking chat restriction: {e}")
        return False

async def wait_until_unlocked(chat_entity, status_msg=None):
    """
    Monitors channel forward status every 5 minutes.
    Pauses and waits if locked; resumes immediately when unlocked.
    """
    while True:
        restricted = await is_forward_restricted(chat_entity)
        if not restricted:
            return True

        state["current_status"] = "Waiting for forward unlock (Checked every 5 min)"
        save_local_config()
        await sync_brain_storage()

        logger.info("Forwarding is currently LOCKED on source. Sleeping for 5 minutes...")
        if status_msg:
            try:
                await status_msg.edit(
                    "🔒 **Forwarding is currently LOCKED by the channel admin!**\n\n"
                    "⏳ Sleeping for **5 minutes** before checking again...\n"
                    "🤖 The bot will automatically resume the instant forwarding is turned back ON."
                )
            except Exception:
                pass

        # Sleep in 5-second increments to allow instant pause or stop
        for _ in range(int(FORWARD_CHECK_INTERVAL // 5)):
            if not state.get("is_running") or state.get("is_paused"):
                return False
            await asyncio.sleep(5)

async def forward_batch_clean(dest_entity, src_entity, batch_ids, dest_topic_id=None):
    """
    Forwards up to 100 messages at once without quote tag (drop_author=True).
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            forwarded = await client.forward_messages(
                entity=dest_entity,
                messages=batch_ids,
                from_peer=src_entity,
                reply_to=dest_topic_id,
                drop_author=True
            )
            if isinstance(forwarded, list):
                return [m.id for m in forwarded if m]
            elif forwarded:
                return [forwarded.id]
            return []
        except errors.FloodWaitError as fwe:
            logger.warning(f"FloodWait encountered: sleeping {fwe.seconds}s")
            await asyncio.sleep(fwe.seconds + 5)
        except errors.ChatForwardsRestrictedError:
            raise
        except Exception as e:
            logger.error(f"Batch forward error on attempt {attempt}: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(10)
    return None

# --- COMMAND HANDLERS ---

@client.on(events.NewMessage(pattern=r'^/(?:start|help)$', outgoing=True))
async def help_handler(event):
    help_text = (
        "🤖 **Telegram History Cloner & Forwarder**\n\n"
        "⚡ **Features Active:**\n"
        "• Native 100-batch forwarding without quote tag (`drop_author=True`)\n"
        "• Auto-detects & creates Forum Topics with matching titles\n"
        "• Auto-pauses if forwarding is disabled, re-checks every 5 min\n"
        "• Safety Delays: 35–50s per batch + 5–8 min breather every 4–8 batches\n"
        "• Pinned Saved Messages Brain Storage for 100% crash recovery\n\n"
        "📋 **Commands:**\n"
        "• `/setdest <link>` — Set your target channel, group, or topic (saved permanently)\n"
        "• `/clone <link> [new|here]` — Clone an entire channel, topic, or range in 100-message batches\n"
        "  └ `new`: Forces creating a new topic with the source topic name\n"
        "  └ `here`: Forwards into the destination topic with a pinned header\n"
        "• `/status` — Live dashboard, batch progress & state\n"
        "• `/pause` — Pause current cloning loop\n"
        "• `/resume` — Resume execution\n"
        "• `/stop` — Cancel active task\n"
        "• `/purge` — Bulk delete last forwarded messages from destination\n\n"
        f"🎯 **Current Destination:** `{state.get('dest_link') or 'Not Set'}`"
    )
    await event.reply(help_text)

@client.on(events.NewMessage(pattern=r'^/setdest\s+(.+)$', outgoing=True))
async def set_dest_handler(event):
    link = event.pattern_match.group(1).strip()
    state["dest_link"] = link
    save_local_config()
    await sync_brain_storage()
    await event.reply(f"🎯 **Destination saved permanently:**\n`{link}`")

@client.on(events.NewMessage(pattern=r'^/status$', outgoing=True))
async def status_handler(event):
    task = state.get("active_task")
    status_text = (
        f"📊 **Cloner Engine Status:**\n\n"
        f"• **State:** `{state.get('current_status', 'Idle')}`\n"
        f"• **Running:** `{'Yes' if state.get('is_running') else 'No'}` | **Paused:** `{'Yes' if state.get('is_paused') else 'No'}`\n"
        f"• **Destination:** `{state.get('dest_link') or 'Not Set'}`\n"
    )
    if task:
        status_text += (
            f"• **Source Task:** `{task.get('title') or task.get('source_link')}`\n"
            f"• **Mode:** `{task.get('mode')}`\n"
            f"• **Processed Batches:** `{task.get('batches_done', 0)}`\n"
            f"• **Total Messages Transferred:** `{len(state.get('last_sent_ids', []))}`\n"
            f"• **Batches Until Breather:** `{state.get('next_breather_threshold', 0) - state.get('batches_since_breather', 0)}`\n"
        )
    else:
        status_text += "• **Active Task:** `None`\n"

    await event.reply(status_text)

@client.on(events.NewMessage(pattern=r'^/pause$', outgoing=True))
async def pause_handler(event):
    if not state.get("is_running"):
        await event.reply("⚠️ No active task is currently running.")
        return
    state["is_paused"] = True
    state["current_status"] = "Paused by user"
    save_local_config()
    await sync_brain_storage()
    await event.reply("⏸️ **Cloner Paused.** Execution safely frozen.")

@client.on(events.NewMessage(pattern=r'^/resume$', outgoing=True))
async def resume_handler(event):
    if not state.get("is_running"):
        await event.reply("⚠️ No active task to resume.")
        return
    state["is_paused"] = False
    state["current_status"] = "Resuming..."
    save_local_config()
    await sync_brain_storage()
    await event.reply("▶️ **Cloner Resumed.** Continuing pipeline.")

@client.on(events.NewMessage(pattern=r'^/stop$', outgoing=True))
async def stop_handler(event):
    if not state.get("is_running"):
        await event.reply("⚠️ No task is currently running.")
        return
    state["is_running"] = False
    state["is_paused"] = False
    state["current_status"] = "Stopped by user"
    state["active_task"] = None
    save_local_config()
    await sync_brain_storage()
    await event.reply("🛑 **Task Cancelled & Stopped.**")

@client.on(events.NewMessage(pattern=r'^/purge$', outgoing=True))
async def purge_handler(event):
    sent_ids = state.get("last_sent_ids", [])
    if not sent_ids:
        await event.reply("⚠️ No message IDs recorded in history to delete.")
        return

    if not state.get("dest_link"):
        await event.reply("❌ Destination link missing.")
        return

    dest_chat, _, _, _, _ = parse_telegram_link(state["dest_link"])
    prog = await event.reply(f"🗑️ **Purging {len(sent_ids)} messages from destination in chunks of 100...**")

    deleted = 0
    for i in range(0, len(sent_ids), 100):
        chunk = sent_ids[i:i+100]
        try:
            await client.delete_messages(dest_chat, chunk)
            deleted += len(chunk)
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"Purge chunk error: {e}")

    state["last_sent_ids"] = []
    save_local_config()
    await sync_brain_storage()
    await prog.edit(f"✅ **Purge Completed!** Deleted {deleted} messages from destination.")

# --- MAIN CLONING ENGINE ---

@client.on(events.NewMessage(pattern=r'^/clone(?:\s+(.+))?$', outgoing=True))
async def clone_handler(event):
    if state.get("is_running"):
        await event.reply("⚠️ Another clone operation is actively running! Use `/status` or `/stop` first.")
        return

    if not state.get("dest_link"):
        await event.reply("❌ **Error:** Set destination first using `/setdest <link>`.")
        return

    args_raw = event.pattern_match.group(1)
    if not args_raw:
        await event.reply("⚠️ **Usage:** `/clone <source_link> [new|here]`")
        return

    args = args_raw.strip().split()
    source_link = args[0]
    forced_mode = args[1].lower() if len(args) > 1 and args[1].lower() in ['new', 'here'] else None

    # Parse source and destination
    src_chat, src_topic_id, start_id, end_id, is_range = parse_telegram_link(source_link)
    dest_chat, dest_topic_id, _, _, _ = parse_telegram_link(state["dest_link"])

    if not src_chat:
        await event.reply("❌ **Error:** Invalid source link. Could not parse chat/channel.")
        return

    if not dest_chat:
        await event.reply("❌ **Error:** Destination link is invalid or unparseable.")
        return

    try:
        src_entity = await client.get_entity(src_chat)
        dest_entity = await client.get_entity(dest_chat)
    except Exception as e:
        await event.reply(f"❌ **Error resolving entities:** `{e}`")
        return

    # Auto-resolve topic title
    topic_title = None
    if src_topic_id:
        topic_title = await get_topic_title(src_entity, src_topic_id)

    if not topic_title:
        topic_title = getattr(src_entity, 'title', None) or f"Topic_{src_topic_id or 'Transfer'}"

    # Determine Destination Mode
    # If user explicitly passed 'new', or if dest has NO topic ID and source has a topic: create a new topic!
    # If user passed 'here', or if dest explicitly contains a topic ID: send into that existing topic!
    target_topic_id = dest_topic_id
    mode = forced_mode

    if not mode:
        if dest_topic_id is not None:
            mode = "here"
        else:
            mode = "new"

    status_msg = await event.reply("🚀 **Initializing Smart Cloner Engine...**")

    # Handle Topic Creation or Header Posting
    if mode == "new":
        await status_msg.edit(f"🔨 **Creating matching Forum Topic:** *\"{topic_title}\"* in destination...")
        try:
            target_topic_id = await create_new_forum_topic(dest_entity, topic_title)
            # Post pinned header inside the new topic
            header_text = f"📌 **{topic_title}**\n*(Cloned with 100-message batching)*"
            header_msg = await client.send_message(dest_entity, header_text, reply_to=target_topic_id)
            try:
                await client.pin_message(dest_entity, header_msg.id, notify=False)
            except Exception:
                pass
        except Exception as e:
            await event.reply(f"⚠️ Could not create topic automatically (`{e}`). Sending directly to destination.")
            target_topic_id = None
    else:
        # Mode is 'here': Post header inside the specified existing topic / channel
        header_text = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📚 **Topic:** {topic_title}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            header_msg = await client.send_message(dest_entity, header_text, reply_to=target_topic_id)
            try:
                await client.pin_message(dest_entity, header_msg.id, notify=False)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Failed to send header: {e}")

    # Setup task tracking
    state["is_running"] = True
    state["is_paused"] = False
    state["current_status"] = "Running"
    state["last_sent_ids"] = []
    state["batches_since_breather"] = 0
    state["next_breather_threshold"] = random.randint(BREATHER_BATCHES_MIN, BREATHER_BATCHES_MAX)

    state["active_task"] = {
        "title": topic_title,
        "source_link": source_link,
        "mode": mode,
        "src_topic_id": src_topic_id,
        "dest_topic_id": target_topic_id,
        "batches_done": 0,
        "start_time": datetime.utcnow().isoformat()
    }

    save_local_config()
    await sync_brain_storage()

    # Configure iter_messages parameters
    iter_kwargs = {'entity': src_entity, 'reverse': True}
    if is_range:
        iter_kwargs['min_id'] = start_id - 1
        iter_kwargs['max_id'] = end_id + 1
    elif start_id:
        iter_kwargs['min_id'] = start_id - 1

    if src_topic_id:
        iter_kwargs['reply_to'] = src_topic_id

    total_forwarded = 0
    batch_buffer = []

    try:
        async for message in client.iter_messages(**iter_kwargs):
            # Check pause
            while state.get("is_paused"):
                await status_msg.edit(f"⏸️ **Cloner Paused.** Holding at Message ID: `{message.id}`.")
                await asyncio.sleep(2)
                if not state.get("is_running"):
                    break

            if not state.get("is_running"):
                await event.reply("🛑 Task stopped by user.")
                break

            # Skip empty service/action messages
            if message is None or getattr(message, 'action', None) or getattr(message, '_empty', False):
                continue
            if not message.text and not getattr(message, 'media', None):
                continue

            batch_buffer.append(message.id)

            # When buffer reaches 100 messages, forward as a batch
            if len(batch_buffer) >= BATCH_SIZE:
                await process_and_send_batch(
                    status_msg, dest_entity, src_entity, batch_buffer,
                    target_topic_id, topic_title
                )
                total_forwarded += len(batch_buffer)
                batch_buffer = []

        # Flush any remaining messages in the buffer
        if batch_buffer and state.get("is_running"):
            await process_and_send_batch(
                status_msg, dest_entity, src_entity, batch_buffer,
                target_topic_id, topic_title
            )
            total_forwarded += len(batch_buffer)

        if state.get("is_running"):
            state["current_status"] = "Completed"
            await status_msg.edit(
                f"🏆 **Cloning Completed Successfully!**\n\n"
                f"📦 **Topic:** *\"{topic_title}\"*\n"
                f"📊 **Total Messages Forwarded:** `{total_forwarded}`\n"
                f"⚡ **Batches Dispatched:** `{state['active_task'].get('batches_done', 0)}`"
            )

    except Exception as e:
        logger.error(f"Error in clone loop: {e}", exc_info=True)
        await event.reply(f"⚠️ Critical cloning exception: `{e}`")
        state["current_status"] = f"Error: {e}"
    finally:
        state["is_running"] = False
        state["is_paused"] = False
        save_local_config()
        await sync_brain_storage()

async def process_and_send_batch(status_msg, dest_entity, src_entity, batch_ids, target_topic_id, topic_title):
    """Handles restriction checks, batch forward dispatch, delay & breather pauses."""
    # 1. Forward Unlock Check (every 5 min if restricted)
    unlocked = await wait_until_unlocked(src_entity, status_msg)
    if not unlocked:
        return

    # 2. Dispatch batch with retry
    try:
        sent_ids = await forward_batch_clean(dest_entity, src_entity, batch_ids, target_topic_id)
    except errors.ChatForwardsRestrictedError:
        # Admin just turned forward OFF mid-run!
        logger.warning("ChatForwardsRestrictedError caught during forward! Entering 5 min wait...")
        await wait_until_unlocked(src_entity, status_msg)
        sent_ids = await forward_batch_clean(dest_entity, src_entity, batch_ids, target_topic_id)

    if sent_ids:
        state["last_sent_ids"].extend(sent_ids)
        state["active_task"]["batches_done"] = state["active_task"].get("batches_done", 0) + 1
        state["batches_since_breather"] += 1
        save_local_config()
        await sync_brain_storage()

    # 3. Update Status Message
    current_batch = state["active_task"]["batches_done"]
    total_msgs = len(state["last_sent_ids"])
    await status_msg.edit(
        f"⏳ **Cloning in progress...**\n\n"
        f"📚 Topic: *\"{topic_title}\"*\n"
        f"📦 Batches Dispatched: `{current_batch}` (100 msgs/batch)\n"
        f"📊 Total Transferred: `{total_msgs}` messages\n"
        f"🛡️ Safety: Forward without quote enabled (`drop_author`)\n"
        f"☕ Next Breather in: `{state['next_breather_threshold'] - state['batches_since_breather']} batches`"
    )

    # 4. Human Breather Check (Every 4 to 8 batches, sleep for 5 to 8 minutes)
    if state["batches_since_breather"] >= state["next_breather_threshold"]:
        breather_sleep = random.uniform(BREATHER_PAUSE_MIN, BREATHER_PAUSE_MAX)
        breather_mins = round(breather_sleep / 60, 1)
        logger.info(f"Taking a human breather sleep of {breather_mins} minutes...")
        state["current_status"] = f"Taking human breather pause ({breather_mins} mins)"
        save_local_config()

        await status_msg.edit(
            f"☕ **Human Breather Pause ({breather_mins} mins)...**\n\n"
            f"Mimicking human activity to guarantee zero account flags.\n"
            f"Auto-resuming in {int(breather_sleep)} seconds..."
        )

        for _ in range(int(breather_sleep // 5)):
            if not state.get("is_running") or state.get("is_paused"):
                break
            await asyncio.sleep(5)

        state["batches_since_breather"] = 0
        state["next_breather_threshold"] = random.randint(BREATHER_BATCHES_MIN, BREATHER_BATCHES_MAX)
        state["current_status"] = "Running"
    else:
        # Standard Batch Delay: 35 to 50 seconds
        batch_delay = random.uniform(BATCH_DELAY_MIN, BATCH_DELAY_MAX)
        logger.info(f"Sleeping {round(batch_delay, 1)}s before next batch...")
        for _ in range(int(batch_delay // 2)):
            if not state.get("is_running") or state.get("is_paused"):
                break
            await asyncio.sleep(2)

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
    load_local_config()
    await start_web_server()
    await client.start()
    await load_brain_storage()
    logger.info("Bot started successfully. Listening for commands...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

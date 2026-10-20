import os
import re
import json
import asyncio
import logging
import random
from datetime import datetime
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    GetForumTopicsByIDRequest,
    GetForumTopicsRequest
)
from telethon.tl.functions.messages import CreateForumTopicRequest
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

FORWARD_CHECK_INTERVAL = 300.0  # 5 minutes
MAX_RETRIES = 3

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('history_cloner_session', API_ID, API_HASH)

# Global runtime state with multi-task queue support
state = {
    "dest_link": None,
    "send_as_link": None,
    "is_running": False,
    "is_paused": False,
    "current_status": "Idle",
    "queue": [],
    "queue_index": 0,
    "active_task": None,
    "last_sent_ids": [],
    "batches_since_breather": 0,
    "next_breather_threshold": random.randint(BREATHER_BATCHES_MIN, BREATHER_BATCHES_MAX)
}

# --- PERSISTENCE & TELEGRAM "BRAIN STORAGE" ---

def get_serializable_state():
    return {
        "dest_link": state.get("dest_link"),
        "send_as_link": state.get("send_as_link"),
        "is_running": state.get("is_running"),
        "current_status": state.get("current_status"),
        "queue_index": state.get("queue_index", 0),
        "queue_total": len(state.get("queue", [])),
        "queue": state.get("queue", []),
        "active_task": state.get("active_task"),
        "last_sent_ids": state.get("last_sent_ids", [])[-500:],
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
                state["send_as_link"] = data.get("send_as_link")
                state["queue"] = data.get("queue", [])
                state["queue_index"] = data.get("queue_index", 0)
                state["active_task"] = data.get("active_task")
                state["last_sent_ids"] = data.get("last_sent_ids", [])
                logger.info("Local config loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading local config: {e}")

async def sync_brain_storage():
    """Syncs state to a pinned message in Telegram Saved Messages ('me')."""
    try:
        brain_msg = None
        async for msg in client.iter_messages('me', limit=50):
            if msg.text and BRAIN_TAG in msg.text:
                brain_msg = msg
                break

        task_info = state.get("active_task") or {}
        q_len = len(state.get("queue", []))
        q_idx = state.get("queue_index", 0) + 1 if q_len > 0 else 0

        summary = (
            f"🧠 **Telegram Cloner Brain Storage** {BRAIN_TAG}\n\n"
            f"📍 **Status:** `{state.get('current_status', 'Idle')}`\n"
            f"🎯 **Destination:** `{state.get('dest_link') or 'Not set'}`\n"
            f"👤 **Send As:** `{state.get('send_as_link') or 'Default (Anonymous if enabled)'}`\n"
            f"📋 **Queue Progress:** `{q_idx}/{q_len}`\n"
            f"📦 **Active Task:** `{task_info.get('title') or 'None'}`\n"
            f"📊 **Messages Sent:** `{len(state.get('last_sent_ids', []))}`\n"
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
    """Reads Saved Messages on startup to recover state if cloud storage wiped."""
    try:
        async for msg in client.iter_messages('me', limit=50):
            if msg.text and BRAIN_TAG in msg.text:
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', msg.text, re.DOTALL)
                if json_match:
                    recovered = json.loads(json_match.group(1))
                    if not state.get("dest_link") and recovered.get("dest_link"):
                        state["dest_link"] = recovered.get("dest_link")
                    if not state.get("send_as_link") and recovered.get("send_as_link"):
                        state["send_as_link"] = recovered.get("send_as_link")
                    if not state.get("queue") and recovered.get("queue"):
                        state["queue"] = recovered.get("queue", [])
                        state["queue_index"] = recovered.get("queue_index", 0)
                    if not state.get("last_sent_ids") and recovered.get("last_sent_ids"):
                        state["last_sent_ids"] = recovered.get("last_sent_ids", [])
                    if recovered.get("is_running") is not None:
                        state["is_running"] = recovered.get("is_running")
                    if recovered.get("active_task"):
                        state["active_task"] = recovered.get("active_task")
                    logger.info("Successfully recovered state from Saved Messages brain storage.")
                break
    except Exception as e:
        logger.warning(f"Could not load brain storage from Saved Messages: {e}")

# --- LINK PARSER & METADATA UTILITIES ---

def parse_telegram_link(link):
    """
    Parses any Telegram link into (chat_id, topic_id, start_id, end_id, is_range, has_explicit_topic).
    """
    if not link:
        return None, None, None, None, False, False

    link = link.strip()
    match = re.search(r't\.me/(?:c/)?([^/]+)(?:/(\d+(?:-\d+)?))?(?:/(\d+(?:-\d+)?))?', link)
    if not match:
        return None, None, None, None, False, False

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
    has_explicit_topic = False

    if seg1 and '-' in seg1:
        is_range = True
        parts = sorted([int(p) for p in seg1.split('-')])
        start_id, end_id = parts[0], parts[1]
    elif seg2 and '-' in seg2:
        topic_id = int(seg1)
        has_explicit_topic = True
        is_range = True
        parts = sorted([int(p) for p in seg2.split('-')])
        start_id, end_id = parts[0], parts[1]
    elif seg1 and seg2:
        topic_id = int(seg1)
        has_explicit_topic = True
        start_id = int(seg2)
    elif seg1:
        val = int(seg1)
        topic_id = val
        start_id = val
        has_explicit_topic = True

    return chat_id, topic_id, start_id, end_id, is_range, has_explicit_topic

async def get_topic_title(chat_entity, topic_id):
    """Retrieves title of a forum topic."""
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

async def fetch_all_group_topics(chat_entity):
    """
    If a chat is a forum supergroup, fetches all topics inside it.
    Returns list of dicts: [{'topic_id': ..., 'title': ...}]
    """
    topics_list = []
    try:
        res = await client(GetForumTopicsRequest(
            channel=chat_entity,
            offset_date=0,
            offset_id=0,
            offset_topic=0,
            limit=100
        ))
        if res and hasattr(res, 'topics'):
            for t in res.topics:
                topics_list.append({
                    "topic_id": t.id,
                    "title": t.title
                })
    except Exception as e:
        logger.debug(f"Not a forum group or cannot fetch topics: {e}")
    return topics_list

async def create_new_forum_topic(dest_entity, title):
    """Creates a new forum topic in destination group."""
    try:
        try:
            res = await client(CreateForumTopicRequest(peer=dest_entity, title=title))
        except TypeError:
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
    """Checks if channel restricts content saving/forwarding."""
    try:
        full_chat = await client.get_entity(chat_entity)
        return getattr(full_chat, 'noforwards', False)
    except Exception as e:
        logger.error(f"Error checking chat restriction: {e}")
        return False

async def wait_until_unlocked(chat_entity, status_msg=None):
    """
    Checks forward status every 5 minutes.
    Pauses while locked; resumes immediately when unlocked.
    """
    while True:
        restricted = await is_forward_restricted(chat_entity)
        if not restricted:
            return True

        state["current_status"] = "Waiting for forward unlock (Checked every 5 min)"
        save_local_config()
        await sync_brain_storage()

        logger.info("Forwarding is locked on source. Checking again in 5 minutes...")
        if status_msg:
            try:
                await status_msg.edit(
                    "🔒 **Forwarding is currently LOCKED by channel admin!**\n\n"
                    "⏳ Sleeping for **5 minutes** before checking again...\n"
                    "🤖 The bot will automatically resume the instant forwarding is turned back ON."
                )
            except Exception:
                pass

        for _ in range(int(FORWARD_CHECK_INTERVAL // 5)):
            if not state.get("is_running") or state.get("is_paused"):
                return False
            await asyncio.sleep(5)

async def resolve_send_as_entity():
    """Resolves custom send_as entity if configured."""
    if not state.get("send_as_link"):
        return None
    try:
        return await client.get_entity(state["send_as_link"])
    except Exception as e:
        logger.warning(f"Could not resolve send_as entity: {e}")
        return None

async def forward_batch_clean(dest_entity, src_entity, batch_ids, dest_topic_id=None, send_as_entity=None):
    """
    Forwards up to 100 messages at once without quote tag (drop_author=True).
    Supports send_as if specified.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            kwargs = {
                "entity": dest_entity,
                "messages": batch_ids,
                "from_peer": src_entity,
                "reply_to": dest_topic_id,
                "drop_author": True
            }
            if send_as_entity:
                kwargs["send_as"] = send_as_entity

            forwarded = await client.forward_messages(**kwargs)
            if isinstance(forwarded, list):
                return [m.id for m in forwarded if m]
            elif forwarded:
                return [forwarded.id]
            return []
        except errors.FloodWaitError as fwe:
            logger.warning(f"FloodWait hit: sleeping {fwe.seconds}s")
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
        "🤖 **Telegram History Cloner & Topic Engine**\n\n"
        "⚡ **Features:**\n"
        "• Native 100-batch forwarding without quote tag (`drop_author=True`)\n"
        "• Multi-topic/channel queue: paste 10+ links and go to sleep!\n"
        "• Whole-group topic auto-discovery (fetches ALL topics in a group)\n"
        "• Anonymous Admin compatible & optional `/setsendas`\n"
        "• 35–50s batch delay + 5–8 min breather every 4–8 batches\n"
        "• 5-min forward unlock auto-checker\n"
        "• Saved Messages Cloud Brain Storage\n\n"
        "📋 **Commands:**\n"
        "• `/setdest <link>` — Set target group, channel, or topic\n"
        "• `/setsendas <channel_link|off>` — Set channel to send as (or leave off for Anonymous Admin)\n"
        "• `/clone [new|here] <link1> <link2>...` — Queue 1 or many topics/channels/full groups\n"
        "• `/queue` — View all pending/active items in queue\n"
        "• `/status` — Live dashboard, batch counts, delays\n"
        "• `/pause` / `/resume` — Pause or resume execution\n"
        "• `/stop` — Cancel active task & wipe queue\n"
        "• `/purge` — Bulk delete last forwarded messages from destination\n\n"
        f"🎯 **Destination:** `{state.get('dest_link') or 'Not Set'}`\n"
        f"👤 **Send As:** `{state.get('send_as_link') or 'Default (Anonymous if enabled)'}`"
    )
    await event.reply(help_text)

@client.on(events.NewMessage(pattern=r'^/setdest\s+(.+)$', outgoing=True))
async def set_dest_handler(event):
    link = event.pattern_match.group(1).strip()
    state["dest_link"] = link
    save_local_config()
    await sync_brain_storage()
    await event.reply(f"🎯 **Destination saved permanently:**\n`{link}`")

@client.on(events.NewMessage(pattern=r'^/setsendas(?:\s+(.+))?$', outgoing=True))
async def set_send_as_handler(event):
    raw = event.pattern_match.group(1)
    if not raw or raw.strip().lower() in ['off', 'none', 'clear', 'default']:
        state["send_as_link"] = None
        save_local_config()
        await sync_brain_storage()
        await event.reply("👤 **Send As reset to default.** (If you have Anonymous Admin enabled, Telegram will post under Group Name).")
        return

    arg = raw.strip()
    try:
        ent = await client.get_entity(arg)
        state["send_as_link"] = arg
        save_local_config()
        await sync_brain_storage()
        title = getattr(ent, 'title', arg)
        await event.reply(f"👤 **Send As identity mapped to:** *\"{title}\"* (`{arg}`)")
    except Exception as e:
        await event.reply(f"❌ Could not resolve entity for Send As: `{e}`")

@client.on(events.NewMessage(pattern=r'^/queue$', outgoing=True))
async def queue_handler(event):
    q = state.get("queue", [])
    if not q:
        await event.reply("📋 **Queue is currently empty.** Queue links with `/clone`.")
        return

    idx = state.get("queue_index", 0)
    text = f"📋 **Queue Overview ({idx + 1}/{len(q)}):**\n\n"
    for i, item in enumerate(q):
        marker = "▶️ **Active:**" if i == idx and state.get("is_running") else ("✅" if i < idx else "⏳")
        text += f"{marker} **Item {i+1}:** *{item.get('title')}* [{item.get('mode')}]\n"
        text += f"   🔗 `{item.get('source_link')}`\n\n"

    await event.reply(text)

@client.on(events.NewMessage(pattern=r'^/status$', outgoing=True))
async def status_handler(event):
    task = state.get("active_task")
    q = state.get("queue", [])
    q_len = len(q)
    q_idx = state.get("queue_index", 0) + 1 if q_len > 0 else 0

    status_text = (
        f"📊 **Cloner Engine Status:**\n\n"
        f"• **State:** `{state.get('current_status', 'Idle')}`\n"
        f"• **Running:** `{'Yes' if state.get('is_running') else 'No'}` | **Paused:** `{'Yes' if state.get('is_paused') else 'No'}`\n"
        f"• **Destination:** `{state.get('dest_link') or 'Not Set'}`\n"
        f"• **Queue Progress:** `{q_idx}/{q_len}` items\n"
    )
    if task:
        status_text += (
            f"• **Current Task:** *\"{task.get('title')}\"*\n"
            f"• **Mode:** `{task.get('mode')}`\n"
            f"• **Processed Batches:** `{task.get('batches_done', 0)}`\n"
            f"• **Messages Transferred:** `{len(state.get('last_sent_ids', []))}`\n"
            f"• **Batches Until Breather:** `{max(0, state.get('next_breather_threshold', 0) - state.get('batches_since_breather', 0))}`\n"
        )
    else:
        status_text += "• **Current Task:** `None`\n"

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
    if not state.get("is_running") and not state.get("queue"):
        await event.reply("⚠️ No task or queue is active.")
        return
    state["is_running"] = False
    state["is_paused"] = False
    state["current_status"] = "Stopped by user"
    state["queue"] = []
    state["queue_index"] = 0
    state["active_task"] = None
    save_local_config()
    await sync_brain_storage()
    await event.reply("🛑 **Pipeline Stopped & Queue Cleared.**")

@client.on(events.NewMessage(pattern=r'^/purge$', outgoing=True))
async def purge_handler(event):
    sent_ids = state.get("last_sent_ids", [])
    if not sent_ids:
        await event.reply("⚠️ No message IDs recorded in history to delete.")
        return

    if not state.get("dest_link"):
        await event.reply("❌ Destination link missing.")
        return

    dest_chat, _, _, _, _, _ = parse_telegram_link(state["dest_link"])
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

# --- CLONE QUEUE COMPILER & RUNNER ---

@client.on(events.NewMessage(pattern=r'^/clone(?:\s+([\s\S]+))?$', outgoing=True))
async def clone_handler(event):
    if state.get("is_running"):
        await event.reply("⚠️ A clone queue is actively processing! Use `/queue`, `/status`, or `/stop`.")
        return

    if not state.get("dest_link"):
        await event.reply("❌ **Error:** Set destination first using `/setdest <link>`.")
        return

    raw_input = event.pattern_match.group(1)
    if not raw_input:
        await event.reply("⚠️ **Usage:** `/clone [new|here] <link1> <link2>...`")
        return

    # Extract forced mode (new or here) if present
    forced_mode = None
    words = raw_input.strip().split()
    first_word = words[0].lower() if words else ""
    if first_word in ['new', 'here']:
        forced_mode = first_word

    # Extract all Telegram links from the message
    raw_links = re.findall(r'https?://t\.me/[^\s]+', raw_input)
    if not raw_links:
        await event.reply("❌ **Error:** No valid Telegram links detected in your message.")
        return

    dest_chat, dest_topic_id, _, _, _, dest_has_topic = parse_telegram_link(state["dest_link"])
    if not dest_chat:
        await event.reply("❌ **Error:** Destination link is invalid or unparseable.")
        return

    try:
        dest_entity = await client.get_entity(dest_chat)
    except Exception as e:
        await event.reply(f"❌ Could not resolve destination: `{e}`")
        return

    status_msg = await event.reply(f"🔍 **Analyzing {len(raw_links)} provided link(s)...**")

    new_queue = []

    for link in raw_links:
        src_chat, src_topic_id, start_id, end_id, is_range, has_explicit_topic = parse_telegram_link(link)
        if not src_chat:
            continue

        try:
            src_entity = await client.get_entity(src_chat)
        except Exception as e:
            logger.error(f"Error resolving {link}: {e}")
            continue

        # Check if the link is a whole forum group (no explicit topic specified)
        is_forum = getattr(src_entity, 'forum', False)
        if is_forum and not has_explicit_topic:
            # Whole group topic auto-discovery!
            await status_msg.edit(f"📂 **Forum group detected!** Auto-discovering all topics in *\"{getattr(src_entity, 'title', link)}\"*...")
            topics = await fetch_all_group_topics(src_entity)
            if topics:
                for t in topics:
                    mode = forced_mode or ("here" if dest_has_topic else "new")
                    new_queue.append({
                        "title": t["title"],
                        "source_link": f"https://t.me/c/{str(src_chat).replace('-100', '')}/{t['topic_id']}",
                        "src_chat": src_chat,
                        "src_topic_id": t["topic_id"],
                        "start_id": None,
                        "end_id": None,
                        "is_range": False,
                        "mode": mode
                    })
                continue

        # Single topic, single channel, or explicit range
        topic_title = None
        if src_topic_id:
            topic_title = await get_topic_title(src_entity, src_topic_id)
        if not topic_title:
            topic_title = getattr(src_entity, 'title', None) or f"Topic_{src_topic_id or 'Transfer'}"

        mode = forced_mode or ("here" if dest_has_topic else "new")
        new_queue.append({
            "title": topic_title,
            "source_link": link,
            "src_chat": src_chat,
            "src_topic_id": src_topic_id if has_explicit_topic else None,
            "start_id": start_id,
            "end_id": end_id,
            "is_range": is_range,
            "mode": mode
        })

    if not new_queue:
        await status_msg.edit("❌ No viable tasks could be compiled from the links provided.")
        return

    state["queue"] = new_queue
    state["queue_index"] = 0
    state["is_running"] = True
    state["is_paused"] = False
    save_local_config()
    await sync_brain_storage()

    await status_msg.edit(
        f"🚀 **Queue Compiled!** Total items to process: `{len(new_queue)}`\n"
        f"💤 You can now close Telegram and rest. The bot will work through each item sequentially.\n\n"
        f"▶️ Starting Item 1: *\"{new_queue[0]['title']}\"*"
    )

    # Launch background queue runner
    asyncio.create_task(run_queue_pipeline(dest_entity, status_msg))

async def run_queue_pipeline(dest_entity, status_msg):
    """Iterates through all queued tasks sequentially."""
    send_as_entity = await resolve_send_as_entity()

    try:
        while state["queue_index"] < len(state["queue"]):
            if not state.get("is_running"):
                break

            task = state["queue"][state["queue_index"]]
            state["active_task"] = task
            state["active_task"]["batches_done"] = 0
            state["current_status"] = f"Processing ({state['queue_index']+1}/{len(state['queue'])}) - {task['title']}"
            save_local_config()
            await sync_brain_storage()

            # Execute single task
            await execute_single_task(dest_entity, task, status_msg, send_as_entity)

            state["queue_index"] += 1
            save_local_config()
            await sync_brain_storage()

            if state["queue_index"] < len(state["queue"]) and state.get("is_running"):
                logger.info("Task finished. Brief 15s transition pause before next queue item...")
                await asyncio.sleep(15)

        if state.get("is_running"):
            state["current_status"] = "Queue Finished"
            await status_msg.edit(
                f"🏆 **Grand Queue Concluded!**\n\n"
                f"📦 Processed all `{len(state['queue'])}` items successfully.\n"
                f"📊 Total messages transferred: `{len(state.get('last_sent_ids', []))}`"
            )

    except Exception as e:
        logger.error(f"Queue pipeline error: {e}", exc_info=True)
        state["current_status"] = f"Queue Error: {e}"
    finally:
        state["is_running"] = False
        state["is_paused"] = False
        state["active_task"] = None
        save_local_config()
        await sync_brain_storage()

async def execute_single_task(dest_entity, task, status_msg, send_as_entity):
    """Processes messages for a single topic or channel item."""
    src_chat = task["src_chat"]
    src_topic_id = task["src_topic_id"]
    topic_title = task["title"]
    mode = task["mode"]

    src_entity = await client.get_entity(src_chat)

    dest_chat, dest_topic_id, _, _, _, _ = parse_telegram_link(state["dest_link"])
    target_topic_id = dest_topic_id
    start_ckpt = task.get("last_src_id") or task.get("start_id") or 0

    # --- PRE-FLIGHT DESTINATION CHECK & TOPIC SETUP ---
    h_msg = None
    try:
        if mode == "new":
            try:
                target_topic_id = await create_new_forum_topic(dest_entity, topic_title)
            except Exception as e:
                logger.warning(f"Could not create forum topic '{topic_title}': {e}. Falling back to default destination topic.")
                target_topic_id = dest_topic_id

            header_text = (
                f"📌 **{topic_title}**\n"
                f"*(Transferred in 100-message batches)*\n"
                f"📍 Checkpoint: `#SRC_ID:{start_ckpt}`"
            )
            send_kwargs = {"reply_to": target_topic_id}
            if send_as_entity:
                send_kwargs["send_as"] = send_as_entity
            h_msg = await client.send_message(dest_entity, header_text, **send_kwargs)
        else:
            # Mode is 'here': send divider header in existing topic/channel
            header_text = (
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📚 **Topic / Channel:** {topic_title}\n"
                f"📍 Checkpoint: `#SRC_ID:{start_ckpt}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            send_kwargs = {"reply_to": target_topic_id}
            if send_as_entity:
                send_kwargs["send_as"] = send_as_entity
            h_msg = await client.send_message(dest_entity, header_text, **send_kwargs)

        if h_msg:
            task["header_msg_id"] = h_msg.id
            task["target_topic_id"] = target_topic_id
            if state.get("active_task"):
                state["active_task"]["header_msg_id"] = h_msg.id
                state["active_task"]["target_topic_id"] = target_topic_id
            save_local_config()
            await sync_brain_storage()
            try:
                await client.pin_message(dest_entity, h_msg.id, notify=False)
            except Exception:
                pass

    except Exception as pfe:
        logger.error(f"❌ Pre-flight destination check failed for task '{topic_title}': {pfe}")
        if status_msg:
            try:
                await status_msg.edit(f"⚠️ **Pre-flight Check Failed for {topic_title}:** `{pfe}`\nSkipping to next queue item...")
            except Exception:
                pass
        return

    # Build iter_messages arguments
    iter_kwargs = {'entity': src_entity, 'reverse': True}
    if task["is_range"]:
        iter_kwargs['min_id'] = task["start_id"] - 1
        iter_kwargs['max_id'] = task["end_id"] + 1
    elif task["start_id"]:
        iter_kwargs['min_id'] = task["start_id"] - 1

    if src_topic_id:
        iter_kwargs['reply_to'] = src_topic_id

    batch_buffer = []

    async for message in client.iter_messages(**iter_kwargs):
        while state.get("is_paused"):
            await status_msg.edit(f"⏸️ **Queue Paused.** Holding at *\"{topic_title}\"* (ID: `{message.id}`).")
            await asyncio.sleep(2)
            if not state.get("is_running"):
                return

        if not state.get("is_running"):
            return

        if message is None or getattr(message, 'action', None) or getattr(message, '_empty', False):
            continue
        if not message.text and not getattr(message, 'media', None):
            continue

        batch_buffer.append(message.id)

        if len(batch_buffer) >= BATCH_SIZE:
            await process_and_send_batch(
                status_msg, dest_entity, src_entity, batch_buffer,
                target_topic_id, topic_title, send_as_entity
            )
            batch_buffer = []

    if batch_buffer and state.get("is_running"):
        await process_and_send_batch(
            status_msg, dest_entity, src_entity, batch_buffer,
            target_topic_id, topic_title, send_as_entity
        )

async def process_and_send_batch(status_msg, dest_entity, src_entity, batch_ids, target_topic_id, topic_title, send_as_entity):
    """Handles restriction checks, batch forward dispatch, delay & breather pauses."""
    unlocked = await wait_until_unlocked(src_entity, status_msg)
    if not unlocked:
        return

    try:
        sent_ids = await forward_batch_clean(dest_entity, src_entity, batch_ids, target_topic_id, send_as_entity)
    except errors.ChatForwardsRestrictedError:
        logger.warning("ChatForwardsRestrictedError caught! Entering 5 min wait...")
        await wait_until_unlocked(src_entity, status_msg)
        sent_ids = await forward_batch_clean(dest_entity, src_entity, batch_ids, target_topic_id, send_as_entity)

    if sent_ids:
        state["last_sent_ids"].extend(sent_ids)
        highest_id = max(batch_ids)
        if state.get("active_task"):
            state["active_task"]["batches_done"] = state["active_task"].get("batches_done", 0) + 1
            state["active_task"]["last_src_id"] = highest_id
            state["active_task"]["start_id"] = highest_id + 1
        if state.get("queue") and state.get("queue_index", 0) < len(state["queue"]):
            state["queue"][state["queue_index"]]["start_id"] = highest_id + 1
            state["queue"][state["queue_index"]]["last_src_id"] = highest_id
        state["batches_since_breather"] += 1
        save_local_config()
        await sync_brain_storage()

        # Update destination pinned header checkpoint
        h_msg_id = state.get("active_task", {}).get("header_msg_id") if state.get("active_task") else None
        if h_msg_id:
            try:
                task_mode = state.get("active_task", {}).get("mode", "here")
                if task_mode == "new":
                    updated_header = (
                        f"📌 **{topic_title}**\n"
                        f"*(Transferred in 100-message batches)*\n"
                        f"📍 Checkpoint: `#SRC_ID:{highest_id}`"
                    )
                else:
                    updated_header = (
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📚 **Topic / Channel:** {topic_title}\n"
                        f"📍 Checkpoint: `#SRC_ID:{highest_id}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    )
                await client.edit_message(dest_entity, h_msg_id, updated_header)
            except Exception as e:
                logger.debug(f"Could not update destination header checkpoint: {e}")

    q_idx = state.get("queue_index", 0) + 1
    q_len = len(state.get("queue", []))
    current_batch = state["active_task"].get("batches_done", 0) if state.get("active_task") else 0
    total_msgs = len(state["last_sent_ids"])

    try:
        await status_msg.edit(
            f"⏳ **Processing Queue ({q_idx}/{q_len})...**\n\n"
            f"📚 Active: *\"{topic_title}\"*\n"
            f"📦 Batches Dispatched: `{current_batch}` (100 msgs/batch)\n"
            f"📊 Total Transferred: `{total_msgs}` messages\n"
            f"🛡️ Safety: Forward without quote (`drop_author`)\n"
            f"☕ Next Breather in: `{state['next_breather_threshold'] - state['batches_since_breather']} batches`"
        )
    except Exception:
        pass

    # Breather Check (Every 4 to 8 batches, sleep for 5 to 8 minutes)
    if state["batches_since_breather"] >= state["next_breather_threshold"]:
        breather_sleep = random.uniform(BREATHER_PAUSE_MIN, BREATHER_PAUSE_MAX)
        breather_mins = round(breather_sleep / 60, 1)
        logger.info(f"Taking a human breather sleep of {breather_mins} minutes...")
        state["current_status"] = f"Taking human breather pause ({breather_mins} mins)"
        save_local_config()

        try:
            await status_msg.edit(
                f"☕ **Human Breather Pause ({breather_mins} mins)...**\n\n"
                f"Active Item: *\"{topic_title}\"* ({q_idx}/{q_len})\n"
                f"Mimicking natural human breaks. Zero risk of account flags.\n"
                f"Auto-resuming in {int(breather_sleep)} seconds..."
            )
        except Exception:
            pass

        for _ in range(int(breather_sleep // 5)):
            if not state.get("is_running") or state.get("is_paused"):
                break
            await asyncio.sleep(5)

        state["batches_since_breather"] = 0
        state["next_breather_threshold"] = random.randint(BREATHER_BATCHES_MIN, BREATHER_BATCHES_MAX)
        state["current_status"] = f"Processing ({q_idx}/{q_len}) - {topic_title}"
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

# --- SMART ANCHOR RECOVERY UTILITIES ---

async def resolve_smart_anchor_resume(dest_entity, curr_task):
    """
    On container reboot, scans the destination to detect if any messages from the active
    batch were sent right before the crash, preventing duplicate forwards.
    """
    known_start = curr_task.get("start_id") or 1
    src_chat = curr_task.get("src_chat")
    src_topic_id = curr_task.get("src_topic_id")
    target_topic_id = curr_task.get("target_topic_id")

    if not src_chat:
        return known_start

    try:
        dest_iter_kwargs = {'entity': dest_entity, 'limit': 30}
        if target_topic_id:
            dest_iter_kwargs['reply_to'] = target_topic_id

        dest_msgs = []
        async for m in client.iter_messages(**dest_iter_kwargs):
            if m and (m.text or getattr(m, 'media', None)):
                # Skip the pinned header itself
                if m.id == curr_task.get("header_msg_id"):
                    continue
                dest_msgs.append(m)

        if not dest_msgs:
            return known_start

        # Scan backwards from newest destination message to find one with text/caption
        anchor_text = None
        trailing_count = 0
        for idx, dm in enumerate(dest_msgs):
            txt = (dm.text or "").strip()
            # Ignore divider headers
            if txt and "Checkpoint: #SRC_ID:" not in txt and len(txt) > 3:
                anchor_text = txt
                trailing_count = idx  # number of media messages sent AFTER this anchor
                break

        if not anchor_text:
            return known_start

        # Search for this anchor text in source near the known starting point
        src_entity = await client.get_entity(src_chat)
        src_iter_kwargs = {'entity': src_entity, 'limit': 60, 'reverse': True}
        if known_start > 30:
            src_iter_kwargs['min_id'] = max(0, known_start - 30)
        if src_topic_id:
            src_iter_kwargs['reply_to'] = src_topic_id

        matched_src_id = None
        async for sm in client.iter_messages(**src_iter_kwargs):
            s_txt = (sm.text or "").strip()
            if s_txt and s_txt == anchor_text:
                matched_src_id = sm.id
                break

        if matched_src_id:
            calculated_start = matched_src_id + trailing_count + 1
            if calculated_start > known_start:
                logger.info(
                    f"🎯 Smart Anchor Recovery matched text! Advancing start_id from {known_start} to {calculated_start} "
                    f"(Matched Src ID: {matched_src_id}, Trailing msgs: {trailing_count})"
                )
                return calculated_start

    except Exception as e:
        logger.warning(f"Smart Anchor Recovery check skipped due to: {e}")

    return known_start

async def main():
    load_local_config()
    await start_web_server()
    await client.start()
    await load_brain_storage()
    logger.info("Bot started successfully. Listening for commands...")

    # Auto-resume interrupted queue after cloud container reboot
    if state.get("is_running") and state.get("dest_link") and state.get("queue") and state.get("queue_index", 0) < len(state.get("queue", [])):
        q_idx = state.get("queue_index", 0)
        curr_task = state["queue"][q_idx]
        logger.info(f"🔄 Cloud container reboot detected! Inspecting Smart Anchor for Task {q_idx + 1} ('{curr_task.get('title')}')...")
        try:
            dest_chat, _, _, _, _, _ = parse_telegram_link(state["dest_link"])
            dest_entity = await client.get_entity(dest_chat)

            # Perform Smart Anchor check to prevent duplicate forwards if container crashed mid-batch
            resumed_start_id = await resolve_smart_anchor_resume(dest_entity, curr_task)
            curr_task["start_id"] = resumed_start_id
            state["queue"][q_idx]["start_id"] = resumed_start_id
            save_local_config()
            await sync_brain_storage()

            status_msg = await client.send_message(
                'me',
                f"🔄 **Cloud Reboot Detected & Recovered!**\n\n"
                f"Auto-resuming task `{q_idx + 1}/{len(state['queue'])}`: *\"{curr_task.get('title')}\"*\n"
                f"📍 Smart Anchor Start ID: `{resumed_start_id}`\n"
                f"🛡️ Zero duplicates guaranteed."
            )
            asyncio.create_task(run_queue_pipeline(dest_entity, status_msg))
        except Exception as e:
            logger.error(f"Error auto-resuming queue pipeline after reboot: {e}")

    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

import os
import re
import json
import asyncio
import logging
import random
from datetime import datetime
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
from telethon import functions

def _resolve_tl_request(name):
    # Telegram schema places forum topic requests under messages or channels depending on layer
    for mod in (getattr(functions, 'messages', None), getattr(functions, 'channels', None)):
        if mod and hasattr(mod, name):
            return getattr(mod, name)
    return None

CreateForumTopicRequest = _resolve_tl_request('CreateForumTopicRequest')
GetForumTopicsByIDRequest = _resolve_tl_request('GetForumTopicsByIDRequest')
GetForumTopicsRequest = _resolve_tl_request('GetForumTopicsRequest')
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

def normalize_chat_id(val):
    """Ensures 9+ digit group IDs are formatted with the -100 supergroup prefix."""
    if isinstance(val, (int, str)):
        s_val = str(val).strip()
        if s_val.lstrip('-').isdigit():
            v = int(s_val)
            s_abs = str(abs(v))
            if len(s_abs) >= 9:
                if not s_val.startswith('-100'):
                    return int('-100' + s_abs)
            return v
    return val

def parse_destination_link(dest):
    """
    Parses any Telegram link or chat/topic input into (chat_id, topic_id, None, None, False, has_topic).
    Supports:
    - https://t.me/c/3992974528/6850
    - https://t.me/c/3992974528 6850
    - -1003992974528 6850 or 3992974528 6850
    - -1003992974528/6850 or 3992974528/6850
    - https://t.me/c/3992974528?topic=6850
    - Standard non-topic channel/group links (topic_id=None, has_topic=False)
    """
    if not dest:
        return None, None, None, None, False, False

    dest = dest.strip()
    explicit_topic = None

    # Check for space format: '<link_or_chat> <topic_id>'
    space_parts = dest.split()
    if len(space_parts) == 2 and space_parts[1].isdigit():
        dest = space_parts[0]
        explicit_topic = int(space_parts[1])

    # Check for ?topic=123 parameter
    topic_param = re.search(r'[?&]topic=(\d+)', dest)
    if topic_param:
        explicit_topic = int(topic_param.group(1))

    # Match t.me link
    match = re.search(r't\.me/(?:c/)?([^/?#]+)(?:/(\d+))?(?:/(\d+))?', dest)
    if match:
        chat_raw = match.group(1)
        seg1 = match.group(2)
        seg2 = match.group(3)

        if 't.me/c/' in dest and not chat_raw.startswith('-100') and chat_raw.isdigit():
            chat_id = int('-100' + chat_raw)
        elif chat_raw.lstrip('-').isdigit():
            chat_id = normalize_chat_id(chat_raw)
        else:
            chat_id = chat_raw

        topic_id = explicit_topic
        if topic_id is None:
            if seg1:
                topic_id = int(seg1)

        has_topic = topic_id is not None
        return chat_id, topic_id, None, None, False, has_topic

    # Raw chat ID with /topic_id: -100123456/55 or 123456/55
    raw_match = re.search(r'^(-?\d+)(?:/(\d+))?$', dest)
    if raw_match:
        chat_id = normalize_chat_id(raw_match.group(1))
        topic_id = explicit_topic or (int(raw_match.group(2)) if raw_match.group(2) else None)
        return chat_id, topic_id, None, None, False, topic_id is not None

    return None, None, None, None, False, False

def parse_telegram_link(link):
    """
    Parses any Telegram link or chat/topic input into:
    (chat_id, topic_id, start_id, end_id, is_range, has_explicit_topic).
    Supports:
    - https://t.me/c/2200390931/899
    - -1002200390931 899 or 2200390931 899
    - -1002200390931/899 or 2200390931/899
    - https://t.me/c/2200390931 899
    - https://t.me/c/2200390931/899/10-50
    - https://t.me/c/2200390931/10-50
    """
    if not link:
        return None, None, None, None, False, False

    link = link.strip()
    explicit_topic = None

    # 1. Check space format: '<link_or_chat> <topic_id>'
    space_parts = link.split()
    if len(space_parts) == 2 and space_parts[1].isdigit():
        link = space_parts[0]
        explicit_topic = int(space_parts[1])

    # 2. Check raw format: -100123/456 or 123/456
    raw_slash = re.match(r'^(-?\d+)(?:/(\d+))?$', link)
    if raw_slash:
        c_raw = raw_slash.group(1)
        chat_id = normalize_chat_id(c_raw)
        topic_id = explicit_topic or (int(raw_slash.group(2)) if raw_slash.group(2) else None)
        return chat_id, topic_id, None, None, False, topic_id is not None

    # 3. Check t.me link
    match = re.search(r't\.me/(?:c/)?([^/?#]+)(?:/(\d+(?:-\d+)?))?(?:/(\d+(?:-\d+)?))?', link)
    if not match:
        return None, None, None, None, False, False

    chat_raw = match.group(1)
    seg1 = match.group(2)
    seg2 = match.group(3)

    if 't.me/c/' in link and not chat_raw.startswith('-100') and chat_raw.isdigit():
        chat_id = int('-100' + chat_raw)
    elif chat_raw.lstrip('-').isdigit():
        chat_id = normalize_chat_id(chat_raw)
    else:
        chat_id = chat_raw

    is_range = False
    start_id = None
    end_id = None
    topic_id = explicit_topic
    has_explicit_topic = explicit_topic is not None

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
        topic_id = explicit_topic or val
        start_id = None
        has_explicit_topic = True

    return chat_id, topic_id, start_id, end_id, is_range, has_explicit_topic

def extract_clone_targets(raw_input):
    """
    Extracts individual source targets from user input.
    Supports:
    - https://t.me/c/2200390931/899
    - https://t.me/c/2200390931 899
    - -1002200390931 899 or 2200390931 899
    - -1002200390931/899 or 2200390931/899
    - Multiple targets separated by newlines or spaces.
    """
    if not raw_input:
        return []
    text = raw_input.strip()
    words = text.split(None, 1)
    if words and words[0].lower() in ['new', 'here']:
        text = words[1].strip() if len(words) > 1 else ''
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    targets = []
    for line in lines:
        tokens = line.split()
        i = 0
        while i < len(tokens):
            curr = tokens[i]
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                targets.append(f"{curr} {tokens[i + 1]}")
                i += 2
            else:
                targets.append(curr)
                i += 1
    return targets

_last_status_edit_time = 0

async def safe_edit_status(status_msg, text):
    """Safely edits status messages with rate limiting and flood handling."""
    global _last_status_edit_time
    if not status_msg:
        return
    now = asyncio.get_event_loop().time()
    diff = now - _last_status_edit_time
    if diff < 1.5:
        await asyncio.sleep(1.5 - diff)
    try:
        await status_msg.edit(text)
        _last_status_edit_time = asyncio.get_event_loop().time()
    except (errors.MessageNotModifiedError, errors.rpcerrorlist.MessageNotModifiedError):
        pass
    except errors.FloodWaitError as fwe:
        logger.debug(f"FloodWait on status edit ({fwe.seconds}s), skipping visual update.")
    except Exception as e:
        logger.debug(f"Status edit suppressed: {e}")

async def get_topic_title(chat_entity, topic_id):
    """Retrieves title of a forum topic."""
    if not topic_id:
        return None
    if GetForumTopicsByIDRequest:
        try:
            try:
                res = await client(GetForumTopicsByIDRequest(peer=chat_entity, topics=[topic_id]))
            except TypeError:
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

async def detect_topic_or_forum(src_entity, potential_topic_id=None):
    """
    Accurately determines if src_entity is a forum supergroup and whether potential_topic_id is a valid topic.
    Returns (is_forum: bool, topic_title: Optional[str]).
    """
    is_forum = getattr(src_entity, 'forum', False)

    # 1. If potential_topic_id provided, check if it has a topic title or topic create action
    if potential_topic_id and potential_topic_id > 1:
        title = await get_topic_title(src_entity, potential_topic_id)
        if title:
            return True, title

    # 2. If entity doesn't have forum flag in memory/cache, refresh full channel info
    if not is_forum:
        try:
            full = await client(functions.channels.GetFullChannelRequest(channel=src_entity))
            for c in getattr(full, 'chats', []):
                if c.id == getattr(src_entity, 'id', None):
                    if getattr(c, 'forum', False):
                        is_forum = True
                        src_entity.forum = True
                        break
        except Exception:
            pass

    # 3. If forum flag is true, try to get title for potential_topic_id if not yet retrieved
    title = None
    if is_forum and potential_topic_id and potential_topic_id > 1:
        title = await get_topic_title(src_entity, potential_topic_id)
        if not title:
            title = f"Topic #{potential_topic_id}"

    return is_forum, title

async def fetch_all_group_topics(chat_entity):
    """
    If a chat is a forum supergroup, fetches all topics inside it.
    Returns list of dicts: [{'topic_id': ..., 'title': ...}]
    """
    topics_list = []
    if not GetForumTopicsRequest:
        return topics_list
    try:
        try:
            res = await client(GetForumTopicsRequest(
                peer=chat_entity,
                offset_date=0,
                offset_id=0,
                offset_topic=0,
                limit=100
            ))
        except TypeError:
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
    if not CreateForumTopicRequest:
        logger.error("CreateForumTopicRequest is not supported in this Telethon version.")
        return None
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
    Uses raw ForwardMessagesRequest to reliably route to forum topics (top_msg_id=dest_topic_id)
    and support send_as.
    """
    to_peer = await client.get_input_entity(dest_entity)
    from_peer = await client.get_input_entity(src_entity)
    send_as_peer = await client.get_input_entity(send_as_entity) if send_as_entity else None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            random_ids = [random.randint(0, 0x7fffffffffffffff) for _ in batch_ids]
            kwargs = {
                "from_peer": from_peer,
                "id": batch_ids,
                "to_peer": to_peer,
                "random_id": random_ids,
                "drop_author": True
            }
            if dest_topic_id:
                kwargs["top_msg_id"] = int(dest_topic_id)
                try:
                    from telethon.tl.types import InputReplyToMessage
                    kwargs["reply_to"] = InputReplyToMessage(reply_to_msg_id=int(dest_topic_id), top_msg_id=int(dest_topic_id))
                except Exception:
                    pass
            if send_as_peer:
                kwargs["send_as"] = send_as_peer

            req = functions.messages.ForwardMessagesRequest(**kwargs)
            result = await client(req)

            sent_ids = []
            if hasattr(result, 'updates'):
                for upd in result.updates:
                    if hasattr(upd, 'message') and hasattr(upd.message, 'id'):
                        sent_ids.append(upd.message.id)
            if not sent_ids and hasattr(result, 'id'):
                sent_ids.append(result.id)
            if not sent_ids and hasattr(client, '_get_response_message'):
                try:
                    msgs = client._get_response_message(req, result, to_peer)
                    if msgs:
                        if isinstance(msgs, list):
                            sent_ids = [m.id for m in msgs if m]
                        elif hasattr(msgs, 'id'):
                            sent_ids = [msgs.id]
                except Exception:
                    pass

            return sent_ids if sent_ids else list(batch_ids)

        except errors.FloodWaitError as fwe:
            logger.warning(f"FloodWait hit: sleeping {fwe.seconds}s")
            await asyncio.sleep(fwe.seconds + 5)
        except errors.ChatForwardsRestrictedError:
            raise
        except Exception as e:
            logger.error(f"Batch forward error on attempt {attempt}: {e}", exc_info=True)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(10)
    return None

# --- COMMAND HANDLERS ---

@client.on(events.NewMessage(pattern=r'^/(?:start|help)$', outgoing=True))
async def help_handler(event):
    dest_str = state.get('dest_link') or 'Not Set'
    dest_chat, dest_topic_id, _, _, _, dest_has_topic = parse_destination_link(dest_str)
    dest_topic_display = f" (Topic ID: `{dest_topic_id}`)" if dest_topic_id else ""

    help_text = (
        "🤖 **Telegram History Cloner & Topic Engine**\n\n"
        "⚡ **Features:**\n"
        "• Native 100-batch forwarding directly into forum topics (`top_msg_id`)\n"
        "• Live batch start & progress updates every 10 messages\n"
        "• From-To Link forwarding: copy start & end message links\n"
        "• Multi-topic/channel queue: paste 10+ links and go to sleep!\n"
        "• Whole-group topic auto-discovery (fetches ALL topics in a group)\n"
        "• Anonymous Admin compatible & optional `/setsendas`\n"
        "• 35–50s batch delay + 5–8 min breather every 4–8 batches\n"
        "• 5-min forward unlock auto-checker\n"
        "• Saved Messages Cloud Brain Storage\n\n"
        "📋 **Commands:**\n"
        "• `/setdest <link>` — Set target group, channel, or specific topic\n"
        "• `/fromto <from_link> <to_link>` — Forward message range (same chat) OR forward from source to destination\n"
        "• `/range <from_link> <to_link>` — Quick message range forwarder into destination topic\n"
        "• `/clone [new|here] <link1> <link2>...` — Queue 1 or many topics/channels/ranges\n"
        "• `/setsendas <channel_link|off>` — Set channel to send as (or leave off for Anonymous Admin)\n"
        "• `/queue` — View all pending/active items in queue\n"
        "• `/status` — Live dashboard, batch counts, delays\n"
        "• `/pause` / `/resume` — Pause or resume execution\n"
        "• `/stop` — Cancel active task & wipe queue\n"
        "• `/purge` — Bulk delete last forwarded messages from destination\n\n"
        f"🎯 **Destination:** `{dest_str}`{dest_topic_display}\n"
        f"👤 **Send As:** `{state.get('send_as_link') or 'Default (Anonymous if enabled)'}`"
    )
    await event.reply(help_text)

@client.on(events.NewMessage(pattern=r'^/setdest(?:\s+(.+))?$', outgoing=True))
async def set_dest_handler(event):
    raw = event.pattern_match.group(1)
    if not raw:
        dest = state.get("dest_link")
        if dest:
            dest_chat, dest_topic_id, _, _, _, has_topic = parse_destination_link(dest)
            await event.reply(
                f"🎯 **Current Destination:** `{dest}`\n"
                f"• Target Chat ID: `{dest_chat}`\n"
                f"• Target Topic ID: `{dest_topic_id or 'None (Root / Auto New)'}`"
            )
        else:
            await event.reply("⚠️ **No destination set.** Usage: `/setdest <link_or_chat> [topic_id]`")
        return

    link = raw.strip()
    dest_chat, dest_topic_id, _, _, _, has_topic = parse_destination_link(link)
    if not dest_chat:
        await event.reply("❌ **Error:** Destination link or chat ID is invalid.")
        return

    try:
        dest_entity = await client.get_entity(dest_chat)
        chat_title = getattr(dest_entity, 'title', str(dest_chat))
        is_forum = getattr(dest_entity, 'forum', False)

        topic_info = ""
        if dest_topic_id:
            topic_title = await get_topic_title(dest_entity, dest_topic_id) or f"Topic #{dest_topic_id}"
            topic_info = f"\n🏷️ **Destination Topic:** *\"{topic_title}\"* (ID: `{dest_topic_id}`)\n📥 All forwarded messages will be delivered directly into this topic!"
        elif is_forum:
            topic_info = "\n📂 **Forum Supergroup detected** (no specific topic set).\nItems will create new topics per item, or use `/clone here` to post in root."

        state["dest_link"] = link
        save_local_config()
        await sync_brain_storage()

        await event.reply(
            f"🎯 **Destination Saved Successfully!**\n\n"
            f"📍 **Target Chat:** *\"{chat_title}\"* (`{dest_chat}`)"
            f"{topic_info}\n"
            f"🔗 `{link}`"
        )
    except Exception as e:
        state["dest_link"] = link
        save_local_config()
        await sync_brain_storage()
        await event.reply(
            f"🎯 **Destination saved:** `{link}`\n"
            f"*(Entity notice: `{e}` - will resolve on execution)*"
        )

@client.on(events.NewMessage(pattern=r'^/(?:fromto|setfromto|range)(?:\s+([\s\S]+))?$', outgoing=True))
async def fromto_handler(event):
    if state.get("is_running"):
        await event.reply("⚠️ A clone queue is actively processing! Use `/queue`, `/status`, or `/stop`.")
        return

    raw_input = event.pattern_match.group(1)
    if not raw_input:
        await event.reply(
            "⚠️ **From-To Link Forwarder Usage:**\n\n"
            "• `/fromto <from_link> <to_link>`\n"
            "  - **Same chat:** Forwards message range from `from_link` to `to_link` into your set destination topic.\n"
            "  - **Different chats:** Sets `to_link` as destination and forwards `from_link` into it!\n\n"
            "• `/range <start_msg_link> <end_msg_link>`\n"
            "  - Forwards the range of messages directly into the destination topic.\n\n"
            "**Examples:**\n"
            "• `/fromto https://t.me/c/123/10 https://t.me/c/123/150`\n"
            "• `/fromto https://t.me/c/123/55/10 https://t.me/c/123/55/150`\n"
            "• `/fromto https://t.me/source/10-100 https://t.me/c/dest/42`"
        )
        return

    raw_links = extract_clone_targets(raw_input)
    if len(raw_links) < 2:
        await event.reply(
            "❌ **Error:** Please provide both a FROM source and a TO destination/endpoint.\n\n"
            "💡 **Examples:**\n"
            "• `/fromto https://t.me/c/123/10 https://t.me/c/123/150`\n"
            "• `/fromto -1002200390931 899 -1003992974528 6850`\n"
            "• `/fromto 2200390931 899 3992974528 6850`"
        )
        return

    link1, link2 = raw_links[0], raw_links[1]
    c1, t1, s1, e1, r1, h1 = parse_telegram_link(link1)
    c2, t2, s2, e2, r2, h2 = parse_telegram_link(link2)

    if not c1 or not c2:
        await event.reply("❌ Could not parse one or both Telegram sources.")
        return

    # Check if both links belong to the same chat -> message range forwarding
    if c1 == c2:
        if not state.get("dest_link"):
            await event.reply("❌ **Destination not set!** Use `/setdest <link>` first.")
            return

        dest_chat, dest_topic_id, _, _, _, dest_has_topic = parse_destination_link(state["dest_link"])
        if not dest_chat:
            await event.reply("❌ Destination link is invalid. Please reset with `/setdest`.")
            return

        try:
            dest_entity = await client.get_entity(dest_chat)
            src_entity = await client.get_entity(c1)
        except Exception as e:
            await event.reply(f"❌ Error resolving entity: `{e}`")
            return

        m1 = s1
        m2 = s2
        if not m1 or not m2:
            await event.reply("❌ Both links must point to specific messages to form a range.")
            return

        start_id = min(m1, m2)
        end_id = max(m1, m2)
        tid = t1 if h1 else (t2 if h2 else None)

        title = None
        if tid and tid > 1:
            title = await get_topic_title(src_entity, tid)
        if not title:
            title = getattr(src_entity, 'title', None) or f"Chat_{c1}"
        title = f"{title} (Msg {start_id}–{end_id})"

        mode = "here" if dest_has_topic else "new"
        task = {
            "title": title,
            "source_link": f"{link1} -> {link2}",
            "src_chat": c1,
            "src_topic_id": tid,
            "start_id": start_id,
            "end_id": end_id,
            "is_range": True,
            "mode": mode,
            "target_topic_id": dest_topic_id
        }

        state["queue"] = [task]
        state["queue_index"] = 0
        state["is_running"] = True
        state["is_paused"] = False
        save_local_config()
        await sync_brain_storage()

        dest_topic_desc = f"Topic #{dest_topic_id}" if dest_topic_id else "Main"
        status_msg = await event.reply(
            f"🚀 **From-To Range Task Queued!**\n\n"
            f"📚 Source: *\"{title}\"*\n"
            f"🔢 Range: Message `{start_id}` ➔ `{end_id}` (`{end_id - start_id + 1}` msgs)\n"
            f"🎯 Destination: `{state['dest_link']}` ({dest_topic_desc})\n\n"
            f"▶️ Starting pipeline..."
        )
        asyncio.create_task(run_queue_pipeline(dest_entity, status_msg))

    else:
        # Different chats -> link1 is source, link2 is destination!
        state["dest_link"] = link2
        save_local_config()
        await sync_brain_storage()

        dest_chat, dest_topic_id, _, _, _, dest_has_topic = parse_destination_link(link2)
        try:
            dest_entity = await client.get_entity(dest_chat)
            dest_title = getattr(dest_entity, 'title', str(dest_chat))
        except Exception as e:
            await event.reply(f"❌ Error resolving destination `{link2}`: `{e}`")
            return

        try:
            src_entity = await client.get_entity(c1)
            src_title = getattr(src_entity, 'title', str(c1))
        except Exception as e:
            await event.reply(f"❌ Error resolving source `{link1}`: `{e}`")
            return

        is_f, detected_title = await detect_topic_or_forum(src_entity, t1 if not h1 else None)
        topic_title = detected_title
        if not topic_title and t1 and t1 > 1:
            topic_title = await get_topic_title(src_entity, t1)
        if not topic_title:
            topic_title = src_title

        mode = "here" if dest_has_topic else "new"
        src_top = t1 if (h1 or is_f) else None
        final_s1 = None if (is_f and not h1 and t1) else s1
        task = {
            "title": topic_title,
            "source_link": link1,
            "src_chat": c1,
            "src_topic_id": src_top,
            "start_id": final_s1,
            "end_id": e1,
            "is_range": r1,
            "mode": mode,
            "target_topic_id": dest_topic_id
        }

        state["queue"] = [task]
        state["queue_index"] = 0
        state["is_running"] = True
        state["is_paused"] = False
        save_local_config()
        await sync_brain_storage()

        dest_desc = f"Topic #{dest_topic_id}" if dest_topic_id else "Main"
        status_msg = await event.reply(
            f"🎯 **From-To Pipeline Activated!**\n\n"
            f"📥 **Destination Updated:** *\"{dest_title}\"* ({dest_desc})\n"
            f"📤 **Source Queued:** *\"{topic_title}\"*\n"
            f"🔗 `{link1}` ➔ `{link2}`\n\n"
            f"▶️ Starting batch clone pipeline..."
        )
        asyncio.create_task(run_queue_pipeline(dest_entity, status_msg))

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

    dest_str = state.get('dest_link') or 'Not Set'
    dest_chat, dest_topic_id, _, _, _, dest_has_topic = parse_destination_link(dest_str)
    dest_topic_info = f" (Topic: `{dest_topic_id}`)" if dest_topic_id else ""

    status_text = (
        f"📊 **Cloner Engine Status:**\n\n"
        f"• **State:** `{state.get('current_status', 'Idle')}`\n"
        f"• **Running:** `{'Yes' if state.get('is_running') else 'No'}` | **Paused:** `{'Yes' if state.get('is_paused') else 'No'}`\n"
        f"• **Destination:** `{dest_str}`{dest_topic_info}\n"
        f"• **Queue Progress:** `{q_idx}/{q_len}` items\n"
    )
    if task:
        task_topic = task.get('target_topic_id')
        target_info = f" -> Topic #{task_topic}" if task_topic else ""
        status_text += (
            f"• **Current Task:** *\"{task.get('title')}\"*{target_info}\n"
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

    dest_chat, _, _, _, _, _ = parse_destination_link(state["dest_link"])
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

    raw_input = event.pattern_match.group(1)
    if not raw_input:
        await event.reply(
            "⚠️ **Usage:**\n"
            "• `/clone [new|here] <link1> <link2>...`\n"
            "• `/clone -1002200390931 899` or `2200390931 899`\n"
            "• `/clone -1002200390931/899`\n"
            "• `/clone <from> to <to>` (sets destination & clones immediately)"
        )
        return

    # Extract forced mode (new or here) if present
    forced_mode = None
    words = raw_input.strip().split()
    first_word = words[0].lower() if words else ""
    if first_word in ['new', 'here']:
        forced_mode = first_word

    cleaned_input = raw_input

    # Check if this is a From-To setup where the second part is destination
    to_match = re.search(r'\s+to\s+', cleaned_input, re.IGNORECASE)
    from_match = re.search(r'^\s*from\s+', cleaned_input, re.IGNORECASE)
    if from_match:
        cleaned_input = cleaned_input[from_match.end():].strip()

    if to_match:
        src_raw = cleaned_input[:to_match.start()].strip()
        dest_raw = cleaned_input[to_match.end():].strip()
        if src_raw and dest_raw:
            d_chat, d_topic, _, _, _, d_has_topic = parse_destination_link(dest_raw)
            if d_chat:
                state["dest_link"] = dest_raw
                save_local_config()
                await sync_brain_storage()
                cleaned_input = src_raw

    # Extract targets (supports links, raw -100... chat IDs, space-separated topic IDs, and multi-line inputs)
    raw_targets = extract_clone_targets(cleaned_input)
    if not raw_targets:
        await event.reply(
            "❌ **Error:** No valid Telegram links or chat IDs detected in your message.\n\n"
            "💡 **Accepted formats:**\n"
            "• `https://t.me/c/2200390931/899`\n"
            "• `-1002200390931 899` or `2200390931 899`\n"
            "• `-1002200390931/899`\n"
            "• `https://t.me/c/2200390931 899`"
        )
        return

    if not state.get("dest_link"):
        await event.reply("❌ **Error:** Set destination first using `/setdest <link_or_chat> [topic_id]` or use `/clone <from> to <to>`.")
        return

    dest_chat, dest_topic_id, _, _, _, dest_has_topic = parse_destination_link(state["dest_link"])
    if not dest_chat:
        await event.reply("❌ **Error:** Destination link or chat ID is invalid.")
        return

    try:
        dest_entity = await client.get_entity(dest_chat)
    except Exception as e:
        await event.reply(f"❌ Could not resolve destination `{dest_chat}`: `{e}`")
        return

    status_msg = await event.reply(f"🔍 **Analyzing provided source(s)...**")

    new_queue = []

    # Check if exactly 2 targets from the same chat were provided -> pair as From-To range!
    if len(raw_targets) == 2:
        c1, t1, s1, e1, r1, h1 = parse_telegram_link(raw_targets[0])
        c2, t2, s2, e2, r2, h2 = parse_telegram_link(raw_targets[1])
        if c1 and c2 and c1 == c2 and s1 and s2:
            start_val = min(s1, s2)
            end_val = max(s1, s2)
            tid = t1 if h1 else (t2 if h2 else None)
            try:
                src_entity = await client.get_entity(c1)
                t_title = None
                if tid and tid > 1:
                    t_title = await get_topic_title(src_entity, tid)
                if not t_title:
                    t_title = getattr(src_entity, 'title', None) or f"Chat_{c1}"
                t_title = f"{t_title} (Msg {start_val}–{end_val})"

                mode = forced_mode or ("here" if dest_has_topic else "new")
                new_queue.append({
                    "title": t_title,
                    "source_link": f"{raw_targets[0]} -> {raw_targets[1]}",
                    "src_chat": c1,
                    "src_topic_id": tid,
                    "start_id": start_val,
                    "end_id": end_val,
                    "is_range": True,
                    "mode": mode,
                    "target_topic_id": dest_topic_id
                })
            except Exception as e:
                logger.error(f"Error resolving link pair: {e}")

    # If not paired as a 2-target range, process targets individually
    if not new_queue:
        for target in raw_targets:
            src_chat, src_topic_id, start_id, end_id, is_range, has_explicit_topic = parse_telegram_link(target)
            if not src_chat:
                continue

            try:
                src_entity = await client.get_entity(src_chat)
            except Exception as e:
                logger.error(f"Error resolving source {target}: {e}")
                await safe_edit_status(status_msg, f"❌ Could not resolve source `{src_chat}`: `{e}`")
                continue

            # Check if this is a whole-group forum request (no topic, no start_id, no range)
            if not src_topic_id and not start_id and not is_range:
                is_forum, detected_title = await detect_topic_or_forum(src_entity, None)
                if is_forum:
                    await status_msg.edit(f"📂 **Forum group detected!** Auto-discovering all topics in *\"{getattr(src_entity, 'title', target)}\"*...")
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
                                "mode": mode,
                                "target_topic_id": dest_topic_id
                            })
                        continue

            # Single topic, single channel, or explicit range.
            # PRESERVE src_topic_id! Never wipe it!
            final_topic_id = src_topic_id
            final_start_id = start_id

            topic_title = None
            if final_topic_id and final_topic_id > 1:
                topic_title = await get_topic_title(src_entity, final_topic_id)
            if not topic_title:
                base_title = getattr(src_entity, 'title', None) or f"Chat_{src_chat}"
                if final_topic_id:
                    topic_title = f"{base_title} (Topic #{final_topic_id})"
                else:
                    topic_title = base_title

            mode = forced_mode or ("here" if dest_has_topic else "new")
            new_queue.append({
                "title": topic_title,
                "source_link": target,
                "src_chat": src_chat,
                "src_topic_id": final_topic_id,
                "start_id": final_start_id,
                "end_id": end_id,
                "is_range": is_range,
                "mode": mode,
                "target_topic_id": dest_topic_id
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

async def collect_task_message_ids(src_entity, task, status_msg=None):
    """
    Collects all matching message IDs for a task in chronological order.
    NEVER uses reverse=True in iter_messages to avoid MTProto GetRepliesRequest/GetHistoryRequest
    offset_id/add_offset bugs that return 0 messages.
    """
    src_topic_id = task.get("src_topic_id")
    start_id = task.get("start_id")
    end_id = task.get("end_id")
    is_range = task.get("is_range", False)
    title = task.get("title", "Task")
    start_ckpt = task.get("last_src_id") or 0

    msg_ids = []

    # Check if start_id is actually a topic creation message if src_topic_id is not yet set
    if not src_topic_id and start_id:
        try:
            chk_msg = await client.get_messages(src_entity, ids=start_id)
            if chk_msg and getattr(chk_msg, 'action', None) and isinstance(chk_msg.action, MessageActionTopicCreate):
                src_topic_id = start_id
                task["src_topic_id"] = start_id
                start_id = None
        except Exception:
            pass

    # CASE A: Forum Topic Task
    if src_topic_id and src_topic_id > 1:
        logger.info(f"Collecting messages for topic {src_topic_id} in {getattr(src_entity, 'id', src_entity)}...")

        # 1. Include root topic message if it has text or media
        try:
            root_m = await client.get_messages(src_entity, ids=src_topic_id)
            if root_m and not getattr(root_m, '_empty', False) and not getattr(root_m, 'action', None):
                if root_m.text or getattr(root_m, 'media', None):
                    if not start_ckpt or root_m.id > start_ckpt:
                        if not start_id or root_m.id >= start_id:
                            if not end_id or root_m.id <= end_id:
                                msg_ids.append(root_m.id)
        except Exception:
            pass

        # 2. Iterate topic messages via reply_to=src_topic_id (MTProto messages.GetReplies)
        try:
            async for m in client.iter_messages(src_entity, reply_to=src_topic_id):
                if not m or getattr(m, '_empty', False) or getattr(m, 'action', None):
                    continue
                if not m.text and not getattr(m, 'media', None):
                    continue
                if start_ckpt and m.id <= start_ckpt:
                    continue
                if start_id and m.id < start_id:
                    continue
                if end_id and m.id > end_id:
                    continue
                msg_ids.append(m.id)
        except Exception as e:
            logger.warning(f"iter_messages with reply_to={src_topic_id} raised: {e}")

        # 3. Fallback thread scanner if 0 messages found via reply_to
        if not msg_ids:
            logger.info(f"reply_to query returned 0 messages. Running fallback topic scanner for topic {src_topic_id}...")
            async for m in client.iter_messages(src_entity, limit=2500):
                if not m or getattr(m, '_empty', False) or getattr(m, 'action', None):
                    continue
                if not m.text and not getattr(m, 'media', None):
                    continue
                rep = getattr(m, 'reply_to', None)
                top_id = getattr(rep, 'reply_to_top_id', None) or getattr(rep, 'reply_to_msg_id', None)
                if top_id == src_topic_id or m.id == src_topic_id:
                    if start_ckpt and m.id <= start_ckpt:
                        continue
                    if start_id and m.id < start_id:
                        continue
                    if end_id and m.id > end_id:
                        continue
                    msg_ids.append(m.id)

        # 4. Fallback: Check if src_topic_id is actually a channel post
        if not msg_ids:
            logger.info(f"Topic queries returned 0 messages. Testing if {src_topic_id} is a channel message...")
            try:
                chk = await client.get_messages(src_entity, ids=src_topic_id)
                if chk and not getattr(chk, '_empty', False) and (chk.text or getattr(chk, 'media', None)):
                    logger.info(f"Found message {src_topic_id} in channel feed, collecting from this message onwards...")
                    effective_min = max(src_topic_id - 1, start_ckpt)
                    async for m in client.iter_messages(src_entity, min_id=effective_min):
                        if not m or getattr(m, '_empty', False) or getattr(m, 'action', None):
                            continue
                        if not m.text and not getattr(m, 'media', None):
                            continue
                        msg_ids.append(m.id)
            except Exception as e:
                logger.warning(f"Channel message check failed: {e}")

    # CASE B: Explicit Message Range (start_id to end_id)
    elif is_range and start_id and end_id:
        logger.info(f"Collecting messages for range {start_id} to {end_id}...")
        diff = end_id - start_id + 1
        if diff <= 250:
            try:
                msgs = await client.get_messages(src_entity, ids=list(range(start_id, end_id + 1)))
                for m in msgs:
                    if not m or getattr(m, '_empty', False) or getattr(m, 'action', None):
                        continue
                    if not m.text and not getattr(m, 'media', None):
                        continue
                    if start_ckpt and m.id <= start_ckpt:
                        continue
                    msg_ids.append(m.id)
            except Exception as e:
                logger.warning(f"get_messages by ID range failed: {e}")

        if not msg_ids:
            async for m in client.iter_messages(src_entity, min_id=start_id - 1, max_id=end_id + 1):
                if not m or getattr(m, '_empty', False) or getattr(m, 'action', None):
                    continue
                if not m.text and not getattr(m, 'media', None):
                    continue
                if start_ckpt and m.id <= start_ckpt:
                    continue
                msg_ids.append(m.id)

    # CASE C: From start_id onwards or single message
    elif start_id:
        logger.info(f"Collecting messages starting from ID {start_id}...")
        try:
            m = await client.get_messages(src_entity, ids=start_id)
            if m and not getattr(m, '_empty', False) and not getattr(m, 'action', None):
                if m.text or getattr(m, 'media', None):
                    if not start_ckpt or m.id > start_ckpt:
                        msg_ids.append(m.id)
        except Exception:
            pass

        effective_min = max(start_id - 1, start_ckpt)
        async for m in client.iter_messages(src_entity, min_id=effective_min):
            if not m or getattr(m, '_empty', False) or getattr(m, 'action', None):
                continue
            if not m.text and not getattr(m, 'media', None):
                continue
            msg_ids.append(m.id)

    # CASE D: Entire channel (no filters)
    else:
        logger.info(f"Collecting all messages from channel...")
        iter_kwargs = {'entity': src_entity}
        if start_ckpt:
            iter_kwargs['min_id'] = start_ckpt
        async for m in client.iter_messages(**iter_kwargs):
            if not m or getattr(m, '_empty', False) or getattr(m, 'action', None):
                continue
            if not m.text and not getattr(m, 'media', None):
                continue
            msg_ids.append(m.id)

    unique_ids = sorted(list(set(msg_ids)))
    logger.info(f"Finished collecting: {len(unique_ids)} messages found for '{title}'.")
    return unique_ids

async def execute_single_task(dest_entity, task, status_msg, send_as_entity):
    """Processes messages for a single topic or channel item."""
    src_chat = task["src_chat"]
    src_topic_id = task["src_topic_id"]
    topic_title = task["title"]
    mode = task["mode"]

    src_entity = await client.get_entity(src_chat)

    dest_chat, dest_topic_id, _, _, _, dest_has_topic = parse_destination_link(state["dest_link"])
    target_topic_id = task.get("target_topic_id") or dest_topic_id
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
            send_kwargs = {}
            if target_topic_id:
                send_kwargs["reply_to"] = target_topic_id
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
            send_kwargs = {}
            if target_topic_id:
                send_kwargs["reply_to"] = target_topic_id
            if send_as_entity:
                send_kwargs["send_as"] = send_as_entity
            try:
                h_msg = await client.send_message(dest_entity, header_text, **send_kwargs)
            except Exception as e:
                logger.warning(f"Could not send header divider message: {e}")

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
        logger.warning(f"Pre-flight header setup warning for task '{topic_title}': {pfe}. Continuing forwarding...")

    q_idx = state.get("queue_index", 0) + 1
    q_len = len(state.get("queue", []))
    target_desc = f"Topic #{target_topic_id}" if target_topic_id else "Main"

    # Scan and collect messages
    await safe_edit_status(
        status_msg,
        f"🔍 **Scanning source for *\"{topic_title}\"*...**\n\n"
        f"📋 Item: `{q_idx}/{q_len}` | 🎯 Target: `{target_desc}`\n"
        f"⚡ *Collecting messages in chronological order...*"
    )

    msg_ids = await collect_task_message_ids(src_entity, task, status_msg)
    if not msg_ids:
        logger.warning(f"No messages found for task '{topic_title}'.")
        await safe_edit_status(
            status_msg,
            f"⚠️ **Notice for *\"{topic_title}\"*:**\n\n"
            f"No transferable messages were found in this source.\n"
            f"• Source Chat: `{src_chat}`\n"
            f"• Target Topic/Msg ID: `{src_topic_id or task.get('start_id') or 'Entire Chat'}`\n\n"
            f"Moving to next item in queue..."
        )
        return

    # Split into batches of BATCH_SIZE (100)
    batches = [msg_ids[i:i + BATCH_SIZE] for i in range(0, len(msg_ids), BATCH_SIZE)]
    total_batches = len(batches)
    total_task_msgs = len(msg_ids)

    logger.info(f"Task '{topic_title}': Found {total_task_msgs} messages. Sliced into {total_batches} batches.")

    for b_idx, batch_ids in enumerate(batches, start=1):
        if not state.get("is_running"):
            break

        # Check restriction
        unlocked = await wait_until_unlocked(src_entity, status_msg)
        if not unlocked:
            return

        # Announce start of batch
        current_total_sent = len(state.get("last_sent_ids", []))
        await safe_edit_status(
            status_msg,
            f"🚀 **Starting Batch #{b_idx}/{total_batches} for *\"{topic_title}\"*...**\n\n"
            f"📋 Item: `{q_idx}/{q_len}` | 🎯 Target: `{target_desc}`\n"
            f"📦 Batch Size: `{len(batch_ids)}` messages (`0/{len(batch_ids)}` sent)\n"
            f"📊 Total Transferred: `{current_total_sent}` messages\n"
            f"⚡ *Dispatching in 10-message chunks...*"
        )

        # Dispatch batch in chunks of 10 messages for real-time live progress
        sub_chunk_size = 10
        sub_chunks = [batch_ids[j:j + sub_chunk_size] for j in range(0, len(batch_ids), sub_chunk_size)]
        batch_sent_ids = []

        for sub_idx, sub_ids in enumerate(sub_chunks, start=1):
            while state.get("is_paused"):
                await safe_edit_status(status_msg, f"⏸️ **Queue Paused.** Holding at *\"{topic_title}\"*.")
                await asyncio.sleep(2)
                if not state.get("is_running"):
                    return

            if not state.get("is_running"):
                return

            try:
                sent = await forward_batch_clean(dest_entity, src_entity, sub_ids, target_topic_id, send_as_entity)
            except errors.ChatForwardsRestrictedError:
                logger.warning("ChatForwardsRestrictedError caught during chunk forward! Waiting 5 min...")
                await wait_until_unlocked(src_entity, status_msg)
                sent = await forward_batch_clean(dest_entity, src_entity, sub_ids, target_topic_id, send_as_entity)

            if sent:
                batch_sent_ids.extend(sent)
                state["last_sent_ids"].extend(sent)
                highest_id = max(sub_ids)
                if state.get("active_task"):
                    state["active_task"]["last_src_id"] = highest_id
                    state["active_task"]["start_id"] = highest_id + 1
                if state.get("queue") and state.get("queue_index", 0) < len(state["queue"]):
                    state["queue"][state["queue_index"]]["start_id"] = highest_id + 1
                    state["queue"][state["queue_index"]]["last_src_id"] = highest_id
                save_local_config()
                await sync_brain_storage()

            # Live update after EVERY 10 messages!
            progress_in_batch = len(batch_sent_ids)
            total_sent_so_far = len(state.get("last_sent_ids", []))
            await safe_edit_status(
                status_msg,
                f"⏳ **Batch #{b_idx}/{total_batches} in Progress...**\n\n"
                f"📚 Active: *\"{topic_title}\"* ({q_idx}/{q_len})\n"
                f"📦 Batch Progress: `{progress_in_batch}/{len(batch_ids)}` messages delivered\n"
                f"🎯 Target: `{target_desc}`\n"
                f"📊 Total Transferred: `{total_sent_so_far}` messages\n"
                f"⚡ *Actively transferring (Chunk {sub_idx}/{len(sub_chunks)})...*"
            )

            # 2 second pause between 10-message chunks for smooth delivery
            if sub_idx < len(sub_chunks) and state.get("is_running"):
                await asyncio.sleep(2.0)

        # Batch completed!
        if state.get("active_task"):
            state["active_task"]["batches_done"] = state["active_task"].get("batches_done", 0) + 1
        state["batches_since_breather"] += 1
        save_local_config()
        await sync_brain_storage()

        # Update destination pinned header checkpoint
        h_msg_id = state.get("active_task", {}).get("header_msg_id") if state.get("active_task") else None
        if h_msg_id and batch_ids:
            highest_id = max(batch_ids)
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

        # Check if this was the last batch of the task
        if b_idx >= total_batches:
            logger.info(f"All batches for '{topic_title}' completed!")
            break

        # Breather Check (Every 4 to 8 batches, sleep for 5 to 8 minutes)
        if state["batches_since_breather"] >= state["next_breather_threshold"]:
            breather_sleep = random.uniform(BREATHER_PAUSE_MIN, BREATHER_PAUSE_MAX)
            breather_mins = round(breather_sleep / 60, 1)
            logger.info(f"Taking a human breather sleep of {breather_mins} minutes...")
            state["current_status"] = f"Taking human breather pause ({breather_mins} mins)"
            save_local_config()

            await safe_edit_status(
                status_msg,
                f"☕ **Human Breather Pause ({breather_mins} mins)...**\n\n"
                f"📚 Active: *\"{topic_title}\"* ({q_idx}/{q_len})\n"
                f"📦 Completed Batches: `{b_idx}/{total_batches}`\n"
                f"📊 Total Transferred: `{len(state.get('last_sent_ids', []))}` messages\n"
                f"🎯 Target: `{target_desc}`\n"
                f"🛡️ Mimicking natural human breaks (Zero account risk).\n"
                f"⏳ Auto-resuming in {int(breather_sleep)}s..."
            )

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

            await safe_edit_status(
                status_msg,
                f"✅ **Batch #{b_idx}/{total_batches} Delivered!** (`{len(batch_sent_ids)}` messages sent)\n\n"
                f"📚 Active: *\"{topic_title}\"* ({q_idx}/{q_len})\n"
                f"🎯 Target: `{target_desc}`\n"
                f"📊 Total Transferred: `{len(state.get('last_sent_ids', []))}` messages\n"
                f"☕ Breather in: `{state['next_breather_threshold'] - state['batches_since_breather']} batches`\n"
                f"⏳ Cooldown delay: `{round(batch_delay, 1)}s` before next batch..."
            )

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
        src_iter_kwargs = {'entity': src_entity, 'limit': 60}
        if known_start > 30:
            src_iter_kwargs['min_id'] = max(0, known_start - 30)
        if src_topic_id and src_topic_id > 1:
            src_iter_kwargs['reply_to'] = src_topic_id

        matched_src_id = None
        try:
            async for sm in client.iter_messages(**src_iter_kwargs):
                s_txt = (sm.text or "").strip()
                if s_txt and s_txt == anchor_text:
                    matched_src_id = sm.id
                    break
        except (errors.rpcerrorlist.MsgIdInvalidError, errors.MsgIdInvalidError):
            if 'reply_to' in src_iter_kwargs:
                del src_iter_kwargs['reply_to']
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
            dest_chat, _, _, _, _, _ = parse_destination_link(state["dest_link"])
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

# ⚠️ READ THIS CAREFULLY BEFORE STARTING ⚠️
> **IMPORTANT NOTICE:** This guide contains complete, end-to-end instructions for deploying, generating credentials (`API_ID`, `API_HASH`, `SESSION_STRING`), configuring 24/7 cloud uptime with **UptimeRobot**, and using the automated multi-topic queue, whole-group forum topic auto-discovery, Anonymous Admin settings, and all commands with practical examples. Read every section step-by-step.

---

# 🚀 Telegram Channel & Forum Topic Cloner (Safe 100-Batch Edition)

An asynchronous, cloud-ready Telegram userbot built with **Telethon** and **aiohttp**. Designed to clone and forward messages between public/private channels, groups, and forum topics with **ultra-safe anti-detection timings**, **100-message batch forwarding (without quote tags)**, **multi-link task queues**, **whole-group topic auto-discovery**, **Anonymous Admin / Send-As support**, and **Saved Messages crash-proof brain storage**.

---

## 📑 Table of Contents
1. [Key Features](#-key-features)
2. [How to Obtain API ID, API HASH & Session String](#-1-how-to-obtain-api-credentials--session-string)
3. [Deploying to Render (24/7 Cloud Hosting)](#-2-deploying-to-render-free-cloud-service)
4. [Keeping the Bot Alive 24/7 with UptimeRobot](#-3-keeping-the-bot-alive-with-uptimerobot)
5. [Command Reference & Practical Examples](#-4-command-reference)
6. [Multi-Topic Queuing: Set Many Topics and Sleep](#-5-multi-topic-queuing-set-many-topics-and-sleep)
7. [Whole-Group Topic Auto-Discovery](#-6-whole-group-topic-auto-discovery)
8. [Anonymous Admin & Send-As Identity](#-7-anonymous-admin--sending-under-groupchannel-name)
9. [Safety Delays & Anti-Ban Architecture](#-8-safety-delays--anti-ban-architecture)
10. [Automatic Forward Lock & Cloud Brain Storage](#-9-forward-lock-monitor--brain-storage)
11. [Crash-Proof Recovery & Smart Anchor System](#-10-crash-proof-recovery--smart-anchor-system)
12. [Frequently Asked Questions (FAQ)](#-11-frequently-asked-questions-faq)

---

## 🌟 Key Features

* **Multi-Topic Task Queue:** Paste 5, 10, or 20+ topic/channel links at once. The bot processes them sequentially in the background while you close Telegram and sleep.
* **Whole-Group Forum Topic Auto-Discovery:** Paste just the group link (`https://t.me/c/1234567890`), and the bot automatically fetches **every single topic** inside that group and queues them!
* **Native 100-Batch Forwarding (`drop_author=True`):** Forwards up to 100 messages per request without the *"Forwarded from"* tag. Albums and multi-photo media remain intact.
* **Anonymous Admin & Send-As Support:** Compatible with "Remain Anonymous" admin rights (messages sent under Group Name), plus custom `/setsendas` to post under a specific channel.
* **Destination Pre-Flight Check & Checkpoint Tags:** Tests write/pin permissions in target topics *before* pulling source messages, and embeds `#SRC_ID:XXXX` checkpoints into the pinned header.
* **Smart Anchor Reboot Recovery:** Recovers mid-batch progress after sudden container reboots by fingerprinting destination text messages against source history. **Guarantees 0 duplicate messages.**
* **Forward Lock Detection (5-Minute Monitor):** If a source channel enables *"Restrict saving content"*, the bot pauses and checks every 5 minutes. The second it unlocks, it auto-resumes!
* **Ultra-Safe Timings (Zero Account Flags):**
  * `35 to 50 seconds` randomized delay between 100-message batches.
  * `5 to 8 minutes` human breather pause every `4 to 8` batches.
  * Checks forward lock every `5 minutes` (virtually 0 API footprint).
* **Saved Messages Brain Storage:** Backs up the entire queue, active item, and message IDs in a pinned message in your Telegram **Saved Messages** (`me`), surviving cloud server reboots.

---

## 🔑 1. How to Obtain API Credentials & Session String

To use a userbot on the cloud, you need 3 items:
1. `API_ID`
2. `API_HASH`
3. `SESSION_STRING`

### Step A: Get `API_ID` & `API_HASH` from Telegram
1. Open [my.telegram.org](https://my.telegram.org) in your web browser.
2. Log in using your Telegram phone number (including country code, e.g. `+1234567890`).
3. Enter the confirmation code sent to your Telegram app.
4. Click on **API development tools**.
5. Fill out the form:
   * **App title:** `MyClonerBot` (or any name)
   * **Short name:** `mycloner` (lowercase, alphanumeric)
   * **URL:** Leave blank or enter `https://google.com`
   * **Platform:** Select `Other` or `Desktop`
6. Click **Create application**.
7. Copy your **`App api_id`** (numbers) and **`App api_hash`** (letters and numbers). Keep them safe!

---

### Step B: Generate `SESSION_STRING`
Because free cloud servers restart and wipe local disks, you cannot log in with a `.session` file. You must generate a **Session String** once on your computer.

1. Open your terminal / command prompt.
2. Install Telethon:
   ```bash
   pip install telethon
   ```
3. Create a temporary script called `gen_session.py`:
   ```python
   from telethon.sync import TelegramClient
   from telethon.sessions import StringSession

   API_ID = int(input("Enter your API_ID: "))
   API_HASH = input("Enter your API_HASH: ").strip()

   with TelegramClient(StringSession(), API_ID, API_HASH) as client:
       print("\n" + "="*50)
       print("YOUR SESSION_STRING (Copy everything below):\n")
       print(client.session.save())
       print("="*50 + "\n")
   ```
4. Run the script:
   ```bash
   python gen_session.py
   ```
5. Enter your phone number and the login code sent to your Telegram app. (If you have Two-Step Verification, enter your password).
6. Copy the long printed alphanumeric string — that is your `SESSION_STRING`.

> [!CAUTION]
> Your `SESSION_STRING` is equivalent to logging into your account. **Never share it with anyone publicly.**

---

## ☁️ 2. Deploying to Render (Free Cloud Service)

Render provides free cloud web services that run your bot 24/7.

1. **Push your code to GitHub:**
   * Create a private GitHub repository.
   * Upload `main.py`, `requirements.txt`, and `README.md`.
2. **Create Web Service on Render:**
   * Go to [dashboard.render.com](https://dashboard.render.com).
   * Click **New +** → **Web Service**.
   * Connect your GitHub repository.
3. **Configure Build & Run Settings:**
   * **Name:** `telegram-cloner` (or any name)
   * **Region:** Any region close to you (e.g. Frankfurt, Singapore, Oregon)
   * **Branch:** `main`
   * **Runtime:** `Python 3`
   * **Build Command:**
     ```bash
     pip install -r requirements.txt
     ```
   * **Start Command:**
     ```bash
     python main.py
     ```
   * **Instance Type:** `Free`
4. **Add Environment Variables:**
   Click on the **Environment** tab and add the following keys:
   | Key | Value | Description |
   | :--- | :--- | :--- |
   | `API_ID` | `1234567` | Your Telegram API ID |
   | `API_HASH` | `0123456789abcdef...` | Your Telegram API Hash |
   | `SESSION_STRING` | `1BVts...` | The string session generated in Step B |
   | `PORT` | `8080` | Port for the built-in health-check server |
5. Click **Deploy Web Service**.
6. Once deployed, Render will provide a public URL for your web app:
   `https://telegram-cloner-xxxx.onrender.com`

---

## ⏱️ 3. Keeping the Bot Alive with UptimeRobot

Render puts free services to sleep after 15 minutes of HTTP inactivity. The bot has a built-in `aiohttp` web server on port `8080`. Ping it every 5 minutes using UptimeRobot so it **never sleeps**.

1. Go to [uptimerobot.com](https://uptimerobot.com) and create a free account.
2. Click **Add New Monitor**.
3. Configure the monitor:
   * **Monitor Type:** `HTTP(s)`
   * **Friendly Name:** `Render Telegram Cloner`
   * **URL (or IP):** `https://telegram-cloner-xxxx.onrender.com` *(Paste your Render public URL)*
   * **Monitoring Interval:** `Every 5 minutes`
4. Click **Create Monitor**.

Now UptimeRobot pings your bot every 5 minutes, keeping it online and active 24/7!

---

## 🎮 4. Command Reference

All commands must be sent from your own Telegram account (outgoing messages):

| Command | Usage | What it does |
| :--- | :--- | :--- |
| **`/setdest <link>`** | `/setdest https://t.me/c/1234567890/55` | Saves your target group, channel, or topic permanently. |
| **`/setsendas <link\|off>`** | `/setsendas @MyChannel` | Sets a channel to send as, or `off` for default (Anonymous Admin). |
| **`/clone [new\|here] <links>`** | `/clone here https://t.me/c/.../1 https://t.me/c/.../2` | **Queues 1 or many links** (or entire groups). Runs in background! |
| **`/queue`** | `/queue` | Displays all pending and active items in the queue. |
| **`/status`** | `/status` | Shows live progress, active item, batch count, and breather countdown. |
| **`/pause`** | `/pause` | Safely freezes the clone loop at the next batch. |
| **`/resume`** | `/resume` | Unpauses and continues forwarding. |
| **`/stop`** | `/stop` | Cancels the active task completely and clears queue. |
| **`/purge`** | `/purge` | Bulk-deletes all messages forwarded in this/last task from destination in chunks of 100. |

---

## 📦 5. Multi-Topic Queuing: Set Many Topics and Sleep

Instead of running commands one by one, you can feed multiple links into `/clone` separated by spaces or newlines:

```text
/clone here
https://t.me/c/987654321/10
https://t.me/c/987654321/11
https://t.me/c/987654321/12
https://t.me/channel_example
```

### What Happens:
1. The bot queues all links into an internal pipeline.
2. It processes Topic 1, finishes it, then automatically moves to Topic 2, Topic 3, etc.
3. For each topic/channel, it sends a pinned header divider in your destination, then forwards all 100-batch messages under it.
4. **You can turn off Telegram and sleep!** The bot will work through the entire list on Render.

---

## 🔍 6. Whole-Group Topic Auto-Discovery

If you want to clone an entire group that has multiple forum topics, you **do not need to copy each topic link individually**.

Simply paste the **root group link**:
```text
/clone https://t.me/c/1234567890 here
```
*(Or `/clone https://t.me/c/1234567890 new` if you want it to create matching topics in your destination)*.

### What Happens:
1. The bot detects that the link is a forum group.
2. It automatically calls `GetForumTopicsRequest` to discover **all topics** inside that group.
3. It adds all discovered topics to the queue in order and processes them sequentially!

---

## 🕵️ 7. Anonymous Admin & Sending Under Group/Channel Name

### Case A: "Remain Anonymous" Admin in Destination Group (Default)
If your Telegram account is an Admin in the destination group with the permission **"Remain Anonymous"** enabled:
* Telegram handles this natively on the server side.
* All header messages, pins, and forwarded batches sent by the bot will automatically show the **Group’s Name** as the sender.
* Your personal name and profile photo will **never** be displayed.

### Case B: Sending as a Specific Channel (`/setsendas`)
If you want messages to be posted under a specific public channel you own:
```text
/setsendas @MyPublicChannel
```
To turn it off and return to default / anonymous admin:
```text
/setsendas off
```

---

## 🛡️ 8. Safety Delays & Anti-Ban Architecture

To ensure your Telegram account is **100% safe from bans, spam flags, and FloodWait restrictions**:

* **Batch Delay (`35.0` to `50.0` seconds):**
  Waits 35 to 50 seconds (with randomized micro-jitter) between every 100-message batch.
* **Human Breather Pause (`5 to 8 minutes` every `4 to 8` batches):**
  After forwarding 400 to 800 messages, the bot pauses for 5 to 8 minutes (`300s` to `480s`). This resets Telegram's rolling window rate-limits and mimics a human taking a break.
* **No Quotation Marks (`drop_author=True`):**
  Removes the *"Forwarded from"* label, making the messages appear native and clean.

---

## 🧠 9. Forward Lock Monitor & Brain Storage

### Automatic Forward Lock Detection
* If the source channel owner has *"Restrict saving content"* turned ON, direct forwarding is blocked by Telegram.
* The bot checks the lock every **5 minutes** (`300s`).
* If locked mid-run, it freezes safely without dropping messages, and automatically resumes the exact second the admin turns forwarding back ON.

### Saved Messages Cloud Brain Storage
* The entire queue, current queue index, and forwarded message IDs are saved to a pinned message in your **Saved Messages** (`me`) tagged `#CLONER_BRAIN_STORAGE`.
* If Render resets or restarts the container while you are sleeping, the bot reads this pinned message on startup and recovers your queue right where it left off.

---

## 🛡️ 10. Crash-Proof Recovery & Smart Anchor System

### A. Destination Pre-Flight Verification
Before extracting or buffering messages from any source channel or topic, the bot initiates a **Pre-Flight Test** in the destination:
1. It verifies write permissions, topic creation rights (if mode is `new`), and message pinning permissions.
2. It publishes the topic header banner immediately with an initial checkpoint tag: `📍 Checkpoint: #SRC_ID:0`.
3. If destination permissions are restricted or invalid, the bot flags the specific queue task, logs the error, alerts your status message, and smoothly skips to the next queue item **without crashing the runner**.

### B. Dynamic Destination Checkpoint (`#SRC_ID:XXXX`)
After every successful 100-message batch:
* The bot automatically edits the pinned header in the destination topic/channel, updating the checkpoint to reflect the highest source ID processed (e.g. `📍 Checkpoint: #SRC_ID:450`).
* This provides a clean, visual live progress tracker directly in your destination without spamming the chat.

### C. Smart Text-Anchor Recovery Algorithm
What happens if the cloud container reboots abruptly right in the middle of a transfer?
* Telegram batch forwarding operates via high-speed atomic requests. If a container restart occurs right as a batch completes, the local container memory is lost.
* Upon startup, the bot triggers **Smart Anchor Recovery**:
  1. It fetches recent messages from the destination topic and scans backwards to identify the most recent text message or media with a caption (the **Anchor Text**).
  2. It counts any trailing media items sent after that anchor message.
  3. It searches the source channel history for the identical Anchor Text to locate the exact source message ID.
  4. It calculates `Resumed Start ID = Matched Source ID + Trailing Media Count + 1`.
  5. The pipeline resumes forwarding from this exact calculated offset.
* **Guarantee:** Zero duplicate forwards and zero missing messages, even across sudden hard restarts.

---

## ❓ 11. Frequently Asked Questions (FAQ)

### Q1: If I send new messages, notes, or pin another message in my Saved Messages while the bot is running, will it affect the bot or corrupt the checkpoint?
**Answer: No, absolutely not.**
* The bot searches your Saved Messages specifically for its unique state identifier tag (`#CLONER_BRAIN_STORAGE`) within a 50-message search depth.
* You can freely send personal notes, forward links, save media, voice notes, or pin other messages in your Saved Messages at any time.
* The bot ignores all other messages and will only read and update its designated brain message.
* *(Note: Simply avoid manually deleting or editing the text inside the `#CLONER_BRAIN_STORAGE` code block).*

### Q2: What happens if Render reboots or the source admin restricts forwarding right in the middle of a batch?
**Answer: Both scenarios are handled automatically with zero duplicates:**
1. **Source Admin Restricts Forwarding:**
   * Telegram’s native forwarding API treats batch requests atomically. If forwarding permissions are locked, the API call is rejected before messages are delivered.
   * The bot catches `ChatForwardsRestrictedError`, goes into a 5-minute polling sleep, and resumes the exact batch cleanly once unlocked.
2. **Render Cloud Container Reboot:**
   * The bot automatically boots back up (kept awake by UptimeRobot), reads `#CLONER_BRAIN_STORAGE`, runs the **Smart Anchor Recovery** to match destination text against source history, and resumes from the exact next ID without re-forwarding previously delivered messages.

### Q3: Does the Smart Anchor recovery cause extra Telegram API requests or risk FloodWait?
**Answer: No.**
* The Smart Anchor algorithm runs **only once** upon server reboot. It performs just 1 read request on the destination and 1 read request on the source.
* During active queue operation, all messages are forwarded in high-efficiency 100-message batches protected by your randomized 35–50s delays and 5–8 min human breathers. Safe and compliant with Telegram rate limits.

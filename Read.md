# Telegram Channel & Group History Cloner Userbot

An asynchronous Telegram userbot built with **Telethon** and **aiohttp**, designed to duplicate, batch forward, and organize message histories between public or private Telegram channels, groups, and forum topics. 

The bot includes safety delays, dynamic slot management, auto-recovery for FloodWait errors, roll-back deletion capabilities, and an embedded health-check web server optimized for 24/7 cloud deployments on **Render** paired with **UptimeRobot**.

---

## Key Features

- **Bounded Tasks & Open-Ended Batches:** Transfer explicit message ranges (e.g., `100-250`) with live percentage bars, or run unbounded batch streams forward from a starting message ID.
- **Forum & Topic Support:** Parses standard channel links, private join links (`/c/`), and modern Telegram supergroup topics/threads.
- **Dynamic Slot System:** Configure multi-stage transfer queues. Modify, add, or remove slots on the fly even while another sequence is actively running.
- **Custom Section Headers:** Automatically send introductory divider titles or custom text before each slot's payload starts transferring.
- **Rollback / Purge Mechanism (`/delete`):** Tracks all transferred message IDs to disk and allows one-command bulk deletion from destination channels in chunks of 100.
- **FloodWait & Rate-Limit Shield:** Employs randomized delay buffers (`2.5s` – `5.5s`) and catches Telegram API FloodWait exceptions, pausing until the lock expires before auto-resuming.
- **Cloud-Ready Web Server:** Ships with a background `aiohttp` server exposing a health-check endpoint on port `8080` (or `$PORT`), enabling keep-alive pings on free-tier container platforms.

---

## Command Reference

All commands must be executed by the logged-in user account (outgoing messages).

| Command | Syntax / Format | Description |
| :--- | :--- | :--- |
| `/start` | `/start` | Displays current status, active target destination, and loaded slots. |
| `/setdest` | `/setdest <link>` | Sets the target channel or topic where messages will be cloned. |
| `/task` | `/task [link/start-end]`<br>`/task<num> [link/start-end]` | Queues a bounded message range. Auto-assigns or targets an explicit slot. |
| `/batch` | `/batch [starting-link]`<br>`/batch<num> [starting-link]` | Queues an open-ended clone starting from the specified message ID. |
| `/mes` / `/meb` | `/mes<slot> <header_text>` | Sets a custom banner/text to send right before processing that slot. Send without text to remove. |
| `/preview` | `/preview` | Summarizes all configured slots and pending operations before running. |
| `/remove` | `/remove <slot>` | Removes a specific slot and cleans its queued configuration. |
| `/pause` | `/pause` | Safely pauses the transfer loop at the next message iteration. |
| `/resume` | `/resume` | Unpauses and continues the operational pipeline. |
| `/delete` | `/delete task<slot>` | Purges all messages copied by that specific slot from the destination channel. |
| `/clear` | `/clear` | Wipes all configured slots (preserves destination link). |
| `/done` | `/done` | Kicks off pipeline execution across all queued slots sequentially. |

---

## Link Format Support

The parser accepts all standard Telegram link styles:

- **Public Channels:** `https://t.me/channel_username/1234`
- **Private Channels:** `https://t.me/c/1234567890/1234`
- **Forum Topics:** `https://t.me/c/1234567890/topic_id/1234`
- **Range Syntax (Tasks only):** `https://t.me/c/1234567890/100-250`

---

## Project Structure

Ensure your repository has the following files before deployment:

```text
├── main.py              # The userbot code provided
├── requirements.txt     # Python dependencies
├── Procfile             # Process file for Render (optional, but recommended)
└── README.md            # Repository documentation

requirements.txt
telethon
aiohttp

Generating Your String Session
Because free cloud containers reset their local disks on every reboot, you must authenticate using a String Session instead of an interactive terminal login.
 * Obtain your API_ID and API_HASH from my.telegram.org under API development tools.
 * Run this short script locally on your machine once to generate the session string:
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = 1234567          # Replace with your API ID
API_HASH = "your_api_hash" # Replace with your API Hash

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\nSAVE THIS SESSION STRING SECURELY:\n")
    print(client.session.save())

 * Copy the printed alphanumeric string; you will paste it into your deployment environment variables as SESSION_STRING.
Deploying to Render (Free Web Service)
Render provides free instances that allow HTTP access, enabling external ping services to keep the container online.
 * Push to GitHub: Push your code (main.py, requirements.txt) to a GitHub repository.
 * Create Web Service on Render:
   * Go to your Render Dashboard.
   * Click New + > Web Service.
   * Connect your GitHub repository.
 * Configure Settings:
   * Name: telegram-cloner-bot (or any preferred identifier)
   * Region: Choose the region closest to you.
   * Branch: main (or master)
   * Runtime: Python 3
   * Build Command: pip install -r requirements.txt
   * Start Command: python main.py
   * Plan Type: Select Free.
 * Configure Environment Variables:
   Under the Environment tab, add the following key-value pairs:
   | Key | Value | Description |
   |---|---|---|
   | API_ID | 1234567 | Your Telegram API ID from my.telegram.org |
   | API_HASH | abcdef1234567... | Your Telegram API Hash from my.telegram.org |
   | SESSION_STRING | 1BVts... | The string session generated in the step above |
   | PORT | 8080 | Port for the built-in aiohttp health check server |
 * Click Create Web Service and wait for deployment logs to display:
   Render Userbot container instance actively running.

 * Copy your public Render application URL (e.g., https://telegram-cloner-bot.onrender.com).
Keeping the Bot Alive with UptimeRobot
Render's free tier spins down web services after 15 minutes of inbound HTTP inactivity. Set up a free monitor on UptimeRobot to ping the built-in HTTP server every 5 minutes.
 * Create a free account at UptimeRobot.
 * From the dashboard, click Add New Monitor.
 * Fill in the monitor settings:
   * Monitor Type: HTTP(s)
   * Friendly Name: Render Telegram Bot Ping
   * URL (or IP): https://your-service-name.onrender.com
   * Monitoring Interval: Every 5 minutes
 * Click Create Monitor.
UptimeRobot will now send an HTTP GET request to / every 5 minutes. The embedded aiohttp server will respond with 200 OK, preventing Render from putting your userbot to sleep during active or pending transfers.
Operational Walkthrough
A standard workflow for copying a series of materials into a target channel:
 * Set target:
   /setdest [https://t.me/c/1987654321/1](https://t.me/c/1987654321/1)

 * Add bounded slot:
   /task [https://t.me/c/1234567890/50-120](https://t.me/c/1234567890/50-120)

 * Attach title banner:
   /mes1 Lecture Series Part 1

 * Preview:
   /preview

 * Start:
   /done

 * Cancel / Purge (if mistakes were made):
   /delete task1

Disclaimers & Fair Use
 * This software acts as an automated Telegram client (Userbot). Ensure you comply with Telegram's Terms of Service.
 * Respect channel copyright and data ownership when duplicating materials across chats.
 * Maintain reasonable delay limits (BASE_DELAY_MIN / BASE_DELAY_MAX) to avoid temporary or permanent Telegram API bans.


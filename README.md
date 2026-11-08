# WAP (WhatsApp Playwright Framework API & Control Center)

> **What-You-See-Is-What-You-Test (WYSIWYT) Administration, Automation & Control Engine for WhatsApp Web**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![Playwright](https://img.shields.io/badge/playwright-1.40+-green.svg)](https://playwright.dev)

WAP is a containerized, browser-backed REST API and web administration suite for WhatsApp Web built with **Playwright** and **FastAPI**. It is engineered as a visual, *"What-You-See-Is-What-You-Test"* companion and alternative to binary socket engines, giving administrators full visual proofing, historical call extraction, automated media maintenance, and an intelligent broadcast suite.

---

## 🌟 Key Capabilities

### 1. 📞 Historical Call Log Auditing (WAP Exclusive)
* Extracts historical call records directly from WhatsApp Web's visual Calls tab and Call Info drawer:
  * **Exact dialed / caller phone number** (even for non-synced contacts).
  * **Call duration timers** (`14m 32s`, `0s (Missed)`).
  * Direction (`incoming`, `outgoing`) and media type (`audio`, `video`).
  * Status classifications: `Answered (Web)` vs `Missed`.
* Configurable call extraction modes: `all`, `whitelist`, or `blacklist` contact targeting (`GET` & `POST /api/config/call-extraction`).

### 2. 🎁 Greetings & Multi-Recipient Sequential Broadcast
* **Email-Style Recipient Chips**: Quick multi-contact selection with instant autocomplete search.
* **Optional / Blank Captions**: Supports image-only greetings without forcing text, or message templates with dynamic `{name}` interpolation.
* **Balanced Image Randomizer & Shuffler**: Uses uniform Fisher-Yates distribution to evenly distribute $N$ images across $M$ contacts (e.g., 5 cards across 10 contacts = exactly 2 contacts per card).
* **AI Magic Card Generation**: Generate thematic greeting cards with zero API keys required (powered by Flux via Pollinations.ai with fallback models). Includes one-click festive tag recommendations.
* **Dynamic Name Personalization (`/api/media/personalize`)**:
  * Renders contact names onto images with frosted glass plates and golden calligraphy.
  * Configurable honorific suffixes (`"and Family"`, `"& Family"`, `"et al."`, `"Ji"`, or `"None"`).
  * Contacts without names automatically receive clean, unbranded generic greeting cards.
* **Resilient Disruption Handling**:
  * **Pause & Resume**: Pause mid-broadcast cleanly without interrupting active messages.
  * **Safe Abort**: Stop remaining dispatches at any moment.
  * **Retry Failed / Remaining**: Re-dispatches only unsent or failed contacts; already-delivered contacts never receive duplicate greetings.
  * Real-time status badges per recipient (`⏳ Pending`, `🚀 Sending...`, `✅ Delivered`, `❌ Failed`).

### 3. 🖥️ Unified Web Control Center & Dashboard (Port 3001)
* Consolidated single pane of glass for all administrative workflows:
  * **Live Viewport Proofing**: Real-time headless browser captures (`GET /api/screenshot`).
  * **Dual Engine Switching**: Seamlessly toggle between WAP and WAHA with confirmation dialogs and auto-redirecting login tabs.
  * **Supervisor Process Orchestration**: Monitor background daemon state (`RUNNING`, `STOPPED`), PID, and uptime, with restart controls and auto-refreshing terminal logs.
  * **Visual Schedule Editor**: Interactive cards for adding, editing, and deleting scheduled jobs saved safely in `user_schedules.json` without exposing core configuration.
  * **Interactive API Docs**: Built-in Swagger UI at `/docs` and ReDoc at `/redoc`.

### 4. 🧹 Group Media Lifecycle Management
* Automatically scans group conversations and purges high-volume media (images, videos, attachments) older than a specified retention window (e.g. 24h, 48h, 7 days) to conserve disk space (`/api/maintenance/auto-clean-media`).

### 5. 💬 Native DOM Keystroke Emulation & Ad-Hoc Sandbox
* Types messages directly into WhatsApp Web's Lexical editor to emit genuine keyboard DOM events, minimizing anti-bot heuristics.
* Ad-hoc test message sandbox for testing delivery without triggering background schedules.

---

## 🆚 Why WAP alongside WAHA?

| Capability | WAHA (HTTP WebSocket API) | WAP (Playwright Visual Engine) |
| :--- | :--- | :--- |
| **Protocol Layer** | Multi-Device Binary WebSockets | Visual DOM via Playwright Chromium |
| **Historical Call Logs** | ❌ Not available over companion socket | ✅ Extracted from visual Calls tab & drawer |
| **Dialed Numbers & Duration**| ❌ Not exposed in WebSocket sync | ✅ Parsed directly from Call Info DOM |
| **Visual Telemetry** | Viewport stream or screenshots | ✅ Native viewport capture (`/api/screenshot`) |
| **Group Media Auto-Purge** | Limited to message revokes | ✅ Dedicated DOM & API media scanner |
| **Greeting Card Personalization**| ❌ External service needed | ✅ Built-in PIL typography & AI generation |
| **Broadcast Flow Control** | Sequential raw loop | ✅ Pause, resume, abort, and retry unsent |

---

## 🚀 Quickstart

### Option A: Using Docker (Recommended)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/hariseenivasan/wap.git
   cd wap
   ```

2. **Start the service**:
   ```bash
   docker-compose up -d
   ```

3. **Open the Control Center**:
   Open `http://localhost:3001/` in your browser.
   * View live QR code or generate an 8-character phone pairing code.
   * Scan or pair your phone under **WhatsApp > Linked Devices > Link a Device**.

4. **Verify Health**:
   ```bash
   curl http://localhost:3001/api/status
   ```

---

### Option B: Local Setup (Python 3.10+)

1. **Install dependencies**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Start the API Server & Control Center**:
   ```bash
   uvicorn src.server:app --host 0.0.0.0 --port 3001
   ```

3. **Explore Documentation**:
   * **Web Control Center**: `http://localhost:3001/`
   * **Interactive Swagger UI**: `http://localhost:3001/docs`
   * **ReDoc**: `http://localhost:3001/redoc`

---

## 📡 Core API Reference

### 1. Health, Session & Viewport

#### `GET /api/status`
Returns the operational health, browser engine, and authentication status.
```json
{
  "status": "WORKING",
  "engine": "playwright",
  "authenticated": true,
  "version": "1.1.0",
  "uptimeSeconds": 3600
}
```
*Possible Status Values*: `STARTING`, `SCAN_QR_CODE`, `WORKING`, `STOPPED`.

#### `GET /api/qr`
Retrieves the authentication QR code.
* **Query Parameters**: `format=image` (default PNG stream) or `format=json`.

#### `GET /api/screenshot`
Captures a live PNG screenshot of the internal browser viewport for visual verification.

---

### 2. Messaging & Media

#### `POST /api/sendText`
Sends a text message using native DOM keystroke emulation.
```json
{
  "chatId": "1234567890@c.us",
  "text": "Hello from WAP!"
}
```

#### `POST /api/sendImage`
Sends an image with an optional caption. If caption is omitted or empty, the image is dispatched cleanly without text.
```json
{
  "chatId": "1234567890@c.us",
  "file_path": "/path/to/image.jpg",
  "caption": "Optional greeting caption"
}
```

#### `POST /api/media/upload`
Uploads an image for greeting distribution or testing (`multipart/form-data`).

#### `POST /api/media/personalize`
Dynamically overlays a contact's name onto an image card with frosted glass typography:
```json
{
  "file_path": "/path/to/base_card.jpg",
  "name": "Jane Doe",
  "suffix": "and Family",
  "greeting_text": "Good Morning"
}
```
*Note*: If `greeting_text` is empty, the nameplate is centered prominently without forcing filler text.

#### `POST /api/media/generate-ai`
Generates thematic greeting cards on demand:
```json
{
  "prompt": "Diwali celebration, golden lamps, rangoli",
  "count": 3
}
```

---

### 3. Historical Call Extraction (WAP Exclusive)

#### `GET /api/calls`
Extracts historical calls from WhatsApp Web's visual interface.
* **Query Parameters**:
  * `limit` (int, default: 25): Maximum records to retrieve.
  * `includeDetails` (bool, default: true): Opens Call Info drawer for exact dialed numbers and duration.
  * `missedOnly` (bool, default: false): Filter to missed calls.
```json
[
  {
    "id": "call_0_1793952100",
    "contactName": "Alex Carter",
    "phoneNumber": "+1 234 567 8900",
    "type": "audio",
    "direction": "incoming",
    "status": "answered",
    "isMissed": false,
    "duration": "12m 45s",
    "durationSeconds": 765,
    "timestamp": "Friday"
  }
]
```

#### `GET /api/config/call-extraction` & `POST /api/config/call-extraction`
Configures targeted extraction rules (`filter_mode`: `all`, `whitelist`, `blacklist`, target contacts, and limit).

---

### 4. Schedules Management

* `GET /api/schedules`: Lists all configured message schedules.
* `POST /api/schedules/add`: Appends a new schedule item.
* `PUT /api/schedules/{index}`: Updates an existing schedule.
* `DELETE /api/schedules/{index}`: Removes a schedule.
* `POST /api/schedules/save`: Saves schedule collection safely to `user_schedules.json`.

---

### 5. Group Media Maintenance

#### `POST /api/maintenance/auto-clean-media`
Scans group chats and deletes media attachments older than the threshold:
```json
{
  "chatId": "Project Updates Group",
  "olderThanHours": 48,
  "deleteForEveryone": false
}
```

---

## 🛠️ Standalone Admin Scripts

Three automation utilities are provided in `examples/`:
1. **Auto-Purge Group Media** (`examples/auto_clean_group_media.py`):
   ```bash
   python examples/auto_clean_group_media.py --group "Team Chat" --hours 48
   ```
2. **Export Call Logs to JSON** (`examples/export_call_logs.py`):
   ```bash
   python examples/export_call_logs.py --output calls.json --limit 50
   ```
3. **Auto-Greet Incoming Inquiries** (`examples/auto_greet.py`):
   ```bash
   python examples/auto_greet.py --interval 10
   ```

---

## ⚖️ License

MIT License. See [LICENSE](LICENSE) for details.

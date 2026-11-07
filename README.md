# WAP (WhatsApp Playwright Framework API)

> **What-You-See-Is-What-You-Test (WYSIWYT) Admin Engine for WhatsApp Web**

WAP is a containerized, browser-backed REST API for WhatsApp Web automation built with **Playwright** and **FastAPI**. It is designed as a visual, *"What-You-See-Is-What-You-Test"* implementation of the WAHA API contract.

While reverse-engineered WebSocket clients (like WAHA) operate at the binary wire level, WAP drives the actual **WhatsApp Web visual DOM**. This allows developers and administrators to perform operations that protocol-level clients cannot:
* **Historical Call Log Extraction**: Scrapes the visual Calls tab to extract exact call durations, dialed phone numbers, direction, and audio/video status.
* **Group Media Lifecycle Management**: Scans group media and automatically purges old images/videos after a configurable retention threshold.
* **Visual Audit & Screenshot Proofing**: Live viewport screenshots (`/api/screenshot`) and QR capture for visual debugging.
* **Auto-Greeting & Message Dispatch**: Native Lexical editor keystroke typing and outgoing message bubble delivery verification.

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
   Or directly via Docker:
   ```bash
   docker run -d -p 3001:3001 -v $(pwd)/session:/app/userdata hariseenivasan/wap
   ```

3. **Scan the QR Code**:
   Open `http://localhost:3001/api/qr` in your browser and scan the QR code with WhatsApp (**Linked Devices > Link a device**).

4. **Verify Session Health**:
   ```bash
   curl http://localhost:3001/api/status
   ```

---

### Option B: Local Setup (Python 3.10+)

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Start the API server**:
   ```bash
   uvicorn src.server:app --host 0.0.0.0 --port 3001
   ```

3. **Interactive Documentation**:
   Interactive Swagger documentation is automatically available at:
   * **Swagger UI**: `http://localhost:3001/docs`
   * **ReDoc**: `http://localhost:3001/redoc`

---

## 📡 API Reference

### 1. Health & Authentication

#### `GET /api/status`
Returns the operational health and authentication state.

* **Response `200 OK`**:
```json
{
  "status": "WORKING",
  "engine": "playwright",
  "authenticated": true,
  "version": "1.0.0",
  "uptimeSeconds": 1420
}
```
*Possible Status Values*: `STARTING`, `SCAN_QR_CODE`, `WORKING`, `STOPPED`.

#### `GET /api/qr`
Retrieves the authentication QR code.
* **Query Parameters**: `format=image` (default) or `format=json`.
* **Response**: Binary PNG stream or `{ "qr": "data:image/png;base64,..." }`.

#### `GET /api/screenshot`
Captures a live PNG screenshot of the internal browser viewport for visual verification.
* **Response**: Binary `image/png` stream.

---

### 2. Messaging

#### `POST /api/sendText`
Sends a text message using native DOM keystroke emulation.

* **Request**:
```json
{
  "chatId": "1234567890@c.us",
  "text": "Hello from WAP API!"
}
```
* **Response `201 Created`**:
```json
{
  "success": true,
  "messageId": "wap_msg_1793952000000",
  "chatId": "1234567890@c.us",
  "timestamp": 1793952000
}
```

#### `GET /api/chats`
Lists recent conversations with unread counts.
* **Query Parameters**:
  * `limit` (int, default: 20)
  * `unreadOnly` (bool, default: false)

#### `GET /api/chats/{chat_id}/messages`
Retrieves recent messages from a conversation.
* **Query Parameters**:
  * `limit` (int, default: 20)

#### `DELETE /api/chats/{chat_id}/messages/{message_id}`
Deletes or revokes a message in the active chat.

---

### 3. Call Log Extraction (WAP Exclusive)

#### `GET /api/calls`
Extracts historical call records from the visual Calls tab. When `includeDetails=true` is enabled, WAP clicks each call item to open the Call Info drawer and extract the exact dialed phone number and call duration.

* **Query Parameters**:
  * `limit` (int, default: 20): Maximum number of call records to retrieve.
  * `includeDetails` (bool, default: true): Open the Call Info drawer for duration and phone number.
  * `missedOnly` (bool, default: false): Filter to only missed/unanswered calls.
  * `type` (string, optional): `"audio"` or `"video"`.

* **Response `200 OK`**:
```json
[
  {
    "id": "call_0_1793952100",
    "contactName": "Alice Smith",
    "phoneNumber": "+1 234 567 8900",
    "type": "video",
    "direction": "incoming",
    "status": "answered",
    "isMissed": false,
    "duration": "14m 32s",
    "durationSeconds": 872,
    "timestamp": "Yesterday, 7:42 PM"
  },
  {
    "id": "call_1_1793952050",
    "contactName": "Bob Jones",
    "phoneNumber": "+1 987 654 3210",
    "type": "audio",
    "direction": "incoming",
    "status": "missed",
    "isMissed": true,
    "duration": "0s",
    "durationSeconds": 0,
    "timestamp": "Today, 12:31 PM"
  }
]
```

---

### 4. Group Media Lifecycle Management

#### `POST /api/maintenance/auto-clean-media`
Scans a group chat, locates image and video messages older than a threshold, and deletes them.

* **Request**:
```json
{
  "chatId": "Project Workspace",
  "olderThanHours": 48,
  "deleteForEveryone": false
}
```
* **Response `200 OK`**:
```json
{
  "success": true,
  "chatId": "Project Workspace",
  "deletedCount": 14
}
```

---

## 🛠️ Developer Examples

Three standalone developer examples are included in the `examples/` directory:

1. **Auto-Purge Group Media** (`examples/auto_clean_group_media.py`):
   ```bash
   python examples/auto_clean_group_media.py --group "Project Workspace" --hours 48
   ```

2. **Export Call Logs** (`examples/export_call_logs.py`):
   ```bash
   python examples/export_call_logs.py --output my_calls.json --limit 50
   ```

3. **Auto-Greet Incoming Messages** (`examples/auto_greet.py`):
   ```bash
   python examples/auto_greet.py --interval 10
   ```

---

## ⚖️ License

MIT License. See [LICENSE](LICENSE) for details.

import os
import time
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.browser_manager import BrowserManager

USER_DATA_DIR = os.getenv("USER_DATA_DIR", "./userdata")
browser = BrowserManager(user_data_dir=USER_DATA_DIR)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize Playwright browser daemon
    try:
        await browser.initialize()
    except Exception as e:
        print(f"[WAP Startup Notice]: Browser init postponed: {e}")
    yield
    # Shutdown: cleanly close browser context to flush LevelDB
    await browser.shutdown()

app = FastAPI(
    title="WAP - WhatsApp Playwright API",
    description="A visual, browser-backed admin REST API for WhatsApp Web automation (WYSIWYT implementation of WAHA).",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Models -----------------

class SendTextRequest(BaseModel):
    chatId: str = Field(..., description="Target phone number or group ID, e.g. 1234567890@c.us", example="1234567890@c.us")
    text: str = Field(..., description="Text message content", example="Hello! Testing automated message.")

class SendMediaRequest(BaseModel):
    chatId: str = Field(..., example="1234567890@c.us")
    fileUrl: str = Field(..., example="http://localhost:3001/sample.png")
    caption: Optional[str] = Field(None, example="Optional image caption")

class CleanMediaRequest(BaseModel):
    chatId: str = Field(..., description="Target Group Name or JID", example="Project Team Discussion")
    olderThanHours: int = Field(48, description="Purge media older than this threshold", example=48)
    deleteForEveryone: bool = Field(False, description="Attempt 'Delete for everyone' if admin")

# ----------------- Routes -----------------

@app.get("/api/status", summary="Session & Engine Health")
async def get_status():
    status = await browser.update_status_check()
    return {
        "status": status,
        "engine": "playwright",
        "authenticated": (status == "WORKING"),
        "version": "1.0.0",
        "uptimeSeconds": int(time.time() - browser.start_time)
    }

@app.get("/api/screenshot", summary="Live Viewport Screenshot")
async def get_screenshot():
    try:
        data = await browser.get_screenshot()
        return Response(content=data, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/qr", summary="Authentication QR Code")
async def get_qr(format: str = Query("image", enum=["image", "json"])):
    try:
        data = await browser.get_qr_screenshot()
        if format == "image":
            return Response(content=data, media_type="image/png")
        import base64
        return {"qr": f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sendText", status_code=201, summary="Send Text Message")
async def send_text(req: SendTextRequest):
    try:
        res = await browser.send_text(req.chatId, req.text)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chats", summary="List Conversations")
async def get_chats(limit: int = 20, unreadOnly: bool = False):
    try:
        return await browser.get_chats(limit=limit, unread_only=unreadOnly)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chats/{chat_id}/messages", summary="Fetch Messages in Chat")
async def get_messages(chat_id: str, limit: int = 20):
    try:
        return await browser.get_messages(target=chat_id, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/chats/{chat_id}/messages/{message_id}", summary="Delete / Revoke Message")
async def delete_message(chat_id: str, message_id: str):
    try:
        success = await browser.delete_message(target=chat_id, message_id=message_id)
        if not success:
            raise HTTPException(status_code=400, detail="Could not delete message")
        return {"success": True, "chatId": chat_id, "messageId": message_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/calls", summary="Extract Call Logs with Duration & Dialed Number")
async def get_calls(
    limit: int = 20,
    includeDetails: bool = True,
    missedOnly: bool = False,
    type: Optional[str] = Query(None, enum=["audio", "video"])
):
    try:
        return await browser.get_calls(
            limit=limit,
            include_details=includeDetails,
            missed_only=missedOnly,
            call_type=type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/maintenance/auto-clean-media", summary="Auto-Purge Old Group Media")
async def clean_media(req: CleanMediaRequest):
    try:
        return await browser.clean_group_media(
            chat_id=req.chatId,
            older_than_hours=req.olderThanHours,
            delete_for_everyone=req.deleteForEveryone
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

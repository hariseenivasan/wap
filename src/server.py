import os
import time
import json
import configparser
import xmlrpc.client
import requests
import re
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Response, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from src.browser_manager import BrowserManager
except (ImportError, ModuleNotFoundError):
    from .browser_manager import BrowserManager

USER_DATA_DIR = os.getenv("USER_DATA_DIR", "./userdata")
WABOT_CONFIG_PATH = os.getenv("WABOT_CONFIG_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config/config.json")))
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

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
    title="WAP - WhatsApp Playwright API & Control Center",
    description="A visual, browser-backed admin REST API & Dashboard for WhatsApp Web automation (WYSIWYT implementation of WAHA).",
    version="1.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Helper Functions -----------------

def get_supervisor_client():
    url = os.getenv("SUPERVISOR_URL")
    if not url:
        inet_conf = "/etc/supervisor/conf.d/inet.conf"
        if os.path.exists(inet_conf):
            try:
                conf = configparser.ConfigParser()
                conf.read(inet_conf)
                user = conf.get("inet_http_server", "username", fallback="")
                pwd = conf.get("inet_http_server", "password", fallback="")
                port = conf.get("inet_http_server", "port", fallback="9001").split(":")[-1]
                auth = f"{user}:{pwd}@" if user and pwd else ""
                url = f"http://{auth}127.0.0.1:{port}/RPC2"
            except Exception:
                url = "http://127.0.0.1:9001/RPC2"
        else:
            url = "http://127.0.0.1:9001/RPC2"
    return xmlrpc.client.ServerProxy(url)

def load_wabot_config() -> dict:
    if os.path.exists(WABOT_CONFIG_PATH):
        try:
            with open(WABOT_CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WAP Error]: Could not load config from {WABOT_CONFIG_PATH}: {e}")
    return {
        "engine": "wap",
        "waha_url": "http://127.0.0.1:3000",
        "wap_url": "http://127.0.0.1:3001",
        "defaults": {
            "period_seconds": 600,
            "jitter_percentage": 15,
            "unread_label": "unread message"
        }
    }

def save_wabot_config(data: dict) -> bool:
    if os.path.exists(os.path.dirname(WABOT_CONFIG_PATH)):
        try:
            with open(WABOT_CONFIG_PATH, "w") as f:
                json.dump(data, f, indent=4)
            return True
        except Exception as e:
            print(f"[WAP Error]: Could not save config to {WABOT_CONFIG_PATH}: {e}")
            return False
    return False

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

class ConfigUpdateRequest(BaseModel):
    period_seconds: Optional[int] = Field(None, ge=60, le=86400)
    jitter_percentage: Optional[int] = Field(None, ge=0, le=50)
    unread_label: Optional[str] = None

class EngineSwitchRequest(BaseModel):
    engine: str = Field(..., pattern="^(wap|waha)$")
    period_seconds: Optional[int] = None
    jitter_percentage: Optional[int] = None
    unread_label: Optional[str] = None

class RequestCodeBody(BaseModel):
    phoneNumber: str = Field(..., description="Phone number with or without country code", example="1234567890")
    countryCode: str = Field("+91", description="Country code", example="+91")
    engine: Optional[str] = Field(None, pattern="^(wap|waha)$", description="Target engine: wap or waha")

# ----------------- UI Dashboard Routes -----------------

@app.get("/", response_class=HTMLResponse, summary="Admin Dashboard UI")
@app.get("/dashboard", response_class=HTMLResponse, summary="Admin Dashboard UI")
async def get_dashboard():
    dashboard_file = os.path.join(CURRENT_DIR, "dashboard.html")
    if os.path.exists(dashboard_file):
        with open(dashboard_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h3>Dashboard file not found</h3>")

@app.get("/login", response_class=HTMLResponse, summary="Authentication & Login View")
async def get_login_page():
    login_file = os.path.join(CURRENT_DIR, "login.html")
    if os.path.exists(login_file):
        with open(login_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h3>Login page not found</h3>")

# ----------------- Configuration & Engine Routes -----------------

@app.get("/api/config", summary="Get WABot Configuration")
async def get_config():
    cfg = load_wabot_config()
    sanitized = cfg.copy()
    if "auth" in sanitized:
        sanitized["auth"] = {"configured": bool(sanitized["auth"].get("phone_number"))}
    if "phone_number" in sanitized:
        sanitized["phone_number"] = "***masked***"
    return sanitized

@app.post("/api/config", summary="Update WABot Configuration")
async def update_config(req: ConfigUpdateRequest):
    cfg = load_wabot_config()
    if "defaults" not in cfg:
        cfg["defaults"] = {}
    if req.period_seconds is not None:
        cfg["defaults"]["period_seconds"] = req.period_seconds
    if req.jitter_percentage is not None:
        cfg["defaults"]["jitter_percentage"] = req.jitter_percentage
    if req.unread_label is not None:
        cfg["defaults"]["unread_label"] = req.unread_label

    if save_wabot_config(cfg):
        return {"success": True, "config": cfg}
    raise HTTPException(status_code=500, detail="Failed to write configuration file.")

@app.post("/api/engine/switch", summary="Double-Confirmed Engine Switch")
async def switch_engine(req: EngineSwitchRequest, request: Request):
    cfg = load_wabot_config()
    cfg["engine"] = req.engine
    
    if "defaults" not in cfg:
        cfg["defaults"] = {}
    if req.period_seconds is not None:
        cfg["defaults"]["period_seconds"] = req.period_seconds
    if req.jitter_percentage is not None:
        cfg["defaults"]["jitter_percentage"] = req.jitter_percentage
    if req.unread_label is not None:
        cfg["defaults"]["unread_label"] = req.unread_label

    if not save_wabot_config(cfg):
        raise HTTPException(status_code=500, detail="Failed to save engine switch in configuration.")

    host = request.headers.get("host", "localhost:3001").split(":")[0]
    
    if req.engine == "waha":
        login_url = f"http://{host}:3000/dashboard"
    else:
        login_url = f"http://{host}:3001/login?engine=wap"

    return {
        "success": True,
        "engine": req.engine,
        "loginUrl": login_url,
        "message": f"Successfully switched WABot engine to {req.engine.upper()}."
    }

# ----------------- Supervisor & WABot Process Management -----------------

@app.get("/api/wabot/status", summary="Get WABot Process Status from Supervisor")
async def get_wabot_status():
    cfg = load_wabot_config()
    active_engine = cfg.get("engine", "wap")
    try:
        client = get_supervisor_client()
        info = client.supervisor.getProcessInfo("wabot")
        uptime = max(0, info["now"] - info["start"]) if info["statename"] == "RUNNING" else 0
        return {
            "name": info["name"],
            "statename": info["statename"],
            "pid": info["pid"],
            "description": info["description"],
            "uptimeSeconds": uptime,
            "engine": active_engine,
            "supervisorAvailable": True
        }
    except Exception as e:
        return {
            "name": "wabot",
            "statename": "UNKNOWN",
            "pid": 0,
            "description": str(e),
            "uptimeSeconds": 0,
            "engine": active_engine,
            "supervisorAvailable": False
        }

@app.post("/api/wabot/restart", summary="Restart WABot Service under Supervisor")
async def restart_wabot():
    try:
        client = get_supervisor_client()
        try:
            client.supervisor.stopProcess("wabot")
        except Exception:
            pass
        # Clear stale locks
        lock = os.path.join(CURRENT_DIR, "../../whatsapp_userdata/SingletonLock")
        if os.path.exists(lock):
            try:
                os.remove(lock)
            except Exception:
                pass
        time.sleep(0.5)
        client.supervisor.startProcess("wabot")
        info = client.supervisor.getProcessInfo("wabot")
        return {"success": True, "statename": info["statename"], "pid": info["pid"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart wabot: {e}")

@app.post("/api/wabot/start", summary="Start WABot Service under Supervisor")
async def start_wabot():
    try:
        client = get_supervisor_client()
        client.supervisor.startProcess("wabot")
        info = client.supervisor.getProcessInfo("wabot")
        return {"success": True, "statename": info["statename"], "pid": info["pid"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start wabot: {e}")

@app.post("/api/wabot/stop", summary="Stop WABot Service under Supervisor")
async def stop_wabot():
    try:
        client = get_supervisor_client()
        client.supervisor.stopProcess("wabot")
        info = client.supervisor.getProcessInfo("wabot")
        return {"success": True, "statename": info["statename"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop wabot: {e}")

@app.get("/api/wabot/logs", summary="Get Latest WABot Logs from Supervisor")
async def get_wabot_logs(bytes_count: int = 4096):
    try:
        client = get_supervisor_client()
        stdout_log, _, _ = client.supervisor.tailProcessStdoutLog("wabot", 0, bytes_count)
        stderr_log, _, _ = client.supervisor.tailProcessStderrLog("wabot", 0, bytes_count)
        return {
            "stdout": stdout_log,
            "stderr": stderr_log
        }
    except Exception as e:
        return {
            "stdout": f"[Log Error]: Could not read logs from supervisor: {e}",
            "stderr": ""
        }

# ----------------- WhatsApp Core Routes -----------------

@app.get("/api/status", summary="Session & Engine Health")
async def get_status(engine: Optional[str] = Query(None, pattern="^(wap|waha)$")):
    cfg = load_wabot_config()
    target_engine = engine or cfg.get("engine", "wap")
    
    if target_engine == "waha":
        try:
            waha_url = cfg.get("waha_url", "http://127.0.0.1:3000").rstrip("/")
            r = requests.get(f"{waha_url}/api/sessions/default", timeout=3)
            if r.status_code == 200:
                s_data = r.json()
                s_status = s_data.get("status", "UNKNOWN")
                return {
                    "status": s_status,
                    "engine": "waha",
                    "activeWabotEngine": cfg.get("engine", "wap"),
                    "authenticated": (s_status == "WORKING"),
                    "version": "1.1.0",
                    "me": s_data.get("me"),
                    "uptimeSeconds": 0
                }
            elif r.status_code == 404:
                return {
                    "status": "STOPPED",
                    "engine": "waha",
                    "activeWabotEngine": cfg.get("engine", "wap"),
                    "authenticated": False,
                    "version": "1.1.0",
                    "uptimeSeconds": 0
                }
        except Exception:
            return {
                "status": "UNREACHABLE",
                "engine": "waha",
                "activeWabotEngine": cfg.get("engine", "wap"),
                "authenticated": False,
                "version": "1.1.0",
                "uptimeSeconds": 0
            }

    status = await browser.update_status_check()
    return {
        "status": status,
        "engine": "playwright",
        "activeWabotEngine": cfg.get("engine", "wap"),
        "authenticated": (status == "WORKING"),
        "version": "1.1.0",
        "uptimeSeconds": int(time.time() - browser.start_time)
    }

@app.get("/api/screenshot", summary="Live Viewport Screenshot")
async def get_screenshot():
    try:
        data = await browser.get_screenshot()
        return Response(content=data, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/qr", summary="Authentication QR Code (WAP & WAHA)")
async def get_qr(
    format: str = Query("image", pattern="^(image|json)$"),
    engine: Optional[str] = Query(None, pattern="^(wap|waha)$")
):
    cfg = load_wabot_config()
    target_engine = engine or cfg.get("engine", "wap")
    
    if target_engine == "waha":
        try:
            waha_url = cfg.get("waha_url", "http://127.0.0.1:3000").rstrip("/")
            try:
                requests.post(f"{waha_url}/api/sessions/start", json={"name": "default"}, timeout=3)
            except Exception:
                pass
            waha_qr_url = f"{waha_url}/api/default/auth/qr?format=image"
            r = requests.get(waha_qr_url, timeout=5)
            if r.status_code == 200:
                if format == "image":
                    return Response(content=r.content, media_type="image/png")
                import base64
                return {"qr": f"data:image/png;base64,{base64.b64encode(r.content).decode('utf-8')}", "engine": "waha"}
            raise HTTPException(status_code=r.status_code, detail=f"WAHA QR returned {r.status_code}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch WAHA QR: {e}")

    try:
        data = await browser.get_qr_screenshot()
        if format == "image":
            return Response(content=data, media_type="image/png")
        import base64
        return {"qr": f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}", "engine": "wap"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auth/request-code", summary="Request Phone Number Pairing Code (WAP & WAHA)")
async def request_auth_code(req: RequestCodeBody):
    cfg = load_wabot_config()
    target_engine = req.engine or cfg.get("engine", "wap")
    
    if target_engine == "waha":
        try:
            waha_url = cfg.get("waha_url", "http://127.0.0.1:3000").rstrip("/")
            raw_digits = re.sub(r'\D', '', req.phoneNumber)
            country_digits = re.sub(r'\D', '', req.countryCode) or "91"
            full_digits = raw_digits if raw_digits.startswith(country_digits) else f"{country_digits}{raw_digits}"
            
            try:
                requests.post(f"{waha_url}/api/sessions/start", json={"name": "default"}, timeout=3)
            except Exception:
                pass
            
            resp = requests.post(
                f"{waha_url}/api/default/auth/request-code",
                json={"phoneNumber": full_digits},
                timeout=15
            )
            if resp.status_code in [200, 201]:
                data = resp.json()
                code = data.get("code") if isinstance(data, dict) else str(data)
                return {
                    "success": True,
                    "code": code,
                    "engine": "waha",
                    "phone": f"+{full_digits}"
                }
            else:
                err_text = resp.text
                try:
                    err_json = resp.json()
                    err_text = err_json.get("message") or err_json.get("error") or err_text
                except Exception:
                    pass
                return {"success": False, "error": f"WAHA pairing error ({resp.status_code}): {err_text}", "engine": "waha"}
        except Exception as e:
            return {"success": False, "error": f"Could not connect to WAHA: {e}", "engine": "waha"}
    else:
        try:
            return await browser.request_pairing_code(req.phoneNumber, req.countryCode)
        except Exception as e:
            return {"success": False, "error": str(e), "engine": "wap"}

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
    type: Optional[str] = Query(None, pattern="^(audio|video)$")
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

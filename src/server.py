import os
import time
import json
import configparser
import xmlrpc.client
import requests
import re
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Response, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from src.browser_manager import BrowserManager
except (ImportError, ModuleNotFoundError):
    from .browser_manager import BrowserManager

USER_DATA_DIR = os.getenv("USER_DATA_DIR", "./userdata")
WABOT_CONFIG_PATH = os.getenv("WABOT_CONFIG_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config/config.json")))
WABOT_SCHEDULES_PATH = os.getenv("WABOT_SCHEDULES_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config/user_schedules.json")))
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "../uploads"))
os.makedirs(UPLOADS_DIR, exist_ok=True)

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

def load_wabot_schedules() -> list:
    if os.path.exists(WABOT_SCHEDULES_PATH):
        try:
            with open(WABOT_SCHEDULES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else [data]
        except Exception as e:
            print(f"[WAP Error]: Could not load schedules from {WABOT_SCHEDULES_PATH}: {e}")
    return []

def save_wabot_schedules(schedules: list) -> bool:
    if os.path.exists(os.path.dirname(WABOT_SCHEDULES_PATH)):
        try:
            if os.path.exists(WABOT_SCHEDULES_PATH):
                try:
                    import shutil
                    shutil.copy2(WABOT_SCHEDULES_PATH, f"{WABOT_SCHEDULES_PATH}.bak")
                except Exception:
                    pass
            with open(WABOT_SCHEDULES_PATH, "w", encoding="utf-8") as f:
                json.dump(schedules, f, indent=4)
            return True
        except Exception as e:
            print(f"[WAP Error]: Could not save schedules to {WABOT_SCHEDULES_PATH}: {e}")
            return False
    return False

def calculate_schedule_status(entry: dict) -> list:
    from datetime import datetime, date
    today = date.today()
    now_time = datetime.now().time()
    results = []
    
    contact = entry.get("contact_name", "Unknown")
    schedules = entry.get("schedules", [])
    
    for idx, s in enumerate(schedules):
        sched_type = s.get("type", "daily")
        start_t_str = s.get("start_time", "00:00")
        end_t_str = s.get("end_time", "23:59")
        
        is_valid_today = False
        next_run_days = 0
        
        if sched_type == "daily":
            is_valid_today = True
        elif sched_type == "interval":
            s_date_str = s.get("start_date")
            interval = s.get("interval_days", 1)
            if s_date_str:
                try:
                    s_date = datetime.strptime(s_date_str, "%Y-%m-%d").date()
                    delta = (today - s_date).days
                    if delta >= 0:
                        rem = delta % interval
                        is_valid_today = (rem == 0)
                        if not is_valid_today:
                            next_run_days = interval - rem
                    else:
                        is_valid_today = False
                        next_run_days = abs(delta)
                except Exception:
                    is_valid_today = True
            else:
                is_valid_today = True
        elif sched_type == "dates":
            dates = s.get("dates", [])
            t_str = today.strftime("%Y-%m-%d")
            t_mmdd = today.strftime("%m-%d")
            is_valid_today = (t_str in dates or t_mmdd in dates)

        is_in_window = False
        is_completed = False
        try:
            start_t = datetime.strptime(start_t_str, "%H:%M").time()
            end_t = datetime.strptime(end_t_str, "%H:%M").time()
            if start_t <= now_time <= end_t:
                is_in_window = True
            elif now_time > end_t:
                is_completed = True
        except Exception:
            pass

        if not is_valid_today:
            status_text = f"Scheduled in {next_run_days} day(s)" if next_run_days > 0 else "Not scheduled today"
            badge_class = "badge-future"
        elif is_in_window:
            status_text = f"ACTIVE NOW ({start_t_str} - {end_t_str})"
            badge_class = "badge-active"
        elif is_completed:
            status_text = f"Completed today (Window ended at {end_t_str})"
            badge_class = "badge-completed"
        else:
            status_text = f"Scheduled today at {start_t_str}"
            badge_class = "badge-pending"

        results.append({
            "index": idx,
            "contact_name": contact,
            "type": sched_type,
            "start_time": start_t_str,
            "end_time": end_t_str,
            "interval_days": s.get("interval_days"),
            "start_date": s.get("start_date"),
            "jitter_percentage": s.get("jitter_percentage", 15),
            "is_valid_today": is_valid_today,
            "is_in_window": is_in_window,
            "is_completed": is_completed,
            "status_text": status_text,
            "badge_class": badge_class
        })
        
    return results

# ----------------- Models -----------------

class SendTextRequest(BaseModel):
    chatId: str = Field(..., description="Target phone number or group ID, e.g. 1234567890@c.us", example="1234567890@c.us")
    text: str = Field(..., description="Text message content", example="Hello! Testing automated message.")
    engine: Optional[str] = Field(None, pattern="^(wap|waha)$", description="Engine override")

class SendImageRequest(BaseModel):
    chatId: str = Field(..., description="Recipient phone number or chat ID", example="1234567890")
    caption: Optional[str] = Field(None, description="Optional caption for image")
    file_path: Optional[str] = Field(None, description="Path on disk or image URL")
    image_id: Optional[str] = Field(None, description="Uploaded image ID")
    engine: Optional[str] = Field(None, pattern="^(wap|waha)$", description="Engine override")

class TestingConfig(BaseModel):
    test_message: str = Field("Hello from WABot Test Workspace!", description="Default test message")
    mode: Optional[str] = Field("wap", pattern="^(wap|waha)$")
    default_recipient: Optional[str] = Field(None, description="Default test recipient")
    delay_seconds: float = Field(1.5, ge=0.5, le=10.0)

class AIGenerateRequest(BaseModel):
    prompt: str = Field(..., description="Base greeting message or visual description")
    tags: Optional[str] = Field(None, description="Style tags, language, or festive themes")
    count: int = Field(1, ge=1, le=8, description="Number of unique images to generate")

class PersonalizeCardRequest(BaseModel):
    image_id: Optional[str] = Field(None, description="Source image ID in uploads")
    file_path: Optional[str] = Field(None, description="Direct file path to source image")
    name: Optional[str] = Field(None, description="Recipient contact name")
    suffix: Optional[str] = Field("and Family", description="Personalization suffix e.g. and Family, et al.")
    greeting_text: Optional[str] = Field("Good Morning", description="Greeting text")
    style: Optional[str] = Field("frosted_gold", description="Styling preset: frosted_gold, ribbon_banner, golden_calligraphy")

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

class CallExtractionConfig(BaseModel):
    target_contacts: List[str] = Field(default_factory=list, description="List of target contact names or phone numbers to extract")
    filter_mode: str = Field("all", pattern="^(all|whitelist)$")
    mode: Optional[str] = None
    include_details: bool = True
    max_calls: int = Field(25, ge=1, le=100)

    def to_dict(self):
        m = self.mode if (self.mode and self.mode in ("all", "whitelist")) else self.filter_mode
        return {
            "target_contacts": self.target_contacts,
            "filter_mode": m,
            "mode": m,
            "include_details": self.include_details,
            "max_calls": self.max_calls
        }

class SchedulesPayload(BaseModel):
    schedules: List[Dict[str, Any]] = Field(..., description="List of schedule items")

class ScheduleItemPayload(BaseModel):
    contact_name: str = Field(..., description="Recipient Name or Phone Number")
    message: str = Field(..., description="Message template content")
    schedules: List[Dict[str, Any]] = Field(default_factory=list, description="List of time windows and recurrence rules")

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

# ----------------- Schedules Management Routes -----------------

@app.get("/api/schedules", summary="Get WABot Message Schedules & Live Status")
async def get_schedules():
    schedules = load_wabot_schedules()
    summary = []
    for item in schedules:
        statuses = calculate_schedule_status(item)
        summary.extend(statuses)
    return {
        "schedules": schedules,
        "summary": summary,
        "count": len(schedules)
    }

@app.post("/api/schedules", summary="Save / Update WABot Message Schedules")
async def update_schedules(payload: SchedulesPayload):
    if save_wabot_schedules(payload.schedules):
        return {
            "success": True,
            "count": len(payload.schedules),
            "message": "Schedules saved successfully to user_schedules.json."
        }
    raise HTTPException(status_code=500, detail="Failed to write schedules to user_schedules.json.")

@app.post("/api/schedules/add", summary="Add New Schedule to user_schedules.json")
async def add_schedule(item: ScheduleItemPayload):
    schedules = load_wabot_schedules()
    schedules.append(item.dict())
    if save_wabot_schedules(schedules):
        return {
            "success": True,
            "count": len(schedules),
            "index": len(schedules) - 1,
            "schedules": schedules,
            "message": "New schedule added successfully."
        }
    raise HTTPException(status_code=500, detail="Failed to add schedule.")

@app.put("/api/schedules/{index}", summary="Update Schedule by Index in user_schedules.json")
async def edit_schedule(index: int, item: ScheduleItemPayload):
    schedules = load_wabot_schedules()
    if index < 0 or index >= len(schedules):
        raise HTTPException(status_code=404, detail=f"Schedule index {index} not found.")
    schedules[index] = item.dict()
    if save_wabot_schedules(schedules):
        return {
            "success": True,
            "count": len(schedules),
            "schedules": schedules,
            "message": f"Schedule #{index} updated successfully."
        }
    raise HTTPException(status_code=500, detail="Failed to update schedule.")

@app.delete("/api/schedules/{index}", summary="Delete Schedule by Index in user_schedules.json")
async def delete_schedule(index: int):
    schedules = load_wabot_schedules()
    if index < 0 or index >= len(schedules):
        raise HTTPException(status_code=404, detail=f"Schedule index {index} not found.")
    removed = schedules.pop(index)
    if save_wabot_schedules(schedules):
        return {
            "success": True,
            "count": len(schedules),
            "removed": removed,
            "schedules": schedules,
            "message": f"Schedule #{index} deleted successfully."
        }
    raise HTTPException(status_code=500, detail="Failed to delete schedule.")

@app.get("/api/config/call-extraction", summary="Get Call Extraction Configuration")
async def get_call_extraction_config():
    cfg = load_wabot_config()
    c = cfg.get("call_extraction", {
        "target_contacts": [],
        "filter_mode": "all",
        "mode": "all",
        "include_details": True,
        "max_calls": 25
    })
    if "mode" not in c:
        c["mode"] = c.get("filter_mode", "all")
    if "filter_mode" not in c:
        c["filter_mode"] = c.get("mode", "all")
    return c

@app.post("/api/config/call-extraction", summary="Update Call Extraction Configuration")
async def update_call_extraction_config(req: CallExtractionConfig):
    cfg = load_wabot_config()
    cfg["call_extraction"] = req.to_dict()
    if save_wabot_config(cfg):
        return {"success": True, "call_extraction": cfg["call_extraction"]}
    raise HTTPException(status_code=500, detail="Failed to save call extraction configuration.")

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

@app.post("/api/sendText", status_code=201, summary="Send Text Message (WAP & WAHA)")
async def send_text(req: SendTextRequest):
    cfg = load_wabot_config()
    active_engine = req.engine or cfg.get("engine", "wap")
    clean_target = req.chatId.replace("@c.us", "").replace("@s.whatsapp.net", "").replace("@g.us", "").strip()

    if active_engine == "waha":
        waha_url = cfg.get("waha_url", "http://127.0.0.1:3000")
        try:
            payload = {
                "chatId": f"{clean_target}@c.us" if "@" not in clean_target else clean_target,
                "text": req.text,
                "session": "default"
            }
            resp = requests.post(f"{waha_url}/api/sendText", json=payload, timeout=15)
            if resp.status_code in (200, 201):
                return resp.json()
            err_msg = resp.text
            try:
                err_msg = resp.json().get("message") or resp.text
            except Exception:
                pass
            return {"success": False, "error": f"WAHA sendText error ({resp.status_code}): {err_msg}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"WAHA sendText failed: {e}")
    else:
        try:
            res = await browser.send_text(clean_target, req.text)
            return res
        except ValueError as ve:
            raise HTTPException(status_code=404, detail=str(ve))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sendImage", status_code=201, summary="Send Image Message (WAP & WAHA)")
async def send_image(req: SendImageRequest):
    cfg = load_wabot_config()
    active_engine = req.engine or cfg.get("engine", "wap")
    clean_target = req.chatId.replace("@c.us", "").replace("@s.whatsapp.net", "").replace("@g.us", "").strip()

    # Resolve file path
    target_path = req.file_path
    if req.image_id and not target_path:
        for f in os.listdir(UPLOADS_DIR):
            if f.startswith(req.image_id):
                target_path = os.path.join(UPLOADS_DIR, f)
                break
                
    if not target_path or not os.path.exists(target_path):
        raise HTTPException(status_code=400, detail="Valid image file path or image_id must be provided.")

    if active_engine == "waha":
        waha_url = cfg.get("waha_url", "http://127.0.0.1:3000")
        try:
            import base64
            with open(target_path, "rb") as img_f:
                b64_data = base64.b64encode(img_f.read()).decode("utf-8")
            ext = os.path.splitext(target_path)[1].lstrip(".").lower() or "jpeg"
            mime = f"image/{ext}" if ext in ["jpeg", "jpg", "png", "webp", "gif"] else "application/octet-stream"
            
            payload = {
                "chatId": f"{clean_target}@c.us" if "@" not in clean_target else clean_target,
                "file": {
                    "mimetype": mime,
                    "filename": os.path.basename(target_path),
                    "url": f"data:{mime};base64,{b64_data}"
                },
                "caption": req.caption or ""
            }
            resp = requests.post(f"{waha_url}/api/sendImage", json=payload, timeout=25)
            if resp.status_code in (200, 201):
                return resp.json()
            err_msg = resp.text
            try:
                err_msg = resp.json().get("message") or resp.text
            except Exception:
                pass
            return {"success": False, "error": f"WAHA sendImage error ({resp.status_code}): {err_msg}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"WAHA sendImage failed: {e}")
    else:
        try:
            return await browser.send_image(target=clean_target, file_path=target_path, caption=req.caption)
        except ValueError as ve:
            raise HTTPException(status_code=404, detail=str(ve))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/media/upload", summary="Upload Image for Greetings / Broadcast")
async def upload_media(file: UploadFile = File(...)):
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            raise HTTPException(status_code=400, detail="Only image files (.jpg, .jpeg, .png, .webp, .gif) are supported.")
        
        img_id = f"img_{int(time.time()*1000)}_{os.urandom(4).hex()}"
        safe_filename = f"{img_id}{ext}"
        target_path = os.path.join(UPLOADS_DIR, safe_filename)
        
        content = await file.read()
        with open(target_path, "wb") as f:
            f.write(content)
            
        return {
            "success": True,
            "imageId": img_id,
            "filename": file.filename,
            "path": target_path,
            "url": f"/api/media/{safe_filename}",
            "size": len(content)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/media/{filename}", summary="Serve Uploaded Media File")
async def get_media_file(filename: str):
    safe_name = os.path.basename(filename)
    path = os.path.join(UPLOADS_DIR, safe_name)
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Media file not found")

@app.post("/api/media/ai-generate", summary="AI Magic Image Generation for Greetings")
async def ai_generate_images(req: AIGenerateRequest):
    import urllib.parse
    import random
    
    cfg = load_wabot_config()
    xai_api_key = cfg.get("xai_api_key") or os.getenv("XAI_API_KEY")
    
    prompt_parts = []
    if req.tags:
        prompt_parts.append(req.tags.strip())
    if req.prompt:
        prompt_parts.append(req.prompt.strip())
    prompt_parts.append("festive greeting card art, high quality, vibrant 4k aesthetic wallpaper")
    full_prompt = ", ".join(prompt_parts)
    
    results = []
    count = min(max(req.count, 1), 8)
    
    for i in range(count):
        seed = random.randint(10000, 9999999)
        img_id = f"ai_{int(time.time()*1000)}_{i}_{seed}"
        filename = f"{img_id}.jpg"
        target_path = os.path.join(UPLOADS_DIR, filename)
        
        # Check xAI Grok API key if available
        if xai_api_key:
            try:
                headers = {"Authorization": f"Bearer {xai_api_key}", "Content-Type": "application/json"}
                payload = {"prompt": full_prompt, "model": "grok-2-image", "n": 1, "response_format": "b64_json"}
                resp = requests.post("https://api.x.ai/v1/images/generations", json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    import base64
                    b64 = resp.json()["data"][0]["b64_json"]
                    with open(target_path, "wb") as f:
                        f.write(base64.b64decode(b64))
                    results.append({
                        "imageId": img_id,
                        "filename": filename,
                        "url": f"/api/media/{filename}",
                        "path": target_path,
                        "source": "grok"
                    })
                    continue
            except Exception as e:
                print(f"[xAI Grok fallback]: {e}")
                
        # Free Instant Generative Engine: Pollinations.ai (Flux)
        try:
            encoded_prompt = urllib.parse.quote(full_prompt)
            api_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
            resp = requests.get(api_url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 1000:
                with open(target_path, "wb") as f:
                    f.write(resp.content)
                results.append({
                    "imageId": img_id,
                    "filename": filename,
                    "url": f"/api/media/{filename}",
                    "path": target_path,
                    "source": "pollinations_flux"
                })
        except Exception as e:
            print(f"[AI Generation error]: {e}")
            
    if not results:
        raise HTTPException(status_code=500, detail="Failed to generate AI images. Please check network connectivity or try again.")
        
    return {
        "success": True,
        "images": results,
        "count": len(results),
        "prompt": full_prompt
    }

@app.post("/api/media/personalize", summary="Personalize Greeting Card with Contact Name")
async def personalize_greeting_card(req: PersonalizeCardRequest):
    # 1. Resolve source image
    source_path = req.file_path
    if req.image_id and not source_path:
        for f in os.listdir(UPLOADS_DIR):
            if f.startswith(req.image_id):
                source_path = os.path.join(UPLOADS_DIR, f)
                break
                
    if not source_path or not os.path.exists(source_path):
        raise HTTPException(status_code=400, detail="Valid base image must be provided.")
        
    # 2. Check if name is present and valid (not just digits/phone)
    raw_name = (req.name or "").strip()
    is_phone_digits = bool(re.match(r"^\+?[0-9\s\-]+$", raw_name)) or len(raw_name) == 0
    
    # If no valid name, return the source image untouched
    if is_phone_digits:
        safe_base = os.path.basename(source_path)
        return {
            "success": True,
            "has_name": False,
            "imageId": req.image_id or os.path.splitext(safe_base)[0],
            "filename": safe_base,
            "url": f"/api/media/{safe_base}",
            "path": source_path,
            "message": "Contact has no named identity; returning base card uncustomized."
        }
        
    # 3. Contact has a valid name: dynamically render stylish text overlay with PIL
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        base_img = Image.open(source_path).convert("RGBA")
        w, h = base_img.size
        
        # Build text strings
        suffix_str = f" {req.suffix.strip()}" if (req.suffix and req.suffix.strip() and req.suffix.lower() != "none") else ""
        recipient_display = f"{raw_name}{suffix_str}"
        greeting_line = req.greeting_text.strip() if req.greeting_text else "Greetings"
        
        # Load fonts (fallback gracefully to system serif/sans or default)
        font_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
        script_font_path = os.path.join(font_dir, "GreatVibes-Regular.ttf")
        sans_font_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        
        script_size = max(24, int(h * 0.065))
        sans_size = max(18, int(h * 0.04))
        
        if os.path.exists(script_font_path):
            font_script = ImageFont.truetype(script_font_path, script_size)
        else:
            font_script = ImageFont.load_default()
            
        if os.path.exists(sans_font_path):
            font_sans = ImageFont.truetype(sans_font_path, sans_size)
        else:
            font_sans = ImageFont.load_default()
            
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Frosted glass card plate at bottom
        card_margin_x = int(w * 0.06)
        card_h = int(h * 0.22)
        card_y0 = h - card_h - int(h * 0.05)
        card_y1 = h - int(h * 0.05)
        
        # Frosted rounded rectangle with subtle golden border
        draw.rounded_rectangle(
            (card_margin_x, card_y0, w - card_margin_x, card_y1),
            radius=int(h * 0.025),
            fill=(15, 23, 42, 215),
            outline=(251, 191, 36, 230),
            width=max(2, int(w * 0.003))
        )
        
        # Draw Greeting Line (Golden Calligraphy)
        center_x = w // 2
        greet_y = card_y0 + int(card_h * 0.35)
        draw.text((center_x + 2, greet_y + 2), greeting_line, fill=(0, 0, 0, 180), font=font_script, anchor="mm")
        draw.text((center_x, greet_y), greeting_line, fill=(251, 191, 36, 255), font=font_script, anchor="mm")
        
        # Draw Recipient Name Line (Crisp bold sans text)
        name_y = card_y0 + int(card_h * 0.72)
        draw.text((center_x + 2, name_y + 2), recipient_display, fill=(0, 0, 0, 180), font=font_sans, anchor="mm")
        draw.text((center_x, name_y), recipient_display, fill=(248, 250, 252, 255), font=font_sans, anchor="mm")
        
        # Composite and save
        composite = Image.alpha_composite(base_img, overlay).convert("RGB")
        
        personalized_id = f"pers_{int(time.time()*1000)}_{os.urandom(3).hex()}"
        out_filename = f"{personalized_id}.jpg"
        out_path = os.path.join(UPLOADS_DIR, out_filename)
        composite.save(out_path, format="JPEG", quality=95)
        
        return {
            "success": True,
            "has_name": True,
            "imageId": personalized_id,
            "filename": out_filename,
            "url": f"/api/media/{out_filename}",
            "path": out_path,
            "recipient": recipient_display,
            "greeting": greeting_line
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Personalization error: {e}")

@app.get("/api/config/testing", summary="Get Testing & Sandbox Configuration")
async def get_testing_config():
    cfg = load_wabot_config()
    return cfg.get("testing", {
        "test_message": "Hello from WABot Test Workspace!",
        "mode": cfg.get("engine", "wap"),
        "delay_seconds": 1.5
    })

@app.post("/api/config/testing", summary="Update Testing & Sandbox Configuration")
async def update_testing_config(req: TestingConfig):
    cfg = load_wabot_config()
    cfg["testing"] = req.dict()
    if save_wabot_config(cfg):
        return {"success": True, "testing": cfg["testing"]}
    raise HTTPException(status_code=500, detail="Failed to save testing configuration.")

@app.get("/api/contacts", summary="Get Searchable Contacts & Recent Chats")
async def get_contacts(search: Optional[str] = Query(None)):
    contacts = []
    seen = set()
    cfg = load_wabot_config()

    # 1. From recent chats
    try:
        chats = await browser.get_chats(limit=40)
        for c in chats:
            name = c.get("name")
            if name and name not in seen:
                seen.add(name)
                contacts.append({"name": name, "source": "chat", "unread": c.get("unreadCount", 0)})
    except Exception:
        pass

    # 2. From call extraction targets
    call_cfg = cfg.get("call_extraction", {})
    for t in call_cfg.get("target_contacts", []):
        if t and t not in seen:
            seen.add(t)
            contacts.append({"name": t, "source": "target"})

    # 3. From user schedules
    try:
        schedules = load_wabot_schedules()
        for s in schedules:
            c_name = s.get("contact_name")
            if c_name and c_name not in seen:
                seen.add(c_name)
                contacts.append({"name": c_name, "source": "schedule"})
    except Exception:
        pass

    # 4. From call history
    try:
        calls = await browser.get_calls(limit=25)
        for cl in calls:
            c_name = cl.get("contactName") or cl.get("phoneNumber")
            if c_name and c_name not in seen and c_name not in ["Favorites", "Add favorite", "Recent"]:
                seen.add(c_name)
                contacts.append({"name": c_name, "source": "call"})
    except Exception:
        pass

    if search:
        s_lower = search.lower().strip()
        contacts = [c for c in contacts if s_lower in c["name"].lower()]

    return contacts

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
    type: Optional[str] = Query(None, pattern="^(audio|video)$"),
    contact: Optional[str] = None
):
    try:
        cfg = load_wabot_config()
        call_cfg = cfg.get("call_extraction", {})
        contacts_filter = []
        if contact:
            contacts_filter = [contact]
        elif call_cfg.get("filter_mode") == "whitelist" and call_cfg.get("target_contacts"):
            contacts_filter = call_cfg.get("target_contacts", [])

        effective_limit = min(limit, call_cfg.get("max_calls", 25))
        effective_details = includeDetails if includeDetails is not None else call_cfg.get("include_details", True)

        return await browser.get_calls(
            limit=effective_limit,
            include_details=effective_details,
            missed_only=missedOnly,
            call_type=type,
            contacts_filter=contacts_filter if contacts_filter else None
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

import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

# Using Pathlib for better path management
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users" / "user.json"
REPORTS_DIR = DATA_DIR / "reports"

def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def load_users() -> List[Dict[str, Any]]:
    _ensure_dir(USERS_FILE.parent)
    if not USERS_FILE.exists():
        with open(USERS_FILE, "w") as f:
            json.dump([], f)
        return []
    
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(data: List[Dict[str, Any]]):
    _ensure_dir(USERS_FILE.parent)
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def find_user(chat_id: str) -> Optional[Dict[str, Any]]:
    data = load_users()
    return next((u for u in data if u["chat_id"] == chat_id), None)

def update_user(chat_id: str, key: str, value: Any):
    data = load_users()
    for user in data:
        if user["chat_id"] == chat_id:
            user[key] = value
            break
    save_users(data)

def create_user(chat_id: str, username: str) -> Dict[str, Any]:
    data = load_users()
    new_user = {
        "id": len(data) + 1,
        "chat_id": chat_id,
        "username": username,
        "name": None,
        "project": None,
        "step": "NONE",
        "chat_history": [],
        "created_at": None # Replace with datetime.now().isoformat()
    }
    data.append(new_user)
    save_users(data)
    return new_user

def load_today_report(user: Dict[str, Any], date: str) -> Optional[Dict[str, Any]]:
    _ensure_dir(REPORTS_DIR)
    filename = f"{user['name'].lower().replace(' ', '-')}-{date}.json"
    filepath = REPORTS_DIR / filename
    if filepath.exists():
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    return None

def save_report(user: Dict[str, Any], task: str, percent: int, status: str, date: str, timestamp: str):
    _ensure_dir(REPORTS_DIR)
    filename = f"{user['name'].lower().replace(' ', '-')}-{date}.json"
    filepath = REPORTS_DIR / filename
    
    if filepath.exists():
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            data = None
    else:
        data = None

    if not data or not isinstance(data, dict) or "tasks" not in data:
        data = None

    if data is None:
        data = {
            "date": date,
            "employee": user.get("name"),
            "project": user.get("project"),
            "tasks": []
        }
    
    data["tasks"].append({
        "task": task,
        "percent": percent,
        "status": status,
        "time": timestamp
    })
    
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

def clear_today_report(user: Dict[str, Any], date: str):
    _ensure_dir(REPORTS_DIR)
    filename = f"{user['name'].lower().replace(' ', '-')}-{date}.json"
    filepath = REPORTS_DIR / filename
    if filepath.exists():
        filepath.unlink()

import mysql.connector
import os
import json
import logging
import time
import pytz
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Database Configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "raise_on_warnings": False
}

# Encryption settings
ENCRYPTED_FIELDS = ["chat_history", "name", "project"]

def _get_encryption_key() -> bytes:
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        logger.warning("CRITICAL: No ENCRYPTION_KEY found in environment! Using a temporary key. Please add ENCRYPTION_KEY to your .env to avoid data loss.")
        # We'll use a hardcoded fallback for development, but warn the user
        return b"g-M4N8lV-Y6S86s-xG-pP2-r69X-w8_L4n8q9q9q9q9="
    return key.encode()

_cipher = Fernet(_get_encryption_key())

def encrypt(data: Optional[str]) -> Optional[bytes]:
    if data is None: return None
    return _cipher.encrypt(data.encode())

def decrypt(data: Optional[bytes]) -> Optional[str]:
    if data is None: return None
    if isinstance(data, str): data = data.encode() # Handle potential string from DB driver
    try:
        return _cipher.decrypt(data).decode()
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return None

def get_db_connection():
    attempts = 0
    while attempts < 5:
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            return conn
        except mysql.connector.Error as err:
            logger.warning(f"Connection attempt {attempts+1} failed: {err}")
            attempts += 1
            time.sleep(2)
    raise Exception("Could not connect to MySQL database after 5 attempts")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            chat_id VARCHAR(50) UNIQUE,
            username VARCHAR(100),
            name LONGBLOB,
            project LONGBLOB,
            step VARCHAR(50) DEFAULT 'NONE',
            chat_history LONGBLOB,
            created_at DATETIME
        )
    """)
    
    # Reports table - combined created_at
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INT AUTO_INCREMENT PRIMARY KEY,
            chat_id VARCHAR(50),
            user_name VARCHAR(255),
            task LONGBLOB,
            percent INT,
            status VARCHAR(50),
            created_at DATETIME,
            FOREIGN KEY (chat_id) REFERENCES users (chat_id)
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

# Initialize database on import
init_db()

def find_user(chat_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE chat_id = %s", (str(chat_id),))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user:
        # Decrypt sensitive fields
        for field in ENCRYPTED_FIELDS:
            val = user.get(field)
            if val is not None:
                decrypted_val = decrypt(val)
                if field == "chat_history":
                    try:
                        user[field] = json.loads(decrypted_val) if decrypted_val else []
                    except (json.JSONDecodeError, TypeError):
                        user[field] = []
                else:
                    user[field] = decrypted_val
            elif field == "chat_history":
                user[field] = []
        
        # Final safety check for chat_history
        if "chat_history" not in user or user["chat_history"] is None:
            user["chat_history"] = []
            
        return user
    return None

def create_user(chat_id: str, username: str) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute(
        "INSERT IGNORE INTO users (chat_id, username, created_at, step) VALUES (%s, %s, %s, 'NONE')",
        (str(chat_id), username, now)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return find_user(chat_id)

def update_user(chat_id: str, key: str, value: Any):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if key in ENCRYPTED_FIELDS:
        store_value = json.dumps(value) if isinstance(value, (list, dict)) else str(value)
        db_value = encrypt(store_value)
    else:
        db_value = value
    
    if key in ["username", "name", "project", "step", "chat_history", "created_at"]:
        query = f"UPDATE users SET {key} = %s WHERE chat_id = %s"
        cursor.execute(query, (db_value, str(chat_id)))
        conn.commit()
    cursor.close()
    conn.close()

def save_report(user: Dict[str, Any], task: str, percent: int, status: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    encrypted_task = encrypt(task)
    user_name = user.get("name", "Unknown")
    
    # Use Cambodia timezone for creation timestamp
    phnom_penh = pytz.timezone('Asia/Phnom_Penh')
    now = datetime.now(phnom_penh).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute(
        "INSERT INTO reports (chat_id, user_name, task, percent, status, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (str(user["chat_id"]), user_name, encrypted_task, percent, status, now)
    )
    conn.commit()
    cursor.close()
    conn.close()

def load_today_report(user: Dict[str, Any], date_str: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Filter by the date portion of created_at
    cursor.execute(
        "SELECT *, DATE_FORMAT(created_at, '%H:%M') as time_str FROM reports WHERE chat_id = %s AND DATE(created_at) = %s", 
        (str(user["chat_id"]), date_str)
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    if not rows:
        return None
    
    tasks = []
    for row in rows:
        tasks.append({
            "task": decrypt(row["task"]),
            "percent": row["percent"],
            "status": row["status"],
            "time": row["time_str"]
        })
        
    return {
        "date": date_str,
        "employee": user.get("name"),
        "project": user.get("project"),
        "tasks": tasks
    }

def clear_today_report(user: Dict[str, Any], date_str: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reports WHERE chat_id = %s AND DATE(created_at) = %s", (str(user["chat_id"]), date_str))
    conn.commit()
    cursor.close()
    conn.close()

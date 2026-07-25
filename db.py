import json
import os
import sqlite3
import sys
from datetime import datetime

if getattr(sys, "frozen", False):
    _base = os.environ.get("LEADSTORM_BASE_DIR", os.path.dirname(sys.executable))
else:
    _base = os.path.dirname(os.path.abspath(__file__))

DB_SLOT_COUNT = 3
# Rotate to the next database once one database reaches 50 lakh rows.
DB_ROW_LIMIT = 5_000_000
DB_STATE_FILE = os.path.join(_base, "db_state.json")
LEGACY_DB_PATH = os.path.join(_base, "leads.db")


def get_db_paths():
    """Return the available SQLite database paths for rotation."""
    paths = []
    if os.path.exists(LEGACY_DB_PATH):
        paths.append(LEGACY_DB_PATH)
    else:
        paths.append(os.path.join(_base, "leads_1.db"))

    for idx in range(2, DB_SLOT_COUNT + 1):
        paths.append(os.path.join(_base, f"leads_{idx}.db"))

    return paths


def _load_db_state():
    if not os.path.exists(DB_STATE_FILE):
        return {"current_slot": 0, "current_count": 0}

    try:
        with open(DB_STATE_FILE, "r", encoding="utf-8") as handle:
            state = json.load(handle)
            if not isinstance(state, dict):
                return {"current_slot": 0, "current_count": 0}
            if "current_slot" not in state:
                state["current_slot"] = 0
            if "current_count" not in state:
                state["current_count"] = 0
            return state
    except Exception:
        return {"current_slot": 0, "current_count": 0}


def _save_db_state(state):
    with open(DB_STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def get_active_db_path():
    """Return the currently active SQLite file path."""
    state = _load_db_state()
    slot = state.get("current_slot", 0)
    paths = get_db_paths()

    if slot < 0 or slot >= len(paths):
        slot = 0

    return paths[slot]


def rotate_to_next_db():
    """Move to the next database slot and persist the selection."""
    paths = get_db_paths()
    state = _load_db_state()
    current_slot = state.get("current_slot", 0)
    next_slot = (current_slot + 1) % len(paths)
    state["current_slot"] = next_slot
    next_path = paths[next_slot]
    state["current_count"] = _get_row_count(next_path)
    _save_db_state(state)
    return next_path


def get_db_connection(db_path=None):
    """Establishes connection to the active SQLite database."""
    target_path = db_path or get_active_db_path()
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    return conn


def _initialize_schema(conn):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            phone TEXT,
            email TEXT,
            website TEXT,
            address TEXT,
            rating REAL,
            review_count INTEGER,
            city TEXT,
            scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            sent_at DATETIME,
            contact_person TEXT,
            establishment_size TEXT
        )
    """)

    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN contact_person TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN establishment_size TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_phone ON leads(phone)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_name_city ON leads(name, city)")
    conn.commit()


def init_db():
    """Initialize all database slots and create the leads table if it doesn't exist."""
    for db_path in get_db_paths():
        conn = get_db_connection(db_path)
        _initialize_schema(conn)
        conn.close()

    state = _load_db_state()
    if "current_slot" not in state:
        state["current_slot"] = 0
    if "current_count" not in state:
        active_path = get_active_db_path()
        state["current_count"] = _get_row_count(active_path)
    _save_db_state(state)

    return get_active_db_path()


def _get_row_count(db_path):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS count FROM leads")
    row_count = cursor.fetchone()[0]
    conn.close()
    return row_count


def lead_exists(phone=None, name=None, city=None):
    """
    Checks if a lead already exists in the database.
    We check by phone number first, and then by the name+city combination if phone is not available.
    """
    for db_path in get_db_paths():
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        if phone and len(phone.strip()) > 3:
            cursor.execute("SELECT 1 FROM leads WHERE phone = ?", (phone.strip(),))
            result = cursor.fetchone()
            if result:
                conn.close()
                return True

        if name and city:
            cursor.execute(
                "SELECT 1 FROM leads WHERE LOWER(name) = ? AND LOWER(city) = ?",
                (name.strip().lower(), city.strip().lower())
            )
            result = cursor.fetchone()
            if result:
                conn.close()
                return True

        conn.close()

    return False


def insert_lead(lead_data, log_callback=None):
    """
    Inserts a new lead into the active database slot.
    If the current slot reaches the maximum row limit, the app rotates to the next database.
    """
    state = _load_db_state()
    current_db_path = get_active_db_path()
    if state.get("current_count", 0) >= DB_ROW_LIMIT:
        current_db_path = rotate_to_next_db()
        if log_callback:
            log_callback(f"[+] Rotating to database: {os.path.basename(current_db_path)}")
        else:
            print(f"[+] Rotating to database: {os.path.basename(current_db_path)}")
        state = _load_db_state()

    conn = get_db_connection(current_db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO leads (name, category, phone, email, website, address, rating, review_count, city, scraped_at, sent_at, contact_person, establishment_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """, (
            lead_data.get("name"),
            lead_data.get("category"),
            lead_data.get("phone"),
            lead_data.get("email"),
            lead_data.get("website"),
            lead_data.get("address"),
            lead_data.get("rating"),
            lead_data.get("review_count"),
            lead_data.get("city"),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            lead_data.get("contact_person"),
            lead_data.get("establishment_size")
        ))
        conn.commit()
        inserted_id = cursor.lastrowid
        conn.close()

        state["current_count"] = state.get("current_count", 0) + 1
        _save_db_state(state)
        return inserted_id
    except sqlite3.Error as e:
        msg = f"[-] Database insertion error: {e}"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
        conn.close()
        return None


def get_unsent_leads():
    """Retrieves all leads that have not been emailed to the user yet."""
    leads = []
    for db_path in get_db_paths():
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM leads WHERE sent_at IS NULL ORDER BY rating DESC, review_count DESC")
        rows = cursor.fetchall()

        for row in rows:
            lead = dict(row)
            lead["db_file"] = os.path.basename(db_path)
            leads.append(lead)

        conn.close()

    return sorted(leads, key=lambda item: (item.get("rating") or 0, item.get("review_count") or 0), reverse=True)


def get_all_leads():
    """Retrieves all leads from the available database slots."""
    leads = []
    for db_path in get_db_paths():
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM leads ORDER BY scraped_at DESC")
        rows = cursor.fetchall()

        for row in rows:
            lead = dict(row)
            lead["db_file"] = os.path.basename(db_path)
            leads.append(lead)

        conn.close()

    return sorted(leads, key=lambda item: item.get("scraped_at", ""), reverse=True)


def mark_leads_as_sent(lead_ids):
    """Marks a list of lead IDs as emailed/sent to the user in every database slot."""
    if not lead_ids:
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    placeholders = ",".join("?" for _ in lead_ids)

    for db_path in get_db_paths():
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"UPDATE leads SET sent_at = ? WHERE id IN ({placeholders})",
                [now_str] + list(lead_ids)
            )
            conn.commit()
        except sqlite3.Error as e:
            print(f"[-] Error marking leads as sent: {e}")

        conn.close()


init_db()

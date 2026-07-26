import json
import os
import sqlite3
import sys
from datetime import datetime

if getattr(sys, "frozen", False):
    _base = os.environ.get("LEADSTORM_BASE_DIR", os.path.dirname(sys.executable))
else:
    _base = os.path.dirname(os.path.abspath(__file__))

DB_SLOT_COUNT = 15
DB_ROW_LIMIT = 5_000_000
DB_FOLDER = os.path.join(_base, "db")
DB_STATE_FILE = os.path.join(DB_FOLDER, "db_state.json")
HISTORY_DB_PATH = os.path.join(DB_FOLDER, "history.db")

def migrate_databases():
    """Safely migrate any existing DB and state files from root directory to the db/ folder."""
    if not os.path.exists(DB_FOLDER):
        os.makedirs(DB_FOLDER, exist_ok=True)

    # Migrate state file
    root_state = os.path.join(_base, "db_state.json")
    folder_state = os.path.join(DB_FOLDER, "db_state.json")
    if os.path.exists(root_state) and not os.path.exists(folder_state):
        try:
            os.rename(root_state, folder_state)
        except Exception as e:
            print(f"[-] Failed to migrate db_state.json: {e}")

    # Migrate legacy leads.db to leads_1.db in folder
    legacy_path = os.path.join(_base, "leads.db")
    target_path_1 = os.path.join(DB_FOLDER, "leads_1.db")
    if os.path.exists(legacy_path) and not os.path.exists(target_path_1):
        try:
            os.rename(legacy_path, target_path_1)
            print("[+] Migrated legacy leads.db to db/leads_1.db")
        except Exception as e:
            print(f"[-] Failed to migrate legacy database: {e}")

    # Migrate existing leads_X.db files from root to db/ folder
    for idx in range(1, DB_SLOT_COUNT + 1):
        root_path = os.path.join(_base, f"leads_{idx}.db")
        folder_path = os.path.join(DB_FOLDER, f"leads_{idx}.db")
        if os.path.exists(root_path) and not os.path.exists(folder_path):
            try:
                os.rename(root_path, folder_path)
                print(f"[+] Migrated leads_{idx}.db from root to db/ folder")
            except Exception as e:
                print(f"[-] Failed to migrate leads_{idx}.db: {e}")

def get_db_paths():
    """Return the available SQLite database paths for rotation."""
    migrate_databases()
    paths = []
    for idx in range(1, DB_SLOT_COUNT + 1):
        paths.append(os.path.join(DB_FOLDER, f"leads_{idx}.db"))
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
    """Move to the next database slot and persist the selection, deleting the old file if it exists to start fresh."""
    paths = get_db_paths()
    state = _load_db_state()
    current_slot = state.get("current_slot", 0)
    next_slot = (current_slot + 1) % len(paths)
    state["current_slot"] = next_slot
    
    next_path = paths[next_slot]
    if os.path.exists(next_path):
        try:
            # Close connection if any open, then delete
            os.remove(next_path)
        except Exception as e:
            print(f"[-] Error deleting database file for fresh slot {next_slot}: {e}")
            
    # Re-initialize the schema for the fresh slot
    conn = get_db_connection(next_path)
    _initialize_schema(conn)
    conn.close()
    
    state["current_count"] = 0
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
    """Initialize all database slots, history database, and create tables if they don't exist."""
    migrate_databases()
    init_history_db()
    
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


# --- Campaign History and Logging Database Functions ---

def init_history_db():
    """Initialize the campaign history database and prune old entries."""
    if not os.path.exists(DB_FOLDER):
        os.makedirs(DB_FOLDER, exist_ok=True)
    
    conn = sqlite3.connect(HISTORY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            location TEXT,
            keyword TEXT,
            target_count INTEGER,
            leads_found INTEGER,
            status TEXT,
            log_data TEXT
        )
    """)
    conn.commit()
    
    # Auto-prune campaigns older than 10 days
    try:
        cursor.execute("DELETE FROM campaigns WHERE timestamp < datetime('now', '-10 days')")
        conn.commit()
    except Exception as e:
        print(f"[-] Failed to prune campaign history logs: {e}")
        
    # Clean up any orphaned campaigns that were left as 'Running' (from previous app crashes/exits)
    try:
        cursor.execute("UPDATE campaigns SET status = 'Interrupted' WHERE status = 'Running'")
        conn.commit()
    except Exception as e:
        print(f"[-] Failed to clean up orphaned campaigns: {e}")
        
    conn.close()


def add_campaign(location, keyword, target_count):
    """Insert a new campaign and return its ID."""
    init_history_db()
    conn = sqlite3.connect(HISTORY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO campaigns (location, keyword, target_count, leads_found, status, log_data)
        VALUES (?, ?, ?, 0, 'Running', '')
    """, (location, keyword, target_count))
    conn.commit()
    campaign_id = cursor.lastrowid
    conn.close()
    return campaign_id


def update_campaign_status(campaign_id, status, leads_found, log_data):
    """Update status, leads count, and final logs of a campaign."""
    init_history_db()
    conn = sqlite3.connect(HISTORY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE campaigns
        SET status = ?, leads_found = ?, log_data = ?
        WHERE id = ?
    """, (status, leads_found, log_data, campaign_id))
    conn.commit()
    conn.close()


def get_campaign_history():
    """Retrieve campaign runs from the last 3 days."""
    init_history_db()
    conn = sqlite3.connect(HISTORY_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM campaigns ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    history = [dict(row) for row in rows]
    conn.close()
    return history


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


def get_total_leads_count():
    """Returns the total number of leads stored across all 15 database slots."""
    total = 0
    for idx in range(1, DB_SLOT_COUNT + 1):
        db_path = os.path.join(DB_FOLDER, f"leads_{idx}.db")
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM leads")
                total += cursor.fetchone()[0]
                conn.close()
            except Exception:
                pass
    return total


init_db()

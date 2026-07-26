import customtkinter as ctk
import threading
import time
import os
import sys
import json
import requests
import platform
import uuid
import hashlib
import webbrowser
import datetime
import subprocess
import traceback

def log_debug(message):
    try:
        if getattr(sys, "frozen", False):
            log_dir = os.path.dirname(sys.executable)
        else:
            log_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(log_dir, "debug.log")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass

def format_lead_count(val):
    try:
        val = int(val)
    except (ValueError, TypeError):
        return "0"

    if val >= 1000000:
        d = val / 1000000.0
        return f"{d:.2f}".rstrip('0').rstrip('.') + "M"
    elif val >= 100000:
        d = val / 100000.0
        return f"{d:.2f}".rstrip('0').rstrip('.') + "L"
    elif val >= 1000:
        d = val / 1000.0
        return f"{d:.2f}".rstrip('0').rstrip('.') + "k"
    return str(val)


# Force Playwright to use the global browser directory, ignoring PyInstaller's _MEI override
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")

# Import our backend logic
try:
    from scraper import scrape_leads_for_query
    import scraper
    from exporter import save_leads
    from email_sender import send_leads_email
    import db
except ImportError as e:
    print(f"Error importing modules: {e}")

# Color System matching the mockup
BG_COLOR = "#F8FAF7"          # Off-white / light cream
SIDEBAR_BG = "#FFFFFF"        # Pure white sidebar
BORDER_COLOR = "#D0E4D5"      # Muted light green border
TEXT_COLOR = "#1E2B22"        # Dark green-slate text
TEXT_MUTED = "#556B5C"        # Gray-green muted text
ACCENT_GREEN = "#0D7A5C"      # Dark forest green (buttons, selected tab)
ACCENT_HOVER = "#095C45"      # Darker hover state
LIGHT_GREEN_BG = "#EBF5EE"    # Light green card background
ACTIVE_TAB_BG = "#E2F0E5"     # Active tab background tint
INPUT_BORDER = "#C6D8CB"      # Input field border


def get_machine_id():
    """Generates a stable, unique SHA-256 hardware fingerprint."""
    try:
        node = str(uuid.getnode())
        processor = platform.processor() or "unknown_proc"
        system = platform.system() or "unknown_sys"
        raw_fingerprint = f"{node}-{processor}-{system}"
        return hashlib.sha256(raw_fingerprint.encode('utf-8')).hexdigest()
    except Exception:
        try:
            return hashlib.sha256(platform.node().encode('utf-8')).hexdigest()
        except Exception:
            return "fallback_machine_id_12345"


def get_api_url():
    """Reads licensing API URL from config.json, with production fallback."""
    url = "https://veloleads.redsorm.in"
    try:
        if getattr(sys, "frozen", False):
            config_path = os.path.join(os.path.dirname(sys.executable), "config.json")
        else:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

        log_debug(f"Checking config path: {config_path}")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                url = cfg.get("licensing_api_url", "https://veloleads.redsorm.in")
        else:
            log_debug("config.json not found, using production fallback.")
    except Exception as e:
        log_debug(f"get_api_url exception: {str(e)}")
    log_debug(f"Resolved API URL: {url}")
    return url


def install_browsers(log_callback):
    """Automatically installs Playwright Chromium if missing, supporting PyInstaller bundles."""
    log_callback("[*] Checking background browser dependency...")
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver_path = compute_driver_executable()

        if isinstance(driver_path, tuple):
            cmd = [*driver_path, 'install', 'chromium']
        else:
            cmd = [driver_path, 'install', 'chromium']

        subprocess.run(cmd, env=get_driver_env(), check=True, capture_output=True)
        log_callback("[+] Browser check complete.")
    except Exception as e:
        log_callback(f"[!] Warning: Could not auto-install browser: {e}")


# Set customtkinter appearance and default theme
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("green")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 1. Configure Windows taskbar icon grouping to show our custom icon instead of Python's default
        if sys.platform == "win32":
            import ctypes
            try:
                myappid = "com.veloleads.app.1.0.0"
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception:
                pass

        # 2. Set Custom Window & Taskbar Icon
        if getattr(sys, "frozen", False):
            icon_path = os.path.join(sys._MEIPASS, "icon.ico")
        else:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
            
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.title("VeloLeads - Automated AI Lead Generator")
        self.geometry("1150x760")
        self.configure(fg_color=BG_COLOR)

        # Define Premium Fonts
        self.font_title = ctk.CTkFont(family="Segoe UI", size=24, weight="bold")
        self.font_section = ctk.CTkFont(family="Segoe UI", size=18, weight="bold")
        self.font_label = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        self.font_input = ctk.CTkFont(family="Segoe UI", size=13)
        self.font_btn = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        self.font_log = ctk.CTkFont(family="Consolas", size=11)

        # Paths for settings and license files
        if getattr(sys, "frozen", False):
            self.settings_path = os.path.join(os.path.dirname(sys.executable), "settings.json")
            self.license_path = os.path.join(os.path.dirname(sys.executable), "license_info.json")
        else:
            self.settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
            self.license_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "license_info.json")

        self.license_username = ""
        self.license_email = ""
        self.license_expires_at = ""

        # Campaign Tracking
        self.is_scraping = False
        # Load the leads count from the most recent campaign run for startup display
        init_leads_count = 0
        try:
            db.init_history_db()
            history = db.get_campaign_history()
            if history:
                init_leads_count = history[0]["leads_found"]
        except Exception:
            pass

        self.session_leads_count = init_leads_count
        self.campaign_leads_history = [0]
        self.current_campaign_id = None
        self.current_log_lines = []
        self.latest_excel_path = None

        # Loading screen
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.loading_frame = ctk.CTkFrame(self, fg_color=BG_COLOR)
        self.loading_frame.grid(row=0, column=0, sticky="nsew")
        self.loading_frame.grid_columnconfigure(0, weight=1)
        self.loading_frame.grid_rowconfigure(0, weight=1)

        self.loading_lbl = ctk.CTkLabel(self.loading_frame, text="Checking subscription validity...", font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"), text_color=TEXT_MUTED)
        self.loading_lbl.grid(row=0, column=0)

        # Close protocol
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Run background license check thread
        threading.Thread(target=self.background_license_check, daemon=True).start()

    def background_license_check(self):
        log_debug(f"Starting background_license_check... License path: {self.license_path}")
        if not os.path.exists(self.license_path):
            log_debug("license_info.json does not exist. Redirecting to login.")
            self.after(0, self.go_to_login)
            return

        try:
            with open(self.license_path, "r", encoding="utf-8") as f:
                lic = json.load(f)

            username = lic.get("username")
            license_key = lic.get("license_key")
            expires_at_str = lic.get("expires_at")
            log_debug(f"Found local license: username={username}, key={license_key}, expires_at={expires_at_str}")

            if not username or not license_key:
                log_debug("Local license username/key missing. Redirecting to login.")
                self.after(0, self.go_to_login)
                return

            self.license_username = username
            self.license_email = lic.get("email", username)
            self.license_expires_at = expires_at_str

            # Check validity via online licensing server
            api_url = get_api_url()
            machine_id = get_machine_id()
            payload = {
                "username": username,
                "license_key": license_key,
                "machine_id": machine_id
            }
            log_debug(f"Verifying local license online: {api_url}/api/license/verify")

            self.after(0, lambda: self.loading_lbl.configure(text="Verifying license... (Waking up server, please wait)"))
            try:
                res = requests.post(f"{api_url}/api/license/verify", json=payload, timeout=60)
                log_debug(f"Verify response status: {res.status_code}")
                log_debug(f"Verify response raw text: {res.text}")
                data = res.json()

                if res.status_code == 200 and data.get("success"):
                    lic["expires_at"] = data.get("expires_at", expires_at_str)
                    self.license_expires_at = lic["expires_at"]
                    if "email" in data:
                        lic["email"] = data["email"]
                        self.license_email = data["email"]
                    with open(self.license_path, "w", encoding="utf-8") as f:
                        json.dump(lic, f, indent=4)
                    log_debug("Local license verified successfully online. Going to main UI.")
                    self.after(0, self.go_to_main)
                else:
                    log_debug("Local license online verification failed (success=False). Going to login.")
                    self.after(0, self.go_to_login)
            except Exception as e:
                log_debug(f"Online verification exception (network timeout/error): {str(e)}")
                # Connection failed, fallback to local date validation (offline support)
                from datetime import datetime as dt
                try:
                    exp_date_str = expires_at_str.split("T")[0]
                    expiry = dt.strptime(exp_date_str, "%Y-%m-%d")
                    log_debug(f"Offline expiry check: expiry date = {expiry}, current date = {dt.now()}")
                    if expiry > dt.now():
                        log_debug("Offline license is still valid. Going to main UI.")
                        self.after(0, self.go_to_main)
                    else:
                        log_debug("Offline license expired. Going to login.")
                        self.after(0, self.go_to_login)
                except Exception as ex:
                    log_debug(f"Offline verification exception: {str(ex)}")
                    self.after(0, self.go_to_login)
        except Exception as e:
            log_debug(f"Outer background_license_check exception: {str(e)}")
            self.after(0, self.go_to_login)

    def go_to_login(self):
        if hasattr(self, "loading_frame"):
            self.loading_frame.destroy()
        self.setup_login_ui()

    def go_to_main(self):
        if hasattr(self, "loading_frame"):
            self.loading_frame.destroy()
        self.setup_main_ui()

    def setup_login_ui(self):
        # Configure layout for center login box
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.login_frame = ctk.CTkFrame(self, fg_color=SIDEBAR_BG, corner_radius=12, border_width=1, border_color=BORDER_COLOR, width=440, height=450)
        self.login_frame.grid(row=0, column=0, sticky="")
        self.login_frame.grid_propagate(False)
        self.login_frame.grid_columnconfigure(0, weight=1)

        self.login_logo = ctk.CTkLabel(self.login_frame, text="VeloLeads", font=ctk.CTkFont(family="Segoe UI", size=30, weight="bold"), text_color=ACCENT_GREEN)
        self.login_logo.grid(row=0, column=0, padx=25, pady=(35, 5))

        self.login_sub = ctk.CTkLabel(self.login_frame, text="Premium License Activation Required", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=TEXT_MUTED)
        self.login_sub.grid(row=1, column=0, padx=25, pady=(0, 25))

        inputs_config = {"border_width": 1, "corner_radius": 8, "border_color": INPUT_BORDER, "fg_color": "#FFFFFF", "text_color": TEXT_COLOR, "font": self.font_input}

        self.login_user_label = ctk.CTkLabel(self.login_frame, text="Username or Email", font=self.font_label, text_color=TEXT_COLOR)
        self.login_user_label.grid(row=2, column=0, padx=35, pady=(5, 2), sticky="w")
        self.login_user_entry = ctk.CTkEntry(self.login_frame, height=40, placeholder_text="Enter your registered username/email", **inputs_config)
        self.login_user_entry.grid(row=3, column=0, padx=35, pady=(0, 12), sticky="ew")

        self.login_key_label = ctk.CTkLabel(self.login_frame, text="License Key", font=self.font_label, text_color=TEXT_COLOR)
        self.login_key_label.grid(row=4, column=0, padx=35, pady=(5, 2), sticky="w")
        self.login_key_entry = ctk.CTkEntry(self.login_frame, height=40, placeholder_text="VELO-XXXX-XXXX-XXXX", **inputs_config)
        self.login_key_entry.grid(row=5, column=0, padx=35, pady=(0, 10), sticky="ew")

        self.login_error_label = ctk.CTkLabel(self.login_frame, text="", font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#EF4444", wraplength=380)
        self.login_error_label.grid(row=6, column=0, padx=35, pady=(0, 15), sticky="w")

        # Action button container
        self.login_btn_frame = ctk.CTkFrame(self.login_frame, fg_color="transparent")
        self.login_btn_frame.grid(row=7, column=0, padx=35, pady=(0, 30), sticky="ew")
        self.login_btn_frame.grid_columnconfigure((0, 1), weight=1)

        self.login_submit_btn = ctk.CTkButton(self.login_btn_frame, text="ACTIVATE", command=self.attempt_activation,
                                             height=40, corner_radius=8, font=self.font_btn,
                                             fg_color=ACCENT_GREEN, hover_color=ACCENT_HOVER, text_color="#FFFFFF")
        self.login_submit_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.login_buy_btn = ctk.CTkButton(self.login_btn_frame, text="BUY LICENSE", command=lambda: webbrowser.open(get_api_url()),
                                          height=40, corner_radius=8, font=self.font_btn,
                                          fg_color=LIGHT_GREEN_BG, hover_color=BORDER_COLOR, text_color=ACCENT_GREEN, border_width=1, border_color=BORDER_COLOR)
        self.login_buy_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")

    def attempt_activation(self):
        username = self.login_user_entry.get().strip()
        license_key = self.login_key_entry.get().strip()

        log_debug(f"Attempting activation with username: '{username}' and key: '{license_key}'")
        if not username or not license_key:
            self.login_error_label.configure(text="Please fill in both username and license key.", text_color="#EF4444")
            return

        self.login_submit_btn.configure(state="disabled", text="ACTIVATING...")
        self.login_buy_btn.configure(state="disabled")
        self.login_error_label.configure(text="Connecting... (Waking up server, please wait up to 1 min)", text_color="#16A34A")

        threading.Thread(target=self.run_activation, args=(username, license_key), daemon=True).start()

    def run_activation(self, username, license_key):
        log_debug("Starting run_activation background thread...")
        try:
            api_url = get_api_url()
            machine_id = get_machine_id()
            payload = {
                "username": username,
                "license_key": license_key,
                "machine_id": machine_id
            }
            log_debug(f"Activation request payload: {json.dumps(payload)}")
            
            target_url = f"{api_url}/api/license/activate"
            log_debug(f"Sending POST to {target_url}...")
            
            res = requests.post(target_url, json=payload, timeout=60)
            log_debug(f"Response status code: {res.status_code}")
            log_debug(f"Response raw text: {res.text}")
            
            data = res.json()
            log_debug(f"Parsed JSON response data: {json.dumps(data)}")

            if res.status_code == 200 and data.get("success"):
                license_data = {
                    "username": data.get("username", username),
                    "email": data.get("email", username if "@" in username else ""), 
                    "license_key": license_key,
                    "expires_at": data.get("expires_at")
                }
                
                log_debug(f"Writing license_info.json to path: {self.license_path}")
                with open(self.license_path, "w", encoding="utf-8") as f:
                    json.dump(license_data, f, indent=4)
                log_debug("Successfully wrote license_info.json")

                self.license_username = license_data["username"]
                self.license_email = license_data["email"]
                self.license_expires_at = license_data["expires_at"]

                log_debug("Scheduling activation_success call on main GUI thread...")
                self.after(0, self.activation_success)
            else:
                msg = data.get("message", "License activation failed.")
                log_debug(f"Activation failed message from server: {msg}")
                self.after(0, lambda: self.activation_failed(msg))
        except Exception as e:
            tb = traceback.format_exc()
            log_debug(f"Exception during run_activation:\n{tb}")
            self.after(0, lambda: self.activation_failed(f"Could not connect to verification server: {str(e)}"))

    def activation_success(self):
        log_debug("activation_success invoked. Destroying login frame and setting up main UI...")
        if hasattr(self, "login_frame"):
            self.login_frame.destroy()
        self.setup_main_ui()

    def activation_failed(self, message):
        self.login_submit_btn.configure(state="normal", text="ACTIVATE")
        self.login_buy_btn.configure(state="normal")
        self.login_error_label.configure(text=message, text_color="#EF4444")

    def renew_plan(self):
        """Opens renewal page in browser with prefilled username/email parameters."""
        api_url = get_api_url()
        webbrowser.open(f"{api_url}?renew={self.license_username}&email={self.license_email}")

    def logout_account(self):
        """Logs out from the active account, deletes local license cache, and redirects to login."""
        log_debug("logout_account called. Deleting license_info.json and redirecting to login...")
        
        # 1. Delete local license cache
        if os.path.exists(self.license_path):
            try:
                os.remove(self.license_path)
                log_debug("Successfully deleted license_info.json")
            except Exception as e:
                log_debug(f"Failed to delete license_info.json: {e}")
        
        # 2. Reset runtime variables
        self.license_username = ""
        self.license_email = ""
        self.license_expires_at = ""
        
        # 3. Destroy main UI and show login screen
        for widget in self.winfo_children():
            widget.destroy()
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.setup_login_ui()

    def setup_main_ui(self):
        # Configure layout for Main SPA Screen (Sidebar + Dynamic content pane)
        self.grid_columnconfigure(0, weight=0) # Sidebar column
        self.grid_columnconfigure(1, weight=1) # Main Content column
        self.grid_rowconfigure(0, weight=1)

        # 1. Left Sidebar Navigation Panel
        self.sidebar_frame = ctk.CTkFrame(self, width=240, corner_radius=0, fg_color=SIDEBAR_BG, border_width=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_frame.grid_propagate(False)

        # Right border line using a tiny frame (looks cleaner than customtkinter border)
        self.sidebar_line = ctk.CTkFrame(self, width=1, fg_color=BORDER_COLOR, corner_radius=0)
        self.sidebar_line.grid(row=0, column=0, sticky="nse")

        # Sidebar Header (Logo)
        self.sidebar_header = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.sidebar_header.grid(row=0, column=0, padx=20, pady=(25, 20), sticky="ew")
        
        # Leaf / Green Icon Mock
        self.logo_icon_canvas = ctk.CTkCanvas(self.sidebar_header, width=28, height=28, bg="white", highlightthickness=0)
        self.logo_icon_canvas.pack(side="left", padx=(0, 10))
        self.logo_icon_canvas.create_oval(2, 2, 26, 26, fill=ACCENT_GREEN, outline="")
        self.logo_icon_canvas.create_oval(8, 8, 20, 20, fill="white", outline="")

        self.logo_label = ctk.CTkLabel(self.sidebar_header, text="VeloLeads", font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"), text_color=TEXT_COLOR)
        self.logo_label.pack(side="left")

        # Tab Navigation Container
        self.nav_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.nav_frame.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        self.nav_frame.grid_columnconfigure(0, weight=1)

        self.nav_buttons = {}
        tabs = [
            ("Lead Scraper", "🔍"),
            ("History", "⏳"),
            ("Reports", "📄")
        ]

        for idx, (tab_name, emoji) in enumerate(tabs):
            btn = ctk.CTkButton(
                self.nav_frame,
                text=f"  {emoji}   {tab_name}",
                font=self.font_btn,
                anchor="w",
                height=42,
                corner_radius=8,
                fg_color="transparent",
                text_color=TEXT_MUTED,
                hover_color=LIGHT_GREEN_BG,
                command=lambda name=tab_name: self.show_view(name)
            )
            btn.grid(row=idx, column=0, pady=4, sticky="ew")
            self.nav_buttons[tab_name] = btn

        # Spacer to push subscription card to bottom
        self.sidebar_frame.grid_rowconfigure(2, weight=1)

        # Bottom Subscription Card
        self.sub_card = ctk.CTkFrame(self.sidebar_frame, fg_color=LIGHT_GREEN_BG, corner_radius=12, border_width=1, border_color=BORDER_COLOR)
        self.sub_card.grid(row=3, column=0, padx=15, pady=(15, 10), sticky="ew")
        self.sub_card.grid_columnconfigure(0, weight=1)

        self.sub_plan = ctk.CTkLabel(self.sub_card, text="Super Plan", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=TEXT_COLOR)
        self.sub_plan.grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")

        exp_dt = "Expired"
        try:
            exp_dt = self.license_expires_at.split("T")[0]
        except Exception:
            exp_dt = self.license_expires_at

        self.sub_expiry = ctk.CTkLabel(self.sub_card, text=f"Valid till {exp_dt}", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=TEXT_MUTED)
        self.sub_expiry.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")

        self.sub_btn = ctk.CTkButton(
            self.sub_card,
            text="Renew",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            height=28,
            fg_color="#D4EAD9",
            hover_color="#C2E2C9",
            text_color=ACCENT_GREEN,
            command=self.renew_plan
        )
        self.sub_btn.grid(row=2, column=0, padx=12, pady=(0, 6), sticky="ew")

        self.logout_btn = ctk.CTkButton(
            self.sub_card,
            text="Log Out",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            height=28,
            fg_color="transparent",
            hover_color="#FADBD8",
            text_color="#C0392B",
            border_width=1,
            border_color="#F5B7B1",
            command=self.logout_account
        )
        self.logout_btn.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")

        # Need Help Support Section
        self.support_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.support_frame.grid(row=4, column=0, padx=15, pady=(5, 20), sticky="ew")
        
        self.support_link = ctk.CTkButton(
            self.support_frame,
            text="💬  Need Help?\n     Chat with support",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            anchor="w",
            height=30,
            fg_color="transparent",
            text_color=TEXT_MUTED,
            hover=False,
            command=self.show_support_dialog
        )
        self.support_link.pack(fill="x")

        # 2. Main Content Container
        self.content_container = ctk.CTkFrame(self, fg_color=BG_COLOR, corner_radius=0)
        self.content_container.grid(row=0, column=1, sticky="nsew")

        # Load settings
        self.load_settings()

        # Initialize view to Lead Scraper
        self.show_view("Lead Scraper")

        # Start Scheduler Thread
        self.last_run_dates = {}
        self.scheduler_thread = threading.Thread(target=self.scheduler_loop, daemon=True)
        self.scheduler_thread.start()

    def show_support_dialog(self):
        """Displays support contact information dialog box."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Contact Support")
        dialog.geometry("420x220")
        dialog.resizable(False, False)
        dialog.configure(fg_color="#FFFFFF")
        dialog.transient(self) # Keep on top of main window
        dialog.grab_set()      # Focus lock
        
        # Center popup on window
        x = self.winfo_x() + (self.winfo_width() // 2) - 210
        y = self.winfo_y() + (self.winfo_height() // 2) - 110
        dialog.geometry(f"+{x}+{y}")

        lbl_title = ctk.CTkLabel(dialog, text="VeloLeads Support", font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"), text_color=ACCENT_GREEN)
        lbl_title.pack(pady=(25, 8))

        msg = "Need help or want to renew your plan?\nGet in touch directly with our support team:"
        lbl_msg = ctk.CTkLabel(dialog, text=msg, font=ctk.CTkFont(family="Segoe UI", size=13), text_color=TEXT_COLOR)
        lbl_msg.pack(pady=5)

        lbl_whatsapp = ctk.CTkLabel(dialog, text="WhatsApp: +91 7780321490", font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"), text_color=ACCENT_GREEN)
        lbl_whatsapp.pack(pady=(10, 2))

        lbl_email = ctk.CTkLabel(dialog, text="Email: veloleads1@gmail.com", font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"), text_color=ACCENT_GREEN)
        lbl_email.pack(pady=(0, 20))

    def show_view(self, view_name):
        """Change navigation active button state and update the content frame."""
        for name, button in self.nav_buttons.items():
            if name == view_name:
                button.configure(fg_color=ACTIVE_TAB_BG, text_color=ACCENT_GREEN)
            else:
                button.configure(fg_color="transparent", text_color=TEXT_MUTED)

        if hasattr(self, "current_view_frame") and self.current_view_frame:
            self.current_view_frame.destroy()

        self.current_view_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.current_view_frame.pack(fill="both", expand=True, padx=25, pady=20)

        if view_name == "Overview":
            self.setup_overview_view()
        elif view_name == "Lead Scraper":
            self.setup_scraper_view()
        elif view_name == "History":
            self.setup_history_view()
        elif view_name == "Reports":
            self.setup_reports_view()
        elif view_name == "Settings":
            self.setup_settings_view()

    # --- 1. OVERVIEW VIEW ---
    def setup_overview_view(self):
        self.current_view_frame.grid_columnconfigure((0, 1), weight=1, uniform="equal")
        self.current_view_frame.grid_rowconfigure((1, 2), weight=1)

        # Page Header
        lbl_header = ctk.CTkLabel(self.current_view_frame, text="Dashboard Overview", font=self.font_title, text_color=TEXT_COLOR)
        lbl_header.grid(row=0, column=0, columnspan=2, sticky="w", pady=(5, 15))

        # Metrics Card 1: Active Database Slot
        card_db = ctk.CTkFrame(self.current_view_frame, fg_color=SIDEBAR_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        card_db.grid(row=1, column=0, padx=(0, 10), pady=(0, 10), sticky="nsew")
        card_db.grid_columnconfigure(0, weight=1)
        
        lbl_db_title = ctk.CTkLabel(card_db, text="Active Database Slot", font=self.font_label, text_color=TEXT_MUTED)
        lbl_db_title.pack(anchor="w", padx=20, pady=(20, 5))
        
        active_db = "leads_1.db"
        try:
            active_db = os.path.basename(db.get_active_db_path())
        except Exception:
            pass
        lbl_db_val = ctk.CTkLabel(card_db, text=active_db, font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"), text_color=ACCENT_GREEN)
        lbl_db_val.pack(anchor="w", padx=20, pady=(0, 5))
        
        # Determine slot idx
        slot_text = "Slot rotation active (1 of 15)"
        try:
            state = db._load_db_state()
            slot_text = f"Slot rotation active ({state.get('current_slot', 0) + 1} of 15)"
        except Exception:
            pass
        lbl_db_desc = ctk.CTkLabel(card_db, text=slot_text, font=ctk.CTkFont(family="Segoe UI", size=11), text_color=TEXT_MUTED)
        lbl_db_desc.pack(anchor="w", padx=20, pady=(0, 20))

        # Metrics Card 2: Total Leads Scraped (Combined)
        card_leads = ctk.CTkFrame(self.current_view_frame, fg_color=SIDEBAR_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        card_leads.grid(row=1, column=1, padx=(10, 0), pady=(0, 10), sticky="nsew")
        
        lbl_leads_title = ctk.CTkLabel(card_leads, text="Total Saved Leads (All Slots)", font=self.font_label, text_color=TEXT_MUTED)
        lbl_leads_title.pack(anchor="w", padx=20, pady=(20, 5))
        
        total_leads = 0
        try:
            for p in db.get_db_paths():
                if os.path.exists(p):
                    total_leads += db._get_row_count(p)
        except Exception:
            pass
        lbl_leads_val = ctk.CTkLabel(card_leads, text=f"{total_leads:,}", font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"), text_color=TEXT_COLOR)
        lbl_leads_val.pack(anchor="w", padx=20, pady=(0, 5))
        
        lbl_leads_desc = ctk.CTkLabel(card_leads, text="Scraped locally & saved securely in SQLite3 database", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=TEXT_MUTED)
        lbl_leads_desc.pack(anchor="w", padx=20, pady=(0, 20))

        # Banner Card (Bottom)
        card_banner = ctk.CTkFrame(self.current_view_frame, fg_color=LIGHT_GREEN_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        card_banner.grid(row=2, column=0, columnspan=2, pady=10, sticky="nsew")
        card_banner.grid_columnconfigure(0, weight=1)
        
        lbl_welcome = ctk.CTkLabel(card_banner, text="Welcome to VeloLeads Campaign Manager!", font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"), text_color=ACCENT_GREEN)
        lbl_welcome.pack(anchor="w", padx=25, pady=(25, 10))

        banner_text = (
            "VeloLeads helps you scrape high-quality B2B leads from Google Maps automatically.\n\n"
            "• Use the 'Lead Scraper' tab to customize campaigns, keywords, and schedules.\n"
            "• Checked database results are automatically rotation-managed to protect storage.\n"
            "• View run histories, diagnostic log entries, and export directly to Excel sheets."
        )
        lbl_desc = ctk.CTkLabel(card_banner, text=banner_text, justify="left", font=ctk.CTkFont(family="Segoe UI", size=13), text_color=TEXT_COLOR)
        lbl_desc.pack(anchor="w", padx=25, pady=(0, 25))

    # --- 2. LEAD SCRAPER VIEW ---
    def setup_scraper_view(self):
        self.current_view_frame.grid_columnconfigure(0, weight=3, uniform="main")
        self.current_view_frame.grid_columnconfigure(1, weight=2, uniform="main")
        self.current_view_frame.grid_rowconfigure(0, weight=1)

        # Left Column: Inputs Form
        form_scroll = ctk.CTkScrollableFrame(self.current_view_frame, fg_color="transparent")
        form_scroll.grid(row=0, column=0, padx=(0, 15), sticky="nsew")
        form_scroll.grid_columnconfigure(0, weight=1)

        lbl_form_title = ctk.CTkLabel(form_scroll, text="Let's Find Amazing Leads! 🔍", font=self.font_title, text_color=TEXT_COLOR)
        lbl_form_title.grid(row=0, column=0, sticky="w", pady=(5, 2))

        lbl_form_sub = ctk.CTkLabel(form_scroll, text="Fill in the details below and we'll do the rest.", font=ctk.CTkFont(family="Segoe UI", size=13), text_color=TEXT_MUTED)
        lbl_form_sub.grid(row=1, column=0, sticky="w", pady=(0, 20))

        inputs_config = {"border_width": 1, "corner_radius": 8, "border_color": INPUT_BORDER, "fg_color": "#FFFFFF", "text_color": TEXT_COLOR, "font": self.font_input}

        # Locations
        lbl_loc = ctk.CTkLabel(form_scroll, text="Locations", font=self.font_label, text_color=TEXT_COLOR)
        lbl_loc.grid(row=2, column=0, sticky="w", pady=(10, 4))
        self.loc_entry = ctk.CTkEntry(form_scroll, height=40, placeholder_text="e.g. Hyderabad, Bangalore, Mumbai", **inputs_config)
        self.loc_entry.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        # Niche / Keywords
        lbl_kw = ctk.CTkLabel(form_scroll, text="Niche / Keywords", font=self.font_label, text_color=TEXT_COLOR)
        lbl_kw.grid(row=4, column=0, sticky="w", pady=(10, 4))
        self.kw_entry = ctk.CTkEntry(form_scroll, height=40, placeholder_text="e.g. Restaurants, Plumbers, Stock Market", **inputs_config)
        self.kw_entry.grid(row=5, column=0, sticky="ew", pady=(0, 10))

        # Extra Info / Prompt Description
        lbl_desc = ctk.CTkLabel(form_scroll, text="Extra Info / Prompt Description", font=self.font_label, text_color=TEXT_COLOR)
        lbl_desc.grid(row=6, column=0, sticky="w", pady=(10, 4))
        self.desc_entry = ctk.CTkEntry(form_scroll, height=40, placeholder_text="e.g. Find suggestion providers or high reviews only", **inputs_config)
        self.desc_entry.grid(row=7, column=0, sticky="ew", pady=(0, 10))

        # Target Emails
        lbl_email = ctk.CTkLabel(form_scroll, text="Target Emails (comma separated)", font=self.font_label, text_color=TEXT_COLOR)
        lbl_email.grid(row=8, column=0, sticky="w", pady=(10, 4))
        self.email_entry = ctk.CTkEntry(form_scroll, height=40, placeholder_text="Enter emails to send report", **inputs_config)
        self.email_entry.grid(row=9, column=0, sticky="ew", pady=(0, 15))

        # Bottom row layouts
        bottom_options_frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
        bottom_options_frame.grid(row=10, column=0, sticky="ew", pady=(0, 10))
        bottom_options_frame.grid_columnconfigure((0, 1), weight=1)

        # Target Leads Count
        leads_frame = ctk.CTkFrame(bottom_options_frame, fg_color="transparent")
        leads_frame.grid(row=0, column=0, padx=(0, 10), sticky="ew")
        lbl_leads = ctk.CTkLabel(leads_frame, text="Leads per Query", font=self.font_label, text_color=TEXT_COLOR)
        lbl_leads.pack(anchor="w")
        self.leads_entry = ctk.CTkEntry(leads_frame, height=36, placeholder_text="e.g. 50", **inputs_config)
        self.leads_entry.pack(fill="x", pady=(2, 0))

        # Auto Schedule Switch
        switch_frame = ctk.CTkFrame(bottom_options_frame, fg_color="transparent")
        switch_frame.grid(row=0, column=1, padx=(10, 0), sticky="ew")
        lbl_switch = ctk.CTkLabel(switch_frame, text="Schedule Daily", font=self.font_label, text_color=TEXT_COLOR)
        lbl_switch.pack(anchor="w")
        self.schedule_switch = ctk.CTkSwitch(switch_frame, text="Run daily", font=self.font_input, progress_color=ACCENT_GREEN, text_color=TEXT_COLOR)
        self.schedule_switch.pack(anchor="w", pady=(8, 0))

        # Auto Run Times Header
        lbl_times_section = ctk.CTkLabel(form_scroll, text="Auto Run Times (Up to 4 times per day)", font=self.font_label, text_color=TEXT_COLOR)
        lbl_times_section.grid(row=11, column=0, sticky="w", pady=(12, 4))

        # Auto Run Times Inputs (4 side-by-side)
        times_container = ctk.CTkFrame(form_scroll, fg_color="transparent")
        times_container.grid(row=12, column=0, sticky="ew", pady=(0, 15))
        times_container.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.schedule_time_entries = []
        for idx in range(4):
            padding_left = 0 if idx == 0 else 6
            padding_right = 0 if idx == 3 else 6
            entry = ctk.CTkEntry(
                times_container, 
                height=36, 
                placeholder_text=f"Time {idx+1} (e.g. 14:30)", 
                **inputs_config
            )
            entry.grid(row=0, column=idx, padx=(padding_left, padding_right), sticky="ew")
            self.schedule_time_entries.append(entry)

        # Load values into form fields
        self.fill_form_inputs()

        # Action Buttons
        self.start_btn = ctk.CTkButton(
            form_scroll,
            text="Start Scraping  →",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            height=46,
            corner_radius=8,
            fg_color=ACCENT_GREEN,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self.start_scraping
        )
        self.start_btn.grid(row=13, column=0, sticky="ew", pady=(15, 5))
        
        if self.is_scraping:
            self.start_btn.configure(state="disabled", text="SCRAPING...", fg_color="#A1A1AA")

        # Save configuration button
        self.save_btn = ctk.CTkButton(
            form_scroll,
            text="Save Configuration",
            font=self.font_btn,
            height=36,
            corner_radius=8,
            fg_color="transparent",
            hover_color=LIGHT_GREEN_BG,
            text_color=ACCENT_GREEN,
            border_width=1,
            border_color=BORDER_COLOR,
            command=self.save_settings_with_notification
        )
        self.save_btn.grid(row=14, column=0, sticky="ew", pady=(5, 20))

        # Right Column: What's Happening & Total Leads Scraped
        right_panel = ctk.CTkFrame(self.current_view_frame, fg_color="transparent")
        right_panel.grid(row=0, column=1, padx=(15, 0), sticky="nsew")
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(0, weight=2)
        right_panel.grid_rowconfigure(1, weight=1)

        # Card 1: What's Happening? (Real-time logs)
        self.card_status = ctk.CTkFrame(right_panel, fg_color=SIDEBAR_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        self.card_status.grid(row=0, column=0, pady=(0, 10), sticky="nsew")
        self.card_status.grid_columnconfigure(0, weight=1)
        self.card_status.grid_rowconfigure(1, weight=1)

        lbl_status_title = ctk.CTkLabel(self.card_status, text="What's happening?", font=self.font_section, text_color=TEXT_COLOR)
        lbl_status_title.grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5))

        # Small Textbox for log snippet
        self.log_box = ctk.CTkTextbox(self.card_status, font=self.font_log, fg_color="transparent", text_color=TEXT_COLOR, wrap="word", corner_radius=0)
        self.log_box.grid(row=1, column=0, padx=15, pady=(0, 5), sticky="nsew")
        self.log_box.configure(state="disabled")
        
        # Populate current logs if any
        if self.current_log_lines:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", "\n".join(self.current_log_lines) + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(self.card_status, height=6, corner_radius=3, progress_color=ACCENT_GREEN, fg_color=LIGHT_GREEN_BG)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=15, pady=(5, 15))
        self.progress_bar.set(0)

        # Card 2: Scraped Leads Details (Last Scraped & Total Leads)
        self.card_scraped = ctk.CTkFrame(right_panel, fg_color=LIGHT_GREEN_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        self.card_scraped.grid(row=1, column=0, pady=(10, 0), sticky="nsew")
        self.card_scraped.grid_columnconfigure((0, 1), weight=1)
        self.card_scraped.grid_rowconfigure(2, weight=1)

        # Stats sub-frame to align metrics neatly
        self.stats_frame = ctk.CTkFrame(self.card_scraped, fg_color="transparent")
        self.stats_frame.grid(row=0, column=0, rowspan=2, columnspan=2, sticky="w", padx=20, pady=(15, 0))
        self.stats_frame.grid_columnconfigure((0, 1), weight=1)

        # 1. Last Scraped
        lbl_last_title = ctk.CTkLabel(self.stats_frame, text="Last Scraped", font=self.font_label, text_color=ACCENT_GREEN)
        lbl_last_title.grid(row=0, column=0, sticky="w")
        self.lbl_last_val = ctk.CTkLabel(self.stats_frame, text=format_lead_count(self.session_leads_count), font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"), text_color=TEXT_COLOR)
        self.lbl_last_val.grid(row=1, column=0, sticky="w", pady=(2, 0))

        # 2. Total Leads
        lbl_total_title = ctk.CTkLabel(self.stats_frame, text="Total Leads", font=self.font_label, text_color=ACCENT_GREEN)
        lbl_total_title.grid(row=0, column=1, sticky="w", padx=(30, 0))
        
        try:
            init_tot = db.get_total_leads_count()
        except Exception:
            init_tot = 0

        self.lbl_total_val = ctk.CTkLabel(self.stats_frame, text=format_lead_count(init_tot), font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"), text_color=TEXT_COLOR)
        self.lbl_total_val.grid(row=1, column=1, sticky="w", padx=(30, 0), pady=(2, 0))

        # View Reports link button
        btn_view_rep = ctk.CTkButton(
            self.card_scraped,
            text="View latest report  →",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="transparent",
            text_color=ACCENT_GREEN,
            hover=False,
            width=80,
            command=self.open_generated_report
        )
        btn_view_rep.grid(row=2, column=0, columnspan=2, sticky="sw", padx=15, pady=(0, 15))

        # Canvas-drawn Sparkline (Mock trend)
        self.sparkline_canvas = ctk.CTkCanvas(self.card_scraped, width=130, height=45, bg=LIGHT_GREEN_BG, highlightthickness=0)
        self.sparkline_canvas.grid(row=0, column=0, columnspan=2, rowspan=3, sticky="ne", padx=20, pady=(15, 0))
        self.draw_sparkline()

    def draw_sparkline(self):
        """Draws a smooth line chart representation on the canvas card."""
        if not hasattr(self, "sparkline_canvas") or not self.sparkline_canvas:
            return
        
        self.sparkline_canvas.delete("all")
        
        # Scale/render history points
        pts = self.campaign_leads_history
        if len(pts) < 2:
            # Default static wavy preview
            points = [10, 40, 30, 20, 55, 38, 80, 15, 105, 32, 130, 8, 145, 22]
        else:
            # Map values dynamically
            max_val = max(pts) if max(pts) > 0 else 1
            points = []
            width = 130
            height = 30
            x_start = 10
            y_start = 40
            
            for idx, val in enumerate(pts):
                x = x_start + idx * (width / (len(pts) - 1))
                y = y_start - (val / max_val) * height
                points.extend([x, y])

        try:
            # Shaded transparent polygon underneath
            poly_points = [points[0], 45] + points + [points[-2], 45]
            self.sparkline_canvas.create_polygon(poly_points, fill="#D2EBE0", outline="")
            
            # Main Green Bezier Line
            self.sparkline_canvas.create_line(points, fill=ACCENT_GREEN, width=3, smooth=True)
        except Exception:
            pass

    def update_leads_labels(self, cnt, tot):
        """Helper to update leads counter labels from background threads."""
        if hasattr(self, "lbl_last_val") and self.lbl_last_val:
            self.lbl_last_val.configure(text=format_lead_count(cnt))
        if hasattr(self, "lbl_total_val") and self.lbl_total_val:
            self.lbl_total_val.configure(text=format_lead_count(tot))

    def open_generated_report(self):
        """Open the latest campaign excel report file or exports folder."""
        path = self.latest_excel_path
        if not path or not os.path.exists(path):
            if getattr(sys, "frozen", False):
                path = os.path.join(os.path.dirname(sys.executable), "exports")
            else:
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
        
        if os.path.exists(path):
            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                self.log(f"[!] Error opening reports folder: {e}")
        else:
            self.log("[!] Export folder not found. No report has been generated yet.")

    def fill_form_inputs(self):
        """Loads entries from settings dictionary into Scraper inputs."""
        settings = self.loaded_settings_dict
        if not settings:
            return

        if settings.get("locations"):
            self.loc_entry.insert(0, settings["locations"])
        if settings.get("keywords"):
            self.kw_entry.insert(0, settings["keywords"])
        if settings.get("description"):
            self.desc_entry.insert(0, settings["description"])
        if settings.get("emails"):
            self.email_entry.insert(0, settings["emails"])
        if settings.get("target") is not None and str(settings["target"]).strip() != "":
            self.leads_entry.insert(0, str(settings["target"]))
        if "schedule_enabled" in settings and settings["schedule_enabled"]:
            self.schedule_switch.select()

        schedule_times = settings.get("schedule_times") or []
        if not schedule_times and "schedule_time" in settings:
            schedule_times = [settings["schedule_time"]]
        
        for idx, time_val in enumerate(schedule_times):
            if idx < len(self.schedule_time_entries) and str(time_val).strip() != "":
                self.schedule_time_entries[idx].insert(0, str(time_val))

    # --- 3. HISTORY VIEW ---
    def setup_history_view(self):
        self.current_view_frame.grid_columnconfigure(0, weight=1, uniform="hist")
        self.current_view_frame.grid_columnconfigure(1, weight=2, uniform="hist")
        self.current_view_frame.grid_rowconfigure(0, weight=1)

        # Left Panel: Campaigns List
        hist_panel = ctk.CTkFrame(self.current_view_frame, fg_color="transparent")
        hist_panel.grid(row=0, column=0, padx=(0, 15), sticky="nsew")
        hist_panel.grid_columnconfigure(0, weight=1)
        hist_panel.grid_rowconfigure(1, weight=1)

        lbl_hist_title = ctk.CTkLabel(hist_panel, text="Campaign History", font=self.font_section, text_color=TEXT_COLOR)
        lbl_hist_title.grid(row=0, column=0, sticky="w", pady=(5, 10))

        self.scroll_campaigns = ctk.CTkScrollableFrame(hist_panel, fg_color=SIDEBAR_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        self.scroll_campaigns.grid(row=1, column=0, sticky="nsew")
        self.scroll_campaigns.grid_columnconfigure(0, weight=1)

        # Right Panel: Terminal Log Box
        self.terminal_panel = ctk.CTkFrame(self.current_view_frame, fg_color=SIDEBAR_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        self.terminal_panel.grid(row=0, column=1, padx=(15, 0), sticky="nsew")
        self.terminal_panel.grid_columnconfigure(0, weight=1)
        self.terminal_panel.grid_rowconfigure(1, weight=1)

        self.lbl_selected_title = ctk.CTkLabel(self.terminal_panel, text="Select a campaign run to view logs", font=self.font_section, text_color=TEXT_COLOR)
        self.lbl_selected_title.grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))

        self.hist_log_box = ctk.CTkTextbox(self.terminal_panel, font=self.font_log, fg_color="transparent", text_color=TEXT_COLOR, wrap="word", corner_radius=0)
        self.hist_log_box.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.hist_log_box.configure(state="disabled")

        # Load campaigns list from database
        self.selected_campaign_row_id = None
        self.refresh_campaign_list()

    def refresh_campaign_list(self):
        """Reads database logs history list and renders it as select cards."""
        # Clear existing cards
        for widget in self.scroll_campaigns.winfo_children():
            widget.destroy()

        try:
            campaigns = db.get_campaign_history()
        except Exception:
            campaigns = []

        if not campaigns:
            lbl_empty = ctk.CTkLabel(self.scroll_campaigns, text="No campaigns run in the last 10 days.", font=self.font_input, text_color=TEXT_MUTED)
            lbl_empty.pack(pady=20)
            return

        self.campaign_buttons = []
        for idx, camp in enumerate(campaigns):
            card = ctk.CTkFrame(self.scroll_campaigns, fg_color=LIGHT_GREEN_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=8, cursor="hand2")
            card.pack(fill="x", padx=5, pady=5)
            
            # Timestamp (Clean text)
            dt_str = camp.get("timestamp", "")
            try:
                # Format ISO datetime if needed
                dt_str = dt_str.split(".")[0]
            except Exception:
                pass
            
            lbl_time = ctk.CTkLabel(card, text=dt_str, font=ctk.CTkFont(family="Segoe UI", size=10), text_color=TEXT_MUTED)
            lbl_time.pack(anchor="w", padx=12, pady=(8, 2))

            # Query description
            query_desc = f"{camp.get('keyword', '')} in {camp.get('location', '')}"
            if len(query_desc) > 30:
                query_desc = query_desc[:27] + "..."
            
            lbl_query = ctk.CTkLabel(card, text=query_desc, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=TEXT_COLOR)
            lbl_query.pack(anchor="w", padx=12, pady=0)

            # Details row (leads found, status badge)
            lbl_details = ctk.CTkLabel(card, text=f"Leads: {camp.get('leads_found', 0)}  |  Status: {camp.get('status', 'Completed')}", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=TEXT_MUTED)
            lbl_details.pack(anchor="w", padx=12, pady=(0, 8))

            # Click selection binding
            for w in [card, lbl_time, lbl_query, lbl_details]:
                w.bind("<Button-1>", lambda event, cid=camp["id"], title=query_desc: self.select_campaign_run(cid, title))

    def select_campaign_run(self, campaign_id, title):
        """Loads and displays logs of a selected past campaign."""
        self.selected_campaign_row_id = campaign_id
        self.lbl_selected_title.configure(text=f"Logs: {title}")

        try:
            campaigns = db.get_campaign_history()
            camp = next((c for c in campaigns if c["id"] == campaign_id), None)
        except Exception:
            camp = None

        log_text = ""
        if camp:
            log_text = camp.get("log_data") or "No log details available for this run."

        self.hist_log_box.configure(state="normal")
        self.hist_log_box.delete("1.0", "end")
        self.hist_log_box.insert("1.0", log_text)
        self.hist_log_box.see("end")
        self.hist_log_box.configure(state="disabled")

    # --- 4. REPORTS VIEW ---
    def setup_reports_view(self):
        self.current_view_frame.grid_columnconfigure(0, weight=1)
        self.current_view_frame.grid_rowconfigure(1, weight=1)

        lbl_title = ctk.CTkLabel(self.current_view_frame, text="Excel Lead Reports", font=self.font_title, text_color=TEXT_COLOR)
        lbl_title.grid(row=0, column=0, sticky="w", pady=(5, 15))

        self.scroll_reports = ctk.CTkScrollableFrame(self.current_view_frame, fg_color=SIDEBAR_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        self.scroll_reports.grid(row=1, column=0, sticky="nsew")
        self.scroll_reports.grid_columnconfigure(0, weight=1)

        self.refresh_reports_list()

    def refresh_reports_list(self):
        """Scans exports folder and renders lists of excel files."""
        # Clear list
        for w in self.scroll_reports.winfo_children():
            w.destroy()

        if getattr(sys, "frozen", False):
            exports_dir = os.path.join(os.path.dirname(sys.executable), "exports")
        else:
            exports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")

        if not os.path.exists(exports_dir):
            os.makedirs(exports_dir, exist_ok=True)

        files = []
        try:
            for f in os.listdir(exports_dir):
                if f.endswith(".xlsx"):
                    fpath = os.path.join(exports_dir, f)
                    ctime = os.path.getctime(fpath)
                    size = os.path.getsize(fpath)
                    files.append((f, fpath, ctime, size))
        except Exception:
            pass

        # Sort files newest first
        files.sort(key=lambda x: x[2], reverse=True)

        if not files:
            lbl_empty = ctk.CTkLabel(self.scroll_reports, text="No Excel reports found in the exports folder.", font=self.font_input, text_color=TEXT_MUTED)
            lbl_empty.pack(pady=40)
            return

        for idx, (filename, filepath, ctime, size_bytes) in enumerate(files):
            row_frame = ctk.CTkFrame(self.scroll_reports, fg_color=LIGHT_GREEN_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=8)
            row_frame.pack(fill="x", padx=10, pady=5)
            row_frame.grid_columnconfigure(1, weight=1)

            # Icon
            lbl_icon = ctk.CTkLabel(row_frame, text="📊", font=ctk.CTkFont(size=20))
            lbl_icon.grid(row=0, column=0, padx=(15, 10), pady=10)

            # Details
            file_date = datetime.datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")
            size_kb = max(1, size_bytes // 1024)
            lbl_details = ctk.CTkLabel(
                row_frame,
                text=f"{filename}\nCreated: {file_date}   |   Size: {size_kb} KB",
                justify="left",
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color=TEXT_COLOR
            )
            lbl_details.grid(row=0, column=1, sticky="w", pady=10)

            # Action Buttons Panel
            actions_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            actions_frame.grid(row=0, column=2, padx=15, pady=10)

            btn_open = ctk.CTkButton(
                actions_frame,
                text="Open File",
                font=self.font_btn,
                width=80,
                height=30,
                fg_color=ACCENT_GREEN,
                hover_color=ACCENT_HOVER,
                command=lambda p=filepath: self.open_excel_path(p)
            )
            btn_open.pack(side="left", padx=5)

            btn_del = ctk.CTkButton(
                actions_frame,
                text="Delete",
                font=self.font_btn,
                width=70,
                height=30,
                fg_color="#EF4444",
                hover_color="#DC2626",
                text_color="#FFFFFF",
                command=lambda p=filepath: self.delete_excel_report(p)
            )
            btn_del.pack(side="left", padx=5)

    def open_excel_path(self, filepath):
        try:
            if platform.system() == "Windows":
                os.startfile(filepath)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", filepath])
            else:
                subprocess.Popen(["xdg-open", filepath])
        except Exception as e:
            self.log(f"[!] Error opening report file: {e}")

    def delete_excel_report(self, filepath):
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
            self.refresh_reports_list()
        except Exception as e:
            self.log(f"[!] Error deleting report file: {e}")

    # --- 5. SETTINGS VIEW ---
    def setup_settings_view(self):
        self.current_view_frame.grid_columnconfigure(0, weight=1)
        self.current_view_frame.grid_rowconfigure(1, weight=1)

        lbl_title = ctk.CTkLabel(self.current_view_frame, text="Preferences & Settings", font=self.font_title, text_color=TEXT_COLOR)
        lbl_title.grid(row=0, column=0, sticky="w", pady=(5, 15))

        settings_scroll = ctk.CTkScrollableFrame(self.current_view_frame, fg_color=SIDEBAR_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        settings_scroll.grid(row=1, column=0, sticky="nsew")
        settings_scroll.grid_columnconfigure(0, weight=1)

        inputs_config = {"border_width": 1, "corner_radius": 8, "border_color": INPUT_BORDER, "fg_color": "#FFFFFF", "text_color": TEXT_COLOR, "font": self.font_input}

        # 1. Server API URL configuration
        lbl_api = ctk.CTkLabel(settings_scroll, text="Licensing Server API Endpoint URL", font=self.font_label, text_color=TEXT_COLOR)
        lbl_api.pack(anchor="w", padx=25, pady=(20, 2))
        
        self.setting_api_entry = ctk.CTkEntry(settings_scroll, height=38, **inputs_config)
        self.setting_api_entry.pack(fill="x", padx=25, pady=(0, 10))
        self.setting_api_entry.insert(0, get_api_url())

        # --- Scraper Filter Rules ---
        lbl_rule_header = ctk.CTkLabel(settings_scroll, text="Scraper Filters Configuration", font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"), text_color=ACCENT_GREEN)
        lbl_rule_header.pack(anchor="w", padx=25, pady=(15, 10))

        # Min Rating Slider
        rating_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
        rating_frame.pack(fill="x", padx=25, pady=5)
        
        self.lbl_rating = ctk.CTkLabel(rating_frame, text=f"Minimum Google Rating: {scraper.FILTERS.get('min_rating', 3.0)}★", font=self.font_label, text_color=TEXT_COLOR)
        self.lbl_rating.pack(side="left")

        self.setting_rating_slider = ctk.CTkSlider(
            rating_frame,
            from_=1.0, to=5.0,
            number_of_steps=40,
            progress_color=ACCENT_GREEN,
            command=self.update_rating_slider_label
        )
        self.setting_rating_slider.pack(side="right", fill="x", expand=True, padx=(20, 0))
        self.setting_rating_slider.set(float(scraper.FILTERS.get("min_rating", 3.0)))

        # Min Reviews Input
        reviews_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
        reviews_frame.pack(fill="x", padx=25, pady=10)
        
        lbl_reviews = ctk.CTkLabel(reviews_frame, text="Minimum Review Count Requirement", font=self.font_label, text_color=TEXT_COLOR)
        lbl_reviews.pack(side="left")
        
        self.setting_reviews_entry = ctk.CTkEntry(reviews_frame, width=80, height=32, **inputs_config)
        self.setting_reviews_entry.pack(side="right", padx=(10, 0))
        self.setting_reviews_entry.insert(0, str(scraper.FILTERS.get("min_reviews", 5)))

        # Require Phone Switch
        self.setting_phone_switch = ctk.CTkSwitch(settings_scroll, text="Require Phone Number (Discard leads with no phone)", font=self.font_label, progress_color=ACCENT_GREEN, text_color=TEXT_COLOR)
        self.setting_phone_switch.pack(anchor="w", padx=25, pady=8)
        if scraper.FILTERS.get("require_phone", True):
            self.setting_phone_switch.select()

        # Strict Phone Validation Switch
        self.setting_strict_phone = ctk.CTkSwitch(settings_scroll, text="Strict Phone Number Format Validation", font=self.font_label, progress_color=ACCENT_GREEN, text_color=TEXT_COLOR)
        self.setting_strict_phone.pack(anchor="w", padx=25, pady=8)
        if scraper.FILTERS.get("strict_phone_validation", True):
            self.setting_strict_phone.select()

        # Deep Research Mode Switch
        self.setting_deep_research = ctk.CTkSwitch(settings_scroll, text="Deep Research Mode (Attempts to find emails/contacts from websites)", font=self.font_label, progress_color=ACCENT_GREEN, text_color=TEXT_COLOR)
        self.setting_deep_research.pack(anchor="w", padx=25, pady=8)
        if scraper.FILTERS.get("deep_research_mode", True):
            self.setting_deep_research.select()

        # Save Button
        btn_save_config = ctk.CTkButton(
            settings_scroll,
            text="Save Settings",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=40,
            fg_color=ACCENT_GREEN,
            hover_color=ACCENT_HOVER,
            command=self.save_preferences_settings
        )
        btn_save_config.pack(fill="x", padx=25, pady=(25, 20))

    def update_rating_slider_label(self, val):
        self.lbl_rating.configure(text=f"Minimum Google Rating: {round(val, 1)}★")

    def save_preferences_settings(self):
        """Save settings and apply them to scraper backend config."""
        api_val = self.setting_api_entry.get().strip()
        min_rating = round(float(self.setting_rating_slider.get()), 1)
        
        try:
            min_reviews = int(self.setting_reviews_entry.get().strip())
        except ValueError:
            min_reviews = 5

        require_phone = bool(self.setting_phone_switch.get() == 1)
        strict_phone = bool(self.setting_strict_phone.get() == 1)
        deep_res = bool(self.setting_deep_research.get() == 1)

        # Apply to Scraper Backend at runtime
        scraper.FILTERS["min_rating"] = min_rating
        scraper.FILTERS["min_reviews"] = min_reviews
        scraper.FILTERS["require_phone"] = require_phone
        scraper.FILTERS["strict_phone_validation"] = strict_phone
        scraper.FILTERS["deep_research_mode"] = deep_res

        # Save config.json (licensing API URL override)
        if getattr(sys, "frozen", False):
            config_path = os.path.join(os.path.dirname(sys.executable), "config.json")
        else:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"licensing_api_url": api_val}, f, indent=4)
        except Exception:
            pass

        # Save other properties to settings.json
        self.save_settings()
        
        # Save scraper preferences in settings dictionary
        self.loaded_settings_dict["min_rating"] = min_rating
        self.loaded_settings_dict["min_reviews"] = min_reviews
        self.loaded_settings_dict["require_phone"] = require_phone
        self.loaded_settings_dict["strict_phone_validation"] = strict_phone
        self.loaded_settings_dict["deep_research_mode"] = deep_res
        
        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.loaded_settings_dict, f, indent=4)
        except Exception:
            pass

        # Toast-like log notification
        self.log("[+] Preferences saved and applied successfully!")

    # --- Campaign Runner & Real-time Logs Management ---

    def log(self, message):
        """Thread-safe logging to the status panel and history db."""
        self.current_log_lines.append(message)
        
        # Update text box on Lead Scraper screen
        if hasattr(self, "log_box") and self.log_box:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", message + "\n")
            
            # Keep only the last 300 lines in memory text box to avoid slow render
            tb_lines = self.log_box.get("1.0", "end").split("\n")
            if len(tb_lines) > 300:
                self.log_box.delete("1.0", f"{len(tb_lines) - 300}.0")

            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        # Periodically flush log_data to SQLite History database
        if self.current_campaign_id is not None:
            try:
                db.update_campaign_status(
                    self.current_campaign_id,
                    "Running",
                    self.session_leads_count,
                    "\n".join(self.current_log_lines)
                )
            except Exception:
                pass

            # If History View is open and this running campaign is selected, refresh real-time log box
            if hasattr(self, "selected_campaign_row_id") and self.selected_campaign_row_id == self.current_campaign_id:
                if hasattr(self, "hist_log_box") and self.hist_log_box:
                    self.hist_log_box.configure(state="normal")
                    self.hist_log_box.delete("1.0", "end")
                    self.hist_log_box.insert("1.0", "\n".join(self.current_log_lines))
                    self.hist_log_box.see("end")
                    self.hist_log_box.configure(state="disabled")

    def start_scraping(self):
        if self.is_scraping:
            self.log("[!] Scraping is already running.")
            return

        locations = [x.strip() for x in self.loc_entry.get().split(",") if x.strip()]
        keywords = [x.strip() for x in self.kw_entry.get().split(",") if x.strip()]
        description = self.desc_entry.get().strip()
        emails = self.email_entry.get().strip()

        try:
            target = int(self.leads_entry.get())
        except ValueError:
            self.log("[!] Please enter a valid number for Target Leads.")
            return

        if not locations or not keywords:
            self.log("[!] Please provide at least one Location and one Keyword.")
            return

        # Save settings when scraping starts
        self.save_settings()

        self.is_scraping = True
        self.session_leads_count = 0
        self.campaign_leads_history = [0]
        self.current_log_lines = []
        self.latest_excel_path = None
        
        # Insert campaign in history DB
        try:
            self.current_campaign_id = db.add_campaign(", ".join(locations), ", ".join(keywords), target)
        except Exception as e:
            print(f"Failed to create campaign run record: {e}")
            self.current_campaign_id = None

        self.start_btn.configure(state="disabled", text="SCRAPING...", fg_color="#A1A1AA")
        if hasattr(self, "progress_bar"):
            self.progress_bar.set(0)
        
        if hasattr(self, "lbl_last_val"):
            self.lbl_last_val.configure(text="0")
        if hasattr(self, "lbl_total_val"):
            try:
                tot = db.get_total_leads_count()
            except Exception:
                tot = 0
            self.lbl_total_val.configure(text=format_lead_count(tot))
        
        self.draw_sparkline()

        # Clear text box logs
        if hasattr(self, "log_box") and self.log_box:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.configure(state="disabled")

        # Run scraper in background thread
        threading.Thread(target=self.run_scraper, args=(locations, keywords, target, description, emails), daemon=True).start()

    def run_scraper(self, locations, keywords, target, description, emails):
        status = "Completed"
        try:
            self.log("="*50)
            self.log(f"[*] Starting VeloLeads Campaign")
            self.log(f"[*] Locations: {', '.join(locations)}")
            self.log(f"[*] Keywords: {', '.join(keywords)}")
            self.log(f"[*] Description filter: {description}")
            self.log(f"[*] Target per query: {target}")
            self.log("="*50)

            install_browsers(self.log)

            total_queries = len(locations) * len(keywords)
            current_query = 0
            all_leads = []

            for loc in locations:
                for kw in keywords:
                    current_query += 1
                    query_str = f"{kw} in {loc}"

                    self.log(f"\n[>>>] Query {current_query}/{total_queries}: {query_str}")
                    
                    if hasattr(self, "progress_bar"):
                        self.after(0, lambda progress=current_query / total_queries: self.progress_bar.set(progress))

                    leads = scrape_leads_for_query(query_str, loc, target, max_scrolls=5, ui_log_callback=self.log, prompt_description=description)
                    if leads:
                        all_leads.extend(leads)
                        self.session_leads_count = len(all_leads)
                        
                        # Add progress point for sparkline graph
                        self.campaign_leads_history.append(self.session_leads_count)
                        
                        try:
                            tot_leads = db.get_total_leads_count()
                        except Exception:
                            tot_leads = self.session_leads_count
                        self.after(0, lambda cnt=self.session_leads_count, tot=tot_leads: self.update_leads_labels(cnt, tot))
                        self.after(0, self.draw_sparkline)
                        
                        self.log(f"[+] Found {len(leads)} valid leads for this query.")
                    else:
                        self.log(f"[-] No leads found or error occurred for '{query_str}'.")

            self.log("\n" + "="*50)
            self.log(f"[*] Scraping Campaign Finished!")
            self.log(f"[*] Total unique leads gathered: {len(all_leads)}")

            if all_leads:
                excel_path = save_leads(all_leads)
                self.latest_excel_path = excel_path
                active_db = db.get_active_db_path()
                self.log(f"[+] Saved Database (SQLite): {os.path.basename(active_db)}")
                
                if excel_path:
                    self.log(f"[+] Saved Excel: {excel_path}")
                    if emails:
                        self.log("[*] Attempting to send report via email...")
                        mail_success = send_leads_email(emails, excel_path, log_callback=self.log)
                        if mail_success:
                            self.log("[+] Report emailed successfully!")
                        else:
                            self.log("[-] Email delivery failed.")
                else:
                    self.log("[-] Excel export failed.")
            else:
                self.log("[-] No leads gathered. Excel report was not generated.")

        except Exception as e:
            status = "Failed"
            err_msg = str(e)
            self.after(0, lambda msg=err_msg: self.log(f"[!] Scraping failed: {msg}"))
        finally:
            # Save final logs status to History DB
            if self.current_campaign_id is not None:
                try:
                    db.update_campaign_status(
                        self.current_campaign_id,
                        status,
                        self.session_leads_count,
                        "\n".join(self.current_log_lines)
                    )
                except Exception:
                    pass

            self.current_campaign_id = None
            self.after(0, self.reset_scraping_state)

    def reset_scraping_state(self):
        self.is_scraping = False
        if hasattr(self, "start_btn") and self.start_btn:
            self.start_btn.configure(state="normal", text="Start Scraping  →", fg_color=ACCENT_GREEN)
        if hasattr(self, "progress_bar") and self.progress_bar:
            self.progress_bar.set(1.0)
        
        # If campaign history is loaded, refresh list in background
        if hasattr(self, "scroll_campaigns"):
            self.refresh_campaign_list()

    # --- Settings Load & Save ---

    def load_settings(self):
        """Loads inputs and configurations from local JSON file."""
        self.loaded_settings_dict = {}
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    self.loaded_settings_dict = json.load(f)
            except Exception:
                pass
        
        # Load and apply runtime filters to scraper
        filters = self.loaded_settings_dict
        scraper.FILTERS["min_rating"] = filters.get("min_rating", 3.0)
        scraper.FILTERS["min_reviews"] = filters.get("min_reviews", 5)
        scraper.FILTERS["require_phone"] = filters.get("require_phone", True)
        scraper.FILTERS["strict_phone_validation"] = filters.get("strict_phone_validation", True)
        scraper.FILTERS["deep_research_mode"] = filters.get("deep_research_mode", True)

    def save_settings_with_notification(self):
        self.save_settings()
        self.log("[+] Configuration saved successfully!")

    def save_settings(self):
        """Builds settings dictionary from input fields and saves to file."""
        if not hasattr(self, "loc_entry"):
            return

        schedule_enabled = bool(self.schedule_switch.get() == 1)
        schedule_times = [entry.get().strip() for entry in self.schedule_time_entries if entry.get().strip()]

        # Maintain other keys while modifying form properties
        self.loaded_settings_dict.update({
            "locations": self.loc_entry.get().strip(),
            "keywords": self.kw_entry.get().strip(),
            "description": self.desc_entry.get().strip(),
            "emails": self.email_entry.get().strip(),
            "target": self.leads_entry.get().strip(),
            "schedule_enabled": schedule_enabled,
            "schedule_times": schedule_times,
            "schedule_time": schedule_times[0] if schedule_times else ""
        })

        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.loaded_settings_dict, f, indent=4)
        except Exception as e:
            self.log(f"[!] Warning: Could not save settings: {e}")

    def scheduler_loop(self):
        """Background daily time check to execute auto-scheduled scrapes."""
        import datetime as dt
        while True:
            time.sleep(30)
            
            # Read schedule settings
            enabled = self.loaded_settings_dict.get("schedule_enabled", False)
            schedule_times = self.loaded_settings_dict.get("schedule_times") or []
            
            if enabled and schedule_times:
                now = dt.datetime.now()
                current_time = now.strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")

                if current_time in schedule_times:
                    last_run_date = self.last_run_dates.get(current_time)
                    if last_run_date != current_date:
                        self.last_run_dates[current_time] = current_date
                        self.after(0, lambda: self.log(f"[*] Daily schedule triggered for time {current_time}!"))
                        self.after(1000, self.start_scraping)

    def on_closing(self):
        if hasattr(self, "loc_entry"):
            self.save_settings()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()

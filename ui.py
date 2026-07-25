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

# Force Playwright to use the global browser directory, ignoring PyInstaller's _MEI override
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")

# Import our backend logic
try:
    from scraper import scrape_leads_for_query
    from exporter import save_leads
    from email_sender import send_leads_email
    import db
except ImportError as e:
    print(f"Error importing modules: {e}")

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
    """Reads licensing API URL from config.json, with localhost fallback."""
    try:
        if getattr(sys, "frozen", False):
            config_path = os.path.join(os.path.dirname(sys.executable), "config.json")
        else:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
            
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return cfg.get("licensing_api_url", "http://localhost:5000")
    except Exception:
        pass
    return "http://localhost:5000"


def install_browsers(log_callback):
    """Automatically installs Playwright Chromium if missing, supporting PyInstaller bundles."""
    import subprocess
    log_callback("[*] Checking/Installing background browser (this may take a minute on first run)...")
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver_path = compute_driver_executable()
        
        # Handle tuple return type in newer Playwright versions (node_exe, cli_js)
        if isinstance(driver_path, tuple):
            cmd = [*driver_path, 'install', 'chromium']
        else:
            cmd = [driver_path, 'install', 'chromium']
            
        subprocess.run(cmd, env=get_driver_env(), check=True, capture_output=True)
        log_callback("[+] Browser check complete.")
    except Exception as e:
        log_callback(f"[!] Warning: Could not auto-install browser. {e}")

# Set extreme modern dark theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("VeloLeads - Automated AI Lead Generator")
        self.geometry("1000x750")
        self.configure(fg_color="#121212") # Deep dark background for main window
        
        # Define Premium Fonts
        self.font_title = ctk.CTkFont(family="Segoe UI", size=28, weight="bold")
        self.font_label = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        self.font_input = ctk.CTkFont(family="Segoe UI", size=13)
        self.font_btn = ctk.CTkFont(family="Segoe UI", size=14, weight="bold")
        self.font_log = ctk.CTkFont(family="Consolas", size=13)

        # Determine paths for settings and license files
        if getattr(sys, "frozen", False):
            self.settings_path = os.path.join(os.path.dirname(sys.executable), "settings.json")
            self.license_path = os.path.join(os.path.dirname(sys.executable), "license_info.json")
        else:
            self.settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
            self.license_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "license_info.json")

        self.license_username = ""
        self.license_email = ""
        self.license_expires_at = ""

        # Loading screen
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.loading_frame = ctk.CTkFrame(self, fg_color="#121212")
        self.loading_frame.grid(row=0, column=0, sticky="nsew")
        self.loading_frame.grid_columnconfigure(0, weight=1)
        self.loading_frame.grid_rowconfigure(0, weight=1)

        self.loading_lbl = ctk.CTkLabel(self.loading_frame, text="Checking subscription validity...", font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"), text_color="#A1A1AA")
        self.loading_lbl.grid(row=0, column=0)

        # Setup close protocol
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Run background license check thread
        threading.Thread(target=self.background_license_check, daemon=True).start()

    def background_license_check(self):
        if not os.path.exists(self.license_path):
            self.after(0, self.go_to_login)
            return

        try:
            with open(self.license_path, "r", encoding="utf-8") as f:
                lic = json.load(f)
            
            username = lic.get("username")
            license_key = lic.get("license_key")
            expires_at_str = lic.get("expires_at")
            
            if not username or not license_key:
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

            try:
                res = requests.post(f"{api_url}/api/license/verify", json=payload, timeout=6)
                data = res.json()

                if res.status_code == 200 and data.get("success"):
                    # Update local copy in case of renewal
                    lic["expires_at"] = data.get("expires_at", expires_at_str)
                    self.license_expires_at = lic["expires_at"]
                    with open(self.license_path, "w", encoding="utf-8") as f:
                        json.dump(lic, f, indent=4)
                    
                    self.after(0, self.go_to_main)
                else:
                    self.after(0, self.go_to_login)
            except Exception:
                # Connection failed, fallback to local date validation (grace period offline support)
                from datetime import datetime
                try:
                    exp_date_str = expires_at_str.split("T")[0]
                    expiry = datetime.strptime(exp_date_str, "%Y-%m-%d")
                    if expiry > datetime.now():
                        self.after(0, self.go_to_main)
                    else:
                        self.after(0, self.go_to_login)
                except Exception:
                    self.after(0, self.go_to_login)
        except Exception:
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

        INPUT_FG = "#1E1E24"
        INPUT_BORDER = "#2B2B36"
        ACCENT_COLOR = "#0066CC"
        ACCENT_HOVER = "#0052A3"
        SIDEBAR_BG = "#18181B"

        self.login_frame = ctk.CTkFrame(self, fg_color=SIDEBAR_BG, corner_radius=12, border_width=1, border_color=INPUT_BORDER, width=480, height=480)
        self.login_frame.grid(row=0, column=0, sticky="")
        self.login_frame.grid_propagate(False)
        self.login_frame.grid_columnconfigure(0, weight=1)

        self.login_logo = ctk.CTkLabel(self.login_frame, text="VeloLeads", font=ctk.CTkFont(family="Segoe UI", size=32, weight="bold"), text_color="#FFFFFF")
        self.login_logo.grid(row=0, column=0, padx=25, pady=(35, 5))

        self.login_sub = ctk.CTkLabel(self.login_frame, text="Premium License Activation Required", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color="#A1A1AA")
        self.login_sub.grid(row=1, column=0, padx=25, pady=(0, 25))

        inputs_config = {"border_width": 1, "corner_radius": 8, "border_color": INPUT_BORDER, "fg_color": INPUT_FG, "font": self.font_input}

        self.login_user_label = ctk.CTkLabel(self.login_frame, text="Username or Email", font=self.font_label, text_color="#A1A1AA")
        self.login_user_label.grid(row=2, column=0, padx=35, pady=(5, 2), sticky="w")
        self.login_user_entry = ctk.CTkEntry(self.login_frame, height=42, placeholder_text="Enter your registered username/email", **inputs_config)
        self.login_user_entry.grid(row=3, column=0, padx=35, pady=(0, 12), sticky="ew")

        self.login_key_label = ctk.CTkLabel(self.login_frame, text="License Key", font=self.font_label, text_color="#A1A1AA")
        self.login_key_label.grid(row=4, column=0, padx=35, pady=(5, 2), sticky="w")
        self.login_key_entry = ctk.CTkEntry(self.login_frame, height=42, placeholder_text="VELO-XXXX-XXXX-XXXX", **inputs_config)
        self.login_key_entry.grid(row=5, column=0, padx=35, pady=(0, 10), sticky="ew")

        self.login_error_label = ctk.CTkLabel(self.login_frame, text="", font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#EF4444", wraplength=400)
        self.login_error_label.grid(row=6, column=0, padx=35, pady=(0, 15), sticky="w")

        # Action button container
        self.login_btn_frame = ctk.CTkFrame(self.login_frame, fg_color="transparent")
        self.login_btn_frame.grid(row=7, column=0, padx=35, pady=(0, 30), sticky="ew")
        self.login_btn_frame.grid_columnconfigure((0, 1), weight=1)

        self.login_submit_btn = ctk.CTkButton(self.login_btn_frame, text="ACTIVATE", command=self.attempt_activation,
                                             height=40, corner_radius=8, font=self.font_btn,
                                             fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER)
        self.login_submit_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.login_buy_btn = ctk.CTkButton(self.login_btn_frame, text="BUY LICENSE", command=lambda: webbrowser.open(get_api_url()),
                                          height=40, corner_radius=8, font=self.font_btn,
                                          fg_color="#27272A", hover_color="#3F3F46", border_width=1, border_color="#3F3F46")
        self.login_buy_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")

    def attempt_activation(self):
        username = self.login_user_entry.get().strip()
        license_key = self.login_key_entry.get().strip()

        if not username or not license_key:
            self.login_error_label.configure(text="Please fill in both username and license key.")
            return

        self.login_submit_btn.configure(state="disabled", text="ACTIVATING...")
        self.login_buy_btn.configure(state="disabled")
        self.login_error_label.configure(text="")

        threading.Thread(target=self.run_activation, args=(username, license_key), daemon=True).start()

    def run_activation(self, username, license_key):
        api_url = get_api_url()
        machine_id = get_machine_id()
        
        payload = {
            "username": username,
            "license_key": license_key,
            "machine_id": machine_id
        }

        try:
            res = requests.post(f"{api_url}/api/license/activate", json=payload, timeout=8)
            data = res.json()

            if res.status_code == 200 and data.get("success"):
                license_data = {
                    "username": data.get("username", username),
                    "email": data.get("email", username), 
                    "license_key": license_key,
                    "expires_at": data.get("expires_at")
                }
                
                with open(self.license_path, "w", encoding="utf-8") as f:
                    json.dump(license_data, f, indent=4)

                self.license_username = license_data["username"]
                self.license_email = license_data["email"]
                self.license_expires_at = license_data["expires_at"]

                self.after(0, self.activation_success)
            else:
                msg = data.get("message", "License activation failed.")
                self.after(0, lambda: self.activation_failed(msg))
        except Exception as e:
            self.after(0, lambda: self.activation_failed(f"Could not connect to verification server: {str(e)}"))

    def activation_success(self):
        if hasattr(self, "login_frame"):
            self.login_frame.destroy()
        self.setup_main_ui()

    def activation_failed(self, message):
        self.login_submit_btn.configure(state="normal", text="ACTIVATE")
        self.login_buy_btn.configure(state="normal")
        self.login_error_label.configure(text=message)

    def renew_plan(self):
        """Opens renewal page in browser with prefilled username/email parameters."""
        api_url = get_api_url()
        webbrowser.open(f"{api_url}?renew={self.license_username}&email={self.license_email}")

    def setup_main_ui(self):
        # Configure layout for main app screen (50/50 weights)
        self.grid_columnconfigure(0, weight=1, uniform="half")
        self.grid_columnconfigure(1, weight=1, uniform="half")
        self.grid_rowconfigure(0, weight=1)

        # Styling Constants
        INPUT_FG = "#1E1E24"
        INPUT_BORDER = "#2B2B36"
        ACCENT_COLOR = "#0066CC"
        ACCENT_HOVER = "#0052A3"
        SIDEBAR_BG = "#18181B"
        
        # --- SIDEBAR (Settings & Inputs) ---
        self.sidebar_frame = ctk.CTkFrame(self, width=420, corner_radius=0, fg_color=SIDEBAR_BG)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_columnconfigure(0, weight=1)
        
        # Header inside sidebar
        self.sidebar_header = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.sidebar_header.grid(row=0, column=0, padx=25, pady=(30, 20), sticky="ew")
        self.sidebar_header.grid_columnconfigure(0, weight=0)
        self.sidebar_header.grid_columnconfigure(1, weight=1)
        self.sidebar_header.grid_columnconfigure(2, weight=0)
        
        self.logo_label = ctk.CTkLabel(self.sidebar_header, text="VeloLeads", font=self.font_title, text_color="#FFFFFF")
        self.logo_label.grid(row=0, column=0, sticky="w")

        # --- HEADER PROFILE (Sleek User Badge in Top Middle) ---
        self.header_profile = ctk.CTkFrame(self.sidebar_header, fg_color="#1E1E24", corner_radius=8, border_width=1, border_color=INPUT_BORDER)
        self.header_profile.grid(row=0, column=1, padx=(15, 10), sticky="ew")

        self.info_container = ctk.CTkFrame(self.header_profile, fg_color="transparent")
        self.info_container.pack(side="left", padx=8, pady=4)

        self.status_lbl = ctk.CTkLabel(self.info_container, text="● PREMIUM ACTIVE", font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color="#10B981")
        self.status_lbl.pack(anchor="w")

        exp_dt = "Expired"
        try:
            exp_dt = self.license_expires_at.split("T")[0]
        except Exception:
            exp_dt = self.license_expires_at

        user_details = f"{self.license_username} ({exp_dt})"
        self.details_lbl = ctk.CTkLabel(self.info_container, text=user_details, font=ctk.CTkFont(family="Segoe UI", size=10), text_color="#FFFFFF")
        self.details_lbl.pack(anchor="w")

        self.renew_badge_btn = ctk.CTkButton(self.header_profile, text="RENEW", command=self.renew_plan,
                                            width=50, height=22, corner_radius=4, font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                                            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER)
        self.renew_badge_btn.pack(side="right", padx=8, pady=4)
        
        self.start_btn = ctk.CTkButton(self.sidebar_header, text="START SCRAPING", command=self.start_scraping, 
                                       width=120, height=35, corner_radius=8, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), 
                                       fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER)
        self.start_btn.grid(row=0, column=2, sticky="e")
        
        # Inputs Dictionary for cleaner styling application
        inputs_config = {"border_width": 1, "corner_radius": 8, "border_color": INPUT_BORDER, "fg_color": INPUT_FG, "font": self.font_input}
        
        # Locations Input
        self.loc_label = ctk.CTkLabel(self.sidebar_frame, text="Locations (comma separated)", font=self.font_label, text_color="#A1A1AA")
        self.loc_label.grid(row=1, column=0, padx=25, pady=(10, 5), sticky="w")
        self.loc_entry = ctk.CTkEntry(self.sidebar_frame, height=45, placeholder_text="e.g. New York, Chicago, Mumbai", **inputs_config)
        self.loc_entry.grid(row=2, column=0, padx=25, pady=(0, 10), sticky="ew")
        
        # Keywords Input
        self.kw_label = ctk.CTkLabel(self.sidebar_frame, text="Niche / Keywords (comma separated)", font=self.font_label, text_color="#A1A1AA")
        self.kw_label.grid(row=3, column=0, padx=25, pady=(10, 5), sticky="w")
        self.kw_entry = ctk.CTkEntry(self.sidebar_frame, height=45, placeholder_text="e.g. Plumbers, Dentists, Construction", **inputs_config)
        self.kw_entry.grid(row=4, column=0, padx=25, pady=(0, 10), sticky="ew")
        
        # Description Input
        self.desc_label = ctk.CTkLabel(self.sidebar_frame, text="Extra Info / Prompt Description", font=self.font_label, text_color="#A1A1AA")
        self.desc_label.grid(row=5, column=0, padx=25, pady=(10, 5), sticky="w")
        self.desc_entry = ctk.CTkEntry(self.sidebar_frame, height=45, placeholder_text="e.g. For crane rental, top rated only", **inputs_config)
        self.desc_entry.grid(row=6, column=0, padx=25, pady=(0, 10), sticky="ew")
        
        # Target Emails Input
        self.email_label = ctk.CTkLabel(self.sidebar_frame, text="Target Emails (comma separated)", font=self.font_label, text_color="#A1A1AA")
        self.email_label.grid(row=7, column=0, padx=25, pady=(10, 5), sticky="w")
        self.email_entry = ctk.CTkEntry(self.sidebar_frame, height=45, placeholder_text="e.g. test@gmail.com, admin@corp.com", **inputs_config)
        self.email_entry.grid(row=8, column=0, padx=25, pady=(0, 10), sticky="ew")
        
        # Max Leads per Query
        self.leads_label = ctk.CTkLabel(self.sidebar_frame, text="Target Leads per Query", font=self.font_label, text_color="#A1A1AA")
        self.leads_label.grid(row=9, column=0, padx=25, pady=(10, 5), sticky="w")
        self.leads_entry = ctk.CTkEntry(self.sidebar_frame, height=45, placeholder_text="e.g. 50", **inputs_config)
        self.leads_entry.grid(row=10, column=0, padx=25, pady=(0, 15), sticky="ew")
        
        # Scheduler Settings
        self.schedule_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.schedule_frame.grid(row=11, column=0, padx=25, pady=(5, 5), sticky="ew")
        
        self.schedule_switch = ctk.CTkSwitch(self.schedule_frame, text="Auto-Schedule Daily", font=self.font_label, progress_color=ACCENT_COLOR)
        self.schedule_switch.pack(side="left")

        self.schedule_times_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.schedule_times_frame.grid(row=12, column=0, padx=25, pady=(0, 10), sticky="ew")
        self.schedule_times_frame.grid_columnconfigure((0,1,2,3), weight=1)

        self.schedule_label = ctk.CTkLabel(self.schedule_times_frame, text="Run at up to 4 times per day", font=self.font_label, text_color="#A1A1AA")
        self.schedule_label.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))

        self.schedule_time_entries = []
        for index in range(4):
            entry = ctk.CTkEntry(self.schedule_times_frame, width=80, placeholder_text="14:30", **inputs_config)
            entry.grid(row=1, column=index, padx=(0, 10), sticky="w")
            self.schedule_time_entries.append(entry)
        
        # Action Buttons
        self.save_btn = ctk.CTkButton(self.sidebar_frame, text="SAVE CONFIGURATION", command=self.save_settings_with_notification, 
                                      height=40, corner_radius=8, font=self.font_btn,
                                      fg_color="#27272A", hover_color="#3F3F46", border_width=1, border_color="#3F3F46")
        self.save_btn.grid(row=13, column=0, padx=25, pady=(15, 5), sticky="ew")
        
        # Spacer to push everything up
        self.sidebar_frame.grid_rowconfigure(14, weight=1)

        # --- MAIN AREA (Logs & Progress) ---
        self.main_frame = ctk.CTkFrame(self, fg_color="#121212", corner_radius=0)
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)
        
        # Terminal-style Log Box Frame
        self.terminal_frame = ctk.CTkFrame(self.main_frame, fg_color="#09090B", border_width=1, border_color="#27272A", corner_radius=12)
        self.terminal_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", pady=(0, 20))
        self.terminal_frame.grid_columnconfigure(0, weight=1)
        self.terminal_frame.grid_rowconfigure(1, weight=1)
        
        # Terminal Header
        self.terminal_header = ctk.CTkFrame(self.terminal_frame, fg_color="#18181B", corner_radius=12)
        self.terminal_header.grid(row=0, column=0, sticky="ew")
        
        # Mac-style dots for aesthetic
        self.dots_frame = ctk.CTkFrame(self.terminal_header, fg_color="transparent")
        self.dots_frame.pack(side="left", padx=15, pady=10)
        for color in ["#FF5F56", "#FFBD2E", "#27C93F"]:
            ctk.CTkFrame(self.dots_frame, width=12, height=12, corner_radius=6, fg_color=color).pack(side="left", padx=4)
            
        self.log_title = ctk.CTkLabel(self.terminal_header, text="veloleads-engine ~ runtime", font=self.font_label, text_color="#71717A")
        self.log_title.pack(side="left", padx=10)
        
        # The actual Log Textbox (Sleek Hacker Terminal look)
        self.log_box = ctk.CTkTextbox(self.terminal_frame, state="disabled", font=self.font_log, 
                                      fg_color="transparent", text_color="#10B981", wrap="word", corner_radius=0)
        self.log_box.grid(row=1, column=0, padx=15, pady=15, sticky="nsew")
        
        # Progress Bar Modernization
        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.progress_frame.grid(row=2, column=0, sticky="ew")
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=10, corner_radius=5, progress_color=ACCENT_COLOR)
        self.progress_bar.pack(fill="x", pady=5)
        self.progress_bar.set(0)

        self.is_scraping = False
        
        # Load saved settings
        self.load_settings()
        
        # Start Scheduler Thread
        self.last_run_dates = {}
        self.scheduler_thread = threading.Thread(target=self.scheduler_loop, daemon=True)
        self.scheduler_thread.start()


    def log(self, message):
        """Thread-safe logging to the terminal text box"""
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def get_schedule_times(self):
        times = []
        for entry in self.schedule_time_entries:
            value = entry.get().strip()
            if value:
                times.append(value)
        return times

    def scheduler_loop(self):
        import datetime
        while True:
            time.sleep(30)
            if self.schedule_switch.get() == 1:
                target_times = self.get_schedule_times()
                if not target_times:
                    continue

                now = datetime.datetime.now()
                current_time = now.strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")

                if current_time in target_times:
                    last_run_date = self.last_run_dates.get(current_time)
                    if last_run_date != current_date:
                        self.last_run_dates[current_time] = current_date
                        self.after(0, lambda: self.log(f"[*] Auto-Schedule triggered at {current_time}!"))
                        self.after(1000, self.start_scraping)

    def load_settings(self):
        """Load settings from local JSON file."""
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if "locations" in data:
                    self.loc_entry.insert(0, data["locations"])
                if "keywords" in data:
                    self.kw_entry.insert(0, data["keywords"])
                if "description" in data:
                    self.desc_entry.insert(0, data["description"])
                if "emails" in data:
                    self.email_entry.insert(0, data["emails"])
                if "target" in data:
                    self.leads_entry.insert(0, str(data["target"]))
                if "schedule_enabled" in data and data["schedule_enabled"]:
                    self.schedule_switch.select()

                schedule_times = data.get("schedule_times") or []
                if not schedule_times and "schedule_time" in data:
                    schedule_times = [data["schedule_time"]]

                for entry, value in zip(self.schedule_time_entries, schedule_times[:4]):
                    entry.insert(0, str(value))

                if len(schedule_times) < 4:
                    for entry in self.schedule_time_entries[len(schedule_times):]:
                        entry.delete(0, "end")
            except Exception as e:
                self.log(f"[!] Warning: Could not load saved settings: {e}")
        else:
            # Defaults
            self.loc_entry.insert(0, "")
            self.kw_entry.insert(0, "")
            self.desc_entry.insert(0, "")
            self.email_entry.insert(0, "")
            self.leads_entry.delete(0, "end")
            for entry in self.schedule_time_entries:
                entry.delete(0, "end")
            self.schedule_time_entries[0].insert(0, "14:30")

    def save_settings_with_notification(self):
        """Save settings and show log notification"""
        self.save_settings()
        self.log("[+] Settings saved successfully!")

    def save_settings(self):
        """Save settings to local JSON file."""
        schedule_times = [entry.get().strip() for entry in self.schedule_time_entries if entry.get().strip()]
        data = {
            "locations": self.loc_entry.get().strip(),
            "keywords": self.kw_entry.get().strip(),
            "description": self.desc_entry.get().strip(),
            "emails": self.email_entry.get().strip(),
            "target": self.leads_entry.get().strip(),
            "schedule_enabled": bool(self.schedule_switch.get() == 1),
            "schedule_times": schedule_times,
            "schedule_time": schedule_times[0] if schedule_times else ""
        }
        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            self.log(f"[!] Warning: Could not save settings: {e}")

    def on_closing(self):
        if hasattr(self, "loc_entry"):
            self.save_settings()
        self.destroy()

    def start_scraping(self):
        if self.is_scraping:
            self.log("[!] Scraping is already running.")
            return
            
        # Save settings when scraping starts
        self.save_settings()
            
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

        self.is_scraping = True
        self.start_btn.configure(state="disabled", text="SCRAPING...", fg_color="#3F3F46")
        self.progress_bar.set(0)
        
        # Run in background thread to prevent UI freezing
        threading.Thread(target=self.run_scraper, args=(locations, keywords, target, description, emails), daemon=True).start()

    def reset_scraping_state(self):
        self.is_scraping = False
        self.start_btn.configure(state="normal", text="START SCRAPING", fg_color="#0066CC")
        self.progress_bar.set(1.0)

    def run_scraper(self, locations, keywords, target, description, emails):
        try:
            self.log("="*50)
            self.log(f"[*] Starting VeloLeads Campaign")
            self.log(f"[*] Locations: {', '.join(locations)}")
            self.log(f"[*] Keywords: {', '.join(keywords)}")
            self.log(f"[*] Description filter: {description}")
            self.log(f"[*] Target per query: {target}")
            self.log("="*50)
            
            # Ensure Playwright browser is installed for new users
            install_browsers(self.log)
            
            total_queries = len(locations) * len(keywords)
            current_query = 0
            all_leads = []
            
            for loc in locations:
                for kw in keywords:
                    current_query += 1
                    
                    query_str = f"{kw} in {loc}"

                    self.log(f"\n[>>>] Query {current_query}/{total_queries}: {query_str}")
                    
                    # Update progress bar
                    self.progress_bar.set(current_query / total_queries)
                    
                    leads = scrape_leads_for_query(query_str, loc, target, max_scrolls=5, ui_log_callback=self.log, prompt_description=description)
                    if leads:
                        all_leads.extend(leads)
                        self.log(f"[+] Found {len(leads)} valid leads for this query.")
                    else:
                        self.log(f"[-] No leads found or error occurred for '{query_str}'.")
                        
            self.log("\n" + "="*50)
            self.log(f"[*] Scraping Campaign Finished!")
            self.log(f"[*] Total unique leads gathered: {len(all_leads)}")
            
            if all_leads:
                excel_path = save_leads(all_leads)
                active_db = db.get_active_db_path() if hasattr(sys.modules.get("db"), "get_active_db_path") else "sqlite database"
                self.log(f"[+] Saved Database (SQLite): {os.path.basename(active_db)}")
                if excel_path:
                    self.log(f"[+] Saved Excel: {excel_path}")

                    if emails:
                        self.log("[*] Attempting to send report via email...")
                        success = send_leads_email(emails, excel_path, log_callback=self.log)
                        if success:
                            self.log("[+] Report emailed successfully!")
                        else:
                            self.log("[-] Email delivery failed.")
                else:
                    self.log("[-] Excel export failed. No email will be sent.")
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda msg=err_msg: self.log(f"[!] Unhandled error during scraping: {msg}"))
        finally:
            self.after(0, self.reset_scraping_state)

if __name__ == "__main__":
    app = App()
    app.mainloop()

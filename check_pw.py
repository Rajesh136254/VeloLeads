import os, sys, subprocess

def install_browsers(log_callback):
    log_callback("[*] Checking/Installing background browser (this may take a minute on first run)...")
    try:
        # If running as PyInstaller exe, sys.executable is the exe itself.
        # It's better to use the playwright command directly if possible.
        subprocess.run(["playwright", "install", "chromium"], check=True, capture_output=True, text=True)
        log_callback("[+] Browser check complete.")
    except Exception as e:
        log_callback(f"[!] Warning: Could not auto-install browser via 'playwright' command.")
        # Fallback for PyInstaller bundled environment
        try:
            from playwright._impl._driver import compute_driver_executable, get_driver_env
            driver = compute_driver_executable()
            subprocess.run([driver, 'install', 'chromium'], env=get_driver_env(), check=True, capture_output=True)
            log_callback("[+] Browser check complete (bundled driver).")
        except Exception as e2:
            log_callback(f"[!] Error: {e2}")


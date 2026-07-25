import json
import os
import sys
import tempfile
import pandas as pd
from datetime import datetime

def save_leads(leads, export_dir="exports"):
    """
    Saves a list of lead dictionaries to an Excel file.
    Creates an exports folder inside the app directory if it doesn't exist.
    """
    if not leads:
        return None

    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isabs(export_dir):
        export_dir = os.path.join(app_dir, export_dir)

    try:
        os.makedirs(export_dir, exist_ok=True)
    except PermissionError:
        fallback_dir = os.path.join(tempfile.gettempdir(), "VeloLeads_exports")
        try:
            os.makedirs(fallback_dir, exist_ok=True)
            export_dir = fallback_dir
        except Exception as e:
            print(f"[!] Cannot create export directory: {e}")
            return None
    except Exception as e:
        print(f"[!] Cannot create export directory: {e}")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_path = os.path.join(export_dir, f"leads_{timestamp}.xlsx")

    try:
        df = pd.DataFrame(leads)
        df.to_excel(excel_path, index=False)
    except PermissionError as e:
        fallback_dir = os.path.join(tempfile.gettempdir(), "VeloLeads_exports")
        try:
            os.makedirs(fallback_dir, exist_ok=True)
            excel_path = os.path.join(fallback_dir, f"leads_{timestamp}.xlsx")
            df.to_excel(excel_path, index=False)
        except Exception as fallback_e:
            print(f"[!] Error saving Excel to fallback directory: {fallback_e}")
            excel_path = None
    except Exception as e:
        print(f"[!] Error saving Excel: {e}")
        excel_path = None

    return excel_path

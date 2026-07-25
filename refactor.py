import os, re

path = r"C:\Users\rajes\Desktop\VeloLeads\scraper.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Remove import db and config loading
content = content.replace("import db", "")
content = re.sub(r'(# Load config.*?config = json\.load\(f\))', r'# Config removed for UI mode', content, flags=re.DOTALL)

# Fix TIMEOUT and FILTERS
content = content.replace('TIMEOUT = config["search"].get("request_timeout_seconds", 10)', 'TIMEOUT = 10')
content = content.replace('config.get("quality_filters", ', '')
content = content.replace("})\n\n", "}\n\n")

# Replace print with log function
log_helper = '''
def log_msg(msg, ui_log_callback=None):
    print(msg)
    if ui_log_callback:
        ui_log_callback(msg)
'''
content = content.replace("def normalize_phone(phone_str):", log_helper + "\ndef normalize_phone(phone_str):")

# Update signature
content = content.replace("def scrape_leads_for_query(query, city, target_new_leads):", "def scrape_leads_for_query(query, city, target_new_leads, max_scrolls=5, ui_log_callback=None):")

# Replace print with log_msg in scrape_leads_for_query
content = re.sub(r'print\((.*?)\)', r'log_msg(\1, ui_log_callback)', content)

# Remove db.lead_exists checks
# 1. Quick DB check before clicking
db_check_pattern = r'# Optimization: Quick DB check before clicking.*?(?=print\([^\n]+Processing New Lead)'
content = re.sub(db_check_pattern, '', content, flags=re.DOTALL)

# 2. Final deduplication check before database entry
final_db_check = r'# Final deduplication check before database entry\n\s+if not db.lead_exists.*?else:\n[^\n]+\n'
replacement = '''# In-memory save to list
            lead_item["id"] = len(new_leads_scraped) + 1
            new_leads_scraped.append(lead_item)
            log_msg(f"   [+] Scraped Lead: {name}", ui_log_callback)
'''
content = re.sub(final_db_check, replacement, content, flags=re.DOTALL)

# Fix scroll_count and nav_attempts
content = content.replace('scroll_count = config["search"].get("max_scrolls", 5)', 'scroll_count = max_scrolls')
content = content.replace('nav_attempts = config.get("search", {}).get("nav_retries", 3)', 'nav_attempts = 3')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Scraper refactored!")

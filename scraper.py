import re
import sys
import time
import urllib.parse
import requests
import random
import phonenumbers
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

import json
import os
import db

# Config removed for UI mode


def _ensure_internet_available(retries=3, base_delay=3):
    """Quickly checks outbound connectivity (retries)."""
    test_url = "https://www.google.com"
    for i in range(retries):
        try:
            requests.get(test_url, timeout=5)
            return True
        except Exception:
            time.sleep(base_delay * (i + 1))
    return False

TIMEOUT = 10
FILTERS = {
    "min_rating": 3.0,
    "min_reviews": 5,
    "require_phone": True,
    "strict_phone_validation": True,
    "deep_research_mode": True
}


def log_msg(msg, ui_log_callback=None):
    print(msg)
    if ui_log_callback:
        ui_log_callback(msg)

LOCATION_REGION_OVERRIDES = {
    "new york": "US",
    "los angeles": "US",
    "chicago": "US",
    "houston": "US",
    "san francisco": "US",
    "miami": "US",
    "boston": "US",
    "london": "GB",
    "manchester": "GB",
    "dubai": "AE",
    "abudhabi": "AE",
    "singapore": "SG",
    "hyderabad": "IN",
    "bangalore": "IN",
    "mumbai": "IN",
    "delhi": "IN",
    "chennai": "IN",
    "kolkata": "IN",
    "india": "IN",
    "united states": "US",
    "usa": "US",
    "uk": "GB",
    "united kingdom": "GB",
    "uae": "AE",
}


def get_region_for_location(location):
    if not location:
        return None

    normalized = location.strip().lower()
    for key, region in LOCATION_REGION_OVERRIDES.items():
        if key in normalized:
            return region

    # Dynamic lookup via Nominatim
    try:
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote_plus(location)}&format=json&addressdetails=1&limit=1"
        headers = {"User-Agent": "VeloLeads/1.0 (LeadGen Tool)"}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                country_code = data[0].get("address", {}).get("country_code")
                if country_code:
                    region = country_code.upper()
                    # Cache it to overrides to avoid repeated API calls
                    LOCATION_REGION_OVERRIDES[normalized] = region
                    return region
    except Exception:
        pass

    return None


def normalize_phone(phone_str):
    """Cleans a raw phone string to digits and plus sign only."""
    if not phone_str:
        return ""

    cleaned = phone_str.replace("Phone:", "").replace("phone:", "").strip()
    cleaned = re.sub(r"(?i)ext\b.*|x\b.*|extension\b.*", "", cleaned)
    return re.sub(r"[^\d+]+", "", cleaned)


def format_phone(phone_str, region=None):
    """Format phone number to E164 if possible based on an inferred region."""
    cleaned = normalize_phone(phone_str)
    if not cleaned:
        return ""

    try:
        if cleaned.startswith("+"):
            number_obj = phonenumbers.parse(cleaned, None)
        elif region:
            number_obj = phonenumbers.parse(cleaned, region)
        else:
            return cleaned

        if phonenumbers.is_valid_number(number_obj):
            return phonenumbers.format_number(number_obj, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return cleaned

    return cleaned


def is_valid_phone(phone_str, region=None):
    """Validate a phone number for a given region if possible."""
    if not phone_str:
        return False

    formatted = format_phone(phone_str, region=region)
    if not formatted:
        return False

    try:
        if formatted.startswith("+"):
            number_obj = phonenumbers.parse(formatted, None)
        elif region:
            number_obj = phonenumbers.parse(formatted, region)
        else:
            # We don't have a region and no country code. 
            # Can't use strict phonenumbers validation. Fallback to length check.
            digits = re.sub(r"\D", "", formatted)
            return 7 <= len(digits) <= 15
    except Exception:
        return False

    if not phonenumbers.is_valid_number(number_obj):
        return False

    number_type = phonenumbers.number_type(number_obj)
    # Reject fixed line (landline) numbers. Allow only Mobile or Fixed/Mobile combinations
    return number_type in (
        phonenumbers.PhoneNumberType.MOBILE,
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
    )


def infer_company_size(review_count, category, name, website, address):
    """Infer company size using review count plus business category or name hints."""
    text = " ".join(filter(None, [category, name, website, address])).lower()
    corporate_indicators = [
        "hospital", "clinic", "university", "school", "college", "hotel",
        "resort", "mall", "corporate", "enterprise", "bank", "airport",
        "factory", "factory", "warehouse", "office", "it park", "business park",
        "hospitality", "chain", "hospital", "corporation", "plaza", "tower",
    ]
    medium_indicators = [
        "center", "centre", "studio", "service", "salon", "clinic", "school",
        "academy", "shop", "bakery", "restaurant", "cafe", "boutique", "deli"
    ]

    if review_count >= 250:
        return "Big / Top Tier"
    if review_count >= 100:
        return "Medium Tier"

    # Bump size based on business category hints
    if any(term in text for term in corporate_indicators) and review_count >= 30:
        return "Medium Tier"
    if any(term in text for term in medium_indicators) and review_count >= 20:
        return "Medium Tier"

    if review_count >= 50:
        return "Medium Tier"
    return "Small"


def parse_quality_requirements(prompt_description):
    """Infer minimum lead quality requirements from the prompt description."""
    desc = (prompt_description or "").strip().lower()
    requirements = {
        "min_reviews": 0,
        "min_rating": 0.0,
        "allow_small": True,
    }

    if not desc:
        return requirements

    if any(term in desc for term in ["only small", "small only", "small size", "small leads", "include small"]):
        requirements["allow_small"] = True
        requirements["min_reviews"] = 0
        requirements["min_rating"] = 0.0
    elif any(term in desc for term in ["high reputed", "high rated", "only high", "high only", "top tier", "top rated", "premium", "trusted", "reputed", "reputable"]):
        requirements["allow_small"] = False
        requirements["min_reviews"] = max(requirements["min_reviews"], 50)
        requirements["min_rating"] = max(requirements["min_rating"], 4.0)
    elif any(term in desc for term in ["medium", "medium tier", "mid tier", "medium size"]):
        requirements["allow_small"] = False
        requirements["min_reviews"] = max(requirements["min_reviews"], 50)
        requirements["min_rating"] = max(requirements["min_rating"], 3.0)
    elif any(term in desc for term in ["any size", "all sizes", "all leads"]):
        requirements["allow_small"] = True
        requirements["min_reviews"] = 0

    if "high" in desc and "medium" in desc and requirements["min_reviews"] < 50:
        requirements["min_reviews"] = 50

    return requirements


def is_chain_establishment(name):
    """
    Detects if a business name appears to be part of a chain/franchise.
    Returns True if it's likely a chain, False if it appears to be an independent establishment.
    """
    if not name:
        return False
    
    name_lower = name.lower().strip()
    
# Common chain indicators - terms that more reliably mean a chain/franchise.
    chain_indicators = [
        "chain", "franchise", "outlet", "branch", "express", "superstore", "hypermarket", "plaza"
    ]

    # Known false-positive legal suffixes that should not by themselves classify a business as a chain.
    false_positive_suffixes = [
        "pvt ltd", "pvt. ltd", "private limited", "ltd", "corp", "inc", "projects", "solutions", "consultants", "services"
    ]

    # If explicit chain markers exist, classify as chain.
    for indicator in chain_indicators:
        if indicator in name_lower:
            return True

    # Numbered locations are chain-like only when not clearly a formal company name.
    if re.search(r"\b\d+\b", name_lower) and not any(term in name_lower for term in false_positive_suffixes):
        return True
    
    # Known major chains database (can be extended)
    known_chains = [
        # Restaurant chains
        "mcdonald's", "mcdonalds", "kfc", "subway", "domino's", "dominos", "pizza hut",
        "burger king", "wendy's", "taco bell", "chipotle", "starbucks", "dunkin",
        "chai point", "cafe coffee day", "ccd", "barista",
        # Hotel chains
        "marriott", "hilton", "hyatt", "radisson", "taj", "itc", "oberoi",
        "novotel", "ibis", "holiday inn", "sheraton", "westin",
        # Dhaba/highway chains
        "hometown", "desi vibes", "dhaba express",
        # QSR chains
        "haldiram's", "haldirams", "bikanervala", "bikanerwala",
        "papa john's", "papa johns", "little italy",
    ]
    
    for chain in known_chains:
        if chain in name_lower:
            return True
    
    return False

def extract_contact_person(text):
    """Heuristically scans page text for contact names/roles (Owner, Manager, Chef, etc.)."""
    if not text:
        return ""
    # Heuristic regex patterns for common role mappings
    patterns = [
        r"(?:owner|founder|manager|chef|proprietor|ceo|partner)\s*(?::|is|of\s+establishment)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*,\s*(?:owner|founder|manager|chef|proprietor|ceo)",
        r"(?:contact\s+person|reach\s+out\s+to|speak\s+with)\s*(?::|is|)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            name = matches[0].strip()
            # Exclude typical false positive web vocabulary
            ignored_words = {
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", 
                "Contact", "About", "Home", "Website", "RedSorm", "Menu", "Our", "We", "Get", 
                "Map", "Location", "Directions", "Privacy", "Terms", "Policies", "Order", "Reservation"
            }
            if name not in ignored_words and len(name.split()) >= 2:
                # Limit length to look like a real name
                if len(name) < 40:
                    return name
    return ""

def extract_emails_from_text(text):
    """Uses regex to extract valid email addresses from text."""
    if not text:
        return []
    # Standard email regex
    email_pattern = r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
    emails = re.findall(email_pattern, text)
    
    # Filter out common false positives and image/icon files
    ignored_domains = {
        "example.com", "w3.org", "sentry.io", "bootstrap.com", "jquery.com",
        "sentry-next.wixpress.com", "wixpress.com", "sentry.io", "wix.com",
        "example.org", "example.net", "test.com", "email.com", "mail.com"
    }
    ignored_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js"}
    
    # Patterns that indicate invalid/automated emails
    invalid_patterns = [
        r"^[0-9a-f]{20,}@",  # Long hex strings (like Sentry IDs)
        r"^[0-9a-f]{8}-[0-9a-f]{4}-",  # UUID patterns
        r"@sentry",  # Sentry error tracking emails
        r"@noreply\.",  # No-reply emails
        r"@mailer\.",  # Mailer daemon emails
        r"@postmaster\.",  # Postmaster emails
    ]
    
    valid_emails = []
    for email in emails:
        email = email.lower().strip()
        domain = email.split("@")[-1] if "@" in email else ""
        
        # Check ignored domains
        if domain in ignored_domains:
            continue
            
        # Check invalid patterns
        is_invalid = False
        for pattern in invalid_patterns:
            if re.search(pattern, email):
                is_invalid = True
                break
        if is_invalid:
            continue
        
        # Check extensions
        if any(email.endswith(ext) for ext in ignored_extensions):
            continue
        
        # Additional validation: must have at least one letter before @
        local_part = email.split("@")[0] if "@" in email else ""
        if not re.search(r"[a-zA-Z]", local_part):
            continue
        
        # Must not be all numbers
        if re.match(r"^[0-9]+@", email):
            continue
            
        valid_emails.append(email)
        
    return list(set(valid_emails))

def scrape_website_for_contact(url, ui_log_callback=None):
    """
    Fetches the website homepage and scans for emails and contact person names.
    If no contact info is found, attempts to locate contact/about pages and search there.
    """
    if not url:
        return {"email": "", "contact_person": ""}
    
    # Ensure scheme
    if not url.startswith("http"):
        url = "http://" + url
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    emails = []
    contact_person = ""
    contact_links = []
    
    try:
        # Step 1: Scrape Homepage
        response = requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        soup = BeautifulSoup(response.text, "html.parser")
        homepage_text = soup.get_text()
        
        # Check mailto links first
        for a in soup.select('a[href^="mailto:"]'):
            email_href = a["href"].replace("mailto:", "").split("?")[0].strip()
            if email_href:
                emails.append(email_href)
                
        # Regex search homepage text
        emails.extend(extract_emails_from_text(response.text))
        
        # Heuristic search for contact person on homepage
        contact_person = extract_contact_person(homepage_text)
        
        # Find contact or about pages
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text().lower()
            if any(term in href or term in text for term in ["contact", "about", "team", "info", "reach"]):
                # Construct absolute link
                full_url = urllib.parse.urljoin(url, a["href"])
                if full_url.startswith(url): # Stay on same site
                    contact_links.append(full_url)
                    
        # Step 2: Scrape Contact/About Pages if emails or contact person missing
        if contact_links and (not emails or not contact_person):
            for link in list(set(contact_links))[:3]: # Limit to top 3 links
                try:
                    c_resp = requests.get(link, headers=headers, timeout=TIMEOUT)
                    c_soup = BeautifulSoup(c_resp.text, "html.parser")
                    page_text = c_soup.get_text()
                    
                    # Search emails
                    if not emails:
                        for a in c_soup.select('a[href^="mailto:"]'):
                            email_href = a["href"].replace("mailto:", "").split("?")[0].strip()
                            if email_href:
                                emails.append(email_href)
                        emails.extend(extract_emails_from_text(c_resp.text))
                        
                    # Search contact person
                    if not contact_person:
                        contact_person = extract_contact_person(page_text)
                        
                except Exception:
                    continue
                    
    except Exception as e:
        log_msg(f"[!] Warning: Failed to scrape website '{url}': {e}", ui_log_callback)
        
    unique_emails = list(set(emails))
    return {
        "email": ", ".join(unique_emails) if unique_emails else "",
        "contact_person": contact_person
    }

def scrape_leads_for_query(query, city, target_new_leads, max_scrolls=5, ui_log_callback=None, prompt_description=None):
    """
    Uses Playwright to scrape Google Maps for a specific search query.
    Extracts name, rating, reviews, phone, and website.
    Filters out duplicates and fetches emails for new leads.
    """
    requirements = parse_quality_requirements(prompt_description)
    region = get_region_for_location(city)

    log_msg(f"[*] Starting scraper for: '{query}' in '{city}'", ui_log_callback)
    log_msg(f"[*] Quality requirement: min_rating={requirements['min_rating']}, min_reviews={requirements['min_reviews']}, allow_small={requirements['allow_small']}", ui_log_callback)
    if region:
        log_msg(f"[*] Location region resolved as: {region}", ui_log_callback)

    scraped_count = 0
    new_leads_scraped = []
    
    with sync_playwright() as p:
        # Launch Chromium (Headless mode, stealth settings)
        browser = p.chromium.launch(headless=True)
        # Set viewport and agent to mimic human
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        # Quick internet connectivity check before attempting navigation
        if not _ensure_internet_available(retries=3, base_delay=3):
            log_msg(f"[!] Warning: No internet connectivity detected. Skipping query '{query}'.", ui_log_callback)
            try:
                browser.close()
            except Exception:
                pass
            return []

        # Navigate directly to Google Maps search with retry logic
        search_url = f"https://www.google.com/maps/search/{urllib.parse.quote_plus(query)}/"
        nav_success = False
        nav_attempts = 3
        for attempt in range(1, nav_attempts + 1):
            try:
                page.goto(search_url, timeout=30000)
                nav_success = True
                break
            except Exception as e:
                log_msg(f"[!] Warning: navigation attempt {attempt}/{nav_attempts} failed for '{query}': {e}", ui_log_callback)
                # Re-check connectivity before retrying
                if not _ensure_internet_available(retries=2, base_delay=2):
                    log_msg(f"[!] Warning: Internet appears down after failed navigation. Aborting query '{query}'.", ui_log_callback)
                    break
                time.sleep(2 * attempt)

        if not nav_success:
            try:
                browser.close()
            except Exception:
                pass
            return []
        
        # Wait for either result cards or 'No results' indicator
        try:
            page.wait_for_selector('div[role="feed"]', timeout=15000)
        except Exception:
            log_msg(f"[-] No results panel found for query: '{query}'", ui_log_callback)
            browser.close()
            return []
            
        # Scroll the left feed panel to load more results
        log_msg("[*] Scrolling to load more listings...", ui_log_callback)
        feed_selector = 'div[role="feed"]'
        scroll_count = max_scrolls
        
        for i in range(scroll_count):
            try:
                # Scroll the feed element downwards
                page.evaluate(
                    f'document.querySelector(\'{feed_selector}\').scrollTop = document.querySelector(\'{feed_selector}\').scrollHeight'
                )
                time.sleep(2) # Wait for network load
            except Exception:
                break
                
        # Find all listings in the sidebar
        # Using a list of selectors to capture listings resiliently
        listings = []
        # Class '.hfpxzc' is the standard link overlay for Google Maps search results
        links = page.locator('a.hfpxzc').all()
        
        log_msg(f"[*] Found {len(links)} potential listings in sidebar.", ui_log_callback)
        
        for idx, link in enumerate(links):
            # Enforce daily limit across target search
            if len(new_leads_scraped) >= target_new_leads:
                log_msg(f"[*] Reached target new leads count of {target_new_leads} for today. Stopping.", ui_log_callback)
                break
                
            name = link.get_attribute("aria-label")
            detail_url = link.get_attribute("href")
            
            if not name:
                continue
                
            name = name.strip()
            
            # Optimization: Check if we already scraped this lead in the current session or historically
            if any(lead.get('Name') == name for lead in new_leads_scraped) or db.lead_exists(name=name, city=city):
                log_msg(f"[~] Skipping existing lead: '{name}' in {city}", ui_log_callback)
                continue
                
            log_msg(f"\n[*] Processing New Lead ({len(new_leads_scraped)+1}/{target_new_leads}): '{name}'", ui_log_callback)
            
            # Click card to open the detail panel
            try:
                link.click()
                # Wait for the detail panel main section to render
                page.wait_for_selector('div[role="main"]', timeout=8000)
                # Short sleep to let animations finish and content load
                time.sleep(1.5)
            except Exception as click_err:
                log_msg(f"[!] Error clicking lead '{name}': {click_err}", ui_log_callback)
                continue
                
            # --- Extract Details ---
            # 1. Rating & Review Count
            rating = None
            review_count = 0
            try:
                # Target class or text matching rating
                rating_elem = page.locator('div[role="main"] span[aria-hidden="true"]').first
                if rating_elem.is_visible():
                    rating_text = rating_elem.inner_text().strip()
                    if re.match(r"^\d(\.\d)?$", rating_text):
                        rating = float(rating_text)
                        
                # Review count is usually inside parentheses next to rating
                reviews_elem = page.locator('span[aria-label*="reviews"]').first
                if reviews_elem.is_visible():
                    rev_text = reviews_elem.get_attribute("aria-label")
                    rev_match = re.search(r"(\d+[\d,]*)\s+reviews", rev_text)
                    if rev_match:
                        review_count = int(rev_match.group(1).replace(",", ""))
            except Exception:
                pass
                
            # 2. Category
            category = ""
            try:
                # Category string is typically near the rating/reviews, next to a button or directly
                category_elem = page.locator('button[class*="DkE7cc"]').first
                if category_elem.is_visible():
                    category = category_elem.inner_text().strip()
                else:
                    # Alternative selector
                    alt_cat = page.locator('span[class*="DkE7cc"]').first
                    if alt_cat.is_visible():
                        category = alt_cat.inner_text().strip()
            except Exception:
                pass
                
            # 3. Phone Number
            phone = ""
            phone_selectors = [
                'button[data-item-id^="phone:tel:"]',
                'a[href^="tel:"]',
                '[aria-label*="Phone:"]',
                '[data-tooltip="Copy phone number"]'
            ]
            for selector in phone_selectors:
                try:
                    elem = page.locator(selector).first
                    if elem.is_visible():
                        # Extract from data-item-id
                        item_id = elem.get_attribute("data-item-id")
                        if item_id and "phone:tel:" in item_id:
                            phone = item_id.replace("phone:tel:", "").strip()
                            break
                        # Extract from aria-label
                        aria = elem.get_attribute("aria-label")
                        if aria and "Phone:" in aria:
                            phone = aria.replace("Phone:", "").strip()
                            break
                        # Extract from text or tooltip
                        phone = elem.inner_text().strip()
                        if phone:
                            break
                except Exception:
                    continue
            
            # Fallback Phone Regex on detailed panel text
            if not phone:
                try:
                    panel_text = page.locator('div[role="main"]').inner_text()
                    phone_match = re.search(r"(\+\d[\d\s\-()]{7,}\d)", panel_text)
                    if phone_match:
                        phone = phone_match.group(0)
                except Exception:
                    pass
                    
            phone = format_phone(phone, region=region)
            
            # 4. Website URL
            website = ""
            website_selectors = [
                'a[data-item-id="authority"]',
                'a[aria-label*="Website:"]',
                'a[data-tooltip*="website"]'
            ]
            for selector in website_selectors:
                try:
                    elem = page.locator(selector).first
                    if elem.is_visible():
                        href = elem.get_attribute("href")
                        if href and not "google.com" in href:
                            website = href
                            break
                except Exception:
                    continue
                    
            # 5. Address
            address = ""
            address_selectors = [
                'button[data-item-id^="address"]',
                '[aria-label*="Address:"]',
                '[data-tooltip="Copy address"]'
            ]
            for selector in address_selectors:
                try:
                    elem = page.locator(selector).first
                    if elem.is_visible():
                        aria = elem.get_attribute("aria-label")
                        if aria and "Address:" in aria:
                            address = aria.replace("Address:", "").strip()
                            break
                        address = elem.inner_text().strip()
                        if address:
                            break
                except Exception:
                    continue
                    
            # Normalize and Enrich Lead details (fetch email and contact person first to support phone OR email checks)
            email = ""
            contact_person = ""
            if website:
                log_msg(f"   [+] Enrichment: Website found '{website}'. Searching for contacts...", ui_log_callback)
                enrichment = scrape_website_for_contact(website, ui_log_callback=ui_log_callback)
                email = enrichment["email"]
                contact_person = enrichment["contact_person"]
                if email:
                    log_msg(f"   [+] Extracted Email(s): {email}", ui_log_callback)
                if contact_person:
                    log_msg(f"   [+] Extracted Contact Person: {contact_person}", ui_log_callback)
                    
            # --- Strict Lead Quality Verification ---
            # 1. Minimum Rating Filter
            min_rating_val = FILTERS.get("min_rating", 3.0)
            if min_rating_val and rating is not None and rating < min_rating_val:
                log_msg(f"   [-] Discarding: Rating ({rating}) is below minimum requirement ({min_rating_val}).", ui_log_callback)
                continue
                
            # 2. Minimum Review Count & Reputed Size Classification Filter
            establishment_size = infer_company_size(review_count, category, name, website, address)

            if establishment_size == "Small" and not requirements["allow_small"]:
                log_msg(f"   [-] Discarding: '{name}' is Small tier and prompt does not allow small leads.", ui_log_callback)
                continue
                
            # 3. Chain Detection - Skip chains/franchises
            if is_chain_establishment(name):
                log_msg(f"   [-] Discarding: '{name}' appears to be a chain/franchise establishment.", ui_log_callback)
                continue
                
            # 4. Phone Number Validation (If phone exists, validate it by region)
            if phone and FILTERS.get("strict_phone_validation", True):
                if not is_valid_phone(phone, region=region):
                    log_msg(f"   [~] Warning: Phone '{phone}' is not a valid number for region {region or 'default'}.", ui_log_callback)
                    phone = "" # Clear invalid phone so user doesn't call a junk number
                    
            # 5. Mandatory Phone or Email Check
            if not phone and not email:
                log_msg("   [-] Discarding: Lead lacks both a valid phone number and an email address.", ui_log_callback)
                continue

            # 6. Quality requirements from prompt description
            if requirements["min_rating"] and rating is not None and rating < requirements["min_rating"]:
                log_msg(f"   [-] Discarding: Rating {rating} is below required {requirements['min_rating']}.", ui_log_callback)
                continue
            if requirements["min_reviews"] and review_count < requirements["min_reviews"]:
                log_msg(f"   [-] Discarding: Review count {review_count} is below required {requirements['min_reviews']}.", ui_log_callback)
                continue

            lead_item = {
                "name": name,
                "category": category or query.split(" in ")[0].capitalize(),
                "phone": phone,
                "email": email,
                "contact_person": contact_person,
                "establishment_size": establishment_size,
                "website": website,
                "address": address,
                "rating": rating,
                "review_count": review_count,
                "city": city
            }
            
            # In-memory save to list
            lead_item["id"] = len(new_leads_scraped) + 1
            new_leads_scraped.append(lead_item)
            
            # Insert to DB for persistent duplicate checking
            db_lead_data = {
                "name": name,
                "category": category,
                "phone": phone,
                "email": email,
                "website": website,
                "address": address,
                "rating": rating,
                "review_count": review_count,
                "city": city,
                "contact_person": contact_person,
                "establishment_size": establishment_size
            }
            db.insert_lead(db_lead_data, log_callback=ui_log_callback)
            
            log_msg(f"   [+] Scraped Lead: {name}", ui_log_callback)

            # --- Deep Research Delay & Pacing ---
            if FILTERS.get("deep_research_mode", True):
                delay = random.uniform(1.5, 3.5)
                log_msg(f"   [~] Deep Research Pacing: Verifying details. Pausing for {delay:.1f} seconds...", ui_log_callback)
                time.sleep(delay)
                
        browser.close()
        
    return new_leads_scraped

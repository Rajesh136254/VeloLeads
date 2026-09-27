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
    # Heuristic regex patterns for common role mappings (expanded for staffing/recruiting)
    patterns = [
        r"(?:owner|founder|manager|chef|proprietor|ceo|partner|hr|recruiter|talent|people|operations)\s*(?::|is|of\s+establishment)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*,\s*(?:owner|founder|manager|chef|proprietor|ceo|hr|recruiter|talent|people|operations)",
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

def classify_emails(emails_list):
    """
    Classifies a list of email strings into role-based categories:
    - HR/Recruitment (hr_emails)
    - Executive/Leadership (exec_emails)
    - Managers (manager_emails)
    - Other/Generic (other_emails)
    Returns a dict with key/comma-separated value strings.
    """
    hr_list = []
    exec_list = []
    manager_list = []
    other_list = []

    hr_patterns = ["hr", "career", "job", "recruit", "talent", "hiring", "people", "work"]
    exec_patterns = ["ceo", "cfo", "cto", "coo", "vp", "president", "director", "founder", "owner", "partner", "executive"]
    manager_patterns = ["manager", "lead", "supervisor", "head"]

    for email in emails_list:
        email = email.lower().strip()
        if not email:
            continue
        local_part = email.split("@")[0]

        # Check HR/Recruiter patterns
        if any(pat in local_part for pat in hr_patterns):
            hr_list.append(email)
        # Check Exec patterns
        elif any(pat in local_part for pat in exec_patterns):
            exec_list.append(email)
        # Check Manager patterns
        elif any(pat in local_part for pat in manager_patterns):
            manager_list.append(email)
        # Otherwise, generic/other
        else:
            other_list.append(email)

    return {
        "hr_emails": ", ".join(hr_list),
        "exec_emails": ", ".join(exec_list),
        "manager_emails": ", ".join(manager_list),
        "other_emails": ", ".join(other_list)
    }


def is_non_commercial_establishment(name, category):
    """
    Determines if an establishment is a non-profit, NGO, government entity, or charity.
    Returns True if it matches any non-commercial keywords.
    """
    name_lower = (name or "").lower()
    cat_lower = (category or "").lower()
    combined = f"{name_lower} {cat_lower}"

    non_comm_keywords = [
        "charity", "foundation", "ngo", "nonprofit", "non-profit", "association",
        "trust", "government", "ministry", "public school", "welfare", "church",
        "temple", "mosque", "embassy", "consulate", "department of", "municipal",
        "police", "fire station", "senate", "parliament", "unicef", "red cross",
        "humanitarian", "social service", "philanthropic"
    ]
    return any(keyword in combined for keyword in non_comm_keywords)


def should_exclude_by_keywords(name, category, full_site_text, exclude_keywords_str):
    """Checks if company name, category, or crawled website text contains any user-specified exclusion keywords."""
    if not exclude_keywords_str:
        return False, ""
    import re
    keywords = [k.strip().lower() for k in exclude_keywords_str.split(",") if k.strip()]
    name_lower = (name or "").lower()
    cat_lower = (category or "").lower()
    site_lower = (full_site_text or "").lower()
    combined = f"{name_lower} {cat_lower} {site_lower}"
    
    for kw in keywords:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, combined):
            return True, kw
    return False, ""


def match_size_range(size, range_str):
    if not range_str or range_str == "Any Size":
        return True
    range_str = range_str.replace(" ", "").lower()
    if "+" in range_str:
        try:
            min_val = int(range_str.replace("+", ""))
            return size >= min_val
        except ValueError:
            return True
    elif "-" in range_str:
        try:
            parts = range_str.split("-")
            min_val = int(parts[0])
            max_val = int(parts[1])
            return min_val <= size <= max_val
        except ValueError:
            return True
    return True


def detect_company_size_from_text(website_text, target_sizes_list):
    """Heuristically extracts company headcount from text and matches it against target_sizes_list (list of ranges)."""
    if not target_sizes_list or "Any Size" in target_sizes_list or len(target_sizes_list) == 0:
         return True, "Any Size"
         
    if not website_text:
         return True, "Not Specified (Empty Site Text)"
         
    import re
    text_lower = website_text.lower()
    # Look for headcount/employee patterns
    patterns = [
        r"(\d+[\d,]*)\s*(?:-\s*\d+[\d,]*)?\s*\+?\s*(?:employees|staff|members|professionals|people|workers|consultants|headcount)",
        r"team of\s*(\d+[\d,]*)\s*\+?",
        r"headcount of\s*(\d+[\d,]*)\s*\+?"
    ]
    
    found_size = None
    for pat in patterns:
        matches = re.findall(pat, text_lower)
        if matches:
            try:
                digit_str = re.sub(r'[^\d]', '', matches[0])
                if digit_str:
                    val = int(digit_str)
                    if 0 < val < 1000000:
                        found_size = val
                        break
            except ValueError:
                continue
                
    if found_size is not None:
        is_match = any(match_size_range(found_size, size_opt) for size_opt in target_sizes_list)
        return is_match, f"{found_size} ({'Matches' if is_match else 'Filtered'})"
        
    return True, "Assumed Match (No explicit size mentioned in text)"


def matches_prompt_description(website_text, prompt_description):
    """Verifies if the scraped company matches the prompt description / extra info criteria."""
    if not prompt_description:
        return True
        
    stopwords = {
        "find", "must", "have", "only", "the", "and", "for", "with", "should", "only", 
        "leads", "companies", "businesses", "in", "at", "who", "where", "please", "reputed", 
        "high", "reviews", "ratings", "reputable", "trust", "highly", "provider", "providers",
        "build", "builds", "using", "use", "uses", "or", "apps", "app", "web", "website", 
        "websites", "company", "service", "services", "solutions", "work", "working", 
        "run", "running", "looking", "hire", "hiring", "recruit", "recruiting", "of", "to", "a"
    }
    words = [w.strip().lower().replace(",", "").replace(".", "").replace(":", "") for w in prompt_description.split() if w.strip().lower() not in stopwords]
    # Remove duplicates and empty strings
    words = list(set([w for w in words if w]))
    if not words:
        return True
        
    website_text_lower = website_text.lower()
    match_count = sum(1 for word in words if word in website_text_lower)
    return match_count > 0


def matches_target_industry(name, category, website_text, target_industry):
    """Verifies if the scraped company is related to the target industry or category."""
    if not target_industry:
        return True
    terms = [t.strip().lower() for t in target_industry.split(",") if t.strip()]
    combined = f"{name} {category} {website_text}".lower()
    
    synonyms = {
        "software": ["software", "tech", "technology", "developer", "programming", "it ", "digital", "app ", "web ", "cloud"],
        "it": ["it ", "information technology", "software", "tech", "technology", "developer", "computer", "systems", "network"],
        "logistics": ["logistics", "shipping", "freight", "transport", "delivery", "warehouse", "supply chain", "cargo"],
        "retail": ["retail", "shop", "store", "commerce", "supermarket", "boutique", "apparel", "clothing"],
        "manufacturing": ["manufacturing", "factory", "industrial", "manufacturer", "production", "assembly", "plant"],
        "finance": ["finance", "bank", "financial", "lending", "credit", "mortgage", "investment", "wealth", "capital"],
        "healthcare": ["healthcare", "medical", "hospital", "clinic", "doctor", "health", "care ", "physician", "dental"],
        "hospitality": ["hospitality", "hotel", "resort", "motel", "stay", "restaurant", "cafe"]
    }
    
    for term in terms:
        if term in combined:
            return True
        for syn_key, syn_list in synonyms.items():
            if term == syn_key or syn_key in term:
                for syn in syn_list:
                    if syn in combined:
                        return True
    return False


def extract_decision_makers(website_text, email_str=""):
    """Identifies B2B decision makers (Founder, CEO, HR Manager, CTO) heuristically from site text."""
    if not website_text:
        return []
        
    import re
    lines = [line.strip() for line in website_text.split("\n") if len(line.strip()) >= 5 and len(line.strip()) <= 100]
    
    role_patterns = {
        "Founder/CEO": r"\b(ceo|founder|co-founder|president|managing director|director|owner)\b",
        "HR/Recruiting": r"\b(hr manager|recruiter|talent acquisition|head of talent|people operations|chief people officer)\b",
        "CTO/Engineering": r"\b(cto|vp of engineering|it director|engineering manager|tech lead)\b",
        "COO/Operations": r"\b(coo|operations manager|chief operating officer|operations director)\b"
    }
    
    name_pattern = r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,2})\b"
    results = []
    seen_names = set()
    
    title_words = {
        "operations", "lead", "manager", "chief", "officer", "people", "talent", 
        "acquisition", "director", "vp", "president", "executive", "founder", 
        "ceo", "cto", "coo", "hr", "recruiter", "owner", "partner", "co-founder", 
        "about", "services", "careers", "jobs", "apply", "privacy", "terms", 
        "home", "location", "phone", "contact", "us", "team", "our", "we", "management"
    }
    
    for line in lines:
        for role, pattern in role_patterns.items():
            if re.search(pattern, line, re.IGNORECASE):
                name_matches = re.findall(name_pattern, line)
                for name in name_matches:
                    name_words = set(name.lower().split())
                    if not name_words.intersection(title_words) and len(name.split()) >= 2:
                        if name not in seen_names:
                            seen_names.add(name)
                            results.append({
                                "name": name,
                                "role": role,
                                "title": re.search(pattern, line, re.IGNORECASE).group(0)
                            })
                            break
    return results


def has_excluded_tld(url_or_email, excluded_tlds=["org", "gov", "edu", "mil"]):
    if not url_or_email:
        return False
    import urllib.parse
    url_lower = url_or_email.lower()
    domain = ""
    if "@" in url_lower:
        domain = url_lower.split("@")[-1]
    else:
        if not url_lower.startswith("http"):
            url_lower = "http://" + url_lower
        try:
            parsed = urllib.parse.urlparse(url_lower)
            domain = parsed.netloc
        except Exception:
            domain = url_lower
            
    if not domain:
        return False
        
    parts = domain.split(".")
    for part in parts[-2:]:
        if part in excluded_tlds:
            return True
    return False


def extract_context_snippet(text, keyword):
    """Finds keyword in text and extracts ~80 chars around it."""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return ""
    start = max(0, idx - 30)
    end = min(len(text), idx + len(keyword) + 50)
    snippet = text[start:end].replace("\n", " ").strip()
    return f"...{snippet}..."


def extract_job_id(url, text=""):
    """
    Tries to extract a job ID or reference code from the job URL or description snippet.
    """
    if not url:
        return ""
    
    import re
    url_lower = url.lower()
    
    # 1. LinkedIn: e.g. /jobs/view/123456789
    m = re.search(r'/jobs/view/(\d+)', url)
    if m:
        return m.group(1)
        
    # 2. Indeed: e.g. jk=abcdef12345
    m = re.search(r'[?&]jk=([a-zA-Z0-9]+)', url)
    if m:
        return m.group(1)
        
    # 3. Generic career sites query parameters: e.g. jobId=9999, reqId=8888, req=7777, job_id=6666
    for param in ["jobid", "reqid", "job_id", "req_id", "requisitionid", "jobid", "requisition"]:
        m = re.search(r'[?&]' + param + r'=([a-zA-Z0-9-_]+)', url_lower)
        if m:
            # Get original case value
            idx = url_lower.find(param + "=") + len(param) + 1
            val = url[idx:].split("&")[0].split("?")[0]
            if val:
                return val

    # 4. Try parsing trailing digit codes: e.g. /job-detail-123456
    m = re.search(r'-(\d{5,15})/?$', url)
    if m:
        return m.group(1)
    m = re.search(r'/(\d{5,15})/?$', url)
    if m:
        return m.group(1)
        
    # 5. Check text for patterns: e.g. "Job ID: R2601816" or "Req ID: 12345"
    if text:
        text_patterns = [
            r'(?:job|req|requisition|ref|reference)\s*(?:id|code|number|#)?\s*[:#-]?\s*([a-zA-Z0-9-_]+)',
            r'job\s*req\s*[:#-]?\s*([a-zA-Z0-9-_]+)'
        ]
        for pat in text_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if len(val) >= 4 and len(val) <= 15:
                    return val
                    
    return ""


def is_educational_or_training_provider(name, category, url, text):
    """
    Checks if the lead or match is associated with training courses, tutorials, programs,
    or educational certifications rather than a real job vacancy.
    """
    name_lower = (name or "").lower()
    cat_lower = (category or "").lower()
    url_lower = (url or "").lower()
    text_lower = (text or "").lower()
    
    # 1. Company Name/Category indicators of training center or school
    edu_indicators = [
        "academy", "institute", "school", "university", "college", "training center",
        "tutorial", "coaching", "classes", "learning", "education", "course", "syllabus"
    ]
    if any(ind in name_lower for ind in edu_indicators) or any(ind in cat_lower for ind in edu_indicators):
        if not ("career" in name_lower or "job" in name_lower):
            return True
            
    # 2. URL paths indicating courses, training, syllabus, tutorials
    course_url_indicators = [
        "/course", "/training", "/syllabus", "/program", "/curriculum", "/class", "/batch",
        "/tutorial", "/admission", "/learn-", "/certification", "/fees", "-course", "-training"
    ]
    if any(ind in url_lower for ind in course_url_indicators):
        return True
        
    # 3. Snippet/Text content indicating selling courses or programs rather than hiring
    course_text_indicators = [
        "placement assistance", "fees", "syllabus", "course modules", "course curriculum",
        "training course", "training program", "certification program", "enroll now",
        "admission open", "batch details", "learn from scratch", "learn data science",
        "career path guide", "roadmap guide", "hands-on projects", "mentor-led", "class schedule"
    ]
    matched_indicators = [ind for ind in course_text_indicators if ind in text_lower]
    if len(matched_indicators) >= 1:
        return True
        
    return False


def check_jobs_via_google_search(company_name, keywords_list, page_context=None, ui_log_callback=None):
    """
    Queries Bing Search via Playwright browser session to retrieve exact job posting URLs.
    Falls back to a new playwright context if page_context is not provided.
    """
    if not company_name or not keywords_list:
        return None, None, None

    def execute_search(page):
        for keyword in keywords_list:
            queries = [
                f'site:linkedin.com/jobs/ "{company_name}" "{keyword}"',
                f'site:indeed.com/ "{company_name}" "{keyword}"',
                f'"{company_name}" ("careers" OR "jobs" OR "hiring") "{keyword}"'
            ]
            for q in queries:
                url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(q)}"
                try:
                    page.goto(url, wait_until="load", timeout=8000)
                    page.wait_for_timeout(2000)
                    
                    locators = page.locator("li.b_algo h2 a, .b_algo h2 a").all()
                    for loc in locators:
                        href = loc.get_attribute("href")
                        if href and not any(ignored in href.lower() for ignored in ["bing.com", "microsoft.com"]):
                            # Filter out generic search URLs from job boards to ensure exact vacancy url
                            href_lower = href.lower()
                            if any(term in href_lower for term in ["/search", "/jobs/search", "search?", "/jobs-in-", "/q-", "/jobs-at-", "keyword="]):
                                continue
                            clean_href = href
                            if "bing.com/ck/a?" in href:
                                try:
                                    u_param = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("u", [""])[0]
                                    if u_param.startswith("a1"):
                                        import base64
                                        b64 = u_param[2:]
                                        b64 += "=" * ((4 - len(b64) % 4) % 4)
                                        clean_href = base64.b64decode(b64.encode("utf-8", errors="ignore")).decode("utf-8", errors="ignore")
                                except Exception:
                                    pass
                            
                            text = page.locator("body").inner_text()
                            job_id = extract_job_id(clean_href, text)
                            snippet = f"Found active job posting on board: '{clean_href}'"
                            return clean_href, snippet, job_id
                except Exception:
                    continue
        return None, None, None

    if page_context:
        try:
            temp_page = page_context.context.new_page()
            try:
                res_url, res_snippet, res_job_id = execute_search(temp_page)
                return res_url, res_snippet, res_job_id
            finally:
                temp_page.close()
        except Exception:
            pass

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                temp_page = browser.new_page()
                res_url, res_snippet, res_job_id = execute_search(temp_page)
                return res_url, res_snippet, res_job_id
            finally:
                browser.close()
    except Exception as e:
        if ui_log_callback:
            log_msg(f"   [~] Playwright search fallback failed: {e}", ui_log_callback)
        
    return None, None, None


def scrape_website_for_contact(url, ui_log_callback=None, company_name=None, page_context=None):
    """
    Fetches the website homepage and scans for emails, contact person names, and social links.
    If staffing_mode is enabled, scans career pages and searches for job vacancies.
    """
    if not url:
        return {
            "email": "",
            "contact_person": "",
            "linkedin_url": "",
            "matched_snippet": "",
            "vacancy_url": "",
            "career_match_found": True,
            "hr_emails": "",
            "exec_emails": "",
            "manager_emails": "",
            "other_emails": "",
            "job_id": "",
            "full_site_text": ""
        }
    
    # Ensure scheme
    if not url.startswith("http"):
        url = "http://" + url
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    emails = []
    contact_person = ""
    contact_links = []
    career_links = []
    
    social_links = {
        "linkedin": "",
        "facebook": "",
        "twitter": ""
    }
    
    career_match_found = True
    matched_snippet = ""
    vacancy_url = ""
    job_id = ""
    full_site_text = ""
    
    staffing_mode = FILTERS.get("staffing_mode", False)
    raw_kw = FILTERS.get("career_keywords", "")
    career_keywords = [k.strip().lower() for k in raw_kw.split(",") if k.strip()]
    
    if staffing_mode and career_keywords:
        career_match_found = False

    try:
        # Step 1: Scrape Homepage
        response = requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        soup = BeautifulSoup(response.text, "html.parser")
        homepage_text = soup.get_text()
        full_site_text += homepage_text + "\n"
        
        # Check mailto links first
        for a in soup.select('a[href^="mailto:"]'):
            email_href = a["href"].replace("mailto:", "").split("?")[0].strip()
            if email_href:
                emails.append(email_href)
                
        # Regex search homepage text
        emails.extend(extract_emails_from_text(response.text))
        
        # Heuristic search for contact person on homepage
        contact_person = extract_contact_person(homepage_text)
        
        # Search social media links and career links
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text().lower()
            
            # Social links
            if "linkedin.com/company/" in href or "linkedin.com/school/" in href:
                social_links["linkedin"] = a["href"]
            elif "facebook.com/" in href and not any(term in href for term in ["sharer", "share", "post", "intent"]):
                social_links["facebook"] = a["href"]
            elif ("twitter.com/" in href or "x.com/" in href) and not any(term in href for term in ["share", "intent", "tweet"]):
                social_links["twitter"] = a["href"]
            
            # Contact links
            if any(term in href or term in text for term in ["contact", "about", "team", "info", "reach"]):
                full_url = urllib.parse.urljoin(url, a["href"])
                if full_url.startswith(url): # Stay on same site
                    contact_links.append(full_url)
                    
            # Career links
            if any(term in href or term in text for term in ["career", "job", "vacancy", "work", "join", "employment", "recruit", "position", "opening"]):
                full_url = urllib.parse.urljoin(url, a["href"])
                if full_url.startswith(url):
                    career_links.append(full_url)

        # De-duplicate links
        contact_links = list(set(contact_links))
        career_links = list(set(career_links))

        # Step 2: Scrape Contact/About Pages
        if contact_links and (not emails or not contact_person):
            for link in contact_links[:3]: # Limit to top 3 links
                try:
                    c_resp = requests.get(link, headers=headers, timeout=TIMEOUT)
                    c_soup = BeautifulSoup(c_resp.text, "html.parser")
                    page_text = c_soup.get_text()
                    full_site_text += page_text + "\n"
                    
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

        # Step 3: Scrape Career Pages specifically if staffing mode is enabled
        if staffing_mode and not career_match_found and career_keywords and career_links:
            for link in career_links[:2]: # Limit to top 2 career links
                try:
                    c_resp = requests.get(link, headers=headers, timeout=TIMEOUT)
                    c_soup = BeautifulSoup(c_resp.text, "html.parser")
                    page_text = c_soup.get_text()
                    full_site_text += page_text + "\n"
                    
                    # Also try to grab emails from career pages
                    for a in c_soup.select('a[href^="mailto:"]'):
                        email_href = a["href"].replace("mailto:", "").split("?")[0].strip()
                        if email_href:
                            emails.append(email_href)
                    emails.extend(extract_emails_from_text(c_resp.text))
                    
                    for kw in career_keywords:
                        snippet = extract_context_snippet(page_text, kw)
                        if snippet:
                            career_match_found = True
                            matched_snippet = snippet
                            vacancy_url = link
                            
                            # Look for an exact job opening link on this careers page
                            exact_job_url = ""
                            for a_tag in c_soup.find_all("a", href=True):
                                a_href = a_tag["href"]
                                a_text = a_tag.get_text().lower()
                                a_href_lower = a_href.lower()
                                
                                # If the link text contains the keyword (e.g. "Data Engineer")
                                if kw in a_text:
                                    exact_job_url = urllib.parse.urljoin(link, a_href)
                                    break
                                # If the URL itself contains the keyword and seems like a job detail page
                                if kw in a_href_lower and any(pat in a_href_lower for pat in ["/job", "/vacancy", "/career", "id=", "req="]):
                                    exact_job_url = urllib.parse.urljoin(link, a_href)
                                    break
                                    
                            if exact_job_url:
                                vacancy_url = exact_job_url
                                
                            job_id = extract_job_id(vacancy_url, page_text)
                            
                            if is_educational_or_training_provider(company_name, "", vacancy_url, page_text):
                                log_msg(f"   [~] Match discarded: Match on '{vacancy_url}' appears to be educational/training content, not a job vacancy.", ui_log_callback)
                                career_match_found = False
                                vacancy_url = ""
                                matched_snippet = ""
                                job_id = ""
                                continue
                                
                            log_msg(f"   [+] Vacancy Match: Found keyword '{kw}' on careers page ({link}). Exact Job URL: {vacancy_url}", ui_log_callback)
                            break
                except Exception:
                    continue

        # Step 4: Fallback checks via Google Search if still not found on website
        if staffing_mode and not career_match_found and career_keywords:
            target_company = company_name or url.replace("http://", "").replace("https://", "").split("/")[0]
            log_msg(f"   [~] Job vacancy not found on website. Performing search engine checks for '{target_company}'...", ui_log_callback)
            matched_val, snippet_text, job_id_val = check_jobs_via_google_search(target_company, career_keywords, page_context=page_context, ui_log_callback=ui_log_callback)
            if matched_val and snippet_text:
                if is_educational_or_training_provider(company_name, "", matched_val, snippet_text):
                    log_msg(f"   [~] Fallback match discarded: Match on '{matched_val}' appears to be educational/course content.", ui_log_callback)
                else:
                    career_match_found = True
                    matched_snippet = snippet_text
                    vacancy_url = matched_val
                    job_id = job_id_val or extract_job_id(matched_val, snippet_text)
                    log_msg(f"   [+] Vacancy Match (Search Fallback): Found job posting at '{vacancy_url}'.", ui_log_callback)
                    
    except Exception as e:
        log_msg(f"[!] Warning: Failed to scrape website '{url}': {e}", ui_log_callback)
        
    unique_emails = list(set(emails))
    email_str = ", ".join(unique_emails) if unique_emails else ""
    
    # Classify emails
    classified = classify_emails(unique_emails)
    
    return {
        "email": email_str,
        "contact_person": contact_person,
        "linkedin_url": social_links["linkedin"],
        "matched_snippet": matched_snippet,
        "vacancy_url": vacancy_url,
        "career_match_found": career_match_found,
        "job_id": job_id,
        "full_site_text": full_site_text,
        **classified
    }

def extract_company_name_from_title(title, domain):
    # Clean subdomains from the domain first
    domain_clean = domain
    for sub in ["careers.", "jobs.", "hiring.", "recruiting.", "workday.", "postings.", "www."]:
        if domain_clean.startswith(sub):
            domain_clean = domain_clean[len(sub):]
            
    if not title:
        return domain_clean.split('.')[0].capitalize()
    # Remove common suffixes
    title_clean = title.replace("Careers", "").replace("Jobs", "").replace("Hiring", "").replace("hiring", "").strip()
    # Split by standard separators
    parts = []
    for sep in [" - ", " | ", " • ", " : "]:
        if sep in title_clean:
            parts = title_clean.split(sep)
            break
    if parts:
        for p in reversed(parts):
            p_clean = p.strip()
            if p_clean and len(p_clean) < 30 and not any(k in p_clean.lower() for k in ["job", "career", "salary", "apply"]):
                return p_clean
    # Fallback to domain name
    return domain_clean.split('.')[0].capitalize()


def clean_bing_url(url):
    """
    Decodes the actual target URL from a Bing tracking link if applicable.
    Format: https://www.bing.com/ck/a?...&u=a1<base64_url>
    """
    if "bing.com/ck/a" not in url:
        return url
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        u_val = params.get("u", [""])[0]
        if u_val.startswith("a1"):
            base64_str = u_val[2:]
            padding = (4 - len(base64_str) % 4) % 4
            base64_str += "=" * padding
            import base64
            decoded = base64.b64decode(base64_str).decode("utf-8", errors="ignore")
            return decoded
    except Exception:
        pass
    return url


def scrape_leads_via_web_search(query, city, target_new_leads, ui_log_callback=None, prompt_description=None):
    """
    Scrapes Bing Web Search directly to find companies hiring for the query/keywords.
    Filters out job boards and directory sites, leaving actual company websites.
    """
    # Reconstruct precise search query based on entered details
    industry = query.split(" in ")[0] if " in " in query else query
    location = city
    career_kw = FILTERS.get("career_keywords", "")
    
    search_query = f'"{industry}"'
    search_query += ' AND ("careers" OR "jobs" OR "hiring" OR "vacancy")'
    if career_kw:
        kws = [k.strip() for k in career_kw.split(",") if k.strip()]
        if kws:
            kw_terms = " OR ".join(f'"{k}"' for k in kws[:3])
            search_query += f' AND ({kw_terms})'
            
    # Append key nouns from prompt description if provided
    if prompt_description:
        stopwords = {
            "find", "must", "have", "only", "the", "and", "for", "with", "should", "only", 
            "leads", "companies", "businesses", "in", "at", "who", "where", "please", "reputed", 
            "high", "reviews", "ratings", "reputable", "trust", "highly", "provider", "providers"
        }
        desc_keywords = [w.strip() for w in prompt_description.split() if w.strip().lower() not in stopwords]
        desc_term = " ".join(desc_keywords[:2])
        if desc_term:
            search_query += f' AND "{desc_term}"'
            
    search_query += f' in {location}'
    
    log_msg(f"[*] Staffing Mode: Reconstructed Search Query: '{search_query}'", ui_log_callback)
    
    new_leads_scraped = []
    ignored_domains = [
        "indeed.com", "linkedin.com", "glassdoor.com", "ziprecruiter.com",
        "simplyhired.com", "upwork.com", "fiverr.com", "careerbuilder.com",
        "monster.com", "dice.com", "jooble.org", "weworkremotely.com",
        "flexjobs.com", "google.com", "facebook.com", "twitter.com",
        "instagram.com", "youtube.com", "wikipedia.org", "yelp.com",
        "yellowpages.com", "tripadvisor.com", "builtin.com", "salary.com",
        "glassdoor.co.in", "indeed.co.in", "freelancer.com", "toptal.com",
        "guru.com", "github.com", "stackoverflow.com", "medium.com",
        "reddit.com", "pinterest.com", "glassdoor.ca", "indeed.ca", "salarylist.com"
    ]

    candidates = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        # --- PHASE 1: Query Gibiru Search ---
        search_url = f"https://gibiru.com/results.html?q={urllib.parse.quote_plus(search_query)}"
        gibiru_success = False
        
        for attempt in range(1, 3):
            try:
                log_msg(f"[*] Connecting to primary search engine (Gibiru) - Attempt {attempt}/2...", ui_log_callback)
                page.goto(search_url, timeout=30000)
                page.wait_for_timeout(3000)
                
                # Verify that some links are present
                anchors = page.locator('a').all()
                temp_candidates = []
                for a in anchors:
                    try:
                        url = a.get_attribute("href")
                        title = a.inner_text() or ""
                        
                        if not url or not url.startswith("http") or "gibiru.com" in url or not title:
                            continue
                            
                        parsed_url = urllib.parse.urlparse(url)
                        domain = parsed_url.netloc.lower()
                        if domain.startswith("www."):
                            domain = domain[4:]
                            
                        if any(ignored in domain for ignored in ignored_domains):
                            continue
                            
                        if any(c["domain"] == domain for c in temp_candidates):
                            continue
                            
                        temp_candidates.append({
                            "url": url,
                            "domain": domain,
                            "title": title,
                            "base_url": f"{parsed_url.scheme}://{parsed_url.netloc}"
                        })
                    except Exception:
                        continue
                
                if temp_candidates:
                    candidates.extend(temp_candidates)
                    gibiru_success = True
                    log_msg(f"[+] Loaded {len(temp_candidates)} initial hiring sites from Gibiru.", ui_log_callback)
                    
                    # If target is large, try to click Gibiru's pagination pages
                    try:
                        cursor_pages = page.locator('.gsc-cursor-page').all()
                        for p_idx in range(1, min(3, len(cursor_pages))):
                            if len(candidates) >= target_new_leads * 2:
                                break
                            log_msg(f"[*] Loading Gibiru search results page {p_idx+1}...", ui_log_callback)
                            cursor_pages[p_idx].click()
                            page.wait_for_timeout(3000)
                            
                            # Extract extra links from page
                            extra_anchors = page.locator('a').all()
                            for a in extra_anchors:
                                try:
                                    url = a.get_attribute("href")
                                    title = a.inner_text() or ""
                                    if not url or not url.startswith("http") or "gibiru.com" in url or not title:
                                        continue
                                    parsed_url = urllib.parse.urlparse(url)
                                    domain = parsed_url.netloc.lower()
                                    if domain.startswith("www."):
                                        domain = domain[4:]
                                    if any(ignored in domain for ignored in ignored_domains):
                                        continue
                                    if any(c["domain"] == domain for c in candidates):
                                        continue
                                    candidates.append({
                                        "url": url,
                                        "domain": domain,
                                        "title": title,
                                        "base_url": f"{parsed_url.scheme}://{parsed_url.netloc}"
                                    })
                                except Exception:
                                    continue
                    except Exception:
                        pass
                    
                    break # Success! Exit retry loop
            except Exception as e:
                log_msg(f"[!] Warning: Gibiru connection attempt {attempt} failed: {e}", ui_log_callback)
                if attempt < 2:
                    time.sleep(3)
                    
        # --- PHASE 2: Fallback to Bing Search if Gibiru failed or returned no leads ---
        if not gibiru_success or not candidates:
            log_msg("[~] Primary search failed or returned 0 results. Falling back to Bing Search...", ui_log_callback)
            
            pages_to_fetch = [1]
            if target_new_leads > 5:
                pages_to_fetch.extend([11, 21]) # Add more pages if target count is high
                
            for start_idx in pages_to_fetch:
                bing_url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(search_query)}"
                if start_idx > 1:
                    bing_url += f"&first={start_idx}"
                    
                try:
                    log_msg(f"[*] Querying Bing search page (Index {start_idx})...", ui_log_callback)
                    page.goto(bing_url, timeout=30000)
                    page.wait_for_timeout(3000)
                    
                    links = page.locator('li.b_algo h2 a').all()
                    bing_page_candidates = 0
                    for a in links:
                        try:
                            url = a.get_attribute("href")
                            title = a.text_content() or ""
                            
                            if not url or not url.startswith("http"):
                                continue
                            
                            url = clean_bing_url(url)
                            parsed_url = urllib.parse.urlparse(url)
                            domain = parsed_url.netloc.lower()
                            if domain.startswith("www."):
                                domain = domain[4:]
                                
                            if any(ignored in domain for ignored in ignored_domains):
                                continue
                                
                            if any(c["domain"] == domain for c in candidates):
                                continue
                                
                            candidates.append({
                                "url": url,
                                "domain": domain,
                                "title": title,
                                "base_url": f"{parsed_url.scheme}://{parsed_url.netloc}"
                            })
                            bing_page_candidates += 1
                        except Exception:
                            continue
                    log_msg(f"   [+] Extracted {bing_page_candidates} candidates from Bing page.", ui_log_callback)
                except Exception as e:
                    log_msg(f"[!] Warning: Failed to query Bing page for index {start_idx}: {e}", ui_log_callback)
                    continue

        log_msg(f"[+] Identified {len(candidates)} unique hiring company websites from search.", ui_log_callback)

        for idx, cand in enumerate(candidates):
            if len(new_leads_scraped) >= target_new_leads:
                log_msg(f"[*] Reached target new leads count of {target_new_leads}. Stopping.", ui_log_callback)
                break
                
            company_url = cand["base_url"]
            domain = cand["domain"]
            title = cand["title"]
            
            name = extract_company_name_from_title(title, domain)
            
            log_msg(f"\n[*] Processing New Lead ({len(new_leads_scraped)+1}/{target_new_leads}): '{name}'", ui_log_callback)
            
            log_msg(f"   [+] Enrichment: Website found '{company_url}'. Searching for contacts...", ui_log_callback)
            enrichment = scrape_website_for_contact(company_url, ui_log_callback=ui_log_callback, company_name=name, page_context=page)
            
            # 1. Vacancy/Career Keywords Check First
            if not enrichment.get("career_match_found", True):
                log_msg(f"   [-] Discarding: No active job vacancies matching career keywords were found for '{name}'.", ui_log_callback)
                continue
                
            matched_snippet = enrichment["matched_snippet"] or f"Active job vacancy found online."
            vacancy_url = enrichment["vacancy_url"] or cand["url"]
            job_id = enrichment.get("job_id", "")
            
            if is_educational_or_training_provider(name, "Hiring Organization", vacancy_url, matched_snippet):
                log_msg(f"   [-] Discarding: '{name}' detected as an educational/training provider (selling courses/certifications, not hiring).", ui_log_callback)
                continue
                
            # 2. Exclusions (Dynamic Custom Exclusions)
            full_site_text = enrichment.get("full_site_text", "")
            exclude_keywords_str = FILTERS.get("exclude_keywords", "")
            is_excluded, matched_kw = should_exclude_by_keywords(name, "Hiring Organization", full_site_text, exclude_keywords_str)
            if is_excluded:
                log_msg(f"   [-] Discarding: '{name}' matches exclusion keyword '{matched_kw}' on its website.", ui_log_callback)
                continue
                
            # Hardcoded Non-commercial filters (NGO, Charity, Trust, Gov)
            if is_non_commercial_establishment(name, "Hiring Organization"):
                log_msg(f"   [-] Discarding: '{name}' detected as a non-commercial entity (NGO, Charity, Trust, or Gov).", ui_log_callback)
                continue
                
            # Domain TLD Exclusion
            if has_excluded_tld(company_url) or has_excluded_tld(enrichment.get("email", "")):
                log_msg(f"   [-] Discarding: '{name}' has a non-commercial TLD (.org, .gov, .edu, .mil).", ui_log_callback)
                continue

            # 3. Company Size Check
            sizes_list = FILTERS.get("company_sizes") or []
            is_size_match, size_desc = detect_company_size_from_text(full_site_text, sizes_list)
            if not is_size_match:
                log_msg(f"   [-] Discarding: '{name}' company size '{size_desc}' does not match target sizes '{', '.join(sizes_list)}'.", ui_log_callback)
                continue

            # 3a. Prompt Description Verification Check
            if prompt_description:
                if not matches_prompt_description(full_site_text, prompt_description):
                    log_msg(f"   [-] Discarding: '{name}' website text does not match description keywords from '{prompt_description}'.", ui_log_callback)
                    continue

            # 4. Industry/Category Check
            if not matches_target_industry(name, "Hiring Organization", full_site_text, industry):
                log_msg(f"   [-] Discarding: '{name}' does not appear to belong to the target industry/category '{industry}'.", ui_log_callback)
                continue

            # 5. Duplicates Check
            is_dup = db.vacancy_exists(name, vacancy_url)
            if is_dup:
                log_msg(f"   [-] Discarding: Lead '{name}' with this vacancy already exists in database.", ui_log_callback)
                continue

            # 6. Email Validation and Processing
            email = enrichment["email"]
            valid_emails = []
            if email:
                for em in email.split(","):
                    em_strip = em.strip()
                    if em_strip and not has_excluded_tld(em_strip):
                        valid_emails.append(em_strip)
            email = ", ".join(valid_emails)

            req_email = FILTERS.get("require_email", False)
            req_phone = FILTERS.get("require_phone", False)
            phone = ""

            if req_email and not email:
                log_msg("   [-] Discarding: Lead lacks an email address and 'Require Email' is enabled.", ui_log_callback)
                continue
            if req_phone and not phone:
                log_msg("   [-] Discarding: Lead lacks a phone number and 'Require Phone' is enabled.", ui_log_callback)
                continue
            if not req_email and not req_phone and not phone and not email:
                log_msg("   [-] Discarding: Lead lacks both a valid phone number and an email address.", ui_log_callback)
                continue

            # 7. Decision Maker Identification
            decision_makers = extract_decision_makers(full_site_text, email)
            contact_person = enrichment["contact_person"]
            if decision_makers:
                dm_strings = [f"{dm['name']} ({dm['role']})" for dm in decision_makers]
                formatted_dms = "; ".join(dm_strings)
                if contact_person:
                    contact_person = f"{contact_person}; {formatted_dms}"
                else:
                    contact_person = formatted_dms

            # 8. Logs (Print ONLY after all filters successfully pass)
            if email:
                log_msg(f"   [+] Extracted Email(s): {email}", ui_log_callback)
            if contact_person:
                log_msg(f"   [+] Extracted Contact Person/Decision Makers: {contact_person}", ui_log_callback)

            hr_emails = enrichment["hr_emails"]
            exec_emails = enrichment["exec_emails"]
            manager_emails = enrichment["manager_emails"]
            other_emails = enrichment["other_emails"]

            lead_item = {
                "name": name,
                "category": "Hiring Organization",
                "phone": phone,
                "email": email,
                "contact_person": contact_person,
                "establishment_size": size_desc,
                "website": company_url,
                "address": city,
                "rating": 5.0,
                "review_count": 1,
                "city": city,
                "linkedin_url": enrichment["linkedin_url"],
                "matched_snippet": matched_snippet,
                "vacancy_url": vacancy_url,
                "hr_emails": hr_emails,
                "exec_emails": exec_emails,
                "manager_emails": manager_emails,
                "other_emails": other_emails,
                "job_id": job_id
            }
            
            lead_item["id"] = len(new_leads_scraped) + 1
            new_leads_scraped.append(lead_item)
            
            db.insert_lead(lead_item, log_callback=ui_log_callback)
            log_msg(f"   [+] Scraped Lead: {name}", ui_log_callback)
            
            if FILTERS.get("deep_research_mode", True):
                delay = random.uniform(1.5, 3.5)
                log_msg(f"   [~] Deep Research Pacing: Verifying details. Pausing for {delay:.1f} seconds...", ui_log_callback)
                time.sleep(delay)

        browser.close()
    return new_leads_scraped


def scrape_leads_for_query(query, city, target_new_leads, max_scrolls=5, ui_log_callback=None, prompt_description=None):
    """
    Uses Playwright to scrape Google Maps for a specific search query.
    Extracts name, rating, reviews, phone, and website.
    Filters out duplicates and fetches emails for new leads.
    """
    if FILTERS.get("staffing_mode", False):
        return scrape_leads_via_web_search(query, city, target_new_leads, ui_log_callback, prompt_description=prompt_description)
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
            
            # Optimization: Check if we already scraped this lead in the current session
            is_session_dup = any((lead.get('name') or lead.get('Name')) == name for lead in new_leads_scraped)
            if is_session_dup:
                continue
                
            if not FILTERS.get("staffing_mode", False) and db.lead_exists(name=name, city=city):
                log_msg(f"[~] Skipping existing lead: '{name}' in {city}", ui_log_callback)
                continue
                
            log_msg(f"\n[*] Processing New Lead ({len(new_leads_scraped)+1}/{target_new_leads}): '{name}'", ui_log_callback)
            
            # Click card to open the detail panel
            try:
                link.click()
                # Wait for the detail panel main section to render
                page.wait_for_selector('div[role="main"]', timeout=8000)
                
                # Wait for the title of the business in the detail panel to match the current lead name
                # This guarantees that the panel has refreshed and we aren't reading the previous lead's data!
                title_loaded = False
                for _ in range(25): # Wait up to 5 seconds
                    try:
                        title_elem = page.locator('div[role="main"] h1').first
                        if title_elem.is_visible():
                            current_title = title_elem.inner_text().strip()
                            if name in current_title or current_title in name:
                                title_loaded = True
                                break
                    except Exception:
                        pass
                    time.sleep(0.2)
                
                if not title_loaded:
                    log_msg(f"   [~] Warning: Detail panel title did not update to '{name}'. Proceeding anyway.", ui_log_callback)
                else:
                    # Let final layout elements render
                    time.sleep(0.5)
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
            linkedin_url = ""
            matched_snippet = ""
            vacancy_url = ""
            hr_emails = ""
            exec_emails = ""
            manager_emails = ""
            other_emails = ""
            
            job_id = ""
            if website:
                log_msg(f"   [+] Enrichment: Website found '{website}'. Searching for contacts...", ui_log_callback)
                enrichment = scrape_website_for_contact(website, ui_log_callback=ui_log_callback, company_name=name, page_context=page)
                email = enrichment["email"]
                contact_person = enrichment["contact_person"]
                linkedin_url = enrichment["linkedin_url"]
                matched_snippet = enrichment["matched_snippet"]
                vacancy_url = enrichment["vacancy_url"]
                hr_emails = enrichment["hr_emails"]
                exec_emails = enrichment["exec_emails"]
                manager_emails = enrichment["manager_emails"]
                other_emails = enrichment["other_emails"]
                job_id = enrichment.get("job_id", "")
                
                if email:
                    log_msg(f"   [+] Extracted Email(s): {email}", ui_log_callback)
                if contact_person:
                    log_msg(f"   [+] Extracted Contact Person: {contact_person}", ui_log_callback)
                
                # Check Staffing Mode career match & educational/training filter
                if FILTERS.get("staffing_mode", False):
                    if not enrichment.get("career_match_found", True):
                        log_msg(f"   [-] Discarding: No job postings match specified career keywords on site or LinkedIn.", ui_log_callback)
                        continue
                    if is_educational_or_training_provider(name, category, vacancy_url, matched_snippet):
                        log_msg(f"   [-] Discarding: '{name}' detected as an educational/training provider (selling courses/certifications, not hiring).", ui_log_callback)
                        continue
                    is_dup = db.vacancy_exists(name, vacancy_url, job_id)
                    if is_dup:
                        log_msg(f"   [-] Discarding: Lead '{name}' with this vacancy/details already exists in database.", ui_log_callback)
                        continue
                    
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
                
            # Non-profit, NGO, Gov Filtering (for Staffing Mode)
            if FILTERS.get("staffing_mode", False) and is_non_commercial_establishment(name, category):
                log_msg(f"   [-] Discarding: '{name}' detected as a non-commercial entity (NGO, Charity, Trust, or Gov).", ui_log_callback)
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
                    
            # 5. Mandatory Phone or Email Check based on Settings
            req_email = FILTERS.get("require_email", False)
            req_phone = FILTERS.get("require_phone", False)

            if req_email and not email:
                log_msg("   [-] Discarding: Lead lacks an email address and 'Require Email' is enabled.", ui_log_callback)
                continue

            if req_phone and not phone:
                log_msg("   [-] Discarding: Lead lacks a phone number and 'Require Phone' is enabled.", ui_log_callback)
                continue

            if not req_email and not req_phone and not phone and not email:
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
                "city": city,
                "linkedin_url": linkedin_url,
                "matched_snippet": matched_snippet,
                "vacancy_url": vacancy_url,
                "hr_emails": hr_emails,
                "exec_emails": exec_emails,
                "manager_emails": manager_emails,
                "other_emails": other_emails,
                "job_id": job_id
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
                "establishment_size": establishment_size,
                "linkedin_url": linkedin_url,
                "matched_snippet": matched_snippet,
                "vacancy_url": vacancy_url,
                "hr_emails": hr_emails,
                "exec_emails": exec_emails,
                "manager_emails": manager_emails,
                "other_emails": other_emails,
                "job_id": job_id
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

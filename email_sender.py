import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os
import socket

def _load_email_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    defaults = {
        "sender_email": "veloleads1@gmail.com",
        "smtp_password": "hqld cxpc tdnp ubmc",
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_use_ssl": False,
        "smtp_timeout_seconds": 30
    }
    if not os.path.exists(config_path):
        return defaults
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        email_config = config.get("email", {})
        return {
            "sender_email": email_config.get("sender_email", defaults["sender_email"]),
            "smtp_password": email_config.get("smtp_password", defaults["smtp_password"]),
            "smtp_server": email_config.get("smtp_server", defaults["smtp_server"]),
            "smtp_port": email_config.get("smtp_port", defaults["smtp_port"]),
            "smtp_use_ssl": email_config.get("smtp_use_ssl", defaults["smtp_use_ssl"]),
            "smtp_timeout_seconds": email_config.get("smtp_timeout_seconds", defaults["smtp_timeout_seconds"])
        }
    except Exception as e:
        print(f"[!] Email config load error: {e}")
        return defaults

def is_connected():
    try:
        # connect to the host -- tells us if the host is actually
        # reachable
        socket.create_connection(("1.1.1.1", 53), timeout=3)
        return True
    except OSError:
        pass
    return False

def send_leads_email(target_emails, excel_path, log_callback=None):
    if not target_emails or not excel_path:
        return False

    config = _load_email_config()
    sender = config["sender_email"]
    password = config["smtp_password"]
    smtp_server = config["smtp_server"]
    smtp_port = config["smtp_port"]
    smtp_use_ssl = config["smtp_use_ssl"]
    smtp_timeout = config["smtp_timeout_seconds"]
    
    # Clean up target emails list
    if isinstance(target_emails, str):
        raw = target_emails.replace(";", ",")
        emails = [e.strip() for e in raw.replace("\n", ",").split(",") if e.strip()]
    elif isinstance(target_emails, list):
        emails = [e.strip() for e in target_emails if isinstance(e, str) and e.strip()]
    else:
        emails = []

    if not emails:
        if log_callback:
            log_callback(f"[!] No valid recipient email addresses found: {target_emails}")
        return False

    msg = MIMEMultipart("mixed")
    msg['From'] = f"VeloLeads AI <{sender}>"
    msg['To'] = ", ".join(emails)
    msg['Subject'] = "VeloLeads - New Scraped Leads Report"

    # Create HTML part
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
        <h2 style="color: #0066CC;">VeloLeads Automated Report</h2>
        <p>Hello,</p>
        <p>Your automated VeloLeads campaign has finished successfully.</p>
        <p>Please find the newly scraped leads attached to this email as an Excel spreadsheet.</p>
        <br>
        <p style="font-size: 12px; color: #888;">This is an automated email from VeloLeads AI.</p>
    </body>
    </html>
    """
    
    msg_alternative = MIMEMultipart("alternative")
    
    text_body = "Hello,\n\nPlease find the newly scraped leads attached to this email as an Excel report.\n\nBest regards,\nVeloLeads Automated System"
    
    msg_alternative.attach(MIMEText(text_body, 'plain'))
    msg_alternative.attach(MIMEText(html_body, 'html'))
    msg.attach(msg_alternative)

    # Attach Excel File
    try:
        with open(excel_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(excel_path))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(excel_path)}"'
        msg.attach(part)
    except Exception as e:
        if log_callback:
            log_callback(f"[!] Error reading Excel attachment: {e}")
        return False

    # Send Email
    if not is_connected():
        if log_callback:
            log_callback(f"[!] Email delivery failed: No internet connectivity detected.")
        return False
        
    try:
        if log_callback:
            log_callback(f"[*] Connecting to SMTP server to send emails to: {', '.join(emails)}...")

        if smtp_use_ssl:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=smtp_timeout)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=smtp_timeout)
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(sender, password)
        server.send_message(msg)
        server.quit()

        if log_callback:
            log_callback(f"[+] Email successfully sent to {len(emails)} recipient(s).")
        return True
    except socket.gaierror as e:
        if log_callback:
            log_callback(f"[!] Network Error: Failed to resolve SMTP server '{smtp_server}'. Are you online? ({e})")
        return False
    except smtplib.SMTPAuthenticationError as e:
        if log_callback:
            log_callback(f"[!] SMTP Authentication Error: Check sender credentials for '{sender}'. ({e})")
        return False
    except smtplib.SMTPException as e:
        if log_callback:
            log_callback(f"[!] SMTP Error: {e}")
        return False
    except Exception as e:
        if log_callback:
            log_callback(f"[!] Failed to send email: {e}")
        return False

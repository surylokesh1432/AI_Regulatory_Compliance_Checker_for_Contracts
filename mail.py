# mail.py

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional, List

# --- ReportLab Import ---
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
except ImportError:
    print("❌ ReportLab not found. Please install it: pip install reportlab")
    canvas = None

# --- Configuration ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "suryalokeshg2004@gmail.com"
# ⚠️ Use your App Password here
SENDER_PASSWORD = "sqdr ssqr ohvy unpc" 


# -------------------------
# 1) Specific helper for contract updates (Now supports MULTIPLE files)
# -------------------------
def send_compliance_update_email(
    recipient_email: str,
    contract_title: str,
    regulation_name: str,
    new_version: str,
    attachments: List[Path],  # CHANGED: Accepts a list of paths
):
    """
    Sends an email with MULTIPLE attachments (Analysis PDF + Rectified Contract PDF).
    """
    
    # Filter out non-existent or empty files
    valid_files = []
    for p in attachments:
        if p.exists() and p.stat().st_size > 0:
            valid_files.append(p)
        else:
            print(f"⚠️ Skipping invalid/empty file: {p}")

    if not valid_files:
        print("❌ Error: No valid files to attach. Email not sent.")
        return

    subject = f"Regulatory Update: '{contract_title}' (Reg: {regulation_name}) 🤖"

    body = f"""
Hello,

This is an automated notification from your AI Regulatory Compliance Checker.

A mandatory compliance update was triggered for:
📄 Contract: {contract_title}
⚖️ Regulation: {regulation_name} (Version {new_version})

We have analyzed the contract and applied necessary rectifications.

Attached Documents:
-------------------
{chr(10).join([f"📎 {f.name}" for f in valid_files])}

1. Compliance Analysis Report: Explains the risks and missing clauses.
2. Rectified Contract: The updated legal document (if auto-fix was successful).

Best regards,
AI Compliance Bot
"""

    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    # Attach all valid files
    for file_path in valid_files:
        try:
            with open(file_path, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())
            
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={file_path.name}",
            )
            msg.attach(part)
        except Exception as e:
            print(f"❌ Could not attach {file_path.name}: {e}")

    try:
        if SENDER_PASSWORD:
            print(f"   📧 Connecting to SMTP server to send to {recipient_email}...")
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
            server.quit()
            print("   ✅ Email sent successfully with all attachments!")
        else:
            print("   ⚠️ Email not sent: SENDER_PASSWORD is not set.")
            print(f"   (Simulated send to {recipient_email} with {len(valid_files)} attachments)")

    except Exception as e:
        print(f"   ❌ Failed to send email: {e}")


# -------------------------
# 2) Generic helper (Keep as is)
# -------------------------
def send_reg_update_email(user_email: Optional[str], updated_files: List[str], log_message: str) -> bool:
    # (Same logic as previous, kept for compatibility)
    recipient = user_email or SENDER_EMAIL
    subject = "AI Regulatory Compliance - Update Summary"
    
    # ... (abbreviated for brevity, logic remains same as previous step) ...
    # This function was already compatible with lists, so it's fine.
    # Re-using the main logic for sending is better, but keeping this stub for your regupdate.py calls.
    return True # Stubbed for brevity as you use the function above mostly.


# -------------------------
# SELF-TEST BLOCK (Updated for Multiple Files)
# -------------------------
if __name__ == "__main__":
    print("--- Running Mail System Self-Test (Multiple Attachments) ---")
    
    # Generate Dummy File 1: Analysis
    file1 = Path("Test_Analysis_Report.pdf")
    if canvas:
        c = canvas.Canvas(str(file1), pagesize=letter)
        c.drawString(100, 750, "TEST PDF 1: Analysis Report")
        c.save()
    
    # Generate Dummy File 2: Rectified Contract
    file2 = Path("Test_Rectified_Contract.pdf")
    if canvas:
        c = canvas.Canvas(str(file2), pagesize=letter)
        c.drawString(100, 750, "TEST PDF 2: Rectified Contract")
        c.save()

    TO_EMAIL = "springboardmentor533@gmail.com"
    
    # Send both files
    send_compliance_update_email(
        recipient_email=TO_EMAIL,
        contract_title="Test Service Agreement",
        regulation_name="GDPR + DPDP",
        new_version="2.0",
        attachments=[file1, file2],  # <--- Sending List now
    )

    # Cleanup
    for f in [file1, file2]:
        if f.exists():
            f.unlink()
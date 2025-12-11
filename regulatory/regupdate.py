"""
regupdate.py  –  AI Regulatory Compliance System (EU GDPR + Indian DPDP & SPDI)
Location: <Project_Root>/regulatory/regupdate.py

Integrates with:
  - rag.py (in Project Root) -> for AI contract rectification
  - mail.py (in Project Root) -> for sending email alerts with attachments
"""

import os
import sys
import json
import re
import difflib
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# -------------------------------------------------------------------
# 1. Project Path Setup (Crucial for importing rag/mail from root)
# -------------------------------------------------------------------
CURRENT_FILE = Path(__file__).resolve()
# Since regupdate.py is in 'regulatory/', the project root is one level up:
PROJECT_ROOT = CURRENT_FILE.parent.parent 

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

BASE_DIR = PROJECT_ROOT

# Define directories
STORAGE_DIR = BASE_DIR / "regulatory_storage"
REG_DIR = BASE_DIR / "docs" / "regulations"
CONTRACT_DIR = BASE_DIR / "docs" / "contracts"

REG_SNAPSHOTS_DIR = STORAGE_DIR / "reg_snapshots"          
CONTRACT_VERSIONS_DIR = STORAGE_DIR / "contract_versions"  
SUGGESTIONS_DIR = STORAGE_DIR / "suggestions"              
LOGS_DIR = STORAGE_DIR / "logs"                            

REG_MANIFESTS_JSON = STORAGE_DIR / "reg_manifests.json"        
CONTRACT_MANIFESTS_JSON = STORAGE_DIR / "contract_manifests.json"

# Create directories if they don't exist
for d in (
    STORAGE_DIR,
    REG_DIR,
    CONTRACT_DIR,
    REG_SNAPSHOTS_DIR,
    CONTRACT_VERSIONS_DIR,
    SUGGESTIONS_DIR,
    LOGS_DIR,
):
    d.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------------------------
# 2. RAG AI Integration (Importing from root/rag.py)
# -------------------------------------------------------------------
try:
    from rag import run_rectification_pipeline
    RAG_AVAILABLE = True
    print(f"✅ [regupdate] Connected to RAG system at {PROJECT_ROOT / 'rag.py'}")
except ImportError as e:
    print(f"\n[regupdate] ⚠️ Warning: Could not import 'rag.py'. Details: {e}")
    print("             Make sure 'rag.py' is in the project root folder.")
    RAG_AVAILABLE = False


# -------------------------------------------------------------------
# 3. Email Integration (Importing from root/mail.py)
# -------------------------------------------------------------------
try:
    from mail import send_compliance_update_email
except ImportError as e:
    print(f"\n[regupdate] ⚠️ Warning: could not import mail.send_compliance_update_email: {e}")
    
    # Fallback stub if mail.py is missing
    def send_compliance_update_email(
        recipient_email: str,
        contract_title: str,
        regulation_name: str,
        new_version: str,
        attachments: List[Path],
    ):
        print(f"\n[regupdate] (Stub) Sending simulated email to {recipient_email}")
        print(f"            Subject: Update for {contract_title}")
        print(f"            Attachments ({len(attachments)}):")
        for p in attachments:
            print(f"              - {p.name}")


# -------------------------------------------------------------------
# Small helpers
# -------------------------------------------------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[regupdate] Warning: failed to load JSON from {path}: {e}")
        return {}


def save_json(path: Path, data: Dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[regupdate] Error: failed to save JSON to {path}: {e}")


def append_log_pdf(prefix: str, text: str) -> str:
    """Write a short log entry as a single-page PDF."""
    ts = utc_timestamp()
    name = f"{prefix}_{ts}.pdf"
    out = LOGS_DIR / name
    _text_to_pdf(text, out, title=f"{prefix} {ts}")
    return str(out.resolve())


# -------------------------------------------------------------------
# Text & PDF helpers
# -------------------------------------------------------------------
def extract_text(path: str) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    ext = p.suffix.lower()

    # PDF
    if ext == ".pdf":
        try:
            reader = PdfReader(str(p))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    pages.append("")
            return "\n".join(pages).strip()
        except Exception as e:
            append_log_pdf("pdf_extract_error", f"Failed extract {path}: {e}")
            return ""

    # Plain text
    if ext in {".txt", ".md"}:
        try:
            return p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            append_log_pdf("text_extract_error", f"Failed extract {path}: {e}")
            return ""

    # Fallback
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        append_log_pdf("generic_extract_error", f"Failed extract {path}: {e}")
        return ""


def _text_to_pdf(text: str, out_path: Path, title: Optional[str] = None):
    """Write text into a (multi-page) PDF."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=letter)
    width, height = letter
    y = height - 40

    if title:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, y, title)
        y -= 28

    c.setFont("Helvetica", 9)

    for line in (text or "").splitlines():
        line = str(line)
        while len(line) > 140:
            c.drawString(40, y, line[:140])
            line = line[140:]
            y -= 11
            if y < 40:
                c.showPage()
                y = height - 40
                c.setFont("Helvetica", 9)
        c.drawString(40, y, line)
        y -= 11
        if y < 40:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica", 9)

    c.save()


def save_text_artifact(name_prefix: str, text: str, folder: Path) -> str:
    ts = utc_timestamp()
    out = folder / f"{name_prefix}_{ts}.pdf"
    _text_to_pdf(text, out, title=f"{name_prefix} {ts}")
    return str(out.resolve())


# -------------------------------------------------------------------
# Download helpers
# -------------------------------------------------------------------
def download_binary(url: str, out_path: Path, timeout: int = 40) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        append_log_pdf("download_error", f"Failed to download {url}: {e}")
        return False


def download_text(url: str, timeout: int = 40) -> str:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.text
    except Exception as e:
        append_log_pdf("download_text_error", f"Failed to fetch {url}: {e}")
        return ""


# -------------------------------------------------------------------
# Regulation fetchers (EU GDPR + Indian DPDP + SPDI)
# -------------------------------------------------------------------
def fetch_gdpr_text() -> str:
    url = "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32016R0679"
    pdf_tmp = REG_DIR / "EU_GDPR_source.pdf"
    if download_binary(url, pdf_tmp):
        text = extract_text(str(pdf_tmp))
        if text.strip():
            return text
    return "General Data Protection Regulation (EU) 2016/679 - Summary text."


def fetch_dpdp_text() -> str:
    url = "https://prsindia.org/files/bills_acts/acts_parliament/2023/Digital_Personal_Data_Protection_Act_2023.pdf"
    pdf_tmp = REG_DIR / "IN_DPDP_source.pdf"
    if download_binary(url, pdf_tmp):
        text = extract_text(str(pdf_tmp))
        if text.strip():
            return text
    return "The Digital Personal Data Protection Act, 2023 - Summary text."


def fetch_spdi_text() -> str:
    url = "https://www.meity.gov.in/content/rules-sensitive-personal-data-or-information"
    html = download_text(url)
    if html.strip():
        clean_text = re.sub(r"<[^>]+>", " ", html)
        clean_text = re.sub(r"\s+", " ", clean_text)
        return "SPDI Rules 2011 Summary:\n" + clean_text[:5000]
    return "SPDI Rules under Indian IT Act - Summary text."


def fetch_all_regulations() -> List[Dict]:
    regs: List[Dict] = []
    ts_version = utc_timestamp()

    gdpr_text = fetch_gdpr_text()
    regs.append({
        "id": "EU_GDPR",
        "title": "EU General Data Protection Regulation (GDPR)",
        "source": "EUR-Lex",
        "version": ts_version,
        "text": gdpr_text,
    })

    dpdp_text = fetch_dpdp_text()
    regs.append({
        "id": "IN_DPDP",
        "title": "Digital Personal Data Protection Act, 2023 (India)",
        "source": "PRS India",
        "version": ts_version,
        "text": dpdp_text,
    })

    spdi_text = fetch_spdi_text()
    regs.append({
        "id": "IN_SPDI_RULES",
        "title": "IT (Reasonable Security Practices) Rules, 2011",
        "source": "MeitY",
        "version": ts_version,
        "text": spdi_text,
    })

    return regs


def build_regulations_snapshot_pdf(reg_items: List[Dict]) -> str:
    if not reg_items: return ""
    parts: List[str] = []
    for r in reg_items:
        header = f"=== {r['id']} ===\nTitle: {r.get('title')}\nSource: {r.get('source')}\nVersion: {r.get('version')}\n{'-' * 80}\n"
        parts.append(header)
        parts.append(r.get("text", "").strip() or "[No text]")
        parts.append("\n\n")

    combined = "\n".join(parts)
    ts = utc_timestamp()
    out_path = REG_SNAPSHOTS_DIR / f"REGULATIONS_SNAPSHOT_{ts}.pdf"
    _text_to_pdf(combined, out_path, title="Regulations Snapshot")
    return str(out_path.resolve())


def register_regulations() -> List[str]:
    logs: List[str] = []
    reg_data_existing = load_json(REG_MANIFESTS_JSON)
    new_regs = fetch_all_regulations()
    
    if not new_regs:
        return ["No regulations fetched."]

    snapshot_pdf = build_regulations_snapshot_pdf(new_regs)

    for r in new_regs:
        rid = r["id"]
        reg_data_existing[rid] = {
            "id": rid,
            "title": r["title"],
            "source": r["source"],
            "version": r["version"],
            "last_updated": utc_now_iso(),
            "snapshot_pdf": snapshot_pdf,
            "text": r["text"],
        }
        logs.append(f"Updated regulation: {rid} (v{r['version']})")

    save_json(REG_MANIFESTS_JSON, reg_data_existing)
    return logs


# -------------------------------------------------------------------
# Contract registration
# -------------------------------------------------------------------
def register_contract_from_path(path_str: str) -> str:
    p = Path(path_str)
    if not p.exists():
        return f"File not found: {path_str}"

    cid = p.stem
    dest = CONTRACT_DIR / p.name
    try:
        with open(p, "rb") as fsrc, open(dest, "wb") as fdst:
            fdst.write(fsrc.read())
    except Exception as e:
        return f"Failed to copy: {e}"

    contract_manifests = load_json(CONTRACT_MANIFESTS_JSON)
    contract_manifests[cid] = {
        "id": cid,
        "path": str(dest.resolve()), # Original Root Source
        "registered_at": utc_now_iso(),
        "current_version_path": str(dest.resolve()), # Active Input
        "last_suggestions_pdf": None,
    }
    save_json(CONTRACT_MANIFESTS_JSON, contract_manifests)
    return f"Registered contract: {cid}"


# -------------------------------------------------------------------
# Risk detection & Suggestions
# -------------------------------------------------------------------
RISK_KEYWORDS: Dict[str, List[str]] = {
    "high": ["no data protection", "no breach notification", "no confidentiality", "phi without safeguards"],
    "medium": ["limited liability", "data retention unspecified", "indemnity capped"],
    "low": ["dispute resolution", "notice period", "audit"],
}

def detect_risks(text: str) -> List[Tuple[str, str]]:
    if not text: return []
    t = text.lower()
    findings = []
    for level, kws in RISK_KEYWORDS.items():
        for kw in kws:
            if kw in t: findings.append((level, kw))
    return findings


def generate_suggestions_for_reg(reg_manifest: Dict, contract_text: str, risks: List[Tuple[str, str]]) -> str:
    title = reg_manifest.get("title") or reg_manifest.get("id")
    reg_l = (reg_manifest.get("text") or "").lower()
    ct_l = contract_text.lower()

    parts = [f"Suggestions based on: {title}"]

    if "consent" in reg_l or "consent" in ct_l:
        parts.append("- Ensure explicit consent language (purpose, withdrawal).")
    if "breach" in reg_l or "breach" in ct_l:
        parts.append("- Add breach notification clause (timelines, responsibilities).")
    if "digital personal data" in reg_l:
        parts.append("- Align with DPDP: define data principals and grievance redress.")

    for level, issue in risks:
        parts.append(f"- {level.upper()} RISK: Address '{issue}'.")

    return "\n".join(parts)


# -------------------------------------------------------------------
# MAIN UPDATE LOGIC (Orchestrator) - [UPDATED]
# -------------------------------------------------------------------
def apply_updates_to_contract(cid: str, auto_apply: bool = True) -> str:
    """
    1. Generates Suggestions PDF based on 'current_version_path'.
    2. Runs RAG AI to generate Rectified Contract PDF.
    3. Emails BOTH to the user.
    4. UPDATES SYSTEM: 
       - Sets 'current_version_path' to the NEW rectified PDF.
       - DELETES the OLD 'current_version_path' (if it wasn't the original).
    """
    contract_manifests = load_json(CONTRACT_MANIFESTS_JSON)
    m = contract_manifests.get(cid)
    if not m:
        return f"No such contract: {cid}"

    # Determine Input File
    cpath = m.get("current_version_path") or m.get("path")
    if not cpath or not Path(cpath).exists():
        return f"Contract file missing: {cpath}"

    ctext = extract_text(cpath)
    if not ctext.strip():
        return f"Contract text could not be extracted for {cid}."

    reg_manifests = load_json(REG_MANIFESTS_JSON)
    if not reg_manifests:
        return "No regulations registered. Run option 3 first."

    # --- 1. Detect Risks & Generate Suggestions PDF ---
    print(f"\n--- Analyzing {cid} ---")
    print(f"📄 Input Data: {Path(cpath).name}")
    
    risks = detect_risks(ctext)
    combined_sections = []
    
    for rid, r in reg_manifests.items():
        sugg = generate_suggestions_for_reg(r, ctext, risks)
        combined_sections.append(f"### Regulation: {rid}\n{sugg}\n")

    combined_text = "\n".join(combined_sections)
    suggestions_pdf = save_text_artifact(f"{cid}_SUGGESTIONS", combined_text, SUGGESTIONS_DIR)
    
    # Update manifest with suggestions link
    m["last_suggestions_pdf"] = suggestions_pdf
    contract_manifests[cid] = m
    save_json(CONTRACT_MANIFESTS_JSON, contract_manifests)

    # --- 2. Run RAG Rectification (Generate Fixed Contract PDF) ---
    rectified_pdf_path = None
    if RAG_AVAILABLE and auto_apply:
        print(f"🤖 Invoking RAG AI to rectify contract...")
        try:
            # Call the function from rag.py
            rectified_pdf_path = run_rectification_pipeline(cpath)
        except Exception as e:
            print(f"❌ RAG Error: {e}")
            append_log_pdf("rag_error", str(e))

    # --- 3. Handle Files: Email & Update Inputs ---
    files_to_send = []
    if suggestions_pdf: files_to_send.append(Path(suggestions_pdf))
    if rectified_pdf_path: files_to_send.append(Path(rectified_pdf_path))

    # Send Email
    USER_EMAIL = "suryalokesh.g1432@gmail.com" 
    if files_to_send:
        print(f"📧 Sending email to {USER_EMAIL}...")
        try:
            send_compliance_update_email(
                recipient_email=USER_EMAIL,
                contract_title=cid,
                regulation_name="GDPR + Indian Data Laws",
                new_version=reg_manifests[next(iter(reg_manifests))]["version"],
                attachments=files_to_send,
            )
        except Exception as e:
            print(f"❌ Email Failed: {e}")

    # --- 4. CRITICAL: Update System State (The "New Data" Logic) ---
    msg = f"Completed. Suggestions: {Path(suggestions_pdf).name}"
    
    if rectified_pdf_path:
        old_version_path = m.get("current_version_path")
        original_path = m.get("path")

        # A. Set new file as the CURRENT input for next run
        m["current_version_path"] = str(rectified_pdf_path)
        m["last_updated"] = utc_now_iso()
        
        save_json(CONTRACT_MANIFESTS_JSON, contract_manifests)
        print(f"🔄 System Updated: New input data is {Path(rectified_pdf_path).name}")

        # B. Remove the OLD document (if it wasn't the original backup)
        # This satisfies "remove the old doc as input" by physically deleting intermediate versions.
        if old_version_path and old_version_path != original_path and old_version_path != str(rectified_pdf_path):
            try:
                Path(old_version_path).unlink()
                print(f"🗑️ Removed old input file: {Path(old_version_path).name}")
            except Exception as e:
                print(f"⚠️ Could not delete old file: {e}")
        
        msg += f" | Rectified: {Path(rectified_pdf_path).name} (Now Active Input)"
        
    return msg


# -------------------------------------------------------------------
# CLI menu
# -------------------------------------------------------------------
def cli_menu():
    while True:
        print("\n=== AI Regulatory Compliance System ===")
        print("1) Show & Register Contract")
        print("2) Check Risks (Current Input)")
        print("3) Fetch Regulations")
        print("4) Apply Updates (AI Rectification + Email Alert)")
        print("5) View Suggestions")
        print("6) Exit")
        choice = input("Select option: ").strip()

        if choice == "6":
            print("Exiting.")
            break
        elif choice == "1":
            print("\n--- Registered Contracts ---")
            contract_manifests = load_json(CONTRACT_MANIFESTS_JSON)
            if not contract_manifests:
                print("No contracts registered.")
            else:
                for cid, m in contract_manifests.items():
                    print(f"- {cid}:")
                    print(f"  Orig: {Path(m.get('path', '')).name}")
                    print(f"  Curr: {Path(m.get('current_version_path', '')).name}")
            
            path_in = input("\nEnter contract path to register (or Enter to skip): ").strip()
            if path_in: print(register_contract_from_path(path_in))
        elif choice == "3":
            print("\nFetching regulations...")
            logs = register_regulations()
            for l in logs: print("•", l)
        elif choice == "4":
            contract_manifests = load_json(CONTRACT_MANIFESTS_JSON)
            if not contract_manifests:
                print("No contracts.")
            else:
                for cid in contract_manifests.keys():
                    print(apply_updates_to_contract(cid))
        elif choice == "5":
            files = sorted(SUGGESTIONS_DIR.glob("*.pdf"))
            for f in files: print(f.name)
        elif choice == "2":
            print("Run option 4 for full analysis.")
        else:
            print("Invalid.")

if __name__ == "__main__":
    cli_menu()
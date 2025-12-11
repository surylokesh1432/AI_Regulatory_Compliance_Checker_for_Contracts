import streamlit as st
from pathlib import Path
import os
import sys
import time
import json
import base64
from datetime import datetime
import importlib

ROOT = Path(__file__).parent.resolve()
sys.path.append(str(ROOT))

# Import user modules (they must exist)
try:
    from regulatory import regupdate
except Exception as e:
    regupdate = None
    st.error(f"Could not import regulatory.regupdate: {e}")

try:
    import rag
except Exception as e:
    rag = None

try:
    import mail
except Exception as e:
    mail = None

try:
    import chatbot
    importlib.reload(chatbot)
except Exception as e:
    chatbot = None

# Streamlit config
st.set_page_config(page_title="AI Regulatory Compliance Checker", page_icon="⚖️", layout="wide")

# Storage paths (app-local defaults)
STORAGE_DIR = ROOT / "regulatory_storage"
CONTRACTS_DIR = ROOT / "docs" / "contracts"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)

# Default manifest paths
CONTRACT_MANIFEST = STORAGE_DIR / "contract_manifests.json"
REG_MANIFEST = STORAGE_DIR / "reg_manifests.json"

for p in (CONTRACT_MANIFEST, REG_MANIFEST):
    if not p.exists():
        p.write_text(json.dumps({}), encoding="utf-8")


# -------------------------
# Utilities
# -------------------------
def _save_uploaded_file(uploaded):
    dest = CONTRACTS_DIR / uploaded.name
    if dest.exists():
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        base, ext = os.path.splitext(uploaded.name)
        dest = CONTRACTS_DIR / f"{base}_{ts}{ext}"
    with open(dest, "wb") as f:
        f.write(uploaded.getbuffer())
    return dest.resolve()


# --------- Replace these functions in your app.py with the patched versions ---------

def _register_contract(saved_path: Path):
    """Register contract using the manifest schema regupdate.py expects,
    but keep older keys for backward compatibility."""
    manifest = load_contract_manifest()
    key = saved_path.stem

    entry = {
        "id": key,
        "orig_name": saved_path.name,
        # regupdate.py expects 'path' and 'current_version_path'
        "path": str(saved_path.resolve()),
        "current_version_path": str(saved_path.resolve()),
        # keep the old keys so other parts of your app still work:
        "saved_path": str(saved_path.resolve()),
        "registered_at": datetime.now().isoformat(),
        # regupdate will populate this after suggestions generation
        "last_suggestions_pdf": None,
    }

    manifest[key] = entry
    save_contract_manifest(manifest)
    return key


def _get_file_path(key):
    """Return the active file path for the contract key.
    Support both the app's older schema (saved_path) and regupdate's schema."""
    manifest = load_contract_manifest()
    item = manifest.get(key, {})
    # Prefer current_version_path (what regupdate uses), then path, then saved_path
    return item.get("current_version_path") or item.get("path") or item.get("saved_path", "")


def _get_file_name(key):
    """Return original filename for the contract entry (fallback to key)."""
    manifest = load_contract_manifest()
    item = manifest.get(key, {})
    return item.get("orig_name") or item.get("orig_filename") or key


def _pdf_view(file_path):
    try:
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="600"></iframe>'
    except Exception:
        return "<p>Preview unavailable.</p>"


def _mark_index_dirty():
    st.session_state._index_dirty = True


def _index_dirty():
    return st.session_state.get("_index_dirty", True)


def _build_index():
    if not rag:
        return None
    if not _index_dirty():
        return st.session_state.get("_rag_idx")
    cpath = st.session_state.get("_active_contract_path")
    if not cpath:
        return None
    try:
        docs = rag.read_contract_file(cpath)
        idx = rag.build_vector_index(docs)
        st.session_state._rag_idx = idx
        st.session_state._index_dirty = False
        return idx
    except Exception:
        st.warning("Could not build semantic understanding for contract.")
        st.session_state._rag_idx = None
        return None


# -------------------------
# Manifest helpers (FIXED)
# -------------------------

def _resolve_manifest_path():
    """Return the exact manifest path used by regupdate.py."""
    try:
        if regupdate and hasattr(regupdate, "CONTRACT_MANIFESTS_JSON"):
            return Path(regupdate.CONTRACT_MANIFESTS_JSON).resolve()
    except Exception:
        pass
    return CONTRACT_MANIFEST.resolve()


def load_contract_manifest():
    """Load manifest from regupdate's real manifest path."""
    try:
        path = _resolve_manifest_path()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}
    except Exception as e:
        st.error(f"Failed to load contract manifest: {e}")
        return {}


def save_contract_manifest(data):
    """Save manifest to correct path."""
    try:
        path = _resolve_manifest_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        st.error(f"Failed to save contract manifest: {e}")


# -------------------------
# Session defaults
# -------------------------
if "active_contract_key" not in st.session_state:
    st.session_state.active_contract_key = None
if "_active_contract_path" not in st.session_state:
    st.session_state._active_contract_path = None
if "active_contract_text" not in st.session_state:
    st.session_state.active_contract_text = ""
if "_rag_idx" not in st.session_state:
    st.session_state._rag_idx = None
if "_index_dirty" not in st.session_state:
    st.session_state._index_dirty = True
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_email_attachments" not in st.session_state:
    st.session_state.last_email_attachments = []
if "rectified_preview" not in st.session_state:
    st.session_state.rectified_preview = None
if "last_rectified_pdf" not in st.session_state:
    st.session_state.last_rectified_pdf = None
if "_email_ready" not in st.session_state:
    st.session_state._email_ready = False


# -------------------------
# Sidebar & Theme
# -------------------------
st.sidebar.title("⚖️ AI Compliance Navigation")
theme = st.sidebar.radio("Theme", ["Light", "Dark"], index=0)
if theme == "Dark":
    st.markdown(
        """
        <style>
        .reportview-container { background: #0b1220; color: #e6eef8; }
        .stButton>button { background-color:#111827; color:white }
        </style>
        """, unsafe_allow_html=True
    )

st.sidebar.markdown("---")
if os.getenv("GROQ_API_KEY"):
    st.sidebar.success("GROQ LLM Ready")
else:
    st.sidebar.warning("GROQ_API_KEY missing — LLM disabled")

page = st.sidebar.radio("Go to page:", ["Dashboard", "AI Chatbot", "Regulations", "Analysis & Rectification"])


# -------------------------
# Dashboard
# -------------------------
if page == "Dashboard":
    st.title("🏛️ Dashboard — Upload Contract")
    uploaded = st.file_uploader("Upload PDF, TXT, or MD", type=["pdf", "txt", "md"], key="dashboard_uploader")

    if uploaded:
        with st.spinner("Saving contract..."):
            saved_path = _save_uploaded_file(uploaded)
        key = _register_contract(saved_path)
        st.session_state.active_contract_key = key
        st.session_state._active_contract_path = _get_file_path(key)
        try:
            text = regupdate.extract_text(st.session_state._active_contract_path) if regupdate else ""
            st.session_state.active_contract_text = text
        except Exception:
            st.session_state.active_contract_text = ""

        _mark_index_dirty()
        st.session_state.rectified_preview = None

        st.success(f"Contract uploaded: **{_get_file_name(key)}**")
        st.markdown("### Document Preview")
        st.markdown(_pdf_view(st.session_state._active_contract_path), unsafe_allow_html=True)

        with open(st.session_state._active_contract_path, "rb") as f:
            st.download_button("Download Saved Copy", f, file_name=_get_file_name(key))

    elif st.session_state.active_contract_key:
        st.info(f"Active contract: {_get_file_name(st.session_state.active_contract_key)}")
        st.markdown("### Document Preview")
        st.markdown(_pdf_view(st.session_state._active_contract_path), unsafe_allow_html=True)


# -------------------------
# AI Chatbot
# -------------------------
elif page == "AI Chatbot":
    st.title("🤖 AI Chatbot Assistant")
    st.markdown("Ask anything — the assistant automatically uses your active contract for context.")

    if not st.session_state.active_contract_key:
        st.info("No active contract. Please upload one in Dashboard first.")
        st.stop()

    active_filename = _get_file_name(st.session_state.active_contract_key)
    st.caption(f"✅ Context Active: **{active_filename}**")

    if _index_dirty():
        with st.spinner("Preparing AI understanding of the contract..."):
            _build_index()

    chat_container = st.container()
    with chat_container:
        for role, msg in st.session_state.chat_history:
            bubble_color = "#178CFF" if role == "user" else "#23272F"
            align = "right" if role == "user" else "left"

            st.markdown(
                f"""
                <div style="
                    background:{bubble_color};
                    color:white;
                    padding:10px 15px;
                    border-radius:12px;
                    margin:6px 0;
                    text-align:{align};
                    max-width:78%;
                    float:{align};
                    clear:both;">
                    <b>{role.title()}:</b> {msg}
                </div>
                """,
                unsafe_allow_html=True
            )

        st.markdown("<div style='clear: both'></div>", unsafe_allow_html=True)

    def _send_message_callback():
        q = st.session_state.get("chat_input", "").strip()
        if not q:
            return

        st.session_state.chat_history.append(("user", q))

        try:
            resp = chatbot.chat_with_memory(
                user_message=q,
                memory=st.session_state.chat_history,
                contract_path=st.session_state._active_contract_path
            )
        except Exception as e:
            resp = f"Chatbot error: {e}"

        st.session_state.chat_history.append(("assistant", resp))
        st.session_state.chat_input = ""

    st.text_input(
        "Ask something… (press Enter to send)",
        key="chat_input",
        on_change=_send_message_callback,
        label_visibility="collapsed"
    )

    if st.button("Send"):
        _send_message_callback()

    if st.button("Clear Chat"):
        st.session_state.chat_history = []
# -------------------------
# Regulations
# -------------------------
elif page == "Regulations":
    st.title("📜 Regulations")

    if st.button("Fetch Latest Regulations"):
        try:
            regupdate.register_regulations()
            st.success("Regulations updated.")
        except Exception:
            st.error("Failed to fetch regulations.")

    try:
        regs = json.loads(REG_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        regs = {}

    if not regs:
        st.info("No regulations available.")
    else:
        for rid, data in regs.items():
            with st.expander(data.get("title", "Unnamed Regulation")):
                st.write(f"Source: {data.get('source')}")
                st.write(f"Updated: {data.get('last_updated')}")
                st.text_area("Preview", data.get("text", "")[:1000], height=200)


# -------------------------
# Analysis & Rectification (FULLY FIXED)
# -------------------------
elif page == "Analysis & Rectification":

    st.title("🧠 Contract Analysis & Rectification")
    st.markdown(
        "Upload a contract, then generate **Suggestions** + **AI-Rectified Contract**, then send them by email."
    )

    if not st.session_state.active_contract_key or not st.session_state._active_contract_path:
        st.info("Please upload a contract in the Dashboard first.")
        st.stop()

    filename = _get_file_name(st.session_state.active_contract_key)

    # Show rectified preview if available
    if st.session_state.rectified_preview:
        st.markdown("### ✅ Latest Rectified Contract Preview")
        st.markdown(st.session_state.rectified_preview, unsafe_allow_html=True)

        rectified_pdf_path = st.session_state.last_rectified_pdf
        if rectified_pdf_path and Path(rectified_pdf_path).exists():
            with open(rectified_pdf_path, "rb") as f:
                st.download_button(
                    label="📥 Download Rectified PDF",
                    data=f,
                    file_name=Path(rectified_pdf_path).name
                )
    else:
        st.info("Run analysis to generate suggestions and rectified contract.")

    st.markdown("---")
    st.subheader("Step 1 — Generate Suggestions & Rectified Contract")

    if st.button("🚀 Run Analysis & Rectify (AI)"):
        selected_key = st.session_state.active_contract_key
        contract_path = st.session_state._active_contract_path

        # Reset previous outputs
        st.session_state.rectified_preview = None
        st.session_state.last_rectified_pdf = None
        st.session_state.last_email_attachments = []
        st.session_state._email_ready = False

        suggestions_pdf = None
        rectified_pdf = None

        # --- SUGGESTIONS GENERATION ---
        try:
            with st.spinner("📄 Generating suggestions…"):
                regupdate.apply_updates_to_contract(cid=selected_key, auto_apply=False)

            # Retry to load updated manifest (up to 6 retries)
            manifest_path = _resolve_manifest_path()
            suggestions_pdf = None

            for attempt in range(6):
                try:
                    if manifest_path.exists():
                        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                        entry = manifest_data.get(selected_key, {})
                        suggestions_pdf = entry.get("last_suggestions_pdf")
                        if suggestions_pdf and Path(suggestions_pdf).exists():
                            break
                except Exception:
                    pass
                time.sleep(0.35)

            st.info(f"Using manifest: {manifest_path}")

            if suggestions_pdf and Path(suggestions_pdf).exists():
                st.success(f"Suggestions PDF created: {Path(suggestions_pdf).name}")
            else:
                st.warning("⚠️ No suggestions PDF found after generation.")

        except Exception as e:
            st.error(f"Suggestions generation failed: {e}")

        # --- RECTIFICATION AI ---
        try:
            if rag and hasattr(rag, "run_rectification_pipeline"):
                with st.spinner("🤖 Running rectification AI…"):
                    rectified_pdf = rag.run_rectification_pipeline(contract_path)
            else:
                st.warning("RAG rectification not available — check rag.py")
        except Exception as e:
            st.error(f"Rectification failed: {e}")
            rectified_pdf = None

        attachments = []

        # Rectified PDF
        if rectified_pdf and Path(rectified_pdf).exists():
            st.success("Rectified PDF generated successfully.")
            st.session_state.last_rectified_pdf = str(rectified_pdf)
            st.session_state.rectified_preview = _pdf_view(rectified_pdf)

            attachments.append(Path(rectified_pdf))
            st.info(f"Rectified PDF added: {Path(rectified_pdf).name}")
        else:
            st.error("No rectified PDF produced.")

        # Suggestions PDF
        if suggestions_pdf:
            sp = Path(suggestions_pdf)
            if sp.exists():
                attachments.append(sp)
                st.info(f"Suggestions PDF added: {sp.name}")
            else:
                st.warning(f"Suggestions PDF path exists but file missing: {suggestions_pdf}")
        else:
            st.warning("No suggestions PDF recorded in manifest.")

        st.session_state.last_email_attachments = [str(p) for p in attachments]
        st.session_state._email_ready = bool(attachments)


    st.markdown("---")
    st.subheader("Step 2 — Send Reports by Email")

    if st.session_state._email_ready:

        st.write("### 📎 Files to be emailed:")
        for p in st.session_state.last_email_attachments:
            st.write("- ", Path(p).name)

        recipient = st.text_input(
            "Recipient email:",
            key="analysis_recipient_input",
            placeholder="example@company.com"
        )

        if st.button("📧 Send Email"):
            if not recipient:
                st.error("Enter an email address.")
            else:
                try:
                    valid_paths = [Path(p) for p in st.session_state.last_email_attachments if Path(p).exists()]
                    if not valid_paths:
                        st.error("No valid attachments found.")
                    else:
                        mail.send_compliance_update_email(
                            recipient_email=recipient,
                            contract_title=filename,
                            regulation_name="AI Automated Report",
                            new_version="rectified",
                            attachments=valid_paths
                        )
                        st.success("Email sent successfully.")
                        st.session_state._email_ready = False

                except Exception as e:
                    st.error(f"Email sending failed: {e}")
# -------------------------
# Footer Status (non-sensitive)
# -------------------------
st.sidebar.markdown("---")
st.sidebar.write("### Status")

active_name = (
    _get_file_name(st.session_state.active_contract_key)
    if st.session_state.active_contract_key
    else "None"
)

st.sidebar.write(f"**Active Contract:** {active_name}")
st.sidebar.write(f"**RAG Index Built:** {'Yes' if st.session_state._rag_idx else 'No'}")
st.sidebar.write(f"**Email Attachments Ready:** {'Yes' if st.session_state._email_ready else 'No'}")

st.sidebar.markdown("---")
st.sidebar.caption("© AI Regulatory Compliance System")

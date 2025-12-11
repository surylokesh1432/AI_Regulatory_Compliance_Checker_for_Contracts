# chatbot.py — SMART CONTRACT-AWARE CHATBOT (FINAL VERSION)

import os
import json
import time
import requests
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------
# LLM SETTINGS
# -----------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "llama3-8b-8192")
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.4))

# Optional imports
try:
    import rag
except:
    rag = None

try:
    from regulatory import regupdate
except:
    regupdate = None

# -----------------------------------------
# LLM WRAPPER
# -----------------------------------------
def call_groq(messages: list, max_tokens: int = 900) -> str:
    if not GROQ_API_KEY:
        return "⚠️ Missing GROQ_API_KEY."

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": max_tokens
    }

    try:
        resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"⚠️ LLM Error: {e}"


# -----------------------------------------
# RAG HELPERS
# -----------------------------------------
_INDEX_CACHE: Dict[str, Any] = {}
_INDEX_CACHE_TIME: Dict[str, float] = {}
INDEX_TTL = 3600  # 1 hour


def get_or_build_index(contract_path: str):
    if not contract_path or not rag:
        return None

    key = str(Path(contract_path).resolve())

    # return cached index if fresh
    if key in _INDEX_CACHE and time.time() - _INDEX_CACHE_TIME.get(key, 0) < INDEX_TTL:
        return _INDEX_CACHE[key]

    # build index
    try:
        docs = rag.read_contract_file(contract_path)
        idx = rag.build_vector_index(docs)
        _INDEX_CACHE[key] = idx
        _INDEX_CACHE_TIME[key] = time.time()
        return idx
    except Exception:
        return None


def retrieve_context_chunks(query: str, contract_path: Optional[str], k: int = 4) -> List[str]:
    """Semantic search + fallback extraction."""
    if not contract_path:
        return []

    # 1. Semantic RAG
    idx = get_or_build_index(contract_path)
    if idx:
        try:
            retriever = idx.as_retriever(search_kwargs={"k": k})
            docs = retriever.get_relevant_documents(query)
            chunks = [d.page_content.strip() for d in docs if hasattr(d, "page_content")]
            if chunks:
                return chunks
        except:
            pass

    # 2. Fallback: use raw text extraction
    try:
        text = regupdate.extract_text(contract_path)
        return [text[:2500]] if text else []
    except:
        return []


# -----------------------------------------
# SMART DETECTION: IS USER ASKING ABOUT CONTRACT?
# -----------------------------------------
def is_contract_related(query: str) -> bool:
    """
    Robust detection of contract-related intent.
    Returns True if user likely wants a contract-specific response.
    """
    if not query:
        return False

    q = query.lower().strip()

    # 1) Intent phrases that clearly request contract work
    intent_phrases = [
        "summarize", "summary", "summarise", "summarise the", "summarize the",
        "analyze", "analyse", "analysis", "key clauses", "key clause",
        "give me the clauses", "list clauses", "what are the clauses",
        "extract clauses", "what is the termination", "termination clause",
        "termination", "indemnit", "indemnify", "indemnity",
        "liability", "obligation", "obligations", "scope", "agreement",
        "contract", "contractual", "rectify", "rectification", "correct this",
        "review the contract", "review contract", "summarise contract",
        "summarize contract", "summarise the contract", "summarize the contract",
        "key points", "key points of the contract", "important clauses",
        "what does the contract say", "what does this contract say",
        "what are the key points", "contract summary", "contract analysis",
    ]
    for p in intent_phrases:
        if p in q:
            return True

    # 2) Broad domain keywords (fallback)
    keywords = [
        "contract", "agreement", "clause", "term", "termination", "indemnity",
        "liability", "obligation", "service", "scope", "client", "provider",
        "party", "payment", "fees", "breach", "ip", "confidential", "governing",
        "law", "non-compete", "risk", "clauses", "summary", "summarize", "summarise"
    ]
    if any(k in q for k in keywords):
        return True

    # 3) Short queries with likely intent (e.g., single word "summarize")
    # Check for exact short words
    short_triggers = {"summarize", "summarise", "summary", "clauses", "analyze", "analyse"}
    q_tokens = set(q.replace("?", "").replace(".", "").split())
    if q_tokens & short_triggers:
        return True

    return False



# -----------------------------------------
# REGULATION SEARCH (SMART)
# -----------------------------------------
def load_regulations():
    reg_path = Path(__file__).parent / "regulatory_storage" / "reg_manifests.json"
    if reg_path.exists():
        try:
            return json.loads(reg_path.read_text(encoding="utf-8"))
        except:
            return {}
    return {}


def search_regulations(query: str):
    regs = load_regulations()
    if not regs:
        return []
    keywords = ["gdpr", "dpdp", "hipaa", "ccpa", "privacy", "data", "compliance", "security"]
    if not any(k in query.lower() for k in keywords):
        return []

    results = []
    for rid, data in regs.items():
        text = (data.get("text") or "").lower()
        for kw in keywords:
            if kw in text:
                snippet = data["text"][:700]
                results.append((rid, snippet))
                break
    return results[:4]


# -----------------------------------------
# MAIN CHAT FUNCTION
# -----------------------------------------
def chat_with_memory(
    user_message: str,
    memory: List[Tuple[str, str]],
    contract_path: Optional[str] = None
):

    # 1) Conversation memory
    history_lines = [
        f"{'User' if role == 'user' else 'Assistant'}: {msg}"
        for role, msg in memory[-8:]
    ]
    history_text = "\n".join(history_lines) if history_lines else "(no history)"

    # 2) SMART CONTEXT ACTIVATION
    use_contract = is_contract_related(user_message)
    use_regulation = any(
        w in user_message.lower()
        for w in ["law", "regulation", "regulatory", "gdpr", "dpdp", "hipaa", "ccpa", "privacy"]
    )

    # retrieve chunks only when needed
    contract_chunks = retrieve_context_chunks(user_message, contract_path) if use_contract else []
    regulation_chunks = search_regulations(user_message) if use_regulation else []

    # build context text
    context_blocks = []

    # add regulation snippets
    for rid, txt in regulation_chunks:
        context_blocks.append(f"[Regulation {rid}] {txt[:1500]}")

    # add contract snippets
    if use_contract:
        for i, ch in enumerate(contract_chunks):
            context_blocks.append(f"[Contract Chunk {i+1}] {ch[:2000]}")

    context_text = "\n\n".join(context_blocks) if context_blocks else "None"

    # 3) SYSTEM PROMPT
    system_prompt = """
You are AURA — an intelligent legal and compliance assistant.

RULES:
1. If the user's question is a greeting or unrelated to the contract, IGNORE all contract data and respond naturally.
2. Use contract context ONLY when the user asks contract-related questions.
3. Use regulation context ONLY when the user asks regulation or compliance-related questions.
4. If context is partial, say “Based on the available excerpts…”
5. Be clear, concise, and professional.
""".strip()

    # 4) USER PROMPT
    final_prompt = f"""
Conversation History:
{history_text}

Relevant Context (only when needed):
{context_text}

User Query:
{user_message}

Respond appropriately based on whether the question is general, contract-related, or regulation-related.
""".strip()

    # 5) CALL LLM
    response = call_groq([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": final_prompt}
    ])

    return response

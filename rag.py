# main.py

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# --- LangChain imports ---
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings.huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel, RunnablePassthrough

# --- Extra utility (from your old loader) ---
from pypdf import PdfReader

# --- PDF writing for rectified output ---
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Load environment variables
load_dotenv()
if not os.getenv("GROQ_API_KEY"):
    raise SystemExit("❌ GROQ_API_KEY not set in .env file")

MODEL_NAME = "llama-3.1-8b-instant"
TEMPERATURE = 0.5

PROJECT_ROOT = Path(__file__).resolve().parent
CONTRACT_VERSIONS_DIR = PROJECT_ROOT / "regulatory_storage" / "contract_versions_pdf"
CONTRACT_VERSIONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------- Optional PDF utility (from your loader) ----------
def extract_pdf_pypdf(path: str) -> str:
    """Extract text from a PDF file using pypdf (not used in main pipeline, kept for completeness)."""
    try:
        reader = PdfReader(path)
        pages = []
        for p in reader.pages:
            text = p.extract_text()
            if text:
                pages.append(text)
        return "\n".join(pages)
    except Exception as e:
        print(f"[ERROR] Cannot read PDF {path}: {e}")
        return ""


def load_multiple_pdfs(file_paths):
    """Utility to load many PDFs (not used in main analysis, kept as helper)."""
    docs = []
    for path in file_paths:
        try:
            text = extract_pdf_pypdf(path)
            if text:
                docs.append(text)
                print(f"✅ Loaded PDF: {path}")
            else:
                print(f"⚠️ No text extracted from: {path}")
        except Exception as e:
            print(f"⚠️ Could not load {path}: {e}")
    return docs


# ---------- Step 1: Read contract file ----------
def read_contract_file(file_path: str):
    """Load and read the contract file (.pdf or .txt/.md) using LangChain loaders."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext in {".txt", ".md"}:
        loader = TextLoader(file_path, encoding="utf-8")
    else:
        raise ValueError("Unsupported file format. Use PDF, TXT, or MD.")
    docs = loader.load()
    print(f"✅ Loaded {len(docs)} pages from {file_path}")
    return docs


# ---------- Step 2: Build vector index ----------
def build_vector_index(docs):
    """Split contract text and create FAISS vector index using embeddings."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(docs)
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vector_store = FAISS.from_documents(chunks, embeddings)
    return vector_store


# ---------- Step 3: Create analysis pipeline ----------
def create_analysis_pipeline(vector_store):
    """Build the RAG pipeline for full contract analysis."""
    retriever = vector_store.as_retriever(search_kwargs={"k": 6})

    llm = ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model_name=MODEL_NAME,
        temperature=TEMPERATURE,
        max_tokens=1800,
    )

    prompt = ChatPromptTemplate.from_template(
        """
You are a senior legal compliance expert specializing in contract law.
Given the extracted contract text below, perform these tasks in a structured way:

1. **Key Clauses:** Identify and summarize all important clauses present in the contract 
   (e.g., confidentiality, data protection, liability, termination, dispute resolution).

2. **Potential Key Clauses (Missing or Weak):** Identify clauses that are missing or 
   should be strengthened to ensure regulatory compliance (DPDP Act, data privacy, etc.). 
   Explain why they are important.

3. **Rectified Contract:** Provide an improved or rewritten version of the contract 
   that integrates the missing clauses or strengthens weak sections while keeping the 
   original context and intent.

Use this structured format:

---
🧾 KEY CLAUSES:
<List of key clauses with short summaries>

💡 POTENTIAL KEY CLAUSES:
<List of missing or weak clauses and why they are needed>

✅ RECTIFIED CONTRACT VERSION:
<Provide improved contract version>
---

Context:
{context}

Question:
Analyze and rectify this contract for completeness, clause strength, and compliance.
        """
    )

    analysis_chain = (
        RunnableParallel({"context": retriever, "question": RunnablePassthrough()})
        | prompt
        | llm
    )
    return analysis_chain


# ---------- Step 4: Analyze contract ----------
def analyze_contract(chain, echo: bool = True) -> str:
    """Run the analysis chain and return the full output text."""
    try:
        if echo:
            print("\n🔍 Analyzing contract... please wait...\n")
        result = chain.invoke("Analyze the contract for clause quality and compliance.")
        output_text = getattr(result, "content", str(result))
        if echo:
            print("\n" + output_text + "\n")
        return output_text
    except Exception as e:
        print("⚠️ Error during analysis:", e)
        return ""


# ---------- Helper: extract rectified contract & save to PDF ----------
def extract_rectified_section(output_text: str) -> str:
    """
    Extract the 'RECTIFIED CONTRACT VERSION' section from the model output.
    Returns the section text or empty string if not found.
    """
    if not output_text:
        return ""
    marker = "RECTIFIED CONTRACT VERSION:"
    idx = output_text.upper().find(marker)
    if idx == -1:
        return ""
    # Take everything after marker
    section = output_text[idx + len(marker) :]
    return section.strip()


def save_rectified_as_pdf(rectified_text: str, original_path: str) -> str:
    """
    Save rectified contract text as a PDF in regulatory_storage/contract_versions_pdf.
    Returns the absolute file path, or empty string if failed.
    """
    if not rectified_text:
        return ""

    CONTRACT_VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    ts = __import__("datetime").datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_name = Path(original_path).stem
    out_path = CONTRACT_VERSIONS_DIR / f"{base_name}_RECTIFIED_{ts}.pdf"

    c = canvas.Canvas(str(out_path), pagesize=letter)
    width, height = letter
    y = height - 40

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, f"Rectified Contract - {base_name}")
    y -= 28
    c.setFont("Helvetica", 10)

    for line in rectified_text.splitlines():
        line = line.rstrip("\n")
        while len(line) > 120:
            c.drawString(40, y, line[:120])
            line = line[120:]
            y -= 12
            if y < 40:
                c.showPage()
                y = height - 40
        c.drawString(40, y, line)
        y -= 12
        if y < 40:
            c.showPage()
            y = height - 40

    c.save()
    return str(out_path.resolve())
# --- rag.py ---

# [Keep all existing imports and setup code...]

# ... existing code ...

# ADD THIS FUNCTION BEFORE 'if __name__ == "__main__":'
def run_rectification_pipeline(file_path: str) -> str:
    """
    Helper for external scripts (like regupdate.py) to run the full pipeline
    and get the path of the generated PDF.
    """
    path_obj = Path(file_path)
    if not path_obj.exists():
        print(f"❌ [RAG] File not found: {file_path}")
        return ""

    print(f"🚀 [RAG] Starting rectification for: {path_obj.name}")
    
    # 1. Read
    docs = read_contract_file(str(path_obj))
    if not docs: 
        return ""

    # 2. Index
    vector_index = build_vector_index(docs)

    # 3. Analyze
    chain = create_analysis_pipeline(vector_index)
    output = analyze_contract(chain, echo=False)

    # 4. Extract & Save
    rectified_text = extract_rectified_section(output)
    if not rectified_text:
        print("⚠️ [RAG] No rectified text generated.")
        return ""

    pdf_path = save_rectified_as_pdf(rectified_text, str(path_obj))
    print(f"✅ [RAG] PDF Saved: {pdf_path}")
    return pdf_path

# [Keep the existing 'if __name__ == "__main__":' block below]

# ---------- MAIN EXECUTION ----------
if __name__ == "__main__":
    # If called with an argument: non-interactive mode for regupdate.py
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        non_interactive = True
    else:
        file_path = input("📄 Enter path to your contract file (.pdf or .txt): ").strip()
        non_interactive = False

    if not Path(file_path).exists():
        raise SystemExit("❌ File not found. Please check the path.")

    # Step 1: Read contract
    documents = read_contract_file(file_path)

    # Step 2: Build index
    vector_index = build_vector_index(documents)

    # Step 3: Create pipeline
    analysis_chain = create_analysis_pipeline(vector_index)

    if non_interactive:
        # Called by regupdate.py → run once, save rectified PDF, print path
        output = analyze_contract(analysis_chain, echo=False)
        rectified = extract_rectified_section(output)
        pdf_path = save_rectified_as_pdf(rectified, file_path) if rectified else ""
        if pdf_path:
            print(pdf_path)  # regupdate.py will try to parse this path
        else:
            print("No rectified section found; no PDF generated.")
    else:
        print("\n✅ Contract Analyzer Ready!")
        print("Type 'analyze' to evaluate, or 'exit' to quit.\n")

        # Interactive loop
        while True:
            command = input("❓ Type 'analyze' to evaluate this contract: ").strip().lower()
            if command in {"exit", "quit"}:
                print("👋 Goodbye!")
                break
            if command in {"analyze", "start", "go"}:
                analyze_contract(analysis_chain, echo=True)

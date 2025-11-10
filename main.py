import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings.huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel, RunnablePassthrough

# ───────────────────────────────────────────────
# STEP 1 – Setup
# ───────────────────────────────────────────────
load_dotenv()
if not os.getenv("GROQ_API_KEY"):
    raise SystemExit("❌ GROQ_API_KEY not set in .env file")

MODEL_NAME = "llama-3.1-8b-instant"
TEMPERATURE = 0.2

# ───────────────────────────────────────────────
# STEP 2 – Load one contract (PDF or TXT)
# ───────────────────────────────────────────────
def load_contract(file_path: str):
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext in {".txt", ".md"}:
        loader = TextLoader(file_path, encoding="utf-8")
    else:
        raise ValueError("Unsupported file format. Use PDF or TXT.")
    docs = loader.load()
    print(f"✅ Loaded {len(docs)} pages from {file_path}")
    return docs

# ───────────────────────────────────────────────
# STEP 3 – Split and embed clauses
# ───────────────────────────────────────────────
def split_and_embed(docs):
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(docs)
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vs = FAISS.from_documents(chunks, embeddings)
    return vs

# ───────────────────────────────────────────────
# STEP 4 – Clause analysis chain
# ───────────────────────────────────────────────
def build_clause_analysis_chain(vectorstore):
    retriever = vectorstore.as_retriever(search_kwargs={"k": 6})

    llm = ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model_name=MODEL_NAME,
        temperature=TEMPERATURE,
        max_tokens=1500,
    )

    prompt = ChatPromptTemplate.from_template("""
You are a senior legal compliance expert specializing in contract law.
Given the extracted contract clauses below, perform these tasks:

1. **Clause Extraction:** List the important clauses (e.g., confidentiality, data protection, liability, termination, dispute resolution).
2. **Clause Evaluation:** Point out any clauses that are missing or weak.
3. **Rectified Contract:** Suggest a rewritten or improved contract section that addresses those weaknesses.

Use this structure in your answer:
---
🧾 CLAUSE SUMMARY:
<List key clauses with short explanations>

⚠️ MISSING OR WEAK CLAUSES:
<List missing or problematic areas>

✅ RECTIFIED CONTRACT VERSION:
<Provide improved contract text ensuring compliance with GDPR, HIPAA, or other standards if relevant.>
---

Context:
{context}

Question:
Analyze and rectify this contract for completeness and compliance.
    """)

    rag_chain = (
        RunnableParallel({"context": retriever, "question": RunnablePassthrough()})
        | prompt
        | llm
    )
    return rag_chain
# ───────────────────────────────────────────────
# STEP 5 – Interactive contract analysis + file saving
# ───────────────────────────────────────────────
if __name__ == "__main__":
    file_path = input("📄 Enter path to your contract file (.pdf or .txt): ").strip()

    if not Path(file_path).exists():
        raise SystemExit("❌ File not found. Please check the path.")

    docs = load_contract(file_path)
    vs = split_and_embed(docs)
    chain = build_clause_analysis_chain(vs)

    print("\n✅ Contract Analyzer Ready! Type 'analyze' (or 'start'/'go') to evaluate, or 'exit' to quit.\n")

    while True:
        q = input("❓ Type 'analyze' to evaluate this contract: ").strip().lower()
        if q in {"exit", "quit"}:
            print("👋 Goodbye!")
            break
        if q in {"analyze", "start", "go"}:
            try:
                print("\n🔍 Analyzing contract... please wait...\n")
                result = chain.invoke("Analyze the contract for clause quality and compliance.")

                # ✅ Extract the text properly (Groq returns a BaseMessage object)
                output_text = ""
                if hasattr(result, "content"):
                    output_text = result.content
                elif isinstance(result, dict) and "output" in result:
                    output_text = result["output"]
                else:
                    output_text = str(result)

                # ✅ Display output in console
                print("\n" + output_text + "\n")

                # ✅ Save to a new text file
                output_file = Path("rectified_contract.txt")
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(output_text)
                print(f"💾 Rectified contract saved as: {output_file.resolve()}")

            except Exception as e:
                print("⚠️ Error:", e)

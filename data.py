from langchain_community.document_loaders import PyPDFLoader

# ✅ Use raw strings for Windows paths (prefix with r)
FILE_PATHS = [
    "C:/Users/surya/OneDrive/Desktop/AI_Regulatory_Compliance_Checker_for_Contracts/docs/AI_Compliance_Contracts.pdf",
    "C:/Users/surya/OneDrive/Desktop/AI_Regulatory_Compliance_Checker_for_Contracts/docs/Business_Contracts_300.pdf"
]


# ✅ Load multiple PDFs safely
docs = []
for path in FILE_PATHS:
    try:
        loader = PyPDFLoader(path)
        loaded_docs = loader.load()
        docs.extend(loaded_docs)
        print(f"✅ Loaded {len(loaded_docs)} pages from: {path}")
    except Exception as e:
        print(f"⚠️ Could not load {path}: {e}")

print(f"\n📚 Total documents loaded: {len(docs)}")

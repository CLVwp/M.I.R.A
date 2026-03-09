import os
import glob
import re

def search_jeece_context(query: str, directory_path: str) -> str:
    """
    Scans up to 50 .txt files in `directory_path` at flat level.
    Extracts lines containing query keywords (ignoring stop words).
    Returns a merged text block limited to 300 words (~400 tokens).
    """
    if not os.path.exists(directory_path):
        return ""

    all_lines = []
    txt_files = glob.glob(os.path.join(directory_path, "*.txt"))[:50]

    for file_path in txt_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                all_lines.extend([line.strip() for line in f if line.strip()])
        except OSError as e:
            print(f"Error reading file {file_path}: {e}")

    # Stop words in French
    stop_words = {
        "le", "la", "les", "un", "une", "des", "du", "de", "d", "l", "qu", "que", "qui", "quoi", "dont",
        "et", "ou", "ni", "mais", "or", "donc", "car", "a", "à", "au", "aux", "en", "dans", "par", "pour",
        "avec", "sans", "sous", "sur", "je", "tu", "il", "elle", "nous", "vous", "ils", "elles",
        "est", "sont", "suis", "es", "sommes", "êtes", "ont", "as", "ai", "être", "avoir",
        "ce", "cet", "cette", "ces", "mon", "ton", "son", "ma", "ta", "sa", "mes", "tes", "ses",
        "comment", "combien", "pourquoi", "quand", "quel", "quelle", "quels", "quelles", "peux", "fait", "fais",
        "s", "t", "m", "n", "c", "j"
    }

    # Extract words from query (only word characters)
    query_words = re.findall(r'\b\w+\b', query.lower())
    keywords = [w for w in query_words if w not in stop_words and len(w) > 2]

    if not keywords:
        # Fallback: if no meaningful keywords (e.g. "Qui es tu ?"), return everything
        matched_lines = all_lines
    else:
        # Score each line based on whole-word matches
        scored_lines = []
        for line in all_lines:
            line_lower = line.lower()
            score = sum(1 for k in keywords if re.search(r'\b' + re.escape(k) + r'\b', line_lower))
            scored_lines.append((score, line))
        
        # Sort by highest score first
        scored_lines.sort(key=lambda x: x[0], reverse=True)
        
        # Only keep lines with at least 1 match
        matched_lines = [line for score, line in scored_lines if score > 0]
        
        # If no line matched any keyword, fallback to providing everything
        if not matched_lines:
            matched_lines = all_lines

    # Merge and limit to 300 words
    merged_text = " ".join(matched_lines)
    words = merged_text.split()
    if len(words) > 300:
        merged_text = " ".join(words[:300])

    return merged_text

query = "Qui es tu ?"
context = search_jeece_context(query, "/home/alex/Documents/ING4S2/PPE/IA/test/SHAIMA/M.I.R.A/jeece_data")
print("Query:", query)
print("Context found:", context)

query = "Quelles sont tes missions ?"
context = search_jeece_context(query, "/home/alex/Documents/ING4S2/PPE/IA/test/SHAIMA/M.I.R.A/jeece_data")
print("Query:", query)
print("Context found:", context)

query = "Que penses tu de la critique de l'équipe de conception ?"
context = search_jeece_context(query, "/home/alex/Documents/ING4S2/PPE/IA/test/SHAIMA/M.I.R.A/jeece_data")
print("Query:", query)
print("Context found:", context)

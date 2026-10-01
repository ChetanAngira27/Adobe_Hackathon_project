import os
import sys
import json
import subprocess
from sentence_transformers import SentenceTransformer, util
from datetime import datetime

def run_HeadingExtraction(pdf_path, outline_path):
    # Run HeadingExtraction.py to extract headings
    subprocess.run([sys.executable, "HeadingExtraction.py", pdf_path, outline_path], cwd=os.path.dirname(__file__), check=True)

def run_section_text_extractor(pdf_path, outline_path, section_texts_path):
    # Run section_text_extractor.py to extract section texts
    result = subprocess.run(
        [sys.executable, "section_text_extractor.py", pdf_path, outline_path],
        cwd=os.path.dirname(__file__),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    with open(section_texts_path, "w", encoding="utf-8") as f:
        f.write(result.stdout)

def load_input(input_json_path):
    with open(input_json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def main(input_json_path, pdfs_dir, output_json_path, top_n=5):
    # Load input
    input_data = load_input(input_json_path)
    persona = input_data["persona"]["role"]
    job = input_data["job_to_be_done"]["task"]
    query = persona + " " + job
    documents = input_data["documents"]

    # Prepare output structure
    output = {
        "metadata": {
            "input_documents": [doc["filename"] for doc in documents],
            "persona": persona,
            "job_to_be_done": job,
            "processing_timestamp": datetime.now().isoformat()
        },
        "extracted_sections": [],
        "subsection_analysis": []
    }

    # Load embedding model
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    # Encode query
    query_embedding = model.encode([query])[0]

    all_sections = []
    # For each document, extract headings and section texts
    for doc in documents:
        pdf_path = os.path.join(pdfs_dir, doc["filename"])
        outline_path = pdf_path + ".outline.json"
        section_texts_path = pdf_path + ".sections.json"

        # Step 1: Extract headings
        run_HeadingExtraction(pdf_path, outline_path)

        # Step 2: Extract section texts
        run_section_text_extractor(pdf_path, outline_path, section_texts_path)

        # Step 3: Load section texts
        with open(section_texts_path, "r", encoding="utf-8") as f:
            section_texts = json.load(f)

        # Step 4: For each section, store info for scoring
        for section in section_texts:
            all_sections.append({
                "document": doc["filename"],
                "section_title": section["text"],
                "page_number": section["page"] + 1,  # 1-based
                "section_text": section["section_text"]
            })

    # Step 5: Generate embeddings for all sections (use section_text for semantic match)
    section_embeddings = model.encode([s["section_text"] for s in all_sections])

    # Step 6: Compute similarity and rank
    if section_embeddings.size > 0 and len(all_sections) > 0:
        similarities = util.cos_sim(query_embedding, section_embeddings)[0].cpu().tolist()
        for i, sim in enumerate(similarities):
            all_sections[i]["similarity"] = sim
    else:
        print("Warning: No sections found for similarity computation.")

    # Step 7: Sort and select top N
    all_sections_sorted = sorted(all_sections, key=lambda x: x["similarity"], reverse=True)
    top_sections = all_sections_sorted[:top_n]

    # Step 8: Fill output
    for rank, sec in enumerate(top_sections, 1):
        output["extracted_sections"].append({
            "document": sec["document"],
            "section_title": sec["section_title"],
            "importance_rank": rank,
            "page_number": sec["page_number"]
        })
        output["subsection_analysis"].append({
            "document": sec["document"],
            "refined_text": sec["section_text"],
            "page_number": sec["page_number"]
        })

    # Step 9: Write output
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python main_pipeline.py input_json_path pdfs_dir output_json_path top_n")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]))

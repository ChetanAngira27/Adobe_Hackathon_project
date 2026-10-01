import pymupdf as fitz
import json
import sys

def load_outline(outline_path):
    with open(outline_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["outline"]

def extract_section_texts(pdf_path, outline):
    doc = fitz.open(pdf_path)
    # Prepare heading positions: (page, heading_idx_on_page, level, text)
    heading_positions = []
    for idx, h in enumerate(outline):
        heading_positions.append({
            "idx": idx,
            "level": h["level"],
            "text": h["text"],
            "page": h["page"]
        })

    # For each heading, find the start and end (next heading of same/higher level or end of doc)
    section_texts = []
    for i, h in enumerate(heading_positions):
        start_page = h["page"]
        end_page = doc.page_count - 1
        for j in range(i+1, len(heading_positions)):
            next_h = heading_positions[j]
            # If next heading is same or higher level, that's our end
            if next_h["page"] > start_page and (next_h["level"] <= h["level"] or next_h["level"] == "H1"):
                end_page = next_h["page"]
                break
        # Extract text from start_page to end_page (exclusive)
        section_text = ""
        for p in range(start_page, end_page):
            section_text += doc[p].get_text()
        section_texts.append({
            "level": h["level"],
            "text": h["text"],
            "page": h["page"],
            "section_text": section_text.strip()
        })
    return section_texts

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python section_text_extractor.py input.pdf outline.json")
        sys.exit(1)
    pdf_path = sys.argv[1]
    outline_path = sys.argv[2]
    outline = load_outline(outline_path)
    section_texts = extract_section_texts(pdf_path, outline)
    payload = json.dumps(section_texts, ensure_ascii=False, indent=2)
    try:
        sys.stdout.write(payload)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(payload.encode("utf-8"))
    sys.stdout.write("\n")

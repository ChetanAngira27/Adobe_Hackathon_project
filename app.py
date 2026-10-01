import json
import os
import re
import tempfile
from typing import List, Dict, Any

import pymupdf as fitz
from flask import Flask, render_template_string, request

app = Flask(__name__)


def extract_title(page):
    blocks = page.get_text("dict")["blocks"]
    title_blocks = []
    max_size = 0
    for block in blocks:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if span["size"] > max_size:
                    max_size = span["size"]

    for block in blocks:
        if "lines" not in block:
            continue
        block_text = ""
        block_y = None
        for line in block["lines"]:
            for span in line["spans"]:
                if abs(span["size"] - max_size) < 0.1:
                    block_text += span["text"].strip() + " "
                    if block_y is None:
                        block_y = span["bbox"][1]
        if block_text.strip():
            title_blocks.append((block_y, block_text.strip()))

    title_blocks.sort(key=lambda x: x[0] if x[0] is not None else 0)
    title = "  ".join([tb[1] for tb in title_blocks])
    return title.strip()


def is_not_heading(text):
    text = text.strip()
    if re.match(r"^[\d\.\s]+$", text):
        return True
    if re.match(r"^\d{4}\.?$", text):
        return True
    if len(text) < 3:
        return True
    return False


def is_proper_heading(text, font_size, avg_font_size, is_bold, prev_text, next_text, p50):
    text = text.strip()
    if is_not_heading(text):
        return False

    numbered_heading = bool(re.match(r"^\d+\.(\d+\.)*\s+[A-Z]", text))
    common_heading = bool(re.match(r"^(Introduction|Overview|Conclusion|References|Acknowledgements|Table of Contents|Revision History)", text, re.IGNORECASE))
    section_heading = bool(re.match(r"^(Chapter|Section|Part)\s+\d+", text, re.IGNORECASE))
    whitespace_padding = prev_text.strip() == "" or next_text.strip() == ""
    large_font = font_size > avg_font_size * 1.2
    bold_and_reasonable_size = is_bold and font_size > avg_font_size * 1.05
    font_size_greater_than_p50 = font_size > p50

    return (
        numbered_heading or common_heading or section_heading or large_font or bold_and_reasonable_size or whitespace_padding or font_size_greater_than_p50
    ) and len(text) > 3


def merge_block_text(block):
    text_parts = []
    max_size = 0
    is_bold = False
    if "lines" not in block:
        return None

    for line in block["lines"]:
        for span in line["spans"]:
            text = span["text"].strip()
            if text:
                text_parts.append(text)
                max_size = max(max_size, span["size"])
                if "Bold" in span["font"]:
                    is_bold = True

    if not text_parts:
        return None

    return {"text": " ".join(text_parts), "font_size": max_size, "is_bold": is_bold}


def classify_heading_level(text, font_size, font_hierarchy):
    text = text.strip()
    if re.match(r"^\d+\.\s+", text):
        return "H1"
    elif re.match(r"^\d+\.\d+\s+", text):
        return "H2"
    elif re.match(r"^\d+\.\d+\.\d+\s+", text):
        return "H3"

    for i, (lower, upper) in enumerate(font_hierarchy):
        if lower <= font_size <= upper:
            return f"H{i + 1}"

    return "H2"


def extract_headings(doc):
    all_blocks = []
    font_sizes = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            block_info = merge_block_text(block)
            if block_info:
                block_info["page"] = page_num + 1
                all_blocks.append(block_info)
                font_sizes.append(block_info["font_size"])

    if not font_sizes:
        return []

    sorted_sizes = sorted(font_sizes)

    def get_percentile(data, pct):
        idx = int(len(data) * pct / 100)
        if idx >= len(data):
            idx = len(data) - 1
        return data[idx]

    avg_font_size = get_percentile(sorted_sizes, 50)
    p98 = get_percentile(sorted_sizes, 98)
    p90 = get_percentile(sorted_sizes, 90)
    p75 = get_percentile(sorted_sizes, 75)
    p50 = get_percentile(sorted_sizes, 50)

    font_hierarchy = [(p90, p98), (p75, p90), (p50, p75)]

    headings = []
    seen_texts = set()

    for block in all_blocks:
        text = block["text"].strip()
        if text in seen_texts:
            continue

        idx = all_blocks.index(block)
        prev_text = all_blocks[idx - 1]["text"] if idx > 0 else ""
        next_text = all_blocks[idx + 1]["text"] if idx < len(all_blocks) - 1 else ""

        if not is_proper_heading(text, block["font_size"], avg_font_size, block["is_bold"], prev_text, next_text, p50):
            continue

        level = classify_heading_level(text, block["font_size"], font_hierarchy)
        headings.append({"level": level, "text": text, "page": block["page"] - 1})
        seen_texts.add(text)

    headings.sort(key=lambda x: (x["page"], x["text"]))

    final_headings = []
    for heading in headings:
        text = heading["text"]
        if re.match(r"^\d+\.$", text):
            continue
        if re.match(r"^\d+\.\s*$", text) and len(text) < 5:
            continue
        final_headings.append(heading)

    return final_headings


def extract_pdf_outline(pdf_path: str) -> Dict[str, Any]:
    document = fitz.open(pdf_path)
    title = extract_title(document[0]) if document.page_count > 0 else ""
    outline = extract_headings(document)
    return {"title": title, "outline": outline}


INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PDF Outline Extractor</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      background: #f4f7fb;
      margin: 0;
      padding: 0;
      color: #222;
    }
    .container {
      max-width: 1000px;
      margin: 50px auto;
      background: white;
      padding: 30px;
      border-radius: 16px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.08);
    }
    h1 {
      margin-top: 0;
    }
    form {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin-bottom: 25px;
    }
    input[type="file"] {
      border: 1px solid #d0d7e2;
      padding: 12px;
      border-radius: 10px;
      background: #fafcff;
      flex: 1;
      min-width: 250px;
    }
    button {
      background: #2463eb;
      color: white;
      border: none;
      padding: 12px 20px;
      border-radius: 10px;
      cursor: pointer;
      font-size: 16px;
    }
    button:hover {
      background: #1d4ec7;
    }
    .result-box {
      background: #0f172a;
      color: #e2e8f0;
      border-radius: 12px;
      padding: 18px;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 14px;
      line-height: 1.6;
    }
    .note {
      color: #475569;
      margin-bottom: 16px;
    }
    .error {
      color: #dc2626;
      background: #fee2e2;
      border-radius: 10px;
      padding: 12px 14px;
      margin-top: 10px;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>PDF Outline Extractor</h1>
    <p class="note">Upload a PDF and the app will extract the document title and outline JSON.</p>

    <form method="post" action="/upload" enctype="multipart/form-data">
      <input type="file" name="pdf" accept=".pdf" required>
      <button type="submit">Extract</button>
    </form>

    {% if result_json %}
      <div class="result-box">{{ result_json }}</div>
    {% endif %}

    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}
  </div>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def home():
    return render_template_string(INDEX_HTML, result_json="", error="")


@app.route("/upload", methods=["POST"])
def upload_pdf():
    uploaded_file = request.files.get("pdf")
    if not uploaded_file or uploaded_file.filename == "":
        return render_template_string(INDEX_HTML, result_json="", error="Please choose a PDF file first.")

    if not uploaded_file.filename.lower().endswith(".pdf"):
        return render_template_string(INDEX_HTML, result_json="", error="Only PDF files are allowed.")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            uploaded_file.save(temp_file.name)
            temp_path = temp_file.name

        result = extract_pdf_outline(temp_path)
        result_json = json.dumps(result, ensure_ascii=False, indent=2)
        return render_template_string(INDEX_HTML, result_json=result_json, error="")
    except Exception as exc:
        return render_template_string(INDEX_HTML, result_json="", error=f"Processing failed: {str(exc)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

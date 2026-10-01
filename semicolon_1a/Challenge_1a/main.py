import pymupdf as fitz
import re
import json
import sys
from collections import Counter
import os


def extract_title(page):
    """Extract the title as all blocks with the largest font size on the first page, joined and sorted by vertical position."""
    blocks = page.get_text("dict")["blocks"]
    title_blocks = []
    max_size = 0

    # Find the largest font size on the page
    for block in blocks:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if span["size"] > max_size:
                    max_size = span["size"]

    # Collect all blocks that use the largest font size
    for block in blocks:
        if "lines" not in block:
            continue
        block_text = ""
        block_y = None
        for line in block["lines"]:
            for span in line["spans"]:
                if abs(span["size"] - max_size) < 0.1:  # Allow for float rounding
                    block_text += span["text"].strip() + " "
                    if block_y is None:
                        block_y = span["bbox"][1]
        if block_text.strip():
            title_blocks.append((block_y, block_text.strip()))

    # Sort by vertical position (top to bottom)
    title_blocks.sort(key=lambda x: x[0] if x[0] is not None else 0)
    # Join all title lines with a space
    title = "  ".join([tb[1] for tb in title_blocks])
    return title.strip()

def is_not_heading(text):
    """Check if text is likely table content or non-heading fragments."""
    text = text.strip()
    
    # Pure numbers or version numbers
    if re.match(r'^[\d\.\s]+$', text):
        return True
    
    # Years
    if re.match(r'^\d{4}\.?$', text):
        return True
    
    # Very short fragments
    if len(text) < 3:
        return True
    
    # Single words that are likely not headings
    # if len(text.split()) == 1 and not re.match(r'^(Introduction|Overview|Conclusion|References|Acknowledgements)', text, re.IGNORECASE):
    #     return True
    
    # # List items starting with numbers but not proper headings
    # if re.match(r'^\d+\.\s+[a-z]', text):  # "1. something" (lowercase)
    #     return True
    
    return False

def is_proper_heading(text, font_size, avg_font_size, is_bold,prev_text,next_text,p50):
    """Determine if text is a proper heading."""
    text = text.strip()
    
    if is_not_heading(text):
        return False
    
    # Numbered headings pattern (1., 2.1, etc.)
    numbered_heading = bool(re.match(r'^\d+\.(\d+\.)*\s+[A-Z]', text))
    
    # Common heading patterns
    common_heading = bool(re.match(r'^(Introduction|Overview|Conclusion|References|Acknowledgements|Table of Contents|Revision History)', text, re.IGNORECASE))
    
    # Section/Chapter patterns
    section_heading = bool(re.match(r'^(Chapter|Section|Part)\s+\d+', text, re.IGNORECASE))

    # Whitespace padding: if the text has a blank line above and below, it's likely a heading
    # This requires context, so you may need to pass previous/next line info to this function.
    # For now, let's assume you pass two extra arguments: prev_text, next_text
    # Example usage: is_proper_heading(text, font_size, avg_font_size, is_bold, prev_text, next_text)
    # Uncomment and use if you adapt the function signature:
    whitespace_padding = prev_text.strip() == "" and next_text.strip() == ""
    
    # Font-based criteria
    large_font = font_size > avg_font_size * 1.2
    bold_and_reasonable_size = is_bold and font_size > avg_font_size * 1.05

    # Additional criterion: font size greater than p50 percentile
    font_size_greater_than_p50 = font_size > p50

    
        
    
    return (numbered_heading or common_heading or section_heading or 
            large_font or bold_and_reasonable_size or whitespace_padding or font_size_greater_than_p50) and len(text) > 3


def merge_block_text(block):
    """Merge all text in a block to handle multi-line headings."""
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
    
    return {
        "text": " ".join(text_parts),
        "font_size": max_size,
        "is_bold": is_bold
    }

def classify_heading_level(text, font_size, font_hierarchy):
    """Classify heading level based on numbering pattern and font size hierarchy."""
    text = text.strip()
    
    # Primary: Numbering pattern classification
    if re.match(r'^\d+\.\s+', text):  # "1. Introduction"
        return "H1"
    elif re.match(r'^\d+\.\d+\s+', text):  # "2.1 Something"
        return "H2"
    elif re.match(r'^\d+\.\d+\.\d+\s+', text):  # "2.1.1 Something"
        return "H3"
    
    # Secondary: Font size hierarchy
    # Secondary: Font size hierarchy classification
    for i, (lower, upper) in enumerate(font_hierarchy):
        if lower <= font_size <= upper:
            return f"H{i+1}"
    
    # Default for common headings
    # if re.match(r'^(Introduction|Overview|Conclusion|References|Acknowledgements|Table of Contents|Revision History|Summary)', text, re.IGNORECASE):
    #     return "H1"
    
    return "H2"  # Default level


def extract_headings(doc):
    """Extract headings from the entire PDF with document-wide analysis."""
    all_blocks = []
    font_sizes = []
    
    # Collect all blocks from all pages
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
    
    # Calculate document-wide font statistics
    # Document-wide font statistics using median instead of mean
    sorted_sizes = sorted((font_sizes))

    # Helper to compute a percentile value (0-100)
    def get_percentile(data, pct):
        idx = int(len(data) * pct / 100)
        if idx >= len(data):
            idx = len(data) - 1
        return data[idx]

    # Use median (50th percentile) for avg_font_size
    avg_font_size = get_percentile(sorted_sizes, 50)

    # Use percentile thresholds for heading hierarchy
    # define percentile thresholds
    p98 = get_percentile(sorted_sizes, 98)   # top 0%–10%
    p90  = get_percentile(sorted_sizes, 90)    # 10%–25%
    p75  = get_percentile(sorted_sizes, 75)    # 25%–50%
    p50  = get_percentile(sorted_sizes, 50)    # below 50%

    # font_hierarchy now holds ranges for H1, H2, H3
    # H1: sizes between p90 and p100
    # H2: sizes between p75 and p90
    # H3: sizes between p50 and p75
    font_hierarchy = [
        (p90, p98),
        (p75, p90),
        (p50, p75)
    ]

    # font_hierarchy = [p90, p75, p50]
    
    # Filter and classify headings
    headings = []
    seen_texts = set()
    
    for block in all_blocks:
        text = block["text"].strip()
        
        # Skip duplicates
        if text in seen_texts:
            continue
        # Find previous and next block text for context
        idx = all_blocks.index(block)
        prev_text = all_blocks[idx - 1]["text"] if idx > 0 else ""
        next_text = all_blocks[idx + 1]["text"] if idx < len(all_blocks) - 1 else ""
        
        # Check if it's a proper heading with context
        if not is_proper_heading(text, block["font_size"], avg_font_size, block["is_bold"], prev_text, next_text,p50):
            continue
        
        # Classify heading level
        level = classify_heading_level(text, block["font_size"], font_hierarchy)
        
        headings.append({
            "level": level,
            "text": text,
            "page": block["page"]-1
        })
        seen_texts.add(text)
    
    # Sort by page order and clean up
    headings.sort(key=lambda x: (x["page"], x["text"]))
    
    # Post-process to fix common issues
    final_headings = []
    for heading in headings:
        text = heading["text"]
        
        # Skip obvious table of contents entries that are just numbers
        if re.match(r'^\d+\.$', text):
            continue
        
        # Skip incomplete numbered headings
        if re.match(r'^\d+\.\s*$', text) and len(text) < 5:
            continue
        
        final_headings.append(heading)
    
    return final_headings


def process_pdf(pdf_path, output_path):
    doc = fitz.open(pdf_path)
    title = extract_title(doc[0])
    outline = extract_headings(doc)
    result = {
        "title": title,
        "outline": outline
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

# if __name__ == "__main__":
#     if len(sys.argv) != 3:
#         print("Usage: python outline_extractor.py input.pdf output.json")
#         sys.exit(1)
#     process_pdf(sys.argv[1], sys.argv[2])



def process_folder(input_folder, output_folder):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    for filename in os.listdir(input_folder):
        if filename.lower().endswith(".pdf"):
            input_pdf = os.path.join(input_folder, filename)
            output_json = os.path.join(output_folder, os.path.splitext(filename)[0] + ".json")
            print(f"Processing: {filename}")
            process_pdf(input_pdf, output_json)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python i3.py input_folder output_folder")
        sys.exit(1)

    input_folder = sys.argv[1]
    output_folder = sys.argv[2]
    process_folder(input_folder, output_folder)

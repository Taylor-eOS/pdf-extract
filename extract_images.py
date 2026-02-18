import os
from pathlib import Path
import fitz
from PIL import Image
from io import BytesIO
from collections import Counter

pdf_path = input("Input file without ending (input): ") or "input"
output_folder = "output" + "_" + pdf_path
pdf_path = pdf_path + ".pdf"
report_path = f"{output_folder}/extraction_report.txt"
min_size = 50
context_chars = 200
SCANNED_PAGE_RATIO = 0.6
SCANNED_SIZE_TOLERANCE = 0.12

def text_is_usable(text):
    return bool(text) and len(text.strip()) >= 3 and text.strip()

def get_all_blocks(page):
    return [(bx0, by0, bx1, by1, text.strip())
            for bx0, by0, bx1, by1, text, *_ in page.get_text("blocks")
            if text.strip()]

def get_headers_on_page(page):
    flags_seen = {}
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                size = span.get("size", 0)
                flags = span.get("flags", 0)
                is_bold = bool(flags & 2**4)
                key = (round(size), is_bold)
                if key not in flags_seen:
                    flags_seen[key] = []
                flags_seen[key].append(text)
    if not flags_seen:
        return []
    max_key = max(flags_seen.keys(), key=lambda k: k[0] * (1.2 if k[1] else 1.0))
    return flags_seen[max_key]

def get_text_before_image(page, img_rect):
    blocks = get_all_blocks(page)
    best_text = ""
    best_y = float("-inf")
    for bx0, by0, bx1, by1, text in blocks:
        if by1 <= img_rect.y1 and by1 > best_y:
            best_y = by1
            best_text = text
    return best_text[-context_chars:]

def get_text_after_image(page, img_rect):
    blocks = get_all_blocks(page)
    best_text = ""
    best_y = float("inf")
    for bx0, by0, bx1, by1, text in blocks:
        if by0 >= img_rect.y0 and by0 < best_y:
            best_y = by0
            best_text = text
    return best_text[:context_chars]

def get_context_lines(page, img_rect):
    lines = []
    before = get_text_before_image(page, img_rect)
    if text_is_usable(before):
        lines.append(f"  Preceding: {before}")
    after = get_text_after_image(page, img_rect)
    if text_is_usable(after):
        lines.append(f"  Following: {after}")
    headers = get_headers_on_page(page)
    if headers:
        lines.append(f"  Header/title: {headers[0][:context_chars]}")
    if not lines:
        all_blocks = get_all_blocks(page)
        for _, _, _, _, text in all_blocks:
            if text_is_usable(text):
                lines.append(f"  Text sample: {text[:context_chars]}")
                break
    return lines if lines else ["  (no usable text found on page)"]

def get_context_from_prev_page(doc, page_num):
    if page_num == 0:
        return None
    prev_page = doc[page_num - 1]
    blocks = get_all_blocks(prev_page)
    for _, _, _, _, text in reversed(blocks):
        if text_is_usable(text):
            return text[-context_chars:]
    return None

def is_scanned_pdf(doc):
    total_pages = len(doc)
    if total_pages == 0:
        return False
    sample_size = min(total_pages, 10)
    pages_with_fullpage_images = 0
    size_counter = Counter()
    page_area_samples = []
    for i in range(sample_size):
        page = doc[i]
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height
        images = page.get_images(full=True)
        for img in images:
            xref = img[0]
            base = doc.extract_image(xref)
            if not base:
                continue
            w = base.get("width", 0)
            h = base.get("height", 0)
            if page_area > 0:
                img_pixel_area = w * h
                page_pixel_area = page_rect.width * page_rect.height
                ratio = img_pixel_area / page_pixel_area if page_pixel_area > 0 else 0
                if ratio > 0.5:
                    pages_with_fullpage_images += 1
                    size_counter[(w, h)] += 1
                    page_area_samples.append((w, h))
    fullpage_ratio = pages_with_fullpage_images / sample_size
    if fullpage_ratio < SCANNED_PAGE_RATIO:
        return False
    if not size_counter:
        return False
    most_common_size, most_common_count = size_counter.most_common(1)[0]
    mw, mh = most_common_size
    uniform_count = sum(
        1 for w, h in page_area_samples
        if abs(w - mw) / max(mw, 1) < SCANNED_SIZE_TOLERANCE
        and abs(h - mh) / max(mh, 1) < SCANNED_SIZE_TOLERANCE
    )
    uniform_ratio = uniform_count / len(page_area_samples) if page_area_samples else 0
    return uniform_ratio >= 0.7

def extract_images_from_pdf(pdf_path, output_folder, min_size, report_path):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Could not open PDF: {e}")
        print(f"Call the file {pdf_path}")
        return
    print("Checking PDF structure...")
    if is_scanned_pdf(doc):
        print("WARNING: This PDF appears to be a scanned document (large uniform images covering most pages).")
        print("Extraction aborted. Use an OCR tool to convert this PDF to text+image format first.")
        doc.close()
        return
    image_count = 0
    seen_xrefs = set()
    report_lines = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            base_image = doc.extract_image(xref)
            if not base_image:
                continue
            width = base_image.get("width", 0)
            height = base_image.get("height", 0)
            if width < min_size or height < min_size:
                continue
            image_bytes = base_image["image"]
            filename = f"page{page_num+1:03d}_img{img_index+1:03d}.jpg"
            filepath = os.path.join(output_folder, filename)
            try:
                pil_img = Image.open(BytesIO(image_bytes))
                if pil_img.mode in ("RGBA", "P", "LA"):
                    pil_img = pil_img.convert("RGB")
                out_bytes = BytesIO()
                pil_img.save(out_bytes, format="JPEG", quality=95)
                with open(filepath, "wb") as img_file:
                    img_file.write(out_bytes.getvalue())
                image_count += 1
                print(f"Saved: {filepath}  ({width}x{height})")
                img_rects = page.get_image_rects(xref)
                img_rect = img_rects[0] if img_rects else fitz.Rect(0, 0, 0, 0)
                context_lines = get_context_lines(page, img_rect)
                if all("no usable text" in l for l in context_lines):
                    prev_text = get_context_from_prev_page(doc, page_num)
                    if prev_text:
                        context_lines = [f"  Text from previous page: {prev_text}"]
                report_lines.append(f"{filename}  [{width}x{height}]  Page {page_num+1}")
                report_lines.extend(context_lines)
                report_lines.append("")
            except Exception as e:
                print(f"Failed to save {filename}: {e}")
    doc.close()
    print(f"Extracted {image_count} images (min size {min_size} px).")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        print(f"Report written to {report_path}")
    except Exception as e:
        print(f"Failed to write report: {e}")

if __name__ == "__main__":
    if Path(output_folder).is_dir():
        print(f"Warning: Input folder already exists. Images would be placed in existing folder.")
    else:
        extract_images_from_pdf(pdf_path, output_folder, min_size, report_path)


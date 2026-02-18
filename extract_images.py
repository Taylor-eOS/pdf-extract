import os
import fitz
from PIL import Image
from io import BytesIO

pdf_path = "input.pdf"
output_folder = "output"
report_path = "extraction_report.txt"
min_size = 80
context_chars = 200

def get_text_before_image(page, img_rect):
    blocks = page.get_text("blocks")
    best_text = ""
    best_y = float("-inf")
    for block in blocks:
        bx0, by0, bx1, by1, text, *_ = block
        text = text.strip()
        if not text:
            continue
        if by1 <= img_rect.y1 and by1 > best_y:
            best_y = by1
            best_text = text
    if not best_text:
        for block in blocks:
            bx0, by0, bx1, by1, text, *_ = block
            text = text.strip()
            if text:
                best_text = text
                break
    return best_text[-context_chars:]

def extract_images_from_pdf(pdf_path, output_folder, min_size, report_path):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Could not open PDF: {e}")
        print(f"Call the file {pdf_path}")
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
                context = get_text_before_image(page, img_rect)
                report_lines.append(f"{filename}  [{width}x{height}]")
                #report_lines.append(f" Page {page_num+1}, preceding text:")
                report_lines.append(f"   {context}")
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
    extract_images_from_pdf(pdf_path, output_folder, min_size, report_path)


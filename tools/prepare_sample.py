#!/usr/bin/env python3
"""Test data generator — splits a text file into chapters for EPUB builder testing."""

import argparse
import html
import json
import os
import random
import shutil


def lines_to_html(lines):
    """Convert plain text lines to HTML paragraphs."""
    paragraphs = []
    current = []
    for line in lines:
        stripped = line.rstrip()
        if stripped:
            current.append(html.escape(stripped))
        else:
            if current:
                paragraphs.append("<p>" + "<br/>\n".join(current) + "</p>")
                current = []
    if current:
        paragraphs.append("<p>" + "<br/>\n".join(current) + "</p>")
    return "\n\n".join(paragraphs)


def main():
    parser = argparse.ArgumentParser(description="Generate test book directory from a text file")
    parser.add_argument("--text", required=True, help="Path to source text file")
    parser.add_argument("--image", required=True, help="Path to test image file")
    parser.add_argument("-n", type=int, required=True, help="Number of chapters")
    parser.add_argument("--output", required=True, help="Output book directory")
    args = parser.parse_args()

    # Read text file
    with open(args.text, "r", encoding="utf-8") as f:
        all_lines = f.readlines()

    total = len(all_lines)
    print(f"Total lines: {total}")
    print(f"Splitting into {args.n} chapters")

    # Create directories
    chapters_dir = os.path.join(args.output, "chapters")
    images_dir = os.path.join(args.output, "images")
    os.makedirs(chapters_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)

    # Copy image
    img_ext = os.path.splitext(args.image)[1]
    img_name = "watercolor" + img_ext
    shutil.copy2(args.image, os.path.join(images_dir, img_name))

    # Pick random chapters for image insertion
    random.seed(42)
    image_chapters = set(random.sample(range(args.n), k=min(3, args.n)))
    print(f"Chapters with images: {sorted(c + 1 for c in image_chapters)}")

    # Split lines evenly
    q, r = divmod(total, args.n)
    chunks = []
    offset = 0
    for i in range(args.n):
        size = q + (1 if i < r else 0)
        chunks.append(all_lines[offset : offset + size])
        offset += size

    # Write .body files
    chapters_meta = []
    for i, chunk in enumerate(chunks):
        body_html = lines_to_html(chunk)

        # Insert image in selected chapters (roughly in the middle)
        if i in image_chapters:
            paragraphs = body_html.split("\n\n")
            mid = len(paragraphs) // 2
            paragraphs.insert(mid, f'<img src="{img_name}" alt="test image"/>')
            body_html = "\n\n".join(paragraphs)

        filename = f"{i + 1:04d}.body"
        filepath = os.path.join(chapters_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(body_html)

        chapters_meta.append({
            "title": f"제{i + 1}장",
            "file": filename,
        })
        print(f"  {filename}: {len(chunk)} lines")

    # Derive title from text filename
    text_basename = os.path.splitext(os.path.basename(args.text))[0]

    # Write book.json
    book_data = {
        "title": text_basename,
        "author": "Unknown",
        "language": "ko",
        "chapters": chapters_meta,
    }

    book_json_path = os.path.join(args.output, "book.json")
    with open(book_json_path, "w", encoding="utf-8") as f:
        json.dump(book_data, f, ensure_ascii=False, indent=2)

    print(f"\nBook directory created: {args.output}")
    print(f"  {len(chapters_meta)} chapters, book.json written")


if __name__ == "__main__":
    main()

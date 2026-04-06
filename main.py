#!/usr/bin/env python3
"""EPUB Builder — converts a structured book directory into an EPUB file."""

import argparse
import json
import os
import re
import sys
import uuid

from ebooklib import epub

DEFAULT_CSS = """\
body {
    font-family: serif;
    line-height: 1.8;
    margin: 1em;
    padding: 0;
    color: #222;
    background-color: #fff;
}

h1, h2, h3, h4, h5, h6 {
    font-family: sans-serif;
    line-height: 1.3;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
}

h1 { font-size: 1.6em; text-align: center; margin-top: 2em; }
h2 { font-size: 1.3em; }
h3 { font-size: 1.1em; }

p {
    margin: 0.5em 0;
    text-indent: 1em;
    text-align: justify;
}

img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 1em auto;
}

blockquote {
    margin: 1em 2em;
    padding-left: 1em;
    border-left: 3px solid #ccc;
    font-style: italic;
}

table {
    border-collapse: collapse;
    margin: 1em auto;
}

td, th {
    border: 1px solid #999;
    padding: 0.4em 0.8em;
}

a {
    color: #336;
    text-decoration: underline;
}
"""

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def guess_media_type(filename):
    ext = os.path.splitext(filename)[1].lower()
    return MEDIA_TYPES.get(ext, "application/octet-stream")


def _html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _clean_line(s):
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    s = re.sub(r"^ +", lambda m: "&#160;" * len(m.group()), s)
    return s.rstrip()


def _wrap(tag, content, cls=None):
    content = _clean_line(content)
    if not content:
        content = "<br/>"
    else:
        content = _html_escape(content)
    if cls:
        return f'<{tag} class="{cls}">{content}</{tag}>\n'
    return f"<{tag}>{content}</{tag}>\n"


def _convert_line(line):
    line = line.rstrip("\n")
    if line == "* * *":
        return _wrap("p", line, cls="separator")
    if line.startswith("@"):
        if len(line) > 1 and line[1] == "@":
            return _wrap("p", line[1:])
        if len(line) > 1 and line[1].isdecimal():
            level = line[1]
            body = line[3:] if len(line) > 2 else ""
            return _wrap(f"h{level}", body)
    return _wrap("p", line)


def convert_txt_to_body(text):
    """Convert plain-text markup to HTML body content (.body format)."""
    return "".join(_convert_line(line) for line in text.splitlines(keepends=True))


def rewrite_image_src(html_content):
    """Rewrite bare image filenames to images/ path."""
    return re.sub(r'src="([^"/]+)"', r'src="images/\1"', html_content)


def build_epub(input_dir, output_path):
    book_json_path = os.path.join(input_dir, "book.json")
    if not os.path.exists(book_json_path):
        print(f"Error: {book_json_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(book_json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    for key in ("title", "author", "language", "chapters"):
        if key not in meta:
            print(f"Error: '{key}' missing in book.json", file=sys.stderr)
            sys.exit(1)

    # Create book
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(meta["title"])
    book.set_language(meta["language"])
    book.add_author(meta["author"])

    # CSS
    css_content = DEFAULT_CSS
    style_css_path = os.path.join(input_dir, "style.css")
    if os.path.exists(style_css_path):
        with open(style_css_path, "r", encoding="utf-8") as f:
            css_content += "\n/* --- style.css override --- */\n" + f.read()

    css_item = epub.EpubItem(
        uid="default_css",
        file_name="style/default.css",
        media_type="text/css",
        content=css_content.encode("utf-8"),
    )
    book.add_item(css_item)

    # Cover image
    cover_filename = meta.get("cover")
    if cover_filename:
        cover_path = os.path.join(input_dir, "images", cover_filename)
        if os.path.exists(cover_path):
            with open(cover_path, "rb") as f:
                book.set_cover("images/" + cover_filename, f.read())
        else:
            print(f"Warning: cover image '{cover_path}' not found", file=sys.stderr)

    # All images (excluding cover)
    images_dir = os.path.join(input_dir, "images")
    if os.path.isdir(images_dir):
        for img_name in os.listdir(images_dir):
            if img_name == cover_filename:
                continue
            img_path = os.path.join(images_dir, img_name)
            if not os.path.isfile(img_path):
                continue
            with open(img_path, "rb") as f:
                img_data = f.read()
            img_item = epub.EpubImage(
                uid="img_" + re.sub(r"[^a-zA-Z0-9]", "_", img_name),
                file_name="images/" + img_name,
                media_type=guess_media_type(img_name),
                content=img_data,
            )
            book.add_item(img_item)

    # Chapters
    chapter_items = []
    for i, ch in enumerate(meta["chapters"]):
        body_path = os.path.join(input_dir, "chapters", ch["file"])
        if not os.path.exists(body_path):
            print(f"Error: chapter file '{body_path}' not found", file=sys.stderr)
            sys.exit(1)

        with open(body_path, "r", encoding="utf-8") as f:
            raw = f.read()

        if os.path.splitext(ch["file"])[1].lower() == ".txt":
            body_content = convert_txt_to_body(raw)
        else:
            body_content = raw

        body_content = rewrite_image_src(body_content)

        chapter = epub.EpubHtml(
            title=ch["title"],
            file_name=f"chapter_{i + 1:04d}.xhtml",
            lang=meta["language"],
        )
        chapter.set_content(body_content)
        chapter.add_item(css_item)
        book.add_item(chapter)
        chapter_items.append(chapter)

    # TOC and spine
    book.toc = tuple(chapter_items)
    book.spine = ["nav"] + chapter_items

    # Navigation
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Write
    epub.write_epub(output_path, book, {})
    size = os.path.getsize(output_path)
    print(f"EPUB created: {output_path} ({size:,} bytes, {len(chapter_items)} chapters)")


def main():
    parser = argparse.ArgumentParser(description="Build EPUB from book directory")
    parser.add_argument("--input", required=True, help="Path to book directory")
    parser.add_argument("--output", required=True, help="Output EPUB file path")
    args = parser.parse_args()
    build_epub(args.input, args.output)


if __name__ == "__main__":
    main()

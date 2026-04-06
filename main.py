#!/usr/bin/env python3
"""EPUB Builder — converts a structured book directory into an EPUB file."""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import uuid

from ebooklib import epub
from PIL import Image


class _SvgCoverHtml(epub.EpubCoverHtml):
    """Cover page that renders the cover image via SVG for proper aspect-ratio scaling."""

    def __init__(self, svg_content, **kwargs):
        super().__init__(**kwargs)
        self.content = svg_content
        self.is_linear = True

    def get_content(self):
        return self.content

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


def _svg_cover_html(cover_filename, width, height):
    return f"""\
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/>
    <title>Cover</title>
    <style type="text/css">
      @page {{ padding: 0pt; margin: 0pt }}
      body {{ text-align: center; padding: 0pt; margin: 0pt; }}
    </style>
  </head>
  <body>
    <div>
      <svg version="1.1" xmlns="http://www.w3.org/2000/svg"
           xmlns:xlink="http://www.w3.org/1999/xlink"
           width="100%" height="100%" viewBox="0 0 {width} {height}"
           preserveAspectRatio="xMidYMid meet">
        <image width="{width}" height="{height}" xlink:href="{cover_filename}"/>
      </svg>
    </div>
  </body>
</html>"""


def _has_transparency(img):
    """Return True if PIL image has any transparent pixels."""
    if img.mode in ("RGBA", "LA"):
        alpha_channel = img.mode.index("A")
        return img.getextrema()[alpha_channel][0] < 255
    if img.mode == "P":
        return "transparency" in img.info
    return False


def _is_animated_gif(image_path):
    with Image.open(image_path) as img:
        return hasattr(img, "n_frames") and img.n_frames > 1


def _resize_image(img, max_size):
    w, h = img.size
    if w > max_size or h > max_size:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img


def _optimize_image(input_path, output_dir, compress=False, max_size=None):
    """Process a single image for EPUB. Returns output filename.

    Resize (PNG/JPEG only, if max_size set) → format conversion (if compress set)
    GIF → copy as-is always
    PNG without transparency → JPEG (quality=85) if compress
    PNG with transparency    → PNG (lossless optimize) if compress
    JPEG                     → save if resized, else copy as-is
    Everything else          → copy as-is
    """
    filename = os.path.basename(input_path)
    name, ext = os.path.splitext(filename)
    ext_lower = ext.lower()

    if ext_lower == ".gif":
        shutil.copy2(input_path, os.path.join(output_dir, filename))
        return filename

    with Image.open(input_path) as img:
        resized = False
        if max_size and ext_lower in (".png", ".jpg", ".jpeg"):
            w, h = img.size
            img = _resize_image(img, max_size)
            resized = (img.size != (w, h))

        if compress and ext_lower == ".png":
            if _has_transparency(img):
                img.save(os.path.join(output_dir, filename), "PNG", optimize=True)
                return filename
            else:
                out_name = name + ".jpg"
                img.convert("RGB").save(
                    os.path.join(output_dir, out_name), "JPEG", quality=85
                )
                return out_name
        elif ext_lower in (".jpg", ".jpeg"):
            if resized:
                img.save(os.path.join(output_dir, filename), "JPEG", quality=85)
            else:
                shutil.copy2(input_path, os.path.join(output_dir, filename))
            return filename
        else:
            if resized:
                img.save(os.path.join(output_dir, filename), "PNG", optimize=True)
            else:
                shutil.copy2(input_path, os.path.join(output_dir, filename))
            return filename


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


def _apply_img_renames(html_content, rename_map):
    """Replace image src filenames according to rename_map (e.g. photo.png → photo.jpg)."""
    if not rename_map:
        return html_content

    def replacer(m):
        old = m.group(1)
        new = rename_map.get(old, old)
        return f'src="images/{new}"'

    return re.sub(r'src="images/([^"]+)"', replacer, html_content)


def build_epub(input_dir, output_path, compress_images=False, max_image_size=None):
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

    # Tags
    for tag in meta.get("tags", []):
        book.add_metadata("DC", "subject", tag.strip())

    # Cover image
    cover_filename = meta.get("cover")
    if cover_filename:
        cover_path = os.path.join(input_dir, "images", cover_filename)
        if os.path.exists(cover_path):
            with open(cover_path, "rb") as f:
                cover_data = f.read()
            # Add cover image without the default (non-SVG) cover HTML
            book.set_cover("images/" + cover_filename, cover_data, create_page=False)
            # Add SVG-based cover page
            with Image.open(cover_path) as img:
                width, height = img.size
            cover_page = _SvgCoverHtml(
                svg_content=_svg_cover_html(cover_filename, width, height),
                image_name="images/" + cover_filename,
            )
            book.add_item(cover_page)
        else:
            print(f"Warning: cover image '{cover_path}' not found", file=sys.stderr)

    # All images (excluding cover)
    images_dir = os.path.join(input_dir, "images")
    img_rename_map = {}  # old_name -> new_name (PNG → JPEG 변환 시)

    def _add_images(src_dir):
        for img_name in os.listdir(src_dir):
            if img_name == cover_filename:
                continue
            img_path = os.path.join(src_dir, img_name)
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

    if os.path.isdir(images_dir):
        if compress_images or max_image_size:
            with tempfile.TemporaryDirectory() as tmp_dir:
                for img_name in os.listdir(images_dir):
                    img_path = os.path.join(images_dir, img_name)
                    if not os.path.isfile(img_path):
                        continue
                    new_name = _optimize_image(
                        img_path, tmp_dir,
                        compress=compress_images,
                        max_size=max_image_size,
                    )
                    if new_name != img_name:
                        img_rename_map[img_name] = new_name
                _add_images(tmp_dir)
        else:
            _add_images(images_dir)

    # Chapters
    chapter_items = []   # all EpubHtml items (for spine)
    toc_entries = []     # TOC: EpubHtml or (Section, [EpubHtml, ...])
    chap_index = 0

    current_section = None   # (Section, [chapters]) being built
    for ch in meta["chapters"]:
        if "file" not in ch:
            # Section header (level item)
            if current_section is not None:
                toc_entries.append(tuple(current_section))
            current_section = [epub.Section(ch["title"]), []]
            continue

        chap_index += 1
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
        body_content = _apply_img_renames(body_content, img_rename_map)

        chapter = epub.EpubHtml(
            title=ch["title"],
            file_name=f"chapter_{chap_index:04d}.xhtml",
            lang=meta["language"],
        )
        chapter.set_content(body_content)
        chapter.add_item(css_item)
        book.add_item(chapter)
        chapter_items.append(chapter)

        if current_section is not None:
            current_section[1].append(chapter)
        else:
            toc_entries.append(chapter)

    if current_section is not None:
        toc_entries.append(tuple(current_section))

    # TOC and spine
    book.toc = tuple(toc_entries)
    spine_start = ["cover", "nav"] if cover_filename else ["nav"]
    book.spine = spine_start + chapter_items

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
    parser.add_argument(
        "--compress",
        action="store_true",
        help="Compress images: convert opaque PNG to JPEG, losslessly optimize transparent PNG",
    )
    parser.add_argument(
        "--max-size",
        type=str,
        default=None,
        help="Resize PNG/JPEG images to fit within N pixels (longest side). "
             "Use 'default' for 1440px, or a positive integer.",
    )
    args = parser.parse_args()

    max_size = None
    if args.max_size is not None:
        if args.max_size.lower() == "default":
            max_size = 1440
        else:
            try:
                max_size = int(args.max_size)
                if max_size <= 0:
                    raise ValueError("must be positive")
            except ValueError:
                parser.error(
                    f"--max-size: '{args.max_size}' is not valid "
                    "(use 'default' or a positive integer)"
                )

    build_epub(args.input, args.output, compress_images=args.compress, max_image_size=max_size)


if __name__ == "__main__":
    main()

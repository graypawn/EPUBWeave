#!/usr/bin/env python3
"""EPUB Builder — converts a structured book directory into an EPUB file."""

import argparse
import importlib.metadata
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
import zipfile
from pathlib import PurePosixPath

from ebooklib import epub
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True


class _SvgCoverHtml(epub.EpubCoverHtml):
    """Cover page that renders the cover image via SVG for proper aspect-ratio scaling."""

    def __init__(self, svg_content, **kwargs):
        super().__init__(**kwargs)
        self.content = svg_content
        self.is_linear = True

    def get_content(self):
        return self.content

def _load_static_css(name):
    css_path = os.path.join(os.path.dirname(__file__), "static", name)
    with open(css_path, "r", encoding="utf-8") as f:
        return f.read()

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

EPUBWEAVE_MANIFEST_PATH = "META-INF/epubweave.json"
EPUBWEAVE_FORMAT_VERSION = 1
EPUB_CONTENT_ROOT = "EPUB"

try:
    __version__ = importlib.metadata.version("epubweave")
except importlib.metadata.PackageNotFoundError:
    __version__ = "2.0.0"


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
        <image width="{width}" height="{height}" xlink:href="images/{cover_filename}"/>
      </svg>
    </div>
  </body>
</html>"""


def _has_transparency(img, threshold=250):
    """Return True if PIL image has visually meaningful transparent pixels."""
    if img.mode in ("RGBA", "LA"):
        alpha_channel = img.mode.index("A")
        return img.getextrema()[alpha_channel][0] < threshold
    if img.mode == "P":
        return "transparency" in img.info
    return False


def _resize_image(img, max_size):
    w, h = img.size
    if w > max_size or h > max_size:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img


def _is_truncated_image(input_path):
    previous = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        with Image.open(input_path) as img:
            img.load()
        return False
    except OSError as exc:
        return "truncated" in str(exc).lower()
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = previous


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

    if _is_truncated_image(input_path):
        print(f"Warning: truncated image repaired during build: {input_path}", file=sys.stderr)

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
                jpeg_img = img if img.mode == "RGB" else img.convert("RGB")
                jpeg_img.save(os.path.join(output_dir, filename), "JPEG", quality=85)
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


def _write_epubweave_manifest(output_path, manifest):
    """Add EPUBWeave's private, non-reading metadata to a generated EPUB."""
    with zipfile.ZipFile(output_path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            EPUBWEAVE_MANIFEST_PATH,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )


def _package_path(href):
    """Return an EPUBWeave writer archive path for an OPF-relative href."""
    return f"{EPUB_CONTENT_ROOT}/{href}"


def _read_package_file(archive, href):
    return archive.read(_package_path(href))


def _safe_image_name(name):
    path = PurePosixPath(name)
    return bool(name) and path.name == name and name not in (".", "..")


def _safe_content_href(href):
    path = PurePosixPath(href)
    return (
        bool(href)
        and not path.is_absolute()
        and ".." not in path.parts
        and path.parts
        and path.parts[0] not in (".", "..")
    )


def _chapter_body_from_xhtml(xhtml, href):
    """Extract EPUBWeave's body fragment without retaining the XHTML wrapper."""
    match = re.search(r"<body(?:\s[^>]*)?>(.*?)</body\s*>", xhtml, re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"chapter '{href}' has no body element")
    # EpubHtml adds outer formatting whitespace. Removing it prevents growth on
    # every unpack → build cycle while leaving meaningful internal markup intact.
    return match.group(1).strip()


def _unpacked_style_content(style_content):
    """Remove the built-in base once before making an editable style.css."""
    default_css = _load_static_css("default.css")
    if default_css and style_content.startswith(default_css):
        style_content = style_content[len(default_css):]
    # EbookLib may omit the final newline when serializing CSS. Canonicalize it
    # once so later unpack/build cycles are identical.
    return style_content.rstrip() + "\n"


def _unpack_error(message):
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def unpack_epub(input_path, output_dir):
    """Unpack an EPUBWeave-generated EPUB into its normalized book directory."""
    if not os.path.isfile(input_path):
        _unpack_error(f"{input_path} not found")
    if os.path.exists(output_dir):
        _unpack_error(f"output directory '{output_dir}' already exists")

    try:
        with zipfile.ZipFile(input_path) as archive:
            try:
                manifest = json.loads(
                    archive.read(EPUBWEAVE_MANIFEST_PATH).decode("utf-8")
                )
            except KeyError:
                _unpack_error("not an EPUBWeave EPUB (metadata manifest missing)")
            except (UnicodeDecodeError, json.JSONDecodeError):
                _unpack_error("EPUBWeave metadata manifest is invalid")

            if (
                manifest.get("format") != "EPUBWeave"
                or manifest.get("version") != EPUBWEAVE_FORMAT_VERSION
            ):
                _unpack_error("unsupported EPUBWeave metadata manifest version")

            metadata = manifest.get("metadata")
            chapters = manifest.get("chapters")
            images = manifest.get("images")
            style_href = manifest.get("style")
            if (
                not isinstance(metadata, dict)
                or not isinstance(chapters, list)
                or not isinstance(images, list)
                or not isinstance(style_href, str)
                or not _safe_content_href(style_href)
            ):
                _unpack_error("EPUBWeave metadata manifest has an invalid structure")

            for field in ("title", "author", "language"):
                if not isinstance(metadata.get(field), str) or not metadata[field]:
                    _unpack_error(f"EPUBWeave metadata manifest is missing '{field}'")
            tags = metadata.get("tags", [])
            if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                _unpack_error("EPUBWeave metadata manifest has invalid tags")

            for image_name in images:
                if not isinstance(image_name, str) or not _safe_image_name(image_name):
                    _unpack_error("EPUBWeave metadata manifest has an invalid image name")

            parent = os.path.dirname(os.path.abspath(output_dir))
            os.makedirs(parent, exist_ok=True)
            temp_dir = tempfile.mkdtemp(prefix=".epubweave-unpack-", dir=parent)
            try:
                chapters_dir = os.path.join(temp_dir, "chapters")
                images_dir = os.path.join(temp_dir, "images")
                os.makedirs(chapters_dir)
                os.makedirs(images_dir)

                try:
                    style_content = _read_package_file(archive, style_href).decode("utf-8")
                except (KeyError, UnicodeDecodeError):
                    _unpack_error("could not extract EPUBWeave stylesheet")
                with open(os.path.join(temp_dir, "style.css"), "w", encoding="utf-8") as f:
                    f.write(_unpacked_style_content(style_content))

                for image_name in images:
                    try:
                        image_content = _read_package_file(archive, f"images/{image_name}")
                    except KeyError:
                        _unpack_error(f"could not extract image '{image_name}'")
                    with open(os.path.join(images_dir, image_name), "wb") as f:
                        f.write(image_content)

                book_meta = {
                    "title": metadata["title"],
                    "author": metadata["author"],
                    "language": metadata["language"],
                    "chapters": [],
                }
                if tags:
                    book_meta["tags"] = tags
                cover = manifest.get("cover")
                if cover is not None:
                    if not isinstance(cover, str) or not _safe_image_name(cover) or cover not in images:
                        _unpack_error("EPUBWeave metadata manifest has an invalid cover")
                    book_meta["cover"] = cover

                chapter_number = 0
                for chapter in chapters:
                    if not isinstance(chapter, dict):
                        _unpack_error("EPUBWeave metadata manifest has an invalid chapter")
                    kind = chapter.get("kind")
                    title = chapter.get("title")
                    if kind not in ("section", "chapter") or not isinstance(title, str) or not title:
                        _unpack_error("EPUBWeave metadata manifest has an invalid chapter")
                    if kind == "section":
                        book_meta["chapters"].append({"title": title})
                        continue

                    href = chapter.get("href")
                    if not isinstance(href, str) or not _safe_content_href(href):
                        _unpack_error("EPUBWeave metadata manifest has an invalid chapter path")
                    try:
                        xhtml = _read_package_file(archive, href).decode("utf-8")
                        body = _chapter_body_from_xhtml(xhtml, href)
                    except (KeyError, UnicodeDecodeError, ValueError) as exc:
                        _unpack_error(f"could not extract chapter '{href}': {exc}")

                    chapter_number += 1
                    filename = f"{chapter_number:04d}.body"
                    with open(os.path.join(chapters_dir, filename), "w", encoding="utf-8") as f:
                        f.write(body)
                    entry = {"title": title, "file": filename}
                    if chapter.get("toc") is False:
                        entry["toc"] = False
                    book_meta["chapters"].append(entry)

                with open(os.path.join(temp_dir, "book.json"), "w", encoding="utf-8") as f:
                    json.dump(book_meta, f, ensure_ascii=False, indent=2)
                    f.write("\n")

                os.rename(temp_dir, output_dir)
                temp_dir = None
            finally:
                if temp_dir and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
    except zipfile.BadZipFile:
        _unpack_error(f"{input_path} is not a valid EPUB/ZIP file")

    print(f"EPUB unpacked: {input_path} -> {output_dir}")


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

    # CSS: default.css is currently empty. Keep the effective stylesheet itself
    # free of build-marker comments so unpacked books do not accumulate wrappers.
    css_content = _load_static_css("default.css")
    style_css_path = os.path.join(input_dir, "style.css")
    if os.path.exists(style_css_path):
        with open(style_css_path, "r", encoding="utf-8") as f:
            css_content += f.read()
    else:
        css_content += _load_static_css("fallback.css")

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

    # Images
    images_dir = os.path.join(input_dir, "images")
    img_rename_map = {}  # old_name -> new_name (PNG → JPEG 변환 시)
    included_image_names = []
    cover_filename = meta.get("cover")

    def _add_cover(src_dir):
        nonlocal cover_filename
        if not cover_filename:
            return
        cover_path = os.path.join(src_dir, cover_filename)
        if not os.path.exists(cover_path):
            orig_path = os.path.join(input_dir, "images", cover_filename)
            print(f"Warning: cover image '{orig_path}' not found", file=sys.stderr)
            cover_filename = None
            return
        with open(cover_path, "rb") as f:
            cover_data = f.read()
        book.set_cover("images/" + cover_filename, cover_data, create_page=False)
        with Image.open(cover_path) as img:
            width, height = img.size
        cover_page = _SvgCoverHtml(
            svg_content=_svg_cover_html(cover_filename, width, height),
            image_name="images/" + cover_filename,
        )
        book.add_item(cover_page)

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
                cover_filename = img_rename_map.get(cover_filename, cover_filename)
                _add_cover(tmp_dir)
                _add_images(tmp_dir)
                included_image_names = sorted(
                    name for name in os.listdir(tmp_dir)
                    if os.path.isfile(os.path.join(tmp_dir, name))
                )
        else:
            _add_cover(images_dir)
            _add_images(images_dir)
            included_image_names = sorted(
                name for name in os.listdir(images_dir)
                if os.path.isfile(os.path.join(images_dir, name))
            )
    elif cover_filename:
        print(
            f"Warning: cover image '{os.path.join(images_dir, cover_filename)}' not found",
            file=sys.stderr,
        )
        cover_filename = None

    # Chapters
    chapter_items = []   # all EpubHtml items (for spine)
    toc_entries = []     # TOC: EpubHtml or (Section, [EpubHtml, ...])
    manifest_chapters = []
    chap_index = 0

    section_index = 0
    current_section = None   # (Section, [chapters]) being built
    for ch in meta["chapters"]:
        if "file" not in ch:
            # Section header — generate a title page
            if current_section is not None:
                toc_entries.append(tuple(current_section))
            section_index += 1
            section_page = epub.EpubHtml(
                title=ch["title"],
                file_name=f"section_{section_index:04d}.xhtml",
                lang=meta["language"],
            )
            section_page.set_content(f'<h1>{ch["title"]}</h1>')
            section_page.add_item(css_item)
            book.add_item(section_page)
            chapter_items.append(section_page)
            current_section = [epub.Section(ch["title"], section_page.file_name), []]
            manifest_chapters.append({
                "kind": "section",
                "title": ch["title"],
                "href": section_page.file_name,
            })
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
        manifest_chapters.append({
            "kind": "chapter",
            "title": ch["title"],
            "href": chapter.file_name,
            "toc": ch.get("toc", True),
        })

        if ch.get("toc", True):
            if current_section is not None:
                current_section[1].append(chapter)
            else:
                toc_entries.append(chapter)

    if current_section is not None:
        toc_entries.append(tuple(current_section))

    # TOC and spine
    book.toc = tuple(toc_entries)
    spine_start = ["cover"] if cover_filename else []
    book.spine = spine_start + chapter_items

    # Navigation
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Write
    epub.write_epub(output_path, book, {})
    _write_epubweave_manifest(output_path, {
        "format": "EPUBWeave",
        "version": EPUBWEAVE_FORMAT_VERSION,
        "metadata": {
            "title": meta["title"],
            "author": meta["author"],
            "language": meta["language"],
            "tags": [tag.strip() for tag in meta.get("tags", [])],
        },
        "style": css_item.file_name,
        "cover": cover_filename,
        "images": included_image_names,
        "chapters": manifest_chapters,
    })
    size = os.path.getsize(output_path)
    print(f"EPUB created: {output_path} ({size:,} bytes, {len(chapter_items)} chapters)")


def main():
    parser = argparse.ArgumentParser(description="Build or unpack an EPUBWeave book")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("--input", required=True, help="Input book directory or EPUB with --unpack")
    parser.add_argument("--output", required=True, help="Output EPUB file or directory with --unpack")
    parser.add_argument(
        "--unpack",
        action="store_true",
        help="Unpack an EPUBWeave-generated EPUB into a normalized book directory",
    )
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

    if args.unpack:
        if args.compress or args.max_size is not None:
            parser.error("--compress and --max-size cannot be used with --unpack")
        unpack_epub(args.input, args.output)
        return

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

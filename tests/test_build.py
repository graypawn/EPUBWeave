"""Integration tests for build_epub and CLI."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

import pytest
from PIL import Image

from main import build_epub


@pytest.fixture
def book_dir():
    """Create a minimal book directory structure."""
    d = tempfile.mkdtemp()
    chapters_dir = os.path.join(d, "chapters")
    images_dir = os.path.join(d, "images")
    os.makedirs(chapters_dir)
    os.makedirs(images_dir)

    # Create cover image
    cover = Image.new("RGB", (600, 800), (100, 100, 200))
    cover.save(os.path.join(images_dir, "cover.jpg"), "JPEG")

    # Create body image
    img = Image.new("RGB", (400, 300), (200, 100, 100))
    img.save(os.path.join(images_dir, "illust.png"), "PNG")

    # Create chapters
    with open(os.path.join(chapters_dir, "001.body"), "w", encoding="utf-8") as f:
        f.write("<h2>1장</h2>\n<p>첫 번째 챕터입니다.</p>\n")

    with open(os.path.join(chapters_dir, "002.body"), "w", encoding="utf-8") as f:
        f.write('<h2>2장</h2>\n<p>이미지 포함.</p>\n<img src="illust.png" alt="삽화"/>\n')

    with open(os.path.join(chapters_dir, "003.txt"), "w", encoding="utf-8") as f:
        f.write("@2 3장 제목\n본문입니다.\n* * *\n끝.\n")

    # Create book.json
    meta = {
        "title": "테스트 책",
        "author": "테스트 저자",
        "language": "ko",
        "cover": "cover.jpg",
        "tags": ["소설", "테스트"],
        "chapters": [
            {"title": "1장 시작", "file": "001.body"},
            {"title": "2장 이미지", "file": "002.body"},
            {"title": "3장 텍스트", "file": "003.txt"},
        ],
    }
    with open(os.path.join(d, "book.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    yield d
    shutil.rmtree(d)


@pytest.fixture
def output_epub():
    fd, path = tempfile.mkstemp(suffix=".epub")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestBuildEpub:
    def test_creates_epub(self, book_dir, output_epub):
        build_epub(book_dir, output_epub)
        assert os.path.exists(output_epub)
        assert os.path.getsize(output_epub) > 0

    def test_epub_is_valid_zip(self, book_dir, output_epub):
        build_epub(book_dir, output_epub)
        assert zipfile.is_zipfile(output_epub)

    def test_contains_chapters(self, book_dir, output_epub):
        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            names = zf.namelist()
            xhtml_files = [n for n in names if n.endswith(".xhtml") and "chapter_" in n]
            assert len(xhtml_files) == 3

    def test_contains_images(self, book_dir, output_epub):
        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            names = zf.namelist()
            image_files = [n for n in names if "images/" in n]
            # cover.jpg + illust.png
            assert len(image_files) >= 2

    def test_contains_cover(self, book_dir, output_epub):
        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            names = zf.namelist()
            cover_files = [n for n in names if "cover" in n.lower() and n.endswith(".xhtml")]
            assert len(cover_files) >= 1

    def test_txt_chapter_converted(self, book_dir, output_epub):
        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            names = zf.namelist()
            ch3 = [n for n in names if "chapter_0003" in n][0]
            content = zf.read(ch3).decode("utf-8")
            assert "<h2>" in content
            assert "separator" in content

    def test_image_src_rewritten(self, book_dir, output_epub):
        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            names = zf.namelist()
            ch2 = [n for n in names if "chapter_0002" in n][0]
            content = zf.read(ch2).decode("utf-8")
            assert 'src="images/illust.png"' in content

    def test_metadata(self, book_dir, output_epub):
        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            # Check OPF for metadata
            opf_files = [n for n in zf.namelist() if n.endswith(".opf")]
            assert len(opf_files) == 1
            opf = zf.read(opf_files[0]).decode("utf-8")
            assert "테스트 책" in opf
            assert "테스트 저자" in opf
            assert "소설" in opf

    def test_compress_renames_png(self, book_dir, output_epub):
        build_epub(book_dir, output_epub, compress_images=True)
        with zipfile.ZipFile(output_epub) as zf:
            names = zf.namelist()
            # illust.png is opaque RGB → should become illust.jpg
            jpg_files = [n for n in names if "illust.jpg" in n]
            assert len(jpg_files) == 1
            # Chapter 2 should reference the renamed image
            ch2 = [n for n in names if "chapter_0002" in n][0]
            content = zf.read(ch2).decode("utf-8")
            assert 'src="images/illust.jpg"' in content

    def test_max_size_resizes(self, book_dir, output_epub):
        # Make a large image
        large_path = os.path.join(book_dir, "images", "illust.png")
        img = Image.new("RGB", (3000, 2000), (200, 100, 100))
        img.save(large_path, "PNG")

        build_epub(book_dir, output_epub, max_image_size=1440)
        with zipfile.ZipFile(output_epub) as zf:
            names = zf.namelist()
            illust = [n for n in names if "illust" in n][0]
            img_data = zf.read(illust)
            import io
            with Image.open(io.BytesIO(img_data)) as img:
                assert max(img.size) <= 1440


class TestBuildEpubSections:
    def test_section_headers(self, book_dir, output_epub):
        # Rewrite book.json with sections
        meta = {
            "title": "섹션 테스트",
            "author": "저자",
            "language": "ko",
            "chapters": [
                {"title": "제1부"},
                {"title": "1장", "file": "001.body"},
                {"title": "2장", "file": "002.body"},
                {"title": "제2부"},
                {"title": "3장", "file": "003.txt"},
            ],
        }
        with open(os.path.join(book_dir, "book.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        assert os.path.exists(output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            xhtml_files = [n for n in zf.namelist() if "chapter_" in n]
            assert len(xhtml_files) == 3


class TestBuildEpubEdgeCases:
    def test_no_cover(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        del meta["cover"]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        assert os.path.exists(output_epub)

    def test_no_images_dir(self, book_dir, output_epub):
        shutil.rmtree(os.path.join(book_dir, "images"))
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        del meta["cover"]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        assert os.path.exists(output_epub)

    def test_no_tags(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        del meta["tags"]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        assert os.path.exists(output_epub)

    def test_single_chapter(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["chapters"] = [{"title": "유일한 챕터", "file": "001.body"}]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            xhtml_files = [n for n in zf.namelist() if "chapter_" in n]
            assert len(xhtml_files) == 1


class TestCLI:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "main.py"] + list(args),
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )

    def test_max_size_default(self, book_dir, output_epub):
        result = self._run(
            "--input", book_dir, "--output", output_epub, "--max-size", "default"
        )
        assert result.returncode == 0

    def test_max_size_integer(self, book_dir, output_epub):
        result = self._run(
            "--input", book_dir, "--output", output_epub, "--max-size", "1080"
        )
        assert result.returncode == 0

    def test_max_size_invalid_string(self, book_dir, output_epub):
        result = self._run(
            "--input", book_dir, "--output", output_epub, "--max-size", "abc"
        )
        assert result.returncode != 0

    def test_max_size_negative(self, book_dir, output_epub):
        result = self._run(
            "--input", book_dir, "--output", output_epub, "--max-size", "-100"
        )
        assert result.returncode != 0

    def test_max_size_zero(self, book_dir, output_epub):
        result = self._run(
            "--input", book_dir, "--output", output_epub, "--max-size", "0"
        )
        assert result.returncode != 0

    def test_compress_flag(self, book_dir, output_epub):
        result = self._run(
            "--input", book_dir, "--output", output_epub, "--compress"
        )
        assert result.returncode == 0

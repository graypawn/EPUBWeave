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

from main import (
    EPUBWEAVE_FORMAT_VERSION,
    EPUBWEAVE_MANIFEST_PATH,
    __version__,
    build_epub,
    unpack_epub,
)


def test_package_major_matches_manifest_format_version():
    assert EPUBWEAVE_FORMAT_VERSION == int(__version__.split(".")[0])


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
            {"title": "1장 시작", "file": "001.body", "spinner": "naver", "id": 1},
            {"title": "2장 이미지", "file": "002.body", "spinner": "munpia", "id": 2},
            {"title": "3장 텍스트", "file": "003.txt", "spinner": "naver", "id": 3},
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

    def test_manifest_preserves_spinner_and_id(self, book_dir, output_epub):
        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            manifest = json.loads(zf.read(EPUBWEAVE_MANIFEST_PATH))
        assert manifest["version"] == EPUBWEAVE_FORMAT_VERSION
        assert manifest["chapters"][0]["spinner"] == "naver"
        assert manifest["chapters"][1]["spinner"] == "munpia"
        assert manifest["chapters"][1]["id"] == 2

    def test_manifest_preserves_source_urls(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        source_urls = {
            "naver": "https://series.naver.com/novel/detail.series?productNo=12345",
            "munpia": "https://novel.munpia.com/67890",
            "custom-spinner": "https://example.com/work/42",
        }
        meta["sourceUrls"] = source_urls
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            manifest = json.loads(zf.read(EPUBWEAVE_MANIFEST_PATH))
        assert manifest["metadata"]["sourceUrls"] == source_urls

    def test_reuses_stylesheet_across_chapters(self, book_dir, output_epub):
        styles_dir = os.path.join(book_dir, "styles")
        os.makedirs(styles_dir)
        with open(os.path.join(styles_dir, "naver.css"), "w", encoding="utf-8") as f:
            f.write("p { color: blue; }\n")
        with open(os.path.join(styles_dir, "munpia.css"), "w", encoding="utf-8") as f:
            f.write("p { color: red; }\n")

        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["chapters"][0]["style"] = "styles/naver.css"
        meta["chapters"][1]["style"] = "styles/munpia.css"
        meta["chapters"][2]["style"] = "styles/naver.css"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            assert zf.namelist().count("EPUB/styles/naver.css") == 1
            assert zf.namelist().count("EPUB/styles/munpia.css") == 1
            manifest = json.loads(zf.read(EPUBWEAVE_MANIFEST_PATH))
        assert [chapter.get("style") for chapter in manifest["chapters"]] == [
            "styles/naver.css",
            "styles/munpia.css",
            "styles/naver.css",
        ]

    def test_id_is_optional(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        del meta["chapters"][0]["id"]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            manifest = json.loads(zf.read(EPUBWEAVE_MANIFEST_PATH))
        assert "id" not in manifest["chapters"][0]

    def test_rejects_missing_chapter_spinner(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        del meta["chapters"][0]["spinner"]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        with pytest.raises(SystemExit):
            build_epub(book_dir, output_epub)

    def test_rejects_duplicate_chapter_id(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["chapters"][1]["id"] = 1
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        with pytest.raises(SystemExit):
            build_epub(book_dir, output_epub)

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
                {"title": "1장", "file": "001.body", "spinner": "naver"},
                {"title": "2장", "file": "002.body", "spinner": "naver"},
                {"title": "제2부"},
                {"title": "3장", "file": "003.txt", "spinner": "naver"},
            ],
        }
        with open(os.path.join(book_dir, "book.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        assert os.path.exists(output_epub)
        with zipfile.ZipFile(output_epub) as zf:
            xhtml_files = [n for n in zf.namelist() if "chapter_" in n]
            assert len(xhtml_files) == 3


class TestUnpackEpub:
    def _unpack_path(self):
        path = tempfile.mkdtemp()
        shutil.rmtree(path)
        return path

    def _tree(self, root):
        result = {}
        for base, _, files in os.walk(root):
            for filename in files:
                path = os.path.join(base, filename)
                result[os.path.relpath(path, root)] = open(path, "rb").read()
        return result

    def test_unpacks_normalized_book_and_is_repeatable(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["chapters"] = [
            {"title": "제1부"},
            {"title": "1장", "file": "001.body", "spinner": "naver", "id": 1},
            {"title": "2장", "file": "002.body", "spinner": "munpia", "id": 2, "toc": False},
            {"title": "제2부"},
            {"title": "3장", "file": "003.txt", "spinner": "naver", "id": 3},
        ]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        first_dir = self._unpack_path()
        unpack_epub(output_epub, first_dir)

        with open(os.path.join(first_dir, "book.json"), encoding="utf-8") as f:
            unpacked = json.load(f)
        assert unpacked["chapters"] == [
            {"title": "제1부"},
            {"title": "1장", "file": "0001.body", "spinner": "naver", "id": 1},
            {"title": "2장", "file": "0002.body", "spinner": "munpia", "id": 2, "toc": False},
            {"title": "제2부"},
            {"title": "3장", "file": "0003.body", "spinner": "naver", "id": 3},
        ]
        assert os.path.exists(os.path.join(first_dir, "style.css"))
        assert open(os.path.join(first_dir, "images", "illust.png"), "rb").read() == open(
            os.path.join(book_dir, "images", "illust.png"), "rb"
        ).read()

        rebuilt_epub = output_epub + ".rebuilt.epub"
        build_epub(first_dir, rebuilt_epub)
        second_dir = self._unpack_path()
        unpack_epub(rebuilt_epub, second_dir)
        assert self._tree(first_dir) == self._tree(second_dir)

        shutil.rmtree(first_dir)
        shutil.rmtree(second_dir)
        os.unlink(rebuilt_epub)

    def test_unpacks_shared_stylesheet_references(self, book_dir, output_epub):
        styles_dir = os.path.join(book_dir, "styles")
        os.makedirs(styles_dir)
        naver_css = "p { color: blue; }\n"
        with open(os.path.join(styles_dir, "naver.css"), "w", encoding="utf-8") as f:
            f.write(naver_css)

        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["chapters"][0]["style"] = "styles/naver.css"
        meta["chapters"][2]["style"] = "styles/naver.css"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        unpacked_dir = self._unpack_path()
        unpack_epub(output_epub, unpacked_dir)

        with open(os.path.join(unpacked_dir, "book.json"), encoding="utf-8") as f:
            unpacked = json.load(f)
        assert unpacked["chapters"][0]["style"] == "styles/naver.css"
        assert unpacked["chapters"][2]["style"] == "styles/naver.css"
        with open(os.path.join(unpacked_dir, "styles", "naver.css"), encoding="utf-8") as f:
            assert f.read() == naver_css

        rebuilt_epub = output_epub + ".rebuilt.epub"
        build_epub(unpacked_dir, rebuilt_epub)
        with zipfile.ZipFile(rebuilt_epub) as zf:
            assert zf.namelist().count("EPUB/styles/naver.css") == 1

        shutil.rmtree(unpacked_dir)
        os.unlink(rebuilt_epub)

    def test_unpacks_source_urls(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        source_urls = {
            "naver": "https://series.naver.com/novel/detail.series?productNo=12345",
            "munpia": "https://novel.munpia.com/67890",
        }
        meta["sourceUrls"] = source_urls
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        build_epub(book_dir, output_epub)
        unpacked_dir = self._unpack_path()
        unpack_epub(output_epub, unpacked_dir)

        with open(os.path.join(unpacked_dir, "book.json"), encoding="utf-8") as f:
            unpacked = json.load(f)
        assert unpacked["sourceUrls"] == source_urls

        shutil.rmtree(unpacked_dir)

    def test_optimized_images_are_not_reprocessed_on_default_rebuild(self, book_dir, output_epub):
        build_epub(book_dir, output_epub, compress_images=True)
        first_dir = self._unpack_path()
        unpack_epub(output_epub, first_dir)
        assert os.path.exists(os.path.join(first_dir, "images", "illust.jpg"))

        rebuilt_epub = output_epub + ".rebuilt.epub"
        build_epub(first_dir, rebuilt_epub)
        second_dir = self._unpack_path()
        unpack_epub(rebuilt_epub, second_dir)
        assert open(os.path.join(first_dir, "images", "illust.jpg"), "rb").read() == open(
            os.path.join(second_dir, "images", "illust.jpg"), "rb"
        ).read()

        shutil.rmtree(first_dir)
        shutil.rmtree(second_dir)
        os.unlink(rebuilt_epub)

    def test_rejects_epub_without_epubweave_manifest(self, tmp_path):
        epub_path = tmp_path / "other.epub"
        with zipfile.ZipFile(epub_path, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")

        with pytest.raises(SystemExit):
            unpack_epub(str(epub_path), str(tmp_path / "book"))

    def test_rejects_version_one_manifest(self, book_dir, output_epub, tmp_path, capsys):
        build_epub(book_dir, output_epub)
        version_one_epub = tmp_path / "version-one.epub"
        with zipfile.ZipFile(output_epub) as source:
            manifest = json.loads(source.read(EPUBWEAVE_MANIFEST_PATH))
            manifest["version"] = 1
            with zipfile.ZipFile(version_one_epub, "w") as archive:
                for item in source.infolist():
                    if item.filename != EPUBWEAVE_MANIFEST_PATH:
                        archive.writestr(item, source.read(item.filename))
                archive.writestr(EPUBWEAVE_MANIFEST_PATH, json.dumps(manifest))

        with pytest.raises(SystemExit):
            unpack_epub(str(version_one_epub), str(tmp_path / "book"))
        assert "does not contain required episode spinner metadata" in capsys.readouterr().err

    @pytest.mark.parametrize("manifest_version", (2, 3))
    def test_unpacks_prior_manifest_without_source_urls(
        self, book_dir, output_epub, tmp_path, manifest_version
    ):
        build_epub(book_dir, output_epub)
        prior_epub = tmp_path / f"version-{manifest_version}.epub"
        with zipfile.ZipFile(output_epub) as source:
            manifest = json.loads(source.read(EPUBWEAVE_MANIFEST_PATH))
            manifest["version"] = manifest_version
            manifest["metadata"].pop("sourceUrls", None)
            with zipfile.ZipFile(prior_epub, "w") as archive:
                for item in source.infolist():
                    if item.filename != EPUBWEAVE_MANIFEST_PATH:
                        archive.writestr(item, source.read(item.filename))
                archive.writestr(EPUBWEAVE_MANIFEST_PATH, json.dumps(manifest))

        unpacked_dir = tmp_path / f"unpacked-v{manifest_version}"
        unpack_epub(str(prior_epub), str(unpacked_dir))
        with open(unpacked_dir / "book.json", encoding="utf-8") as f:
            unpacked = json.load(f)
        assert "sourceUrls" not in unpacked


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

    def test_rejects_invalid_source_urls(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["sourceUrls"] = {"naver": ""}
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        with pytest.raises(SystemExit):
            build_epub(book_dir, output_epub)

    def test_single_chapter(self, book_dir, output_epub):
        meta_path = os.path.join(book_dir, "book.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["chapters"] = [
            {"title": "유일한 챕터", "file": "001.body", "spinner": "naver"}
        ]
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

    def test_unpack(self, book_dir, output_epub, tmp_path):
        build_epub(book_dir, output_epub)
        output_dir = tmp_path / "unpacked"
        result = self._run(
            "--unpack", "--input", output_epub, "--output", str(output_dir)
        )
        assert result.returncode == 0
        assert (output_dir / "book.json").exists()

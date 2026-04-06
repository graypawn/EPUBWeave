"""Tests for text processing functions."""

from main import (
    _html_escape,
    _clean_line,
    _convert_line,
    convert_txt_to_body,
    rewrite_image_src,
    _apply_img_renames,
    guess_media_type,
)


class TestHtmlEscape:
    def test_ampersand(self):
        assert _html_escape("A & B") == "A &amp; B"

    def test_lt_gt(self):
        assert _html_escape("<p>") == "&lt;p&gt;"

    def test_no_escape_needed(self):
        assert _html_escape("hello") == "hello"

    def test_all_special(self):
        assert _html_escape("&<>") == "&amp;&lt;&gt;"


class TestCleanLine:
    def test_nbsp_replaced(self):
        assert "\u00a0" not in _clean_line("a\u00a0b")

    def test_zero_width_space_removed(self):
        assert "\u200b" not in _clean_line("a\u200bb")

    def test_leading_spaces_to_nbsp(self):
        result = _clean_line("  hello")
        assert result.startswith("&#160;&#160;")

    def test_trailing_whitespace_stripped(self):
        assert _clean_line("hello   ") == "hello"


class TestConvertLine:
    def test_plain_text(self):
        assert _convert_line("hello") == "<p>hello</p>\n"

    def test_h2(self):
        assert _convert_line("@2 제목") == "<h2>제목</h2>\n"

    def test_h3(self):
        assert _convert_line("@3 소제목") == "<h3>소제목</h3>\n"

    def test_separator(self):
        result = _convert_line("* * *")
        assert 'class="separator"' in result
        assert "* * *" in result

    def test_escape_at(self):
        result = _convert_line("@@실제 골뱅이")
        assert "<p>" in result
        assert "@실제 골뱅이" in result
        assert "@@" not in result

    def test_empty_line(self):
        result = _convert_line("")
        assert "<br/>" in result

    def test_special_chars_escaped(self):
        result = _convert_line("A & B")
        assert "&amp;" in result


class TestConvertTxtToBody:
    def test_multiline(self):
        text = "@2 제목\n본문입니다.\n* * *\n끝.\n"
        result = convert_txt_to_body(text)
        assert "<h2>" in result
        assert "<p>" in result
        assert "separator" in result

    def test_empty(self):
        assert convert_txt_to_body("") == ""

    def test_single_line(self):
        result = convert_txt_to_body("hello")
        assert result == "<p>hello</p>\n"


class TestRewriteImageSrc:
    def test_bare_filename(self):
        html = '<img src="photo.png" alt="test"/>'
        result = rewrite_image_src(html)
        assert 'src="images/photo.png"' in result

    def test_already_has_path(self):
        html = '<img src="images/photo.png"/>'
        result = rewrite_image_src(html)
        # Should not double-prefix (images/ contains /, so regex won't match)
        assert 'src="images/photo.png"' in result

    def test_multiple_images(self):
        html = '<img src="a.png"/><img src="b.jpg"/>'
        result = rewrite_image_src(html)
        assert 'src="images/a.png"' in result
        assert 'src="images/b.jpg"' in result

    def test_no_images(self):
        html = "<p>no images</p>"
        assert rewrite_image_src(html) == html


class TestApplyImgRenames:
    def test_rename(self):
        html = '<img src="images/photo.png"/>'
        result = _apply_img_renames(html, {"photo.png": "photo.jpg"})
        assert 'src="images/photo.jpg"' in result

    def test_no_rename_needed(self):
        html = '<img src="images/photo.jpg"/>'
        result = _apply_img_renames(html, {"other.png": "other.jpg"})
        assert 'src="images/photo.jpg"' in result

    def test_empty_map(self):
        html = '<img src="images/photo.png"/>'
        assert _apply_img_renames(html, {}) == html

    def test_multiple_renames(self):
        html = '<img src="images/a.png"/><img src="images/b.png"/>'
        rename_map = {"a.png": "a.jpg", "b.png": "b.jpg"}
        result = _apply_img_renames(html, rename_map)
        assert 'src="images/a.jpg"' in result
        assert 'src="images/b.jpg"' in result


class TestGuessMediaType:
    def test_jpg(self):
        assert guess_media_type("photo.jpg") == "image/jpeg"

    def test_jpeg(self):
        assert guess_media_type("photo.jpeg") == "image/jpeg"

    def test_png(self):
        assert guess_media_type("image.png") == "image/png"

    def test_gif(self):
        assert guess_media_type("anim.gif") == "image/gif"

    def test_svg(self):
        assert guess_media_type("icon.svg") == "image/svg+xml"

    def test_unknown(self):
        assert guess_media_type("file.xyz") == "application/octet-stream"

"""Tests for image processing functions."""

import os
import shutil
import tempfile

import pytest
from PIL import Image

from main import (
    _has_transparency,
    _resize_image,
    _optimize_image,
)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def output_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def _make_png(path, size=(100, 100), mode="RGB", transparent=False):
    img = Image.new(mode, size, (255, 0, 0))
    if transparent and mode == "RGBA":
        pixels = img.load()
        for x in range(size[0]):
            for y in range(size[1]):
                pixels[x, y] = (255, 0, 0, 0)
    img.save(path, "PNG")


def _make_jpeg(path, size=(100, 100)):
    img = Image.new("RGB", size, (0, 255, 0))
    img.save(path, "JPEG")


def _make_gif(path, size=(100, 100), frames=1):
    imgs = [Image.new("RGB", size, (i * 50, 0, 0)) for i in range(frames)]
    if frames > 1:
        imgs[0].save(path, "GIF", save_all=True, append_images=imgs[1:], loop=0)
    else:
        imgs[0].save(path, "GIF")


# --- _has_transparency ---

class TestHasTransparency:
    def test_rgb_no_transparency(self):
        img = Image.new("RGB", (10, 10), (255, 0, 0))
        assert _has_transparency(img) is False

    def test_rgba_fully_opaque(self):
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        assert _has_transparency(img) is False

    def test_rgba_with_transparency(self):
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
        assert _has_transparency(img) is True

    def test_rgba_partial_transparency(self):
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
        assert _has_transparency(img) is True

    def test_p_mode_with_transparency(self):
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
        img = img.convert("P")
        # P mode from RGBA typically has transparency info
        if "transparency" in img.info:
            assert _has_transparency(img) is True

    def test_l_mode(self):
        img = Image.new("L", (10, 10), 128)
        assert _has_transparency(img) is False



# --- _resize_image ---

class TestResizeImage:
    def test_larger_than_max(self):
        img = Image.new("RGB", (2000, 1000))
        result = _resize_image(img, 1440)
        w, h = result.size
        assert w <= 1440
        assert h <= 1440

    def test_smaller_than_max(self):
        img = Image.new("RGB", (800, 600))
        result = _resize_image(img, 1440)
        assert result.size == (800, 600)

    def test_exact_max(self):
        img = Image.new("RGB", (1440, 1440))
        result = _resize_image(img, 1440)
        assert result.size == (1440, 1440)

    def test_preserves_aspect_ratio(self):
        img = Image.new("RGB", (3000, 1500))
        result = _resize_image(img, 1440)
        w, h = result.size
        assert abs(w / h - 2.0) < 0.01

    def test_rgba_preserved(self):
        img = Image.new("RGBA", (2000, 1000), (255, 0, 0, 128))
        result = _resize_image(img, 1440)
        assert result.mode == "RGBA"


# --- _optimize_image ---

class TestOptimizeImage:
    def test_gif_copied_as_is(self, tmp_dir, output_dir):
        path = os.path.join(tmp_dir, "anim.gif")
        _make_gif(path, frames=3)
        result = _optimize_image(path, output_dir, compress=True, max_size=100)
        assert result == "anim.gif"
        assert os.path.exists(os.path.join(output_dir, "anim.gif"))

    def test_compress_opaque_png_to_jpeg(self, tmp_dir, output_dir):
        path = os.path.join(tmp_dir, "opaque.png")
        _make_png(path, mode="RGB")
        result = _optimize_image(path, output_dir, compress=True)
        assert result == "opaque.jpg"
        assert os.path.exists(os.path.join(output_dir, "opaque.jpg"))

    def test_compress_transparent_png_stays_png(self, tmp_dir, output_dir):
        path = os.path.join(tmp_dir, "transparent.png")
        _make_png(path, mode="RGBA", transparent=True)
        result = _optimize_image(path, output_dir, compress=True)
        assert result == "transparent.png"
        assert os.path.exists(os.path.join(output_dir, "transparent.png"))

    def test_resize_large_png(self, tmp_dir, output_dir):
        path = os.path.join(tmp_dir, "big.png")
        _make_png(path, size=(2000, 2000), mode="RGB")
        result = _optimize_image(path, output_dir, max_size=1440)
        assert result == "big.png"
        with Image.open(os.path.join(output_dir, "big.png")) as img:
            assert max(img.size) <= 1440

    def test_resize_large_jpeg(self, tmp_dir, output_dir):
        path = os.path.join(tmp_dir, "big.jpg")
        _make_jpeg(path, size=(2000, 1500))
        result = _optimize_image(path, output_dir, max_size=1440)
        assert result == "big.jpg"
        with Image.open(os.path.join(output_dir, "big.jpg")) as img:
            assert max(img.size) <= 1440

    def test_small_image_not_resized(self, tmp_dir, output_dir):
        path = os.path.join(tmp_dir, "small.png")
        _make_png(path, size=(100, 100), mode="RGB")
        result = _optimize_image(path, output_dir, max_size=1440)
        assert result == "small.png"

    def test_no_options_copies_as_is(self, tmp_dir, output_dir):
        path = os.path.join(tmp_dir, "photo.png")
        _make_png(path, size=(500, 500), mode="RGB")
        original_size = os.path.getsize(path)
        result = _optimize_image(path, output_dir)
        assert result == "photo.png"
        assert os.path.getsize(os.path.join(output_dir, "photo.png")) == original_size

    def test_compress_and_resize(self, tmp_dir, output_dir):
        path = os.path.join(tmp_dir, "large_opaque.png")
        _make_png(path, size=(3000, 2000), mode="RGB")
        result = _optimize_image(path, output_dir, compress=True, max_size=1440)
        # Opaque PNG → JPEG after resize
        assert result == "large_opaque.jpg"
        with Image.open(os.path.join(output_dir, "large_opaque.jpg")) as img:
            assert max(img.size) <= 1440

    def test_gif_not_resized(self, tmp_dir, output_dir):
        path = os.path.join(tmp_dir, "big.gif")
        _make_gif(path, size=(2000, 2000), frames=1)
        result = _optimize_image(path, output_dir, max_size=1440)
        assert result == "big.gif"
        # GIF is copied as-is, not resized
        with Image.open(os.path.join(output_dir, "big.gif")) as img:
            assert img.size == (2000, 2000)

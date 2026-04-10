# EPUBWeave CLI Interface Specification

For AI integration: crrawlers, orchestration UIs, and automation tools.

## Command Format

```bash
python main.py --input <input_dir> --output <output.epub> [--compress] [--max-size <size>]
```

## Arguments

| Argument | Type | Required | Default | Format |
|----------|------|----------|---------|--------|
| `--input` | string | Yes | - | Absolute or relative path to book directory |
| `--output` | string | Yes | - | Absolute or relative path to output EPUB file |
| `--compress` | flag | No | false | No value required |
| `--max-size` | string | No | - | `'default'` (1440px) or positive integer (e.g., `1080`) |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Failure (error message in stderr) |
| 2 | Invalid arguments (error message in stderr) |

## Output Format

### Success (exit 0)

**stdout:**
```
EPUB created: /path/to/output.epub (1234567 bytes, 42 chapters)
```

**stderr:**
- (empty)

### Failure (exit 1)

**stdout:**
- (empty)

**stderr:**
```
Error: <specific error message>
```

Common error messages:
- `Error: <path> not found` — book.json or chapter file missing
- `Error: '<key>' missing in book.json` — required field absent
- `--max-size: '<value>' is not valid (use 'default' or a positive integer)` — invalid max-size value

## Input Contract: book.json

**Required fields (string):**
- `title` — book title
- `author` — author name
- `language` — ISO 639-1 language code (e.g., `ko`, `en`, `ja`)

**Required fields (array):**
- `chapters[]` — array of chapter objects

**Optional fields:**
- `cover` (string) — cover image filename in `images/` directory
- `tags` (array) — array of tag strings for metadata

**Chapter object:**
- `title` (string, required) — chapter or section title
- `file` (string, optional) — path to chapter file in `chapters/` directory
  - If absent: treated as TOC section header; subsequent chapters group under this section
  - If present: must exist and be readable
- `toc` (boolean, optional, default `true`) — include this chapter in the table of contents
  - Only applies when `file` is present
  - Set to `false` to add the page to the spine (readable in flow) but hide it from the TOC

**Validation:**
- Missing required fields → exit 1
- `chapters` empty → exit 1 (no chapters to process)
- Referenced `chapters[].file` does not exist → exit 1
- `cover` file does not exist → warning (stderr), but continue (exit 0)

## Directory Structure Contract

```
<input_dir>/
├── book.json              (required)
├── style.css              (optional — overrides fallback.css when present)
├── chapters/              (required if chapters have files)
│   ├── NNNN.body          (HTML fragment)
│   ├── NNNN.txt           (plain text with markup)
│   └── ...
└── images/                (optional)
    ├── cover.jpg
    ├── illustration.png
    └── ...
```

### CSS resolution order

| Condition | CSS applied |
|-----------|-------------|
| `style.css` present | `static/default.css` (empty) + `style.css` |
| `style.css` absent  | `static/default.css` (empty) + `static/fallback.css` |

`static/fallback.css` contains the built-in default styles (typography, `.ibox`, `.intro`, etc.).

## File Format Contracts

### `.body` files

- HTML fragment (no `<html>`, `<body>` tags)
- Character encoding: UTF-8
- Image references: bare filenames only (e.g., `src="photo.png"`)
  - Builder prepends `images/` automatically
- Constraints: well-formed HTML only

### `.txt` files

- Plain UTF-8 text with markup
- Markup rules:
  - `@2 <title>` → `<h2><title></h2>` (h2-h6 supported)
  - `@3 <title>` → `<h3><title></h3>`
  - `* * *` → `<p class="separator">* * *</p>`
  - `@@<text>` → `<p>@<text></p>` (escape leading @)
  - Empty lines → `<p><br/></p>`
  - Regular text → `<p><text></p>`
- No image references allowed (use `.body` files instead)

### Image files

- **Supported formats:** PNG, JPEG, GIF, SVG, WebP
- **Processing:**
  - GIF: always copied as-is (no resizing)
  - PNG/JPEG: resized if `--max-size` set (PNG/JPEG only)
  - PNG: converted to JPEG if `--compress` set (only if visually opaque, alpha min ≥ 250)
  - Transparent PNG (alpha min < 250): preserved as PNG if `--compress` set
  - Other formats: copied as-is
- **Original files:** never modified (processing in temp directory)
- **Transparency:** RGBA/LA channels and palette transparency preserved; alpha ≥ 250 treated as opaque
- **Max-size:** longest edge capped at value; aspect ratio maintained

## Option Semantics

### `--compress`

- **For PNG:** Visually opaque PNG (alpha min ≥ 250) → JPEG (quality=85); Transparent PNG (alpha min < 250) → PNG (lossless optimize)
- **For JPEG:** (no effect; JPEG already compressed)
- **For GIF:** (no effect; copied as-is)
- **Result:** Image filenames may change (e.g., `photo.png` → `photo.jpg`)
  - Builder updates chapter references automatically

### `--max-size`

- **Value:** `'default'` or positive integer
- **Invalid values:** non-positive integers, non-numeric strings → exit 2
- **Effect:** PNG/JPEG longest edge ≤ max_size (aspect ratio preserved)
- **GIF:** not resized regardless of setting
- **Can be used without `--compress`**

### Both `--compress` and `--max-size`

- **Order:** resize first, then convert format
- **Example:** `--compress --max-size 1440`
  - Resize PNG/JPEG to ≤1440px
  - Then convert opaque PNG to JPEG
  - Result: optimized + resized

## Constraints & Assumptions

1. **File paths:** All paths relative to current working directory
2. **Encoding:** All text files UTF-8
3. **Image max size:** No built-in limit on individual image file size
4. **Chapter count:** No limit
5. **Concurrent execution:** Safe (each invocation uses temp directory)
6. **Performance:** ~1-5 seconds typical (depends on image count/size)
7. **Output file:** Overwrites if exists; no backup created

## Error Handling

| Condition | Exit Code | stderr Output |
|-----------|-----------|---------------|
| book.json missing | 1 | `Error: <path> not found` |
| Required field missing | 1 | `Error: '<field>' missing in book.json` |
| Chapter file missing | 1 | `Error: chapter file '<path>' not found` |
| Invalid --max-size | 2 | `--max-size: '<value>' is not valid ...` |
| Negative or zero --max-size | 2 | `--max-size: '<value>' is not valid ...` |
| Cover file missing | 0 | `Warning: cover image '<path>' not found` (stderr) |
| Image file read error | 1 | `Error: <message>` |

## Success Indicators

- **Exit code:** 0
- **stdout:** Message starting with `EPUB created:`
- **Output file:** Created and valid EPUB (ZIP format, contains OPF)

## Test/Validation Commands

```bash
# Validate book structure without generating EPUB
# (not supported; use --output /tmp/test.epub)

# Check exit code
python main.py --input book --output out.epub && echo "Success" || echo "Failed: $?"

# Verify output is valid ZIP (EPUB)
unzip -t out.epub > /dev/null && echo "Valid EPUB"
```

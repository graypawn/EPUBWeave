# EPUBWeave

크롤러가 생성한 `book/` 디렉토리 구조를 EPUB 파일로 변환하는 빌더.

## 설치

```bash
pip install -r requirements.txt
```

필수 패키지: `ebooklib`, `pillow`

## 사용법

```bash
python main.py --input <book_dir> --output <output.epub> [옵션]
```

### 기본 예시

```bash
python main.py --input book --output result.epub
```

### 이미지 최적화

```bash
# 이미지 압축 (불투명 PNG → JPEG 변환, 투명 PNG → 무손실 최적화)
python main.py --input book --output result.epub --compress

# 이미지 리사이즈 (기본값 1440px)
python main.py --input book --output result.epub --max-size default

# 이미지 리사이즈 (지정 크기)
python main.py --input book --output result.epub --max-size 1080

# 압축 + 리사이즈 동시 적용
python main.py --input book --output result.epub --compress --max-size default
```

| 옵션 | 설명 |
|------|------|
| `--compress` | 불투명 PNG를 JPEG(quality=85)로 변환, 투명 PNG는 무손실 최적화 |
| `--max-size default` | PNG/JPEG를 1440px 이내로 리사이즈 (긴 변 기준) |
| `--max-size <정수>` | PNG/JPEG를 지정 크기 이내로 리사이즈 |

- 리사이즈는 PNG/JPEG에만 적용 (GIF는 항상 원본 유지)
- 원본 이미지 파일은 수정되지 않음 (임시 디렉토리에서 처리)
- 리사이즈 후 압축 순서로 실행

## book 디렉토리 구조

크롤러는 다음 구조의 디렉토리를 생성해야 한다:

```
book/
├── book.json
├── style.css          (선택)
├── chapters/
│   ├── 0001.body
│   ├── 0002.body
│   ├── 0003.txt
│   └── ...
└── images/
    ├── cover.jpg
    ├── illustration.png
    └── ...
```

### book.json

```json
{
  "title": "책 제목",
  "author": "저자",
  "language": "ko",
  "cover": "cover.jpg",
  "tags": ["태그1", "태그2"],
  "chapters": [
    {"title": "프롤로그", "file": "0001.body"},
    {"title": "제1부"},
    {"title": "1장 시작", "file": "0002.body"},
    {"title": "2장 전개", "file": "0003.body"},
    {"title": "제2부"},
    {"title": "3장 결말", "file": "0004.txt"}
  ]
}
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `title` | O | 책 제목 |
| `author` | O | 저자 |
| `language` | O | 언어 코드 (예: `ko`, `en`, `ja`) |
| `chapters` | O | 챕터 목록 |
| `cover` | X | 커버 이미지 파일명 (`images/` 내) |
| `tags` | X | 태그 목록 (EPUB 메타데이터 subject) |

### chapters 항목

- **`file` 있음**: 챕터. `chapters/` 디렉토리 내의 파일을 참조
- **`file` 없음**: TOC 섹션 헤더. 이후 챕터들이 해당 섹션 아래에 그룹핑됨

### 챕터 파일 형식

#### `.body` 파일

HTML fragment. `<html>`, `<body>` 태그 없이 본문 내용만 포함:

```html
<h2>챕터 제목</h2>
<p>본문 내용...</p>
<img src="illustration.png" alt="삽화"/>
<p>계속...</p>
```

이미지 참조 시 파일명만 사용 (`images/` 경로는 빌더가 자동 추가).

#### `.txt` 파일

간단한 마크업을 지원하는 텍스트 파일. 빌더가 `.body` 형식으로 자동 변환:

```
@2 챕터 제목
첫 번째 문단입니다.
두 번째 문단입니다.
* * *
구분선 뒤의 내용입니다.
@@로 시작하면 @가 하나로 이스케이프됩니다.
```

| 마크업 | 변환 결과 |
|--------|-----------|
| `@2 제목` | `<h2>제목</h2>` |
| `@3 소제목` | `<h3>소제목</h3>` |
| `* * *` | `<p class="separator">* * *</p>` |
| `@@텍스트` | `<p>@텍스트</p>` (이스케이프) |
| 일반 텍스트 | `<p>텍스트</p>` |
| 빈 줄 | `<p><br/></p>` |

### style.css (선택)

`book/` 루트에 `style.css` 파일이 있으면 해당 스타일이 적용됨.
없으면 `static/fallback.css`의 기본 스타일이 대신 적용됨.

| 상황 | 적용 스타일 |
|------|------------|
| `style.css` 있음 | `static/default.css` (빈 파일) + `style.css` |
| `style.css` 없음 | `static/default.css` (빈 파일) + `static/fallback.css` |

커스텀 스타일을 완전히 처음부터 작성하려면 `style.css`만 정의하면 됨.
기본 스타일을 유지하면서 일부만 수정하려면 `static/fallback.css`의 내용을 `style.css`에 복사한 뒤 수정.

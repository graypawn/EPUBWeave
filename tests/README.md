# 수동 테스트 가이드

EPUB 리더에서만 확인할 수 있는 항목들.

## 준비

```bash
# 테스트용 book 디렉토리 생성
python tools/prepare_sample.py --text <텍스트파일> --image <이미지파일> -n 10 --output book

# EPUB 생성
python main.py --input book --output result.epub
```

## 테스트 항목

### 1. 커버 이미지

- [ ] 커버가 첫 페이지에 표시되는가
- [ ] 이미지 비율이 유지되는가 (찌그러짐 없음)
- [ ] 세로로 긴 이미지, 가로로 긴 이미지 모두 정상 표시
- [ ] 라이브러리 목록에서 커버 썸네일이 보이는가

### 2. 목차 (TOC)

- [ ] 목차에 모든 챕터가 나열되는가
- [ ] 목차에서 챕터 클릭 시 해당 위치로 이동하는가
- [ ] 섹션 헤더가 있는 경우 계층 구조로 표시되는가
  ```json
  {
    "chapters": [
      {"title": "제1부"},
      {"title": "1장", "file": "0001.body"},
      {"title": "2장", "file": "0002.body"},
      {"title": "제2부"},
      {"title": "3장", "file": "0003.body"}
    ]
  }
  ```
- [ ] 섹션 없이 플랫 목차도 정상 동작하는가

### 3. 본문 렌더링

- [ ] 문단 간격이 적절한가 (line-height, margin)
- [ ] 들여쓰기(text-indent)가 적용되는가
- [ ] `<h2>`, `<h3>` 등 제목이 본문과 구분되는가
- [ ] 긴 챕터에서 스크롤/페이지 넘김이 자연스러운가

### 4. 이미지 (본문 내)

- [ ] 본문 속 이미지가 정상 표시되는가
- [ ] 이미지가 화면 너비에 맞게 축소되는가 (max-width: 100%)
- [ ] 이미지 전후 여백이 적절한가

### 5. .txt 챕터

- [ ] `@2 제목`이 `<h2>`로 렌더링되는가
- [ ] `* * *` 구분선이 표시되는가
- [ ] `@@`이스케이프가 `@`로 표시되는가
- [ ] 빈 줄이 적절한 간격으로 표시되는가

### 6. 커스텀 CSS

- [ ] `style.css`가 있을 때 기본 스타일 위에 덮어쓰기되는가
  ```css
  /* book/style.css 예시 */
  body { background-color: #f5f5dc; }
  p { text-indent: 0; }
  ```
- [ ] `style.css`가 없을 때 기본 스타일만 적용되는가

### 7. 이미지 최적화 결과

```bash
# 압축만
python main.py --input book --output compressed.epub --compress

# 리사이즈만
python main.py --input book --output resized.epub --max-size 1080

# 둘 다
python main.py --input book --output both.epub --compress --max-size default
```

- [ ] 압축: 불투명 PNG가 JPEG로 변환되어도 화질 저하가 눈에 띄지 않는가
- [ ] 압축: 투명 PNG가 투명도를 유지한 채 표시되는가
- [ ] 리사이즈: 이미지가 흐릿해지지 않는가
- [ ] 파일 크기 비교: 최적화 전후 EPUB 크기 차이가 합리적인가

### 8. EPUB 리더 호환성

다음 리더에서 위 항목들을 확인:

- [ ] Calibre (데스크톱)
- [ ] Apple Books (iOS/macOS)
- [ ] Google Play Books (Android)
- [ ] Ridibooks (Android/iOS)

### 9. 엣지 케이스

- [ ] 챕터가 1개뿐인 책
- [ ] 이미지가 없는 책 (커버 없음, 본문 이미지 없음)
- [ ] 매우 긴 챕터 (1만 줄 이상)
- [ ] 한국어/일본어/영어 혼합 텍스트

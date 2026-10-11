# CSS Classes

`static/fallback.css`에서 제공하는 클래스 목록 (사용자가 `style.css`를 따로 지정하지 않은 경우 적용되는 기본 스타일). 크롤러/변환기가 HTML을 생성할 때 참조.

## 빌더가 자동 추가하는 래퍼 클래스 (v3+)

| Class | 용도 | 적용 위치 |
|-------|------|-----------|
| `.episode` | 모든 챕터 본문의 공통 래퍼 | `<article class="episode spinner-naver">` |
| `.spinner-{spinner}` | 스피너별 식별 클래스 | `<article class="episode spinner-naver">` |

스피너 이름이 `naver`, `munpia`, `textspinner` 등일 때 각각 `.spinner-naver`, `.spinner-munpia`, `.spinner-textspinner`가 추가됩니다.
이를 이용해 공통 `style.css`에서 스피너별 공통 스타일을 정의할 수 있습니다:

```css
/* 네이버 스피너 본문 */
.spinner-naver .dialogue { color: blue; }

/* 문피아 스피너 본문 */
.spinner-munpia .dialogue { color: red; }
```

## 구조 클래스

| Class | 용도 | 사용 예시 |
|-------|------|-----------|
| `.none` | 숨김 요소 (크롤러 잔여물 등) | `<span class="none">...</span>` |
| `.no` | 회차 번호 | `<p class="no">제1화</p>` |
| `.separator` | 장면 구분 기호 | `<p class="separator">* * *</p>` |

## 블록 클래스

| Class | 용도 | 사용 예시 |
|-------|------|-----------|
| `.intro` | 작품 소개/시놉시스 블록 | `<div class="intro">줄거리...</div>` |
| `.ibox` | 작중 삽입 텍스트 (편지, 메시지, 시스템 창 등) | `<div class="ibox"><p>내용</p></div>` |

## 수평선 변형

| Class | 용도 |
|-------|------|
| `hr` (기본) | 점선 구분선 |
| `hr.l1` | 얇은 실선 장면 전환선 |
| `hr.l2` | 굵은 실선 장면 전환선 |

# 뉴스 모니터

보유종목 + IT/과학/흥미 뉴스 자동 수집기
GitHub Actions로 하루 3회 자동 실행 → GitHub Pages에 표시

라이브: https://heycooldown.github.io/news

---

## 파일 구성

```
news/
├── .github/workflows/crawl.yml  ← GitHub Actions 자동화
├── crawl.py                     ← 크롤러
├── index.html                   ← 대시보드 UI
├── news.json                    ← 크롤링 결과 (자동 갱신)
└── README.md
```

---

## 설치 순서

### 1. GitHub 레포 생성
- 레포 이름: `news` (→ heycooldown.github.io/news 로 접근됨)
- **Public** 으로 생성

### 2. GitHub Secrets 설정
레포 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 값 |
|------|-----|
| `NAVER_CLIENT_ID` | 네이버 Client ID |
| `NAVER_CLIENT_SECRET` | 네이버 Client Secret |

### 3. GitHub Pages 활성화
레포 → Settings → Pages
→ Source: **Deploy from a branch**
→ Branch: **master** / **(root)**
→ Save

### 4. 수동 실행 테스트
레포 → Actions → 뉴스 크롤링 자동화 → Run workflow

---

## 실행 시간 (KST)

| 시간 | 내용 |
|------|------|
| 08:00 | 아침 뉴스 (하루 1회) |

---

## 뉴스 소스

### 국내 IT
| 소스 | 카테고리 |
|------|---------|
| 네이버 뉴스 API | 보유종목 (자동 연동) |
| 전자신문 | IT |
| ZDNet Korea | IT |
| IT조선 | IT |
| 디지털데일리 | IT |
| AI타임스 | IT |

### 국내 과학
| 소스 | 카테고리 |
|------|---------|
| 헬로디디 | 과학 |

### 해외 IT
| 소스 | 카테고리 |
|------|---------|
| Hacker News | IT |
| MIT Tech Review | IT |
| Ars Technica | IT |
| The Verge | IT |

### 해외 과학
| 소스 | 카테고리 |
|------|---------|
| Nature News | 과학 |
| ScienceDaily | 과학 |
| Science Magazine | 과학 |
| New Scientist | 과학 |
| NASA News | 과학 |
| Live Science | 과학 |

### 흥미
| 소스 | 카테고리 |
|------|---------|
| Interesting Engineering | 흥미 |
| Futurism | 흥미 |
| Atlas Obscura | 흥미 |

### 일본어 학습
| 소스 | 내용 |
|------|------|
| NHK Easy News (nhkeasier.com) | やさしい日本語ニュース, 후리가나 원문 + 한국어 번역 + 낭독 음성 |

---

## 정치 뉴스 차단
대통령, 국회, 여당, 야당, 민주당, 국민의힘, 정치, 선거, 탄핵 등 자동 필터링

---

## 기술 메모

- 커밋 방식: `git commit --amend + push --force` → 커밋 1개만 유지
- 네이버 API 키는 GitHub Secrets로만 관리 (코드에 하드코딩 없음)
- workflow 권한: `permissions: contents: write`, `fetch-depth: 0`
- 보유종목/IT·과학 뉴스는 `trafilatura`로 원문 URL에서 본문 전체를 추출해 저장 (추출 실패 시 RSS 요약으로 폴백)

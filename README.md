# 📰 뉴스 모니터

보유종목 + IT/과학 뉴스 자동 수집기  
GitHub Actions로 하루 3회 자동 실행 → GitHub Pages에 표시

---

## 설치 순서

### 1. GitHub 레포 생성
- 레포 이름: `news` (→ heycooldown.github.io/news 로 접근됨)
- **Public** 으로 생성

### 2. 파일 업로드
```
news/
├── .github/workflows/crawl.yml
├── crawl.py
├── index.html
├── news.json          ← 빈 파일로 먼저 올려두기
└── README.md
```

news.json 초기값 (빈 파일):
```json
{"holdings": [], "tech": [], "updated": ""}
```

### 3. GitHub Secrets 설정
레포 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 값 |
|------|-----|
| `NAVER_CLIENT_ID` | 네이버 Client ID |
| `NAVER_CLIENT_SECRET` | 네이버 Client Secret |

### 4. GitHub Pages 활성화
레포 → Settings → Pages  
→ Source: **Deploy from a branch**  
→ Branch: **main** / **(root)**  
→ Save

### 5. 수동 실행 테스트
레포 → Actions → 뉴스 크롤링 자동화 → Run workflow

---

## 실행 시간 (KST)
| 시간 | 내용 |
|------|------|
| 08:00 | 아침 뉴스 |
| 15:30 | 장마감 전 |
| 21:00 | 저녁 국제 |

---

## 뉴스 소스
| 소스 | 카테고리 |
|------|---------|
| 네이버 뉴스 API | 보유종목 (자동 연동) |
| 전자신문, ZDNet, IT동아, 디지털데일리 | IT |
| 사이언스타임즈, 동아사이언스 | 과학 |
| Hacker News, MIT Tech Review | IT (해외) |
| Nature News, ScienceDaily | 과학 (해외) |

---

## 정치 뉴스 차단 키워드
대통령, 국회, 여당, 야당, 민주당, 국민의힘, 정치, 선거, 탄핵 등 자동 필터링

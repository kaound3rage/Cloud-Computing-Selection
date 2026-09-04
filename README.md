# EduPintar — Repo Skeleton (Latihan LKS Cloud Computing)

Repository untuk mengerjakan **Soal Latihan LKS DIY Bidang Cloud Computing 2026 —
studi kasus EduPintar** (Intelligent Course Recommendation &amp; Enrollment
Forecasting API). Mayoritas komponen sudah diimplementasikan siap pakai.

## Struktur

```
repo-skeleton/
├── .github/workflows/ci.yml        # CI/CD pipeline (build, lint, dataset release)
├── .gitignore                      # Ignored files
├── dataset/
│   ├── dataset.py                  # Generator dataset sintetis (CLI)
│   ├── requirements.txt            # Python dependencies
│   └── output/                     # Hasil dataset CSV
│       ├── course_catalog.csv
│       ├── learner_activities.csv
│       ├── learner_profiles.csv
│       └── membership_history.csv
├── ETL/
│   └── sparks.py                   # AWS Glue PySpark job (Penyimpanan, transformasi)
├── lambda/
│   ├── lambda_recommendation/      # Lambda rekomendasi kursus
│   │   ├── lambda_function.py
│   │   ├── requirements.txt
│   │   └── .env.example
│   └── lambda_forecasting/         # Lambda forecasting enrollment
│       ├── lambda_function.py
│       ├── requirements.txt
│       └── .env.example
├── el-frontend/
│   ├── main.go                     # Server Go + reverse proxy (inject x-api-key)
│   ├── go.mod
│   ├── Dockerfile                  # Multi-stage build
│   ├── .dockerignore
│   ├── .env.example
│   └── html/                       # Halaman frontend (CSS + JS fetch)
│       ├── index.html
│       ├── recommendation.html
│       └── forecasting.html
├── ai-incident-response/
│   ├── app.py                      # FastAPI webhook incident response + LLM
│   ├── requirements.txt
│   ├── Dockerfile                  # Multi-stage build
│   ├── .dockerignore
│   └── .env.example
└── machine_learning/
    └── training.ipynb              # Training model ML
```

## Quick Start

### 1. Generate dataset
```bash
pip install -r dataset/requirements.txt
python dataset/dataset.py                       # ukuran default (~1000/500/10000/750)
python dataset/dataset.py --learners 500 --courses 200 --seed 42   # kustom + reproducible
```

### 2. Jalankan frontend (Go)
```bash
cd el-frontend
go run .       # default PORT=3000
```

### 3. Jalankan AI Incident Response (FastAPI)
```bash
cd ai-incident-response
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080
```

### 4. Build Docker images
```bash
docker build -t el-frontend ./el-frontend
docker build -t ai-incident-response ./ai-incident-response
```

## Endpoint API

| Route (frontend)      | Target Lambda / Service        | Body                              |
| --------------------- | ------------------------------ | --------------------------------- |
| `POST /api/recommend` | `API_RECOMMEND` (Lambda)       | `{learner_id, course_id}`         |
| `POST /api/forecast`  | `API_FORECAST` (Lambda)        | `{course_id, days}`               |
| `POST /webhook`       | ai-incident-response (SNS)     | SNS message (Subscription/Notify) |
| `GET /health`         | ai-incident-response           | —                                 |

## Tech Stack

| Komponen       | Teknologi                        |
| -------------- | -------------------------------- |
| Dataset        | Python, Pandas, Faker            |
| ETL            | PySpark, AWS Glue                |
| ML Model       | Jupyter Notebook, Scikit-learn   |
| Backend        | Python, FastAPI, Boto3           |
| Frontend       | Go, HTML/CSS/JS                  |
| Container      | Docker (multi-stage)             |
| CI/CD          | GitHub Actions + GHCR            |
| Cloud Services | AWS Lambda, S3, DynamoDB, EC2    |

Selamat mengerjakan!

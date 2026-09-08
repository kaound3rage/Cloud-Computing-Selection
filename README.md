# AgroSense — Repo Skeleton (Latihan LKS Cloud Computing)

Repository untuk mengerjakan **Soal Latihan LKS DIY Bidang Cloud Computing 2026 —
studi kasus AgroSense** (Smart Crop Risk & Yield Forecasting Platform, tema
TaniCerdas). Mayoritas komponen sudah diimplementasikan siap pakai.

## Struktur

```
repo-skeleton/
├── .github/workflows/ci.yml        # CI/CD pipeline (build, dataset release)
├── .gitignore                      # Ignored files
├── dataset/
│   ├── dataset.py                  # Generator dataset sintetis (CLI)
│   ├── requirements.txt            # Python dependencies
│   └── output/                     # Hasil dataset CSV
│       ├── farm_profiles.csv       # ~1000 lahan pertanian
│       ├── crop_catalog.csv        # ~500 jenis padi/tanaman
│       ├── farm_activities.csv     # ~10000 aktivitas tanam/pupuk/panen
│       └── harvest_history.csv     # ~750 riwayat panen
├── ETL/
│   └── sparks.py                   # AWS Glue PySpark job (validasi + feature)
├── lambda/
│   ├── lambda_recommendation/      # Lambda prediksi risiko gagal panen
│   │   ├── lambda_function.py      #   (synch, API Gateway + x-api-key)
│   │   ├── requirements.txt
│   │   └── .env.example
│   └── lambda_forecasting/         # Lambda forecasting hasil panen
│       ├── lambda_function.py      #   (EventBridge schedule, tulis DynamoDB)
│       ├── requirements.txt
│       └── .env.example
├── el-frontend/
│   ├── main.go                     # Server Go + reverse proxy (inject x-api-key)
│   ├── go.mod
│   ├── Dockerfile                  # Multi-stage build
│   ├── .dockerignore
│   ├── .env.example
│   └── html/                       # Halaman frontend (CSS + JS fetch)
│       ├── index.html              #   landing page
│       ├── risk.html               #   form prediksi risiko gagal panen
│       └── forecasting.html        #   form perkiraan hasil panen
└── machine_learning/
    └── training.ipynb              # Training model ML (risk + yield)
```

## Quick Start

### 1. Generate dataset
```bash
pip install -r dataset/requirements.txt
python dataset/dataset.py                       # ukuran default (~1000/500/10000/750)
python dataset/dataset.py --seed 42             # reproducible
```

### 2. Jalankan frontend (Go)
```bash
cd el-frontend
go run .       # default PORT=3000
```

### 3. Build Docker images
```bash
docker build -t el-frontend ./el-frontend
```

## Endpoint API

| Route (frontend)              | Target Lambda / Service                    | Body                              |
| ----------------------------- | ------------------------------------------ | --------------------------------- |
| `POST /api/predict-risk`      | `API_PREDICT_RISK` (Lambda, via proxy x-api-key) | `{farm_id, crop_id}`        |
| `GET /api/yield-forecast/{crop_id}` | DynamoDB `YIELD_HISTORY_TABLE` (langsung) | —                            |
| `GET /risk`, `GET /forecasting` | Halaman frontend                         | —                                |
| `GET /health`                 | frontend                                   | —                                 |

## Tech Stack

| Komponen       | Teknologi                        |
| -------------- | -------------------------------- |
| Dataset        | Python, Pandas, Faker            |
| ETL            | PySpark, AWS Glue                |
| ML Model       | Jupyter Notebook, Scikit-learn   |
| Frontend       | Go, HTML/CSS/JS                  |
| Container      | Docker (multi-stage)             |
| CI/CD          | GitHub Actions + GHCR            |
| Cloud Services | AWS Lambda, S3, DynamoDB, EC2, CloudWatch |

Selamat mengerjakan!
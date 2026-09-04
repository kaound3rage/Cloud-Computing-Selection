# EduPintar — Repo Skeleton (Latihan LKS Cloud Computing)

Kerangka awal repository untuk mengerjakan **Soal Latihan LKS DIY Bidang Cloud
Computing 2026 — studi kasus EduPintar** (lihat PDF soal).

Semua file di sini adalah **stub/kerangka** (berisi komentar `TODO`), bukan
solusi jadi — silakan lengkapi sesuai instruksi di masing-masing Bagian pada
soal.

## Struktur

```
repo-skeleton/
├── .github/workflows/ci.yml        # CI/CD pipeline
├── .gitignore                       # Ignored files
├── dataset/
│   ├── dataset.py                   # Script pembuat dataset
│   ├── requirements.txt             # Python dependencies
│   └── output/                      # Hasil dataset CSV
│       ├── course_catalog.csv
│       ├── learner_activities.csv
│       ├── learner_profiles.csv
│       └── membership_history.csv
├── ETL/
│   └── sparks.py                    # ETL dengan PySpark
├── lambda/
│   ├── lambda_recommendation/
│   │   ├── lambda_function.py
│   │   └── .env.example
│   └── lambda_forecasting/
│       ├── lambda_function.py
│       └── .env.example
├── el-frontend/
│   ├── main.go                      # Frontend Go
│   ├── go.mod
│   ├── Dockerfile
│   ├── .env.example
│   └── html/
│       ├── index.html
│       ├── recommendation.html
│       └── forecasting.html
├── ai-incident-response/
│   ├── app.py                       # FastAPI backend
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
└── machine_learning/
    └── training.ipynb               # Training model ML
```

## Urutan pengerjaan yang disarankan

1. **Bagian 1** — lengkapi `dataset/dataset.py`, buat S3 bucket & Glue
   (`ETL/sparks.py`), latih model di `machine_learning/training.ipynb`,
   lengkapi kedua Lambda di `lambda/`, lalu buat API Gateway.
2. **Bagian 2** — lengkapi `el-frontend/` (Go) dan `ai-incident-response/`
   (FastAPI), buat Dockerfile masing-masing, lalu lengkapi
   `.github/workflows/ci.yml`.
3. **Bagian 3** — buat tabel DynamoDB, CloudWatch Alarms, SNS Topic, deploy ke
   EC2, lalu uji end-to-end sesuai bagian 3.5 di soal.

## Tech Stack

| Komponen       | Teknologi                        |
| -------------- | -------------------------------- |
| Dataset        | Python, Pandas                   |
| ETL            | PySpark, AWS Glue                |
| ML Model       | Jupyter Notebook, Scikit-learn   |
| Backend        | Python, FastAPI, Boto3           |
| Frontend       | Go, HTML/CSS/JS                  |
| Container      | Docker                           |
| CI/CD          | GitHub Actions                   |
| Cloud Services | AWS Lambda, S3, DynamoDB, EC2    |

Selamat mengerjakan!

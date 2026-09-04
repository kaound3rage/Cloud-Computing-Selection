# EduPintar — Repo Skeleton (Latihan LKS Cloud Computing)

Kerangka awal repository untuk mengerjakan **Soal Latihan LKS DIY Bidang Cloud
Computing 2026 — studi kasus EduPintar** (lihat PDF soal).

Semua file di sini adalah **stub/kerangka** (berisi komentar `TODO`), bukan
solusi jadi — silakan lengkapi sesuai instruksi di masing-masing Bagian pada
soal.

## Struktur

```
repo/
├── .github/workflows/ci.yml
├── dataset/
│   ├── dataset.py
│   └── requirements.txt
├── ETL/sparks.py
├── lambda/
│   ├── lambda_recommendation/
│   └── lambda_forecasting/
├── el-frontend/
│   ├── main.go  go.mod  Dockerfile  .env.example
│   └── html/
├── ai-incident-response/
│   ├── app.py  requirements.txt  Dockerfile  .env.example
└── machine_learning/training.ipynb
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

Selamat mengerjakan!

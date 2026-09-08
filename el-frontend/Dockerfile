# Multi-stage build for farm-frontend (AgroSense, di folder el-frontend).
# Stage 1: build Go binary.
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# Static binary agar bisa jalan di image alpine minimal.
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /out/farm-frontend main.go

# Stage 2: runtime minimal.
FROM alpine:3.20
WORKDIR /app
# ca-certificates wajib untuk HTTPS ke API Gateway & DynamoDB.
RUN apk add --no-cache ca-certificates
COPY --from=builder /out/farm-frontend ./farm-frontend
COPY html ./html
EXPOSE 3000
CMD ["./farm-frontend"]

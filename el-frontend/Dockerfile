# TODO: lengkapi multi-stage build (base image golang untuk build,
# lalu image minimal untuk runtime). Expose port 3000.

FROM golang:1.22 AS builder
WORKDIR /app
COPY . .
# RUN go mod tidy && go build -o el-frontend main.go

FROM golang:1.22
WORKDIR /app
# COPY --from=builder /app/el-frontend .
COPY html ./html
EXPOSE 3000
# CMD ["./el-frontend"]

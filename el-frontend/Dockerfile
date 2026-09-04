# Multi-stage build for el-frontend
# Stage 1: build the Go binary
FROM golang:1.22 AS builder
WORKDIR /app
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/el-frontend main.go

# Stage 2: minimal runtime image
FROM scratch
WORKDIR /app
COPY --from=builder /out/el-frontend ./el-frontend
COPY html ./html
EXPOSE 3000
CMD ["./el-frontend"]

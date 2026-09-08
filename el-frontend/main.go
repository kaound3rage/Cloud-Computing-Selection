// main.go — AgroSense farm-frontend (di folder el-frontend).
//
// Server Go sederhana (net/http saja, tanpa framework berat):
//   GET  /              -> html/index.html
//   GET  /risk          -> html/risk.html
//   GET  /forecasting   -> html/forecasting.html
//   POST /api/predict-risk       -> reverse proxy ke API_PREDICT_RISK
//                                  (inject header x-api-key: API_GATEWAY_KEY)
//   GET  /api/yield-forecast/{crop_id} -> query LANGSUNG ke DynamoDB tabel
//                                  YIELD_HISTORY_TABLE via AWS SDK for Go v2.
//                                  Mengembalikan forecast terbaru untuk crop_id.
//                                  (Jangan proxy endpoint ini ke API Gateway.)
//
// Env vars (lihat .env.example):
//   API_PREDICT_RISK, API_GATEWAY_KEY, YIELD_HISTORY_TABLE, AWS_REGION, PORT.
//
// Skema DynamoDB yang diasumsikan untuk YIELD_HISTORY_TABLE:
//   partition key: crop_id (S), atribut: forecast_period (S),
//   forecast_quantity_ton (N), generated_at (S, ISO8601).
//   Jika tabel memakai sort key forecast_period/generated_at, Query akan
//   mengembalikan item terbaru lebih dulu (ScanIndexForward=false).
package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/feature/dynamodb/attributevalue"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

var (
	// cropIDPattern memvalidasi crop_id di path URL (permissive, aman untuk DynamoDB key).
	cropIDPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

	// ddbClient di-init malas (lazy) agar server tetap bisa start tanpa
	// kredensial AWS (cek DoD: docker run harus listening tanpa kredensial asli).
	ddbOnce   sync.Once
	ddbClient *dynamodb.Client
	ddbErr    error
)

func main() {
	apiPredictRisk := os.Getenv("API_PREDICT_RISK")
	apiKey := os.Getenv("API_GATEWAY_KEY")
	yieldTable := os.Getenv("YIELD_HISTORY_TABLE")
	awsRegion := os.Getenv("AWS_REGION")
	port := os.Getenv("PORT")
	if port == "" {
		port = "3000"
	}

	if apiKey == "" {
		log.Println("[WARN] API_GATEWAY_KEY is not set; x-api-key will be injected as empty")
	}
	if apiPredictRisk == "" {
		log.Println("[WARN] API_PREDICT_RISK is not set; POST /api/predict-risk will return 502")
	}
	if yieldTable == "" {
		log.Println("[WARN] YIELD_HISTORY_TABLE is not set; GET /api/yield-forecast/* will return 502")
	}
	if awsRegion == "" {
		log.Println("[WARN] AWS_REGION is not set; DynamoDB client will rely on SDK default chain")
	}

	mux := http.NewServeMux()

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// "/" di Go 1.22 ServeMux mencocokkan semua path tak terdaftar,
		// jadi tolak path selain "/" agar tidak bocor ke index.
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		http.ServeFile(w, r, "html/index.html")
	})

	mux.HandleFunc("/risk", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		http.ServeFile(w, r, "html/risk.html")
	})

	mux.HandleFunc("/forecasting", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		http.ServeFile(w, r, "html/forecasting.html")
	})

	// Backward-compat: halaman lama /recommendation diarahkan ke /risk.
	mux.HandleFunc("/recommendation", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/risk", http.StatusMovedPermanently)
	})

	mux.HandleFunc("/api/predict-risk", proxyHandler(apiPredictRisk, apiKey))

	// Prefix handler: /api/yield-forecast/{crop_id}
	mux.HandleFunc("/api/yield-forecast/", func(w http.ResponseWriter, r *http.Request) {
		yieldForecastHandler(w, r, yieldTable, awsRegion)
	})
	// Tanpa {crop_id} -> 400 yang jelas (bukan 404 generik).
	mux.HandleFunc("/api/yield-forecast", func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "missing crop_id in path (expected /api/yield-forecast/{crop_id})", http.StatusBadRequest)
	})

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok","service":"farm-frontend"}`))
	})

	server := &http.Server{
		Addr:         ":" + port,
		Handler:      loggingMiddleware(mux),
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	log.Printf("farm-frontend listening on :%s (region=%s table=%s)", port, awsRegion, yieldTable)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server error: %v", err)
	}
}

// loggingMiddleware mencatat setiap request (method, path, durasi).
func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		log.Printf("%s %s %s", r.Method, r.URL.Path, time.Since(start).Round(time.Millisecond))
	})
}

// proxyHandler meneruskan POST /api/predict-risk ke upstream API Gateway
// dengan header x-api-key yang di-inject dari env API_GATEWAY_KEY.
func proxyHandler(target string, apiKey string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if target == "" {
			http.Error(w, "upstream not configured (API_PREDICT_RISK is empty)", http.StatusBadGateway)
			return
		}
		u, err := url.Parse(target)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			http.Error(w, "invalid upstream url", http.StatusInternalServerError)
			return
		}

		proxy := httputil.NewSingleHostReverseProxy(u)
		originalDirector := proxy.Director
		proxy.Director = func(req *http.Request) {
			originalDirector(req)
			req.Header.Set("x-api-key", apiKey)
			// Pastikan upstream menerima JSON (form frontend mengirim JSON).
			if req.Header.Get("Content-Type") == "" {
				req.Header.Set("Content-Type", "application/json")
			}
		}
		proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			log.Printf("proxy error to %s: %v", target, err)
			http.Error(w, "upstream request failed", http.StatusBadGateway)
		}
		proxy.ServeHTTP(w, r)
	}
}

// yieldForecastHandler melayani GET /api/yield-forecast/{crop_id} dengan
// query langsung ke DynamoDB (tidak via API Gateway).
func yieldForecastHandler(w http.ResponseWriter, r *http.Request, table, region string) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	cropID, ok := extractCropID(r.URL.Path)
	if !ok {
		http.Error(w, "missing or invalid crop_id in path (expected /api/yield-forecast/{crop_id})", http.StatusBadRequest)
		return
	}
	if table == "" {
		http.Error(w, "YIELD_HISTORY_TABLE is not configured", http.StatusBadGateway)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	client, err := getDynamoClient(ctx, region)
	if err != nil {
		log.Printf("dynamodb init failed: %v", err)
		http.Error(w, "failed to init dynamodb client", http.StatusInternalServerError)
		return
	}

	items, err := queryYieldHistory(ctx, client, table, cropID)
	if err != nil {
		log.Printf("dynamodb query failed crop=%s: %v", cropID, err)
		http.Error(w, "failed to query yield history", http.StatusBadGateway)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"crop_id":   cropID,
		"forecasts": items,
		"count":     len(items),
	})
}

// extractCropID mengambil {crop_id} dari path /api/yield-forecast/{crop_id}.
// Mengembalikan ok=false jika kosong atau tidak lolos validasi.
func extractCropID(path string) (string, bool) {
	const prefix = "/api/yield-forecast/"
	if !strings.HasPrefix(path, prefix) {
		return "", false
	}
	cropID := strings.Trim(strings.TrimPrefix(path, prefix), "/")
	// Tolak sub-path tambahan (mis. /api/yield-forecast/C001/extra).
	if cropID == "" || strings.Contains(cropID, "/") {
		return "", false
	}
	if !cropIDPattern.MatchString(cropID) {
		return "", false
	}
	return cropID, true
}

// getDynamoClient membuat (sekali saja) client DynamoDB dari default AWS
// config chain. Region dari env AWS_REGION diutamakan bila diisi.
func getDynamoClient(ctx context.Context, region string) (*dynamodb.Client, error) {
	ddbOnce.Do(func() {
		var opts []func(*config.LoadOptions) error
		if region != "" {
			opts = append(opts, config.WithRegion(region))
		}
		cfg, err := config.LoadDefaultConfig(ctx, opts...)
		if err != nil {
			ddbErr = err
			return
		}
		// Jika region masih kosong (tanpa env & tanpa shared config),
		// fallback eksplisit agar error-nya jelas, bukan silent us-east-1.
		if cfg.Region == "" {
			cfg.Region = "ap-southeast-1"
			log.Println("[WARN] AWS region resolved empty; falling back to ap-southeast-1")
		}
		ddbClient = dynamodb.NewFromConfig(cfg)
	})
	return ddbClient, ddbErr
}

// queryYieldHistory mengambil forecast terbaru untuk crop_id.
// Strategi: Query by partition key crop_id, terbaru dulu, limit 20.
// Hasil di-sort menurun berdasarkan generated_at bila tersedia.
func queryYieldHistory(ctx context.Context, client *dynamodb.Client, table, cropID string) ([]map[string]any, error) {
	out, err := client.Query(ctx, &dynamodb.QueryInput{
		TableName:              aws.String(table),
		KeyConditionExpression: aws.String("crop_id = :c"),
		ExpressionAttributeValues: map[string]types.AttributeValue{
			":c": &types.AttributeValueMemberS{Value: cropID},
		},
		ScanIndexForward: aws.Bool(false),
		Limit:            aws.Int32(20),
	})
	if err != nil {
		return nil, err
	}

	items := make([]map[string]any, 0, len(out.Items))
	for _, av := range out.Items {
		var m map[string]any
		if err := attributevalue.UnmarshalMap(av, &m); err != nil {
			// Lewati item korup, jangan gagalkan seluruh response.
			log.Printf("warn: skip unparsable item for crop=%s: %v", cropID, err)
			continue
		}
		items = append(items, m)
	}

	// Sort terbaru dulu bila ada generated_at (ISO8601 string sort = kronologis).
	sort.SliceStable(items, func(i, j int) bool {
		gi, _ := items[i]["generated_at"].(string)
		gj, _ := items[j]["generated_at"].(string)
		if gi != gj {
			return gi > gj
		}
		pi, _ := items[i]["forecast_period"].(string)
		pj, _ := items[j]["forecast_period"].(string)
		return pi > pj
	})
	return items, nil
}

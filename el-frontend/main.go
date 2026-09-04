// el-frontend/main.go
//
// EduPintar frontend server — serves static HTML and reverse-proxies
// API requests to the backend with an x-api-key header injected.
//
// Routes:
//   GET  /               -> html/index.html
//   GET  /recommendation -> html/recommendation.html
//   GET  /forecasting    -> html/forecasting.html
//   POST /api/recommend  -> reverse proxy ke API_RECOMMEND (inject x-api-key)
//   POST /api/forecast   -> reverse proxy ke API_FORECAST (inject x-api-key)
//
// Env vars (lihat .env.example):
//   API_RECOMMEND, API_FORECAST, API_GATEWAY_KEY, PORT

package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"
)

func main() {
	apiRecommend := os.Getenv("API_RECOMMEND")
	apiForecast := os.Getenv("API_FORECAST")
	apiKey := os.Getenv("API_GATEWAY_KEY")
	port := os.Getenv("PORT")
	if port == "" {
		port = "3000"
	}

	if apiKey == "" {
		log.Println("[WARN] API_GATEWAY_KEY is not set; x-api-key will be injected as empty")
	}

	mux := http.NewServeMux()

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		serveStatic(w, r, "html")
	})

	mux.HandleFunc("/recommendation", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "html/recommendation.html")
	})

	mux.HandleFunc("/forecasting", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "html/forecasting.html")
	})

	mux.HandleFunc("/api/recommend", proxyHandler(apiRecommend, apiKey))
	mux.HandleFunc("/api/forecast", proxyHandler(apiForecast, apiKey))

	server := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	log.Printf("el-frontend listening on :%s", port)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server error: %v", err)
	}
}

// serveStatic serves a file from the static root, guarding against
// path traversal by resolving clean paths.
func serveStatic(w http.ResponseWriter, r *http.Request, root string) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	path := r.URL.Path
	if path == "/" {
		path = "/index.html"
	}

	// Prevent directory traversal
	clean := strings.TrimPrefix(strings.TrimLeft(path, "/"), "/")
	if strings.Contains(clean, "..") {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}

	http.ServeFile(w, r, root+"/"+clean)
}

// proxyHandler returns an HTTP handler that reverse-proxies to the given
// target, injecting the x-api-key header on every request.
func proxyHandler(target string, apiKey string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if target == "" {
			http.Error(w, "upstream not configured", http.StatusBadGateway)
			return
		}

		u, err := url.Parse(target)
		if err != nil {
			http.Error(w, "invalid upstream url", http.StatusInternalServerError)
			return
		}

		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		proxy := httputil.NewSingleHostReverseProxy(u)
		originalDirector := proxy.Director
		proxy.Director = func(req *http.Request) {
			originalDirector(req)
			req.Header.Set("x-api-key", apiKey)
			req.Header.Set("Content-Type", "application/json")
		}

		proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			log.Printf("proxy error to %s: %v", target, err)
			http.Error(w, "upstream request failed", http.StatusBadGateway)
		}

		proxy.ServeHTTP(w, r)
	}
}

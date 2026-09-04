// el-frontend/main.go
//
// TODO:
//   GET  /              -> html/index.html
//   GET  /recommendation -> html/recommendation.html
//   GET  /forecasting    -> html/forecasting.html
//   POST /api/recommend  -> reverse proxy ke API_RECOMMEND (inject header x-api-key)
//   POST /api/forecast   -> reverse proxy ke API_FORECAST (inject header x-api-key)
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
)

func main() {
	apiRecommend := os.Getenv("API_RECOMMEND")
	apiForecast := os.Getenv("API_FORECAST")
	apiKey := os.Getenv("API_GATEWAY_KEY")
	port := os.Getenv("PORT")
	if port == "" {
		port = "3000"
	}

	mux := http.NewServeMux()

	// TODO: serve static HTML files
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "html/index.html")
	})
	mux.HandleFunc("/recommendation", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "html/recommendation.html")
	})
	mux.HandleFunc("/forecasting", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "html/forecasting.html")
	})

	// TODO: implement reverse proxy handlers that inject x-api-key
	mux.HandleFunc("/api/recommend", proxyHandler(apiRecommend, apiKey))
	mux.HandleFunc("/api/forecast", proxyHandler(apiForecast, apiKey))

	log.Printf("el-frontend listening on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, mux))
}

// proxyHandler is a stub — implement the actual reverse proxy + header injection.
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
		// TODO: gunakan httputil.NewSingleHostReverseProxy(u) dan Director
		// untuk menambahkan header x-api-key sebelum request diteruskan.
		_ = httputil.NewSingleHostReverseProxy(u)
		http.Error(w, "TODO: implement reverse proxy", http.StatusNotImplemented)
	}
}

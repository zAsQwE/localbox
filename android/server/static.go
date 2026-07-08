package main

//
// LocalBox Go-сервер — раздача веб-клиента (для телефонов игроков). Порт идеи server/client.js.
// Отдаёт файлы из LOCALBOX_CLIENT_DIR; текстовым файлам переписывает адреса Jackbox-API на
// наш serverUrl, чтобы запросы клиента шли на наш сервер. SPA-фолбэк на index.html.
//

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// Хосты Jackbox-API, которые в клиенте надо переписать на наш serverUrl.
var rewriteHosts = []string{
	"ecast.jackboxgames.com", "api.jackbox.tv", "www.jackbox.tv", "jackbox.tv",
	"ecast.jackbox.tv", "bc.jackbox.tv", "blobcast.jackbox.tv",
	"jackbox.ru", "www.jackbox.ru", "jackbox.fun", "www.jackbox.fun",
}

func serveClient(w http.ResponseWriter, req *http.Request) bool {
	if clientDir == "" {
		return false
	}
	rel := strings.TrimPrefix(req.URL.Path, "/")
	if rel == "" {
		rel = "index.html"
	}
	// защита от выхода за пределы каталога
	clean := filepath.Clean("/" + rel)
	full := filepath.Join(clientDir, clean)
	if !strings.HasPrefix(full, filepath.Clean(clientDir)) {
		return false
	}

	info, err := os.Stat(full)
	if err != nil || info.IsDir() {
		// SPA-фолбэк: путь без расширения → index.html
		if filepath.Ext(rel) == "" {
			full = filepath.Join(clientDir, "index.html")
			if _, err := os.Stat(full); err != nil {
				return false
			}
		} else {
			return false // пусть отдаст 404 (или другой источник)
		}
	}

	data, err := os.ReadFile(full)
	if err != nil {
		return false
	}
	ct := contentType(full)
	if isTextType(ct) {
		s := string(data)
		for _, h := range rewriteHosts {
			s = strings.ReplaceAll(s, h, serverURL)
		}
		// Страница по http → понижаем API/ws до http/ws (иначе браузер режет http→https
		// по CORS, а самоподписанный серт не доверен — игрок «не может зайти»).
		if req.TLS == nil {
			s = strings.ReplaceAll(s, "https://"+serverURL, "http://"+serverURL)
			s = strings.ReplaceAll(s, "wss://"+serverURL, "ws://"+serverURL)
		}
		data = []byte(s)
	}
	w.Header().Set("Content-Type", ct)
	w.Write(data)
	return true
}

func contentType(path string) string {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".html", ".htm":
		return "text/html; charset=utf-8"
	case ".js", ".mjs":
		return "application/javascript; charset=utf-8"
	case ".css":
		return "text/css; charset=utf-8"
	case ".json":
		return "application/json; charset=utf-8"
	case ".png":
		return "image/png"
	case ".jpg", ".jpeg":
		return "image/jpeg"
	case ".gif":
		return "image/gif"
	case ".svg":
		return "image/svg+xml"
	case ".webp":
		return "image/webp"
	case ".mp3":
		return "audio/mpeg"
	case ".ogg":
		return "audio/ogg"
	case ".woff":
		return "font/woff"
	case ".woff2":
		return "font/woff2"
	default:
		return "application/octet-stream"
	}
}
func isTextType(ct string) bool {
	return strings.HasPrefix(ct, "text/") || strings.Contains(ct, "javascript") || strings.Contains(ct, "json")
}

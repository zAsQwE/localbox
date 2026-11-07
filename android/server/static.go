package main

import (
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var rewriteHosts = []string{
	"ecast-prod-use2.jackboxgames.com", "ecast.jackboxgames.com", "blobcast.jackboxgames.com",
	"jb-ecast.klucva.ru", "server.rujackbox.loamfy.com", "jack.nevpn2.fenst4r.live", "jack.fenst4r.live",
	"ecast.jackbox.tv", "blobcast.jackbox.tv", "api.jackbox.tv", "bc.jackbox.tv", "dev.jackbox.tv", "www.jackbox.tv", "jackbox.tv",
	"www.jackbox.ru", "jackbox.ru", "www.jackbox.fun", "jackbox.fun", "www.jackbox.su", "jackbox.su",
}
var nestedClientPath = regexp.MustCompile(`^main/(pp\d+|ppad)/([^/]+)(/.*)$`)
var flatClientPath = regexp.MustCompile(`^main/(pp\d+|ppad)-([^/]+)(/.*)$`)
var hostnameCheck = regexp.MustCompile(`((?:window|document)\.location\.hostname\s*(?:===?|!==?)\s*)(["'])([^"']+)(["'])`)
var schemeSetting = regexp.MustCompile(`(\bscheme\s*:\s*|this\.scheme\s*=\s*)(["'])(https|wss)(["'])`)
var integrityAttribute = regexp.MustCompile(`(?i)\s+integrity\s*=\s*(?:"[^"]*"|'[^']*')`)

func layoutPaths(path string) []string {
	if parts := nestedClientPath.FindStringSubmatch(path); parts != nil {
		return []string{path, "main/" + parts[1] + "-" + parts[2] + parts[3]}
	}
	if parts := flatClientPath.FindStringSubmatch(path); parts != nil {
		return []string{path, "main/" + parts[1] + "/" + parts[2] + parts[3]}
	}
	return []string{path}
}
func resolveClient(base, relative string) string {
	if base == "" || strings.ContainsAny(relative, "\\\x00:") {
		return ""
	}
	for _, part := range strings.Split(relative, "/") {
		if strings.HasPrefix(part, ".") {
			return ""
		}
	}
	root, err := filepath.EvalSymlinks(base)
	if err != nil {
		return ""
	}
	full, err := filepath.EvalSymlinks(filepath.Join(root, relative))
	if err != nil {
		return ""
	}
	rel, err := filepath.Rel(root, full)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return ""
	}
	if info, err := os.Stat(full); err == nil && info.Mode().IsRegular() {
		return full
	}
	return ""
}
func rewriteClientText(text, authority string, secure bool) string {
	hostname := authority
	if host, _, err := net.SplitHostPort(authority); err == nil {
		hostname = host
	}
	text = hostnameCheck.ReplaceAllStringFunc(text, func(value string) string {
		parts := hostnameCheck.FindStringSubmatch(value)
		for _, host := range rewriteHosts {
			if parts[3] == host {
				return parts[1] + parts[2] + hostname + parts[4]
			}
		}
		return value
	})
	for _, host := range rewriteHosts {
		text = strings.ReplaceAll(text, host, authority)
	}
	text = integrityAttribute.ReplaceAllString(text, "")
	if !secure {
		text = strings.ReplaceAll(text, "https://"+authority, "http://"+authority)
		text = strings.ReplaceAll(text, "wss://"+authority, "ws://"+authority)
		text = schemeSetting.ReplaceAllStringFunc(text, func(value string) string {
			p := schemeSetting.FindStringSubmatch(value)
			scheme := "http"
			if p[3] == "wss" {
				scheme = "ws"
			}
			return p[1] + p[2] + scheme + p[4]
		})
	}
	return text
}
func serveClient(w http.ResponseWriter, req *http.Request) bool {
	if clientDir == "" {
		return false
	}
	relative := strings.TrimPrefix(req.URL.Path, "/")
	if relative == "" {
		relative = "index.html"
	}
	dirs := []string{clientDir, filepath.Join(filepath.Dir(clientDir), "client"), filepath.Join(filepath.Dir(clientDir), "client-ru")}
	// Navigation always uses the selected language. Only asset files use the other client's fallback.
	if relative == "index.html" || filepath.Ext(relative) == "" {
		dirs = dirs[:1]
	}
	full := ""
	for _, dir := range dirs {
		for _, candidate := range layoutPaths(relative) {
			if full = resolveClient(dir, candidate); full != "" {
				break
			}
		}
		if full != "" {
			break
		}
	}
	if full == "" && filepath.Ext(relative) == "" {
		full = resolveClient(clientDir, "index.html")
	}
	if full == "" {
		return false
	}
	ct := contentType(full)
	w.Header().Set("Content-Type", ct)
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if !isTextType(ct) {
		http.ServeFile(w, req, full)
		return true
	}
	data, err := os.ReadFile(full)
	if err != nil {
		return false
	}
	data = []byte(rewriteClientText(string(data), req.Host, req.TLS != nil))
	w.Header().Set("Cache-Control", "no-cache")
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
	case ".json", ".jet", ".map":
		return "application/json; charset=utf-8"
	case ".webmanifest":
		return "application/manifest+json; charset=utf-8"
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
	case ".ico":
		return "image/x-icon"
	case ".mp3":
		return "audio/mpeg"
	case ".ogg":
		return "audio/ogg"
	case ".wav":
		return "audio/wav"
	case ".m4a":
		return "audio/mp4"
	case ".mp4":
		return "video/mp4"
	case ".webm":
		return "video/webm"
	case ".woff":
		return "font/woff"
	case ".woff2":
		return "font/woff2"
	case ".ttf":
		return "font/ttf"
	case ".otf":
		return "font/otf"
	default:
		return "application/octet-stream"
	}
}
func isTextType(ct string) bool {
	return strings.HasPrefix(ct, "text/") || strings.Contains(ct, "javascript") || strings.Contains(ct, "json") || strings.Contains(ct, "svg")
}

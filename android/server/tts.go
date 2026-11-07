package main

// Bounded, in-process bridge to Android's offline TextToSpeech engine. Android
// writes a private WAV; the game's normal /tts/generate request waits for it.
import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type speechJob struct {
	ID         string  `json:"id"`
	Text       string  `json:"text"`
	Rate       float64 `json:"rate"`
	File       string  `json:"file"`
	done       chan string
	owner      *speechSession
	dispatched bool
}

var speech = struct {
	sync.Mutex
	ready   bool
	message string
	jobs    map[string]*speechJob
	queue   []string
	retired map[string]string
}{message: "Озвучка ещё не готова", jobs: make(map[string]*speechJob), retired: make(map[string]string)}
var speechFile = regexp.MustCompile(`^[a-f0-9]{32}\.wav$`)

// Accessed only while holding engineMu, like Client/Room state.
var speechOrigins = map[string]bool{}

func requestOrigin(r *http.Request) string {
	scheme := "http"
	if r.TLS != nil {
		scheme = "https"
	}
	return scheme + "://" + r.Host
}

// A game on loopback can publish an audio URL in a room entity. Controllers
// need their own web port and protocol, especially when they connect over HTTPS.
func controllerSpeechURLs(value interface{}, client *Client) interface{} {
	if client == nil || client.isHost || client.role == "host" || client.origin == "" {
		return value
	}
	switch item := value.(type) {
	case string:
		parsed, err := url.Parse(item)
		if err == nil && (parsed.Scheme == "http" || parsed.Scheme == "https") && parsed.User == nil && (speechOrigins[parsed.Host] || parsed.Host == serverURL) && strings.HasPrefix(parsed.Path, "/tts/") && speechFile.MatchString(strings.TrimPrefix(parsed.Path, "/tts/")) {
			origin, _ := url.Parse(client.origin)
			parsed.Scheme = origin.Scheme
			parsed.Host = origin.Host
			return parsed.String()
		}
	case map[string]interface{}:
		copy := make(map[string]interface{}, len(item))
		for key, nested := range item {
			copy[key] = controllerSpeechURLs(nested, client)
		}
		return copy
	case []interface{}:
		copy := make([]interface{}, len(item))
		for index, nested := range item {
			copy[index] = controllerSpeechURLs(nested, client)
		}
		return copy
	}
	return value
}
func initSpeechOrigins(host string, ports ...int) {
	speechOrigins = map[string]bool{}
	for _, port := range ports {
		for _, address := range []string{host, "127.0.0.1", "localhost"} {
			speechOrigins[net.JoinHostPort(address, itoa(port))] = true
		}
	}
}

func setSpeechState(ready bool, message string) {
	speech.Lock()
	defer speech.Unlock()
	speech.ready = ready
	speech.message = message
	if !ready {
		for id := range speech.jobs {
			cancelSpeechJob(id, message)
		}
	}
}
func speechState() map[string]interface{} {
	speech.Lock()
	defer speech.Unlock()
	return map[string]interface{}{"ready": speech.ready, "message": speech.message}
}
func nextSpeechJob() string {
	speech.Lock()
	defer speech.Unlock()
	for len(speech.queue) > 0 {
		id := speech.queue[0]
		speech.queue = speech.queue[1:]
		if job := speech.jobs[id]; job != nil {
			job.dispatched = true
			data, _ := json.Marshal(job)
			return string(data)
		}
	}
	return ""
}
func finishSpeechJob(id, failure string) {
	speech.Lock()
	defer speech.Unlock()
	job := speech.jobs[id]
	if job == nil {
		if path, exists := speech.retired[id]; exists {
			os.Remove(path)
			delete(speech.retired, id)
		}
		return
	}
	if failure == "" {
		file, err := os.Open(job.File)
		if err != nil {
			failure = "Не создан WAV озвучки"
		} else {
			header := make([]byte, 12)
			_, err = io.ReadFull(file, header)
			info, statErr := file.Stat()
			file.Close()
			if err != nil || statErr != nil || info.Size() < 44 || info.Size() > 16<<20 || string(header[:4]) != "RIFF" || string(header[8:]) != "WAVE" {
				failure = "Движок вернул некорректный WAV"
			}
		}
		if failure == "" {
			if err := os.Rename(job.File, filepath.Join(filepath.Dir(job.File), id+".wav")); err != nil {
				failure = err.Error()
			}
		}
	}
	if failure != "" {
		os.Remove(job.File)
		if job.owner != nil {
			delete(job.owner.files, id)
		}
	}
	delete(speech.jobs, id)
	job.done <- failure
}
func speechRate(value interface{}) float64 {
	text := strings.TrimSpace(fmt.Sprint(value))
	rate, err := strconv.ParseFloat(strings.TrimSuffix(text, "%"), 64)
	if err != nil || math.IsNaN(rate) || math.IsInf(rate, 0) {
		return 1
	}
	if strings.HasSuffix(text, "%") {
		rate /= 100
	}
	if rate < 0.5 {
		return 0.5
	}
	if rate > 2 {
		return 2
	}
	return rate
}
func pruneSpeech(directory string) {
	entries, _ := os.ReadDir(directory)
	var files []os.FileInfo
	var size int64
	for _, entry := range entries {
		if speechFile.MatchString(entry.Name()) {
			if info, err := entry.Info(); err == nil && info.Mode().IsRegular() {
				files = append(files, info)
				size += info.Size()
			}
		}
	}
	sort.Slice(files, func(i, j int) bool { return files[i].ModTime().Before(files[j].ModTime()) })
	for len(files) >= 128 || size > 64<<20 {
		if len(files) == 0 {
			break
		}
		os.Remove(filepath.Join(directory, files[0].Name()))
		size -= files[0].Size()
		files = files[1:]
	}
}
func serveSpeech(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Path == "/tts/generate" {
		if r.Method != "POST" {
			w.Header().Set("Allow", "POST")
			http.Error(w, "method not allowed", 405)
			return true
		}
		var body struct {
			Text     string      `json:"text"`
			Rate     interface{} `json:"rate"`
			RoomCode string      `json:"roomCode"`
			RoomID   string      `json:"roomId"`
			Code     string      `json:"code"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&body); err != nil || strings.TrimSpace(body.Text) == "" {
			writeJSON(w, 400, map[string]interface{}{"success": false, "error": "missing or invalid text"})
			return true
		}
		text := []rune(body.Text)
		if len(text) > 900 {
			text = text[:900]
		}
		code := body.RoomCode
		if code == "" {
			code = body.RoomID
		}
		if code == "" {
			code = body.Code
		}
		owner, root := speechRequestContext(r, code)
		speech.Lock()
		if owner != nil && owner.closed {
			speech.Unlock()
			writeJSON(w, 410, map[string]interface{}{"success": false, "error": "Партия завершена"})
			return true
		}
		if !speech.ready {
			message := speech.message
			speech.Unlock()
			writeJSON(w, 503, map[string]interface{}{"success": false, "error": message})
			return true
		}
		if len(speech.jobs) >= 4 {
			speech.Unlock()
			writeJSON(w, 429, map[string]interface{}{"success": false, "error": "Очередь озвучки занята"})
			return true
		}
		directory := filepath.Join(root, "tts")
		if err := os.MkdirAll(directory, 0700); err != nil {
			speech.Unlock()
			http.Error(w, "TTS storage unavailable", 500)
			return true
		}
		pruneSpeech(directory)
		var token [16]byte
		if _, err := rand.Read(token[:]); err != nil {
			speech.Unlock()
			http.Error(w, "TTS token unavailable", 500)
			return true
		}
		id := hex.EncodeToString(token[:])
		job := &speechJob{ID: id, Text: string(text), Rate: speechRate(body.Rate), File: filepath.Join(directory, id+".part.wav"), done: make(chan string, 1), owner: owner}
		if owner != nil {
			owner.files[id] = job.File
		}
		speech.jobs[id] = job
		speech.queue = append(speech.queue, id)
		speech.Unlock()
		defer func() {
			speech.Lock()
			cancelSpeechJob(id, "Запрос озвучки отменён")
			speech.Unlock()
			os.Remove(job.File)
		}()
		timer := time.NewTimer(45 * time.Second)
		defer timer.Stop()
		select {
		case failure := <-job.done:
			if failure != "" {
				writeJSON(w, 503, map[string]interface{}{"success": false, "error": failure})
				return true
			}
			scheme := "http"
			if r.TLS != nil {
				scheme = "https"
			}
			writeJSON(w, 200, map[string]interface{}{"success": true, "url": scheme + "://" + r.Host + "/tts/" + id + ".wav"})
		case <-r.Context().Done():
		case <-timer.C:
			writeJSON(w, 504, map[string]interface{}{"success": false, "error": "Истекло время ожидания озвучки"})
		}
		return true
	}
	if strings.HasPrefix(r.URL.Path, "/tts/") {
		name := strings.TrimPrefix(r.URL.Path, "/tts/")
		if !speechFile.MatchString(name) {
			http.NotFound(w, r)
			return true
		}
		w.Header().Set("Content-Type", "audio/wav")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Cache-Control", "no-store")
		engineMu.Lock()
		path := filepath.Join(storageDir, "tts", name)
		engineMu.Unlock()
		http.ServeFile(w, r, path)
		return true
	}
	return false
}

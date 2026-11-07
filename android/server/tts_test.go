package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func speechFixture(t *testing.T) *httptest.Server {
	t.Helper()
	old := storageDir
	storageDir = t.TempDir()
	setSpeechState(true, "fixture")
	server := httptest.NewServer(http.HandlerFunc(rootHandler))
	t.Cleanup(func() { setSpeechState(false, "stopped"); server.Close(); storageDir = old })
	return server
}
func awaitSpeech(t *testing.T) speechJob {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if next := nextSpeechJob(); next != "" {
			var job speechJob
			if err := json.Unmarshal([]byte(next), &job); err != nil {
				t.Fatal(err)
			}
			return job
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("no speech job")
	return speechJob{}
}
func TestSpeechGeneratedWAVAndHTTPSOrigin(t *testing.T) {
	server := speechFixture(t)
	// Use the real HTTPS handler so the returned audio URL keeps the requesting protocol and port.
	tlsServer := httptest.NewTLSServer(http.HandlerFunc(rootHandler))
	defer tlsServer.Close()
	response := make(chan *http.Response, 1)
	requestError := make(chan error, 1)
	go func() {
		r, err := tlsServer.Client().Post(tlsServer.URL+"/tts/generate", "application/json", strings.NewReader(`{"text":"Привет, мир!","voice":"Matthew","rate":"125%"}`))
		if err != nil {
			requestError <- err
			return
		}
		response <- r
	}()
	job := awaitSpeech(t)
	if job.Text != "Привет, мир!" || job.Rate != 1.25 {
		t.Fatal(job)
	}
	wav := make([]byte, 48)
	copy(wav, "RIFF")
	copy(wav[8:], "WAVE")
	wav[44] = 15
	if err := os.WriteFile(job.File, wav, 0600); err != nil {
		t.Fatal(err)
	}
	finishSpeechJob(job.ID, "")
	select {
	case r := <-response:
		defer r.Body.Close()
		var result struct {
			Success bool
			URL     string
		}
		json.NewDecoder(r.Body).Decode(&result)
		if r.StatusCode != 200 || !result.Success || !strings.HasPrefix(result.URL, tlsServer.URL+"/tts/") {
			t.Fatal(result, r.StatusCode)
		}
		audio, err := tlsServer.Client().Get(result.URL)
		if err != nil {
			t.Fatal(err)
		}
		defer audio.Body.Close()
		data, _ := io.ReadAll(audio.Body)
		if audio.Header.Get("Content-Type") != "audio/wav" || !bytes.Equal(data, wav) {
			t.Fatal("bad audio", audio.StatusCode)
		}
		if _, err := os.Stat(job.File); !os.IsNotExist(err) {
			t.Fatal("staging WAV remained")
		}
	case err := <-requestError:
		t.Fatal(err)
	case <-time.After(3 * time.Second):
		t.Fatal("generation did not complete")
	}
	r, err := http.Get(server.URL + "/tts/not-a-file.wav")
	if err != nil {
		t.Fatal(err)
	}
	r.Body.Close()
	if r.StatusCode != 404 {
		t.Fatal(r.StatusCode)
	}
}
func TestSpeechCancellationAndEngineUnavailable(t *testing.T) {
	server := speechFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	request, _ := http.NewRequestWithContext(ctx, "POST", server.URL+"/tts/generate", strings.NewReader(`{"text":"test"}`))
	done := make(chan struct{})
	go func() {
		r, _ := http.DefaultClient.Do(request)
		if r != nil {
			r.Body.Close()
		}
		close(done)
	}()
	job := awaitSpeech(t)
	cancel()
	<-done
	deadline := time.Now().Add(3 * time.Second)
	for {
		speech.Lock()
		remaining := len(speech.jobs)
		queued := len(speech.queue)
		speech.Unlock()
		if remaining == 0 && queued == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("cancelled request retained")
		}
		time.Sleep(time.Millisecond)
	}
	// A late callback after cancellation must discard its private partial file.
	os.WriteFile(job.File, []byte("late"), 0600)
	finishSpeechJob(job.ID, "")
	if _, err := os.Stat(job.File); !os.IsNotExist(err) {
		t.Fatal("late partial remained")
	}
	setSpeechState(false, "Нет офлайн-голосов")
	r, err := http.Post(server.URL+"/tts/generate", "application/json", strings.NewReader(`{"text":"test"}`))
	if err != nil {
		t.Fatal(err)
	}
	defer r.Body.Close()
	body, _ := io.ReadAll(r.Body)
	if r.StatusCode != 503 || !strings.Contains(string(body), "Нет офлайн-голосов") {
		t.Fatal(r.StatusCode, string(body))
	}
}
func TestSpeechBoundedQueueAndStop(t *testing.T) {
	server := speechFixture(t)
	responses := make(chan int, 4)
	for index := 0; index < 4; index++ {
		go func() {
			r, err := http.Post(server.URL+"/tts/generate", "application/json", strings.NewReader(`{"text":"waiting"}`))
			if err != nil {
				responses <- 0
				return
			}
			r.Body.Close()
			responses <- r.StatusCode
		}()
	}
	deadline := time.Now().Add(3 * time.Second)
	for {
		speech.Lock()
		count := len(speech.jobs)
		speech.Unlock()
		if count == 4 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("queue not filled")
		}
		time.Sleep(time.Millisecond)
	}
	r, err := http.Post(server.URL+"/tts/generate", "application/json", strings.NewReader(`{"text":"overflow"}`))
	if err != nil {
		t.Fatal(err)
	}
	r.Body.Close()
	if r.StatusCode != 429 {
		t.Fatal(r.StatusCode)
	}
	setSpeechState(false, "Сервер остановлен")
	for index := 0; index < 4; index++ {
		select {
		case status := <-responses:
			if status != 503 {
				t.Fatal(status)
			}
		case <-time.After(3 * time.Second):
			t.Fatal("stop left a pending request")
		}
	}
}
func TestSpeechInvalidAudioAndRate(t *testing.T) {
	server := speechFixture(t)
	response := make(chan int, 1)
	go func() {
		r, err := http.Post(server.URL+"/tts/generate", "application/json", strings.NewReader(`{"text":"test","rate":"NaN"}`))
		if err != nil {
			response <- 0
			return
		}
		r.Body.Close()
		response <- r.StatusCode
	}()
	job := awaitSpeech(t)
	if job.Rate != 1 {
		t.Fatal(job.Rate)
	}
	os.WriteFile(job.File, []byte("not audio"), 0600)
	finishSpeechJob(job.ID, "")
	if status := <-response; status != 503 {
		t.Fatal(status)
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(job.File), job.ID+".wav")); !os.IsNotExist(err) {
		t.Fatal("invalid audio was published")
	}
}

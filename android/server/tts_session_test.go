package main

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func TestSpeechPartyCleanup(t *testing.T) {
	for _, ending := range []string{"blob", "event", "disconnect", "stop"} {
		t.Run(ending, func(t *testing.T) {
			server := speechFixture(t)
			engineMu.Lock()
			oldRooms := rooms
			rooms = map[string]*Room{}
			engineMu.Unlock()
			var clients []*websocket.Conn
			t.Cleanup(func() {
				for _, client := range clients {
					client.Close()
				}
				connectionWorkers.Wait()
				engineMu.Lock()
				rooms = oldRooms
				engineMu.Unlock()
			})
			create := func(tag string) (string, *websocket.Conn) {
				t.Helper()
				r, err := http.Post(server.URL+"/api/v2/rooms", "application/json", strings.NewReader(`{"userId":"host","appTag":"`+tag+`"}`))
				if err != nil {
					t.Fatal(err)
				}
				var body struct{ Body struct{ Code, Token string } }
				json.NewDecoder(r.Body).Decode(&body)
				r.Body.Close()
				client := dial(t, wsURL(server, "/api/v2/rooms/"+body.Body.Code+"/play?role=host&host-token="+body.Body.Token+"&user-id=host"))
				clients = append(clients, client)
				readUntil(t, client, "client/welcome")
				return body.Body.Code, client
			}
			request := func(code string) <-chan int {
				result := make(chan int, 1)
				go func() {
					r, err := http.Post(server.URL+"/tts/generate", "application/json", strings.NewReader(`{"text":"test","roomCode":"`+code+`"}`))
					if err != nil {
						result <- 0
						return
					}
					r.Body.Close()
					result <- r.StatusCode
				}()
				return result
			}
			complete := func(job speechJob) string {
				t.Helper()
				wav := make([]byte, 48)
				copy(wav, "RIFF")
				copy(wav[8:], "WAVE")
				if err := os.WriteFile(job.File, wav, 0600); err != nil {
					t.Fatal(err)
				}
				finishSpeechJob(job.ID, "")
				return filepath.Join(filepath.Dir(job.File), job.ID+".wav")
			}
			checkStatus := func(url string, expected int) {
				t.Helper()
				r, err := http.Get(url)
				if err != nil {
					t.Fatal(err)
				}
				r.Body.Close()
				if r.StatusCode != expected {
					t.Fatalf("GET %s: %d, want %d", url, r.StatusCode, expected)
				}
			}
			code, host := create("rapbattle")
			// Real game requests have no room code: identify the sole connected host.
			first := request("")
			job := awaitSpeech(t)
			published := complete(job)
			if status := <-first; status != 200 {
				t.Fatal(status)
			}
			checkStatus(server.URL+"/tts/"+job.ID+".wav", 200)
			otherCode, _ := create("quiplash2")
			other := request(otherCode)
			otherJob := awaitSpeech(t)
			otherFile := complete(otherJob)
			if status := <-other; status != 200 {
				t.Fatal(status)
			}
			// A round scoreboard is not the end of the party.
			send(t, host, map[string]interface{}{"opcode": "object/set", "params": map[string]interface{}{"key": "bc:room", "val": map[string]interface{}{"state": "Scoreboard", "gameFinished": false}}})
			readUntil(t, host, "ok")
			checkStatus(server.URL+"/tts/"+job.ID+".wav", 200)
			// A player cannot end the party or trigger cleanup through a writable blob.
			player := dial(t, wsURL(server, "/api/v2/rooms/"+code+"/play?role=player&user-id=player&name=Player"))
			clients = append(clients, player)
			readUntil(t, player, "client/welcome")
			send(t, player, map[string]interface{}{"opcode": "game/ended", "params": map[string]interface{}{}})
			if result(readUntil(t, player, "error"))["code"] != float64(2023) {
				t.Fatal("player ended game")
			}
			engineMu.Lock()
			rooms[code].speechEntity("bc:room", map[string]interface{}{"gameFinished": true}, true)
			engineMu.Unlock()
			checkStatus(server.URL+"/tts/"+job.ID+".wav", 200)
			pending := request(code)
			running := awaitSpeech(t)
			queued := request(code)
			deadline := time.Now().Add(3 * time.Second)
			for {
				speech.Lock()
				count := len(speech.queue)
				speech.Unlock()
				if count == 1 {
					break
				}
				if time.Now().After(deadline) {
					t.Fatal("no queued speech")
				}
				time.Sleep(time.Millisecond)
			}
			switch ending {
			case "blob":
				send(t, host, map[string]interface{}{"opcode": "object/set", "params": map[string]interface{}{"key": "bc:room", "val": map[string]interface{}{"gameFinished": true}}})
				readUntil(t, host, "ok")
			case "event":
				send(t, host, map[string]interface{}{"opcode": "game/ended", "params": map[string]interface{}{}})
				readUntil(t, host, "ok")
			case "disconnect":
				host.Close()
			case "stop":
				stopEmbedded()
			}
			for _, response := range []<-chan int{pending, queued} {
				select {
				case status := <-response:
					if status != 503 {
						t.Fatal(status)
					}
				case <-time.After(3 * time.Second):
					t.Fatal("party left pending synthesis")
				}
			}
			if nextSpeechJob() != "" {
				t.Fatal("ended party remained queued")
			}
			checkStatus(server.URL+"/tts/"+job.ID+".wav", 404)
			if _, err := os.Stat(published); !os.IsNotExist(err) {
				t.Fatal("party WAV remains")
			}
			if _, err := os.Stat(otherFile); err != nil {
				t.Fatal("other game's audio was deleted", err)
			}
			if ending == "stop" {
				// A restart may use another storage folder before Android calls back.
				engineMu.Lock()
				storageDir = t.TempDir()
				engineMu.Unlock()
			}
			if ending == "event" || ending == "blob" {
				if status := <-request(code); status != 410 {
					t.Fatal("closed party accepted speech", status)
				}
				if ending == "event" {
					send(t, host, map[string]interface{}{"opcode": "game/started", "params": map[string]interface{}{}})
				} else {
					send(t, host, map[string]interface{}{"opcode": "object/set", "params": map[string]interface{}{"key": "bc:customer:player", "val": map[string]interface{}{"state": "EnterSingleText"}}})
				}
				readUntil(t, host, "ok")
				replay := request(code)
				replayJob := awaitSpeech(t)
				replayFile := complete(replayJob)
				if status := <-replay; status != 200 {
					t.Fatal("replay", status)
				}
				// The old engine can recreate its staging file after cleanup.
				os.WriteFile(running.File, []byte("late Android output"), 0600)
				finishSpeechJob(running.ID, "")
				if _, err := os.Stat(replayFile); err != nil {
					t.Fatal("late callback damaged replay", err)
				}
			} else {
				os.WriteFile(running.File, []byte("late Android output"), 0600)
				finishSpeechJob(running.ID, "")
			}
			if _, err := os.Stat(running.File); !os.IsNotExist(err) {
				t.Fatal("late staging audio remains")
			}
			if _, err := os.Stat(filepath.Join(filepath.Dir(running.File), running.ID+".wav")); !os.IsNotExist(err) {
				t.Fatal("late audio published")
			}
		})
	}
}

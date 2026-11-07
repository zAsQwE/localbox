package main

import (
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// Room holds the current party; speech.Mutex guards its files and closed flag.
// A replay gets a different session so an old callback cannot delete new audio.
type speechSession struct {
	closed bool
	files  map[string]string // job ID -> absolute private staging path
}

// Called with engineMu held. Lock order is always engineMu -> speech.Mutex.
func (r *Room) startSpeechSession() {
	if !strings.EqualFold(r.appTag, "rapbattle") {
		return
	}
	speech.Lock()
	defer speech.Unlock()
	if r.speechSession == nil || r.speechSession.closed {
		r.speechSession = &speechSession{files: make(map[string]string)}
	}
}

func (r *Room) endSpeechSession() {
	speech.Lock()
	defer speech.Unlock()
	owner := r.speechSession
	if owner == nil || owner.closed {
		return
	}
	owner.closed = true
	for id, job := range speech.jobs {
		if job.owner == owner {
			cancelSpeechJob(id, "Партия завершена")
		}
	}
	for id, staging := range owner.files {
		os.Remove(staging)
		os.Remove(filepath.Join(filepath.Dir(staging), id+".wav"))
	}
	owner.files = nil
}

// notifyHost is false only for entities written by the trusted game host.
func (r *Room) speechEntity(key string, value interface{}, notifyHost bool) {
	if notifyHost || !strings.EqualFold(r.appTag, "rapbattle") {
		return
	}
	blob, ok := value.(map[string]interface{})
	if !ok {
		return
	}
	if (key == "room" || key == "bc:room") && blob["gameFinished"] == true {
		r.endSpeechSession()
	} else if blob["state"] == "EnterSingleText" {
		r.startSpeechSession()
	}
}

func speechRequestContext(req *http.Request, code string) (*speechSession, string) {
	engineMu.Lock()
	defer engineMu.Unlock()
	var active, matches []*Room
	var selected *Room
	address, _, _ := net.SplitHostPort(req.RemoteAddr)
	address = strings.TrimPrefix(address, "::ffff:")
	for _, room := range rooms {
		if room.host == nil || !room.host.connected {
			continue
		}
		active = append(active, room)
		if code != "" && room.code == code {
			selected = room
		}
		if client := room.host.client; client != nil && client.conn != nil {
			host, _, _ := net.SplitHostPort(client.conn.RemoteAddr().String())
			if strings.TrimPrefix(host, "::ffff:") == address {
				matches = append(matches, room)
			}
		}
	}
	if selected == nil && code == "" {
		if len(matches) == 1 {
			selected = matches[0]
		} else if len(active) == 1 {
			selected = active[0]
		}
	}
	if selected != nil {
		return selected.speechSession, storageDir
	}
	return nil, storageDir
}

// speech.Mutex is held. Remember dispatched paths until Android's late callback,
// including when the server has already restarted with another storage folder.
func cancelSpeechJob(id, reason string) {
	job := speech.jobs[id]
	if job == nil {
		return
	}
	if job.dispatched {
		speech.retired[id] = job.File
	}
	delete(speech.jobs, id)
	for index, queued := range speech.queue {
		if queued == id {
			speech.queue = append(speech.queue[:index], speech.queue[index+1:]...)
			break
		}
	}
	os.Remove(job.File)
	if job.owner != nil {
		delete(job.owner.files, id)
	}
	job.done <- reason
}

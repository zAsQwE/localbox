package main

//
// LocalBox Go-сервер — артефакты (рисунки/песни). Порт server/lib/artifacts.js.
// Хранит storage/artifacts/<categoryId>_<id>.json.
//

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync/atomic"
)

var artifactSeq int64 = 1

func artifactsDir() string { return filepath.Join(storageDir, "artifacts") }

func artifactCreate(categoryID string, blob interface{}) string {
	id := itoa(int(atomic.AddInt64(&artifactSeq, 1)))
	_ = os.MkdirAll(artifactsDir(), 0o755)
	b, _ := json.Marshal(blob)
	_ = os.WriteFile(filepath.Join(artifactsDir(), categoryID+"_"+id+".json"), b, 0o644)
	return id
}

func artifactGet(categoryID, id string) json.RawMessage {
	b, err := os.ReadFile(filepath.Join(artifactsDir(), categoryID+"_"+id+".json"))
	if err != nil {
		return nil
	}
	return json.RawMessage(b)
}

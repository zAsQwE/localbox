package main

//
// LocalBox Go-сервер — мелкие помощники: приведение типов из разобранного JSON и лог.
//

import (
	"log"
	"os"
)

var debug = os.Getenv("LOCALBOX_DEBUG") == "1"

func logf(format string, a ...interface{}) { log.Printf(format, a...) }
func dbg(format string, a ...interface{}) {
	if debug {
		log.Printf(format, a...)
	}
}

func str(v interface{}) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func toBool(v interface{}) bool {
	b, _ := v.(bool)
	return b
}

// toFloat — число из разобранного JSON (всегда float64) или из int.
func toFloat(v interface{}) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case int:
		return float64(n), true
	case int64:
		return float64(n), true
	}
	return 0, false
}
func toFloatOr(v interface{}, def float64) float64 {
	if f, ok := toFloat(v); ok {
		return f
	}
	return def
}
func toInt(v interface{}) (int, bool) {
	if f, ok := toFloat(v); ok {
		return int(f), true
	}
	return 0, false
}

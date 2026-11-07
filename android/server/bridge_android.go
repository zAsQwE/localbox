//go:build android && cgo

package main

/*
#include <stdlib.h>
*/
import "C"

//export LocalBoxStart
func LocalBoxStart(directory, host *C.char, gamePort, webPort C.int) *C.char {
	if err := startEmbedded(C.GoString(directory), C.GoString(host), int(gamePort), int(webPort)); err != nil {
		return C.CString(err.Error())
	}
	return nil
}

//export LocalBoxStop
func LocalBoxStop() { stopEmbedded() }

//export LocalBoxStatus
func LocalBoxStatus() *C.char { return C.CString(embeddedStatus()) }

//export LocalBoxSpeechState
func LocalBoxSpeechState(ready C.int, message *C.char) {
	setSpeechState(ready != 0, C.GoString(message))
}

//export LocalBoxSpeechNext
func LocalBoxSpeechNext() *C.char { return C.CString(nextSpeechJob()) }

//export LocalBoxSpeechDone
func LocalBoxSpeechDone(id, failure *C.char) { finishSpeechJob(C.GoString(id), C.GoString(failure)) }

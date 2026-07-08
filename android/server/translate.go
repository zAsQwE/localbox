package main

//
// LocalBox Go-сервер — перевод внутренних сообщений (entity-store, Ecast) в события Blobcast
// (старый протокол). Порт server/lib/translate.js. Пустая карта = слать нечего.
//

import "strings"

func translate(msg map[string]interface{}, roomID, ctxUserID, hostUserID string) map[string]interface{} {
	r, _ := msg["result"].(map[string]interface{})
	if r == nil {
		r = map[string]interface{}{}
	}
	opcode, _ := msg["opcode"].(string)

	switch opcode {
	case "client/connected":
		if str(r["role"]) != "player" {
			return nil
		}
		event := "CustomerJoinedRoom"
		if toBool(r["reconnect"]) {
			event = "CustomerRejoinedRoom"
		}
		return map[string]interface{}{
			"type": "Event", "event": event, "roomId": roomID,
			"customerUserId": str(r["userId"]), "customerName": str(r["name"]),
			"options": map[string]interface{}{"roomcode": "", "name": str(r["name"]), "email": "", "phone": ""},
		}
	case "client/disconnected", "client/kicked":
		if str(r["role"]) != "player" {
			return nil
		}
		return map[string]interface{}{"type": "Event", "event": "CustomerLeftRoom", "roomId": roomID, "customerUserId": ctxUserID}
	case "client/send":
		return map[string]interface{}{"type": "Event", "event": "CustomerMessage", "roomId": roomID, "userId": ctxUserID, "message": r["body"]}
	case "client/welcome":
		if ctxUserID == hostUserID {
			return nil // хосту JoinRoom не нужен
		}
		joinType := "audience"
		if r["profile"] != nil {
			joinType = "player"
		}
		return map[string]interface{}{
			"type": "Result", "action": "JoinRoom", "success": true, "initial": !toBool(r["reconnect"]),
			"roomId": roomID, "joinType": joinType, "userId": ctxUserID,
			"options": map[string]interface{}{"roomcode": "", "name": str(r["name"]), "email": "", "phone": ""},
		}
	case "room/exit":
		return map[string]interface{}{"type": "Event", "event": "RoomDestroyed", "roomId": roomID}
	case "object":
		key := str(r["key"])
		if strings.HasPrefix(key, "bc:") {
			event := "CustomerBlobChanged"
			if key == "bc:room" {
				event = "RoomBlobChanged"
			}
			return map[string]interface{}{"type": "Event", "event": event, "roomId": roomID, "blob": r["val"]}
		}
		return nil
	default:
		return nil
	}
}

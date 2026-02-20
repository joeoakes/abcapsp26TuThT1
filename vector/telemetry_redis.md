# Team 1 Maze Telemetry + Mission Logging (Redis)

## Project Summary

This project extends the SDL2 Maze game to send structured JSON data to HTTPS servers and store it in Redis.

The maze client sends:

1. **Telemetry JSON** (every move)
2. **Mission JSON** (summary of a full maze run)

The AI server receives the JSON payloads and saves them in Redis using team-specific keys so the professor can identify our data separately.

**Team name / namespace:** `team1tt`

---

## What the Maze App Sends

### 1) Telemetry JSON (Move-by-Move)

The maze app sends telemetry every time the player moves.

### Example telemetry JSON (from maze terminal)
```
{"team": "team1tt","event_type": "player_move","input": {"device":"keyboard","move_sequence":135},"player": {"position":{"x":20,"y":13}},"goal_reached":false,"timestamp":"2026-02-20T20:12:57Z","session_id":"53418bfd-ef31-4237-8e0e-6c228d6c01f4"}
Example telemetry JSON when goal is reached
{"team": "team1tt","event_type": "player_move","input": {"device":"keyboard","move_sequence":136},"player": {"position":{"x":20,"y":14}},"goal_reached":true,"timestamp":"2026-02-20T20:12:58Z","session_id":"53418bfd-ef31-4237-8e0e-6c228d6c01f4"}
```
### 2) Mission JSON (Full Maze Session Summary)
At the end of a mission (success or abort), the maze app prints and sends a mission payload.
## Example mission JSON (success)
```
{"team":"team1tt","mission_id":"MISSION_001","robot_id":"MAZE_CLIENT_01","mission_type":"maze_run","start_time":1771618188,"end_time":1771618378,"moves_left_turn":25,"moves_right_turn":45,"moves_straight":26,"moves_reverse":40,"moves_total":136,"distance_traveled":136.00,"duration_seconds":190,"mission_result":"success","abort_reason":"none"}
```
### Example Maze App Terminal Output
This is what the local maze terminal looks like while running:
```
Posting telemetry JSON:
{"team": "team1tt","event_type": "player_move","input": {"device":"keyboard","move_sequence":135},"player": {"position":{"x":20,"y":13}},"goal_reached":false,"timestamp":"2026-02-20T20:12:57Z","session_id":"53418bfd-ef31-4237-8e0e-6c228d6c01f4"}
{"status":"ok"}

Posting telemetry JSON:
{"team": "team1tt","event_type": "player_move","input": {"device":"keyboard","move_sequence":136},"player": {"position":{"x":20,"y":14}},"goal_reached":true,"timestamp":"2026-02-20T20:12:58Z","session_id":"53418bfd-ef31-4237-8e0e-6c228d6c01f4"}
{"status":"ok"}

===== MISSION PAYLOAD JSON =====
{"team":"team1tt","mission_id":"MISSION_001","robot_id":"MAZE_CLIENT_01","mission_type":"maze_run","start_time":1771618188,"end_time":1771618378,"moves_left_turn":25,"moves_right_turn":45,"moves_straight":26,"moves_reverse":40,"moves_total":136,"distance_traveled":136.00,"duration_seconds":190,"mission_result":"success","abort_reason":"none"}
===============================
MISSION POST URL = https://10.170.8.109:8443/mission
{"status":"ok"}
Mission payload sent to https://10.170.8.109:8443/mission
```
### Example AI Server Terminal Output (HTTPS Server + Redis)
The AI server prints the raw JSON payload and confirms Redis insert.
## Example telemetry receive log
```
RAW JSON RECEIVED:
{"team":"team1tt","event_type":"player_move", ... }

Redis insert success. Key: team1tt:telemetry:1771618376
## Example mission receive log
RAW JSON RECEIVED:
{"team":"team1tt","mission_id":"MISSION_001", ... }

Redis insert success. Key: team1tt:mission:1771618378

Redis Storage Format
Both telemetry and mission payloads are stored as Redis hashes with a json field.
Telemetry keys
* Format: team1tt:telemetry:<unix_timestamp>
Example:
* team1tt:telemetry:1771546049
Mission keys
* Format: team1tt:mission:<unix_timestamp>
Example:
* team1tt:mission:1771618378
```
### How to View Saved Data in Redis (Commands)
## A) List telemetry entries
redis-cli --scan --pattern "team1tt:telemetry:*"
## B) Open one telemetry entry (full hash)
redis-cli HGETALL team1tt:telemetry:1771546049
# Example telemetry entry output
```
1) "json"
2) "{\"team\": \"team1tt\",\"event_type\": \"player_move\",\"input\": {\"device\":\"keyboard\",\"move_sequence\":62},\"player\": {\"position\":{\"x\":3,\"y\":11}},\"goal_reached\":false,\"timestamp\":\"2026-02-20T00:07:14Z\",\"session_id\":\"31ffb25c-80e3-496c-98f6-2e0ba4d8169f\"}"
```
## C) List mission entries
```
redis-cli --scan --pattern "team1tt:mission:*"
```
## D) Open one mission entry (full hash)
```
redis-cli HGETALL team1tt:mission:1771618378
```
### Example mission entry output
```
1) "json"
2) "{\"team\":\"team1tt\",\"mission_id\":\"MISSION_001\",\"robot_id\":\"MAZE_CLIENT_01\",\"mission_type\":\"maze_run\",\"start_time\":1771618188,\"end_time\":1771618378,\"moves_left_turn\":25,\"moves_right_turn\":45,\"moves_straight\":26,\"moves_reverse\":40,\"moves_total\":136,\"distance_traveled\":136.00,\"duration_seconds\":190,\"mission_result\":\"success\",\"abort_reason\":\"none\"}"
```
## Helpful Redis Commands (Optional)
# View only the JSON field (telemetry)
```
redis-cli HGET team1tt:telemetry:1771546049 json
```
# View only the JSON field (mission)
```
redis-cli HGET team1tt:mission:1771618378 json
```
## Endpoints Used
# Telemetry endpoints (/move)
* Logging server: https://10.170.8.101:8443/move
* AI server: https://10.170.8.109:8443/move
# Mission endpoint (/mission)
* AI server: https://10.170.8.109:8443/mission

### What This Demonstrates
* SDL2 maze gameplay telemetry generation
* HTTPS POST requests from client to server
* Team-tagged JSON payloads (team1tt)
* Redis storage of telemetry and mission records
* Retrieval and inspection of saved entries using redis-cli

### Notes
* Telemetry is sent on every valid move
* Mission payload is sent when the mission is:
    * success (goal reached), or
    * aborted (e.g., user exits)
* Some telemetry posts may fail if one server is unreachable, but the other endpoint can still succeed

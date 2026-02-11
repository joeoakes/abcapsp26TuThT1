# Maze / Mission Vector Database Schema

This vector database stores semantic embeddings of robot maze missions to enable retrieval augmented generation (RAG), analytics, and AI-assisted reasoning about past missions. Each mission is represented as a structured JSON document and converted into one or more vector embeddings for similarity search.

The schema is designed to support:

* Querying similar missions
* Comparing performance across missions
* Retrieving historical context for AI analysis
* Debugging robot behavior
* Generating mission summaries and insights

---

## 1. Vector Record Structure

Each mission is stored as a vector record with the following high-level fields:

```json
{
  "id": "string",
  "embedding": [0.123, -0.452, ...],
  "metadata": { ... },
  "raw_text": "string"
}
```

### Field Descriptions

| Field       | Type    | Description                                  |
| ----------- | ------- | -------------------------------------------- |
| `id`        | string  | Unique identifier for the mission vector     |
| `embedding` | float[] | Vector embedding generated from mission text |
| `metadata`  | object  | Structured mission fields for filtering      |
| `raw_text`  | string  | Human readable serialized mission report     |

---

## 2. Mission Metadata Schema

The metadata field stores structured values extracted from each mission report.

```json
{
  "mission_id": "TEST_MISSION",
  "robot_id": "TEST_ROBOT",
  "mission_type": "patrol",
  "start_time": 1770330033,
  "end_time": 1770330064,
  "duration_seconds": 31,

  "moves_left_turn": 27,
  "moves_right_turn": 32,
  "moves_straight": 47,
  "moves_reverse": 8,
  "moves_total": 114,

  "distance_traveled": 24.41,
  "mission_result": "success",
  "abort_reason": "user exited"
}
```

### Metadata Field Descriptions

| Field               | Type    | Description                            |
| ------------------- | ------- | -------------------------------------- |
| `mission_id`        | string  | Unique mission identifier              |
| `robot_id`          | string  | Robot identifier                       |
| `mission_type`      | string  | Maze or patrol mission category        |
| `start_time`        | integer | Unix timestamp when mission started    |
| `end_time`          | integer | Unix timestamp when mission ended      |
| `duration_seconds`  | integer | Total mission duration                 |
| `moves_left_turn`   | integer | Count of left turns                    |
| `moves_right_turn`  | integer | Count of right turns                   |
| `moves_straight`    | integer | Count of forward moves                 |
| `moves_reverse`     | integer | Count of reverse moves                 |
| `moves_total`       | integer | Total movement commands                |
| `distance_traveled` | float   | Total distance traveled                |
| `mission_result`    | string  | success or failure                     |
| `abort_reason`      | string  | Reason for mission abort if applicable |

---

## 3. Raw Text Representation for Embedding

Each mission is converted into a descriptive text block before embedding to preserve semantic meaning:


Mission TEST_MISSION executed by robot TEST_ROBOT.
Mission type: patrol.
Duration: 31 seconds.
Moves: 27 left turns, 32 right turns, 47 straight moves, 8 reverse moves.
Total moves: 114.
Distance traveled: 24.41 units.
Mission result: success.
Abort reason: user exited.


This raw text is used to generate embeddings for similarity search

---

## 4. Indexing Strategy

The vector database is indexed by:

* Semantic similarity (via embeddings)
* Metadata filters (e.g., mission_result = success)
* Numeric filters (e.g., duration_seconds < 60)
* Robot identity filters (robot_id)

This enables hybrid search:

* Vector similarity search + metadata filtering
* Performance comparison across mission types
* Retrieval of historical mission patterns

---

## 5. Example Vector Insertion Payload

```json
{
  "id": "mission_TEST_MISSION",
  "embedding": [0.0123, -0.9981, 0.2211],
  "metadata": {
    "mission_id": "TEST_MISSION",
    "robot_id": "TEST_ROBOT",
    "mission_type": "patrol",
    "duration_seconds": 31,
    "moves_total": 114,
    "distance_traveled": 24.41,
    "mission_result": "success"
  },
  "raw_text": "Mission TEST_MISSION executed by robot TEST_ROBOT. Mission type patrol. Duration 31 seconds. Total moves 114. Distance traveled 24.41. Result success."
}
```

---

## 6. RAG Usage

The AI server queries this vector database to:

* Retrieve similar missions for context
* Provide explanations of robot behavior
* Diagnose navigation inefficiencies
* Generate mission summaries
* Recommend parameter tuning for future missions

This enables closed-loop learning between:
Robot → Logger → Vector DB → AI Server → Insights → Improved Control Logic



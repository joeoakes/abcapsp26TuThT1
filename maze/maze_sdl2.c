// maze_sdl2.c
// SDL2 Maze with telemetry + HTTPS mission posting + optional AI autoplay (/init + /next).
//
// Controls (manual): Arrow keys or WASD. R = regenerate. Esc = quit.
// Runtime toggle: P = autoplay on/off.
// Controller: Left Shoulder toggles autoplay, Back toggles dashboard, Start regenerates, D-pad moves.
// Autoplay: MAZE_AUTOPLAY=1 (keyboard movement ignored; brain drives moves).

#include <SDL2/SDL.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <uuid/uuid.h>
#include <curl/curl.h>
#include <string.h>

/* ===========================
   ===== CONFIG / GLOBALS =====
   =========================== */

#define MAZE_W 21
#define MAZE_H 15
#define CELL   32
#define PAD    16

// Wall bitmask for each cell
enum { WALL_N = 1, WALL_E = 2, WALL_S = 4, WALL_W = 8 };

typedef struct {
    uint8_t walls;
    bool visited;
} Cell;

static Cell g[MAZE_H][MAZE_W];

// Stores a session ID for all of the moves
static char session_id[37];

// Flag to print status only once per session
static bool printed_status = false;

// ===== Mission stats =====
static time_t mission_start_time = 0;
static int moves_left = 0;
static int moves_right = 0;
static int moves_straight = 0;
static int moves_reverse = 0;
static int moves_total = 0;
static double distance_traveled = 0.0;
static bool mission_active = false;

// URLs
static const char *g_logging_url = NULL;
static const char *g_ai_url      = NULL;
static const char *g_mission_url = NULL;
static const char *g_dashboard_url = NULL;
static const char *g_tls_ca_file = NULL;
static const char *g_tls_client_cert = NULL;
static const char *g_tls_client_key = NULL;
static bool g_tls_insecure = false;

// Brain (autoplay) endpoints
static const char *g_brain_init_url = NULL;
static const char *g_brain_next_url = NULL;
static bool g_autoplay = false;

// When true, we show an in-app dashboard overlay and pause movement.
static bool g_in_dashboard = false;
static bool g_draw_dashboard_overlay = false;
static SDL_GameController* g_controller = NULL;

// Mission results for the in-app dashboard (most recent first).
// We only track missions created during this single program run.
static bool g_mission_history[20];
static int g_mission_history_count = 0;
static int g_missions_run = 0;
static int g_missions_success = 0;

// (single-window dashboard overlay mode)

#if defined(__APPLE__)
#ifdef __cplusplus
extern "C" {
#endif
int dashboard_embed_show(SDL_Window *window, const char *url_cstr);
void dashboard_embed_hide(void);
#ifdef __cplusplus
}
#endif
#endif

/* ===========================
   ===== FORWARD DECLS ========
   =========================== */

static void build_mission_json(
    char* out,
    size_t out_size,
    const char* mission_id,
    const char* result,
    const char* abort_reason
);

static void print_full_mission_json(
    const char* mission_id,
    const char* result,
    const char* abort_reason
);

static void save_https_mission(const char* json, const char* mission_url);

static int http_post_json(const char* url, const char* json, char* out_resp, size_t out_resp_cap, long timeout_ms);

/* ===========================
   ===== CURL HELPERS =========
   =========================== */

// Callback to discard curl response body (prevents spam to stdout)
static size_t discard_response(void* ptr, size_t size, size_t nmemb, void* userdata) {
    (void)ptr; (void)userdata;
    return size * nmemb;
}

struct Memory {
    char*  buf;
    size_t cap;
    size_t len;
};

static size_t write_to_mem(void* contents, size_t size, size_t nmemb, void* userp) {
    size_t realsize = size * nmemb;
    struct Memory* mem = (struct Memory*)userp;

    if (mem->len + realsize + 1 > mem->cap) {
        // truncate if response is too big
        realsize = (mem->cap > mem->len + 1) ? (mem->cap - mem->len - 1) : 0;
    }
    if (realsize > 0) {
        memcpy(mem->buf + mem->len, contents, realsize);
        mem->len += realsize;
        mem->buf[mem->len] = '\0';
    }
    return size * nmemb;
}

static int http_post_json(const char* url, const char* json, char* out_resp, size_t out_resp_cap, long timeout_ms) {
    if (!url) return -1;

    CURL* curl = curl_easy_init();
    if (!curl) return -1;

    struct curl_slist* headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    // capture response (optional)
    struct Memory mem;
    mem.buf = out_resp;
    mem.cap = out_resp_cap;
    mem.len = 0;
    if (out_resp && out_resp_cap > 0) out_resp[0] = '\0';

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

    bool is_https = (url && strncmp(url, "https://", 8) == 0);
    if (is_https) {
        // Secure-by-default TLS settings. Use MAZE_TLS_INSECURE=1 only for temporary local debugging.
        curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, g_tls_insecure ? 0L : 1L);
        curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, g_tls_insecure ? 0L : 2L);
        if (g_tls_ca_file && g_tls_ca_file[0] != '\0') {
            curl_easy_setopt(curl, CURLOPT_CAINFO, g_tls_ca_file);
        }
        if (g_tls_client_cert && g_tls_client_cert[0] != '\0') {
            curl_easy_setopt(curl, CURLOPT_SSLCERT, g_tls_client_cert);
        }
        if (g_tls_client_key && g_tls_client_key[0] != '\0') {
            curl_easy_setopt(curl, CURLOPT_SSLKEY, g_tls_client_key);
        }
    }

    // response handling
    if (out_resp && out_resp_cap > 0) {
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_to_mem);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &mem);
    } else {
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, discard_response);
    }

    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, timeout_ms);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, (timeout_ms > 300 ? 300L : timeout_ms));

    CURLcode res = curl_easy_perform(curl);

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    return (res == CURLE_OK) ? 0 : -1;
}

// Gets time in ISO-8601
static void get_iso8601_time(char* buf, size_t len) {
    time_t now = time(NULL);
    struct tm* gmt = gmtime(&now);
    strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", gmt);
}

/* ===========================
   ===== TELEMETRY / MISSION ==
   =========================== */

static void save_https_move(
    const char* session_id_,
    int px, int py,
    int move_sequence, bool goal_reached,
    const char* HTTPS_URL
) {
    if (!HTTPS_URL) return;

    char timestamp[32];
    get_iso8601_time(timestamp, sizeof(timestamp));

    char json[512];
    snprintf(json, sizeof(json),
        "{"
          "\"team\":\"team1tt\","
          "\"event_type\":\"player_move\","
          "\"input\":{\"device\":\"keyboard\",\"move_sequence\":%d},"
          "\"player\":{\"position\":{\"x\":%d,\"y\":%d}},"
          "\"goal_reached\":%s,"
          "\"timestamp\":\"%s\","
          "\"session_id\":\"%s\""
        "}",
        move_sequence,
        px, py,
        goal_reached ? "true" : "false",
        timestamp,
        session_id_
    );

    (void)http_post_json(HTTPS_URL, json, NULL, 0, 500L);

    // Optional: print once to show program is alive
    if (!printed_status) {
        printf("{\"status\":\"ok\"}\n");
        printed_status = true;
    }
}

static void save_json_move(
    const char* session_id_,
    int px, int py,
    int move_sequence,
    bool goal_reached
) {
    char timestamp[32];
    get_iso8601_time(timestamp, sizeof(timestamp));

    FILE* f = fopen("maze_moves.log", "a");
    if (!f) return;

    fprintf(f,
        "{\n"
        "  \"session_id\": \"%s\",\n"
        "  \"event_type\": \"player_move\",\n"
        "  \"input\": {\"device\":\"keyboard\",\"move_sequence\":%d},\n"
        "  \"player\": {\"position\":{\"x\":%d,\"y\":%d}},\n"
        "  \"goal_reached\":%s,\n"
        "  \"timestamp\":\"%s\"\n"
        "}\n\n",
        session_id_, move_sequence, px, py,
        goal_reached ? "true" : "false",
        timestamp
    );

    fclose(f);
}

static void save_https_mission(const char* json, const char* mission_url) {
    if (!mission_url) return;

    printf("MISSION POST URL = %s\n", mission_url);

    if (http_post_json(mission_url, json, NULL, 0, 1200L) != 0) {
        fprintf(stderr, "Mission POST failed (%s)\n", mission_url);
    } else {
        printf("Mission payload sent to %s\n", mission_url);
    }
}

static void print_full_mission_json(
    const char* mission_id,
    const char* result,
    const char* abort_reason
) {
    char mission_json[1024];
    build_mission_json(mission_json, sizeof(mission_json), mission_id, result, abort_reason);

    printf("\n===== MISSION PAYLOAD JSON =====\n%s\n===============================\n", mission_json);

    save_https_mission(mission_json, g_mission_url);
}

static void build_mission_json(
    char* out,
    size_t out_size,
    const char* mission_id,
    const char* result,
    const char* abort_reason
) {
    time_t end_time = time(NULL);
    int duration = (int)difftime(end_time, mission_start_time);

    snprintf(out, out_size,
        "{"
          "\"team\":\"team1tt\","
          "\"mission_id\":\"%s\","
          "\"robot_id\":\"MAZE_CLIENT_01\","
          "\"mission_type\":\"maze_run\","
          "\"start_time\":%ld,"
          "\"end_time\":%ld,"
          "\"moves_left_turn\":%d,"
          "\"moves_right_turn\":%d,"
          "\"moves_straight\":%d,"
          "\"moves_reverse\":%d,"
          "\"moves_total\":%d,"
          "\"distance_traveled\":%.2f,"
          "\"duration_seconds\":%d,"
          "\"mission_result\":\"%s\","
          "\"abort_reason\":\"%s\""
        "}",
        mission_id,
        mission_start_time,
        end_time,
        moves_left,
        moves_right,
        moves_straight,
        moves_reverse,
        moves_total,
        distance_traveled,
        duration,
        result,
        abort_reason
    );
}

/* ===========================
   ===== MAZE GENERATION ======
   =========================== */

static inline bool in_bounds(int x, int y) {
    return (x >= 0 && x < MAZE_W && y >= 0 && y < MAZE_H);
}

static void knock_down(int x, int y, int nx, int ny) {
    if (nx == x && ny == y - 1) { // N
        g[y][x].walls &= ~WALL_N;
        g[ny][nx].walls &= ~WALL_S;
    } else if (nx == x + 1 && ny == y) { // E
        g[y][x].walls &= ~WALL_E;
        g[ny][nx].walls &= ~WALL_W;
    } else if (nx == x && ny == y + 1) { // S
        g[y][x].walls &= ~WALL_S;
        g[ny][nx].walls &= ~WALL_N;
    } else if (nx == x - 1 && ny == y) { // W
        g[y][x].walls &= ~WALL_W;
        g[ny][nx].walls &= ~WALL_E;
    }
}

static void maze_init(void) {
    for (int y = 0; y < MAZE_H; y++) {
        for (int x = 0; x < MAZE_W; x++) {
            g[y][x].walls = WALL_N | WALL_E | WALL_S | WALL_W;
            g[y][x].visited = false;
        }
    }
}

static void maze_generate(int sx, int sy) {
    typedef struct { int x, y; } P;
    P stack[MAZE_W * MAZE_H];
    int top = 0;

    g[sy][sx].visited = true;
    stack[top++] = (P){sx, sy};

    while (top > 0) {
        P cur = stack[top - 1];
        int x = cur.x, y = cur.y;

        P neigh[4];
        int ncount = 0;

        const int dx[4] = { 0, 1, 0, -1 };
        const int dy[4] = { -1, 0, 1, 0 };

        for (int i = 0; i < 4; i++) {
            int nx = x + dx[i], ny = y + dy[i];
            if (in_bounds(nx, ny) && !g[ny][nx].visited) {
                neigh[ncount++] = (P){nx, ny};
            }
        }

        if (ncount == 0) {
            top--;
            continue;
        }

        int pick = rand() % ncount;
        int nx = neigh[pick].x, ny = neigh[pick].y;

        knock_down(x, y, nx, ny);
        g[ny][nx].visited = true;
        stack[top++] = (P){nx, ny};
    }

    for (int y = 0; y < MAZE_H; y++)
        for (int x = 0; x < MAZE_W; x++)
            g[y][x].visited = false;
}

/* ===========================
   ===== RENDERING ============
   =========================== */

static void draw_maze(SDL_Renderer* r) {
    int ox = PAD;
    int oy = PAD;

    SDL_SetRenderDrawColor(r, 230, 230, 230, 255);

    for (int y = 0; y < MAZE_H; y++) {
        for (int x = 0; x < MAZE_W; x++) {
            int x0 = ox + x * CELL;
            int y0 = oy + y * CELL;
            int x1 = x0 + CELL;
            int y1 = y0 + CELL;

            uint8_t w = g[y][x].walls;

            if (w & WALL_N) SDL_RenderDrawLine(r, x0, y0, x1, y0);
            if (w & WALL_E) SDL_RenderDrawLine(r, x1, y0, x1, y1);
            if (w & WALL_S) SDL_RenderDrawLine(r, x0, y1, x1, y1);
            if (w & WALL_W) SDL_RenderDrawLine(r, x0, y0, x0, y1);
        }
    }
}

static void draw_player_goal(SDL_Renderer* r, int px, int py) {
    int ox = PAD;
    int oy = PAD;

    SDL_Rect goal = {
        ox + (MAZE_W - 1) * CELL + 6,
        oy + (MAZE_H - 1) * CELL + 6,
        CELL - 12,
        CELL - 12
    };
    SDL_SetRenderDrawColor(r, 40, 160, 70, 255);
    SDL_RenderFillRect(r, &goal);

    SDL_Rect p = {
        ox + px * CELL + 8,
        oy + py * CELL + 8,
        CELL - 16,
        CELL - 16
    };
    SDL_SetRenderDrawColor(r, 255, 255, 0, 255);
    SDL_RenderFillRect(r, &p);
}

static void draw_filled_rect(SDL_Renderer* r, int x, int y, int w, int h, Uint8 R, Uint8 G, Uint8 B, Uint8 A) {
    SDL_Rect rect = { x, y, w, h };
    SDL_SetRenderDrawBlendMode(r, SDL_BLENDMODE_BLEND);
    SDL_SetRenderDrawColor(r, R, G, B, A);
    SDL_RenderFillRect(r, &rect);
}

static const uint8_t* glyph5x7(char c) {
    // 5x7 uppercase bitmap font for HUD labels.
    static const uint8_t blank[7] = {0,0,0,0,0,0,0};
    static const uint8_t colon[7] = {0,4,0,0,4,0,0};
    static const uint8_t A[7] = {14,17,17,31,17,17,17};
    static const uint8_t D[7] = {30,17,17,17,17,17,30};
    static const uint8_t E[7] = {31,16,16,30,16,16,31};
    static const uint8_t L[7] = {16,16,16,16,16,16,31};
    static const uint8_t M[7] = {17,27,21,21,17,17,17};
    static const uint8_t N[7] = {17,25,21,19,17,17,17};
    static const uint8_t O[7] = {14,17,17,17,17,17,14};
    static const uint8_t P[7] = {30,17,17,30,16,16,16};
    static const uint8_t R[7] = {30,17,17,30,20,18,17};
    static const uint8_t T[7] = {31,4,4,4,4,4,4};
    static const uint8_t U[7] = {17,17,17,17,17,17,14};
    static const uint8_t Y[7] = {17,17,10,4,4,4,4};

    switch (c) {
        case 'A': return A;
        case 'D': return D;
        case 'E': return E;
        case 'L': return L;
        case 'M': return M;
        case 'N': return N;
        case 'O': return O;
        case 'P': return P;
        case 'R': return R;
        case 'T': return T;
        case 'U': return U;
        case 'Y': return Y;
        case ':': return colon;
        case ' ': return blank;
        default: return blank;
    }
}

static void draw_text5x7(SDL_Renderer* r, int x, int y, int scale, const char* text, Uint8 R, Uint8 G, Uint8 B, Uint8 A) {
    if (!text || scale <= 0) return;
    SDL_SetRenderDrawBlendMode(r, SDL_BLENDMODE_BLEND);
    SDL_SetRenderDrawColor(r, R, G, B, A);

    int cx = x;
    for (const char* p = text; *p; ++p) {
        const uint8_t* g = glyph5x7(*p);
        for (int row = 0; row < 7; row++) {
            for (int col = 0; col < 5; col++) {
                if ((g[row] >> (4 - col)) & 1) {
                    SDL_Rect px = { cx + col * scale, y + row * scale, scale, scale };
                    SDL_RenderFillRect(r, &px);
                }
            }
        }
        cx += 6 * scale; // 5 pixels + 1 spacing
    }
}

static void draw_dashboard_overlay(SDL_Renderer* r, int win_w, int win_h, bool won_local) {
    // Dark translucent overlay
    draw_filled_rect(r, 0, 0, win_w, win_h, 0, 0, 0, 190);

    const int left_x = PAD;
    const int right_x = win_w - PAD;
    const int panel_w = right_x - left_x;

    // Header bar: green on success/goal reached, red on aborted, blue while running.
    Uint8 headerR = 40, headerG = 110, headerB = 200;
    if (!mission_active) {
        if (won_local) { headerR = 63; headerG = 185; headerB = 80; }  // green
        else { headerR = 248; headerG = 81; headerB = 73; }     // red
    }
    draw_filled_rect(r, left_x, PAD, panel_w, 44, headerR, headerG, headerB, 220);

    // Move breakdown bars (vertical stack)
    int total = moves_total > 0 ? moves_total : 1;
    const int bar_x = left_x + 12;
    const int bar_w = panel_w - 24;
    const int bar_h = 10;
    int bar_y = PAD + 62;

    // Straight (forward)
    int pct = (moves_straight * 100) / total;
    draw_filled_rect(r, bar_x, bar_y, (bar_w * pct) / 100, bar_h, 88, 166, 255, 230);
    bar_y += 16;

    // Left
    pct = (moves_left * 100) / total;
    draw_filled_rect(r, bar_x, bar_y, (bar_w * pct) / 100, bar_h, 188, 140, 255, 230);
    bar_y += 16;

    // Right
    pct = (moves_right * 100) / total;
    draw_filled_rect(r, bar_x, bar_y, (bar_w * pct) / 100, bar_h, 255, 166, 87, 230);
    bar_y += 16;

    // Reverse
    pct = (moves_reverse * 100) / total;
    draw_filled_rect(r, bar_x, bar_y, (bar_w * pct) / 100, bar_h, 248, 81, 73, 230);

    // Success rate bar (bottom-left)
    int rate = 0;
    if (g_missions_run > 0) {
        rate = (g_missions_success * 100) / g_missions_run;
    }
    const int sr_x = left_x;
    const int sr_y = win_h - PAD - 58;
    draw_filled_rect(r, sr_x, sr_y, panel_w, 16, 48, 54, 61, 230);
    // Fill color from yellow->green
    Uint8 fillR = (rate > 60) ? 63 : 210;
    Uint8 fillG = (rate > 60) ? 185 : 146;
    Uint8 fillB = (rate > 60) ? 80 : 34;
    draw_filled_rect(r, sr_x, sr_y, (panel_w * rate) / 100, 16, fillR, fillG, fillB, 240);

    // Mission history mini-cards (bottom-right)
    const int cards_x = left_x + panel_w - 160;
    int card_y = sr_y - 90;
    int max_cards = 5;
    for (int i = 0; i < max_cards; i++) {
        int idx = g_mission_history_count - 1 - i;
        if (idx < 0) break;
        bool success = g_mission_history[idx];
        Uint8 R = success ? 63 : 248;
        Uint8 G = success ? 185 : 81;
        Uint8 B = success ? 80 : 73;
        draw_filled_rect(r, cards_x, card_y + i * 18, 140, 12, R, G, B, 230);
    }
}

static void draw_mode_hud(SDL_Renderer* r) {
    const char* mode_text = g_autoplay ? "MODE: AUTOPLAY" : "MODE: MANUAL";
    const int scale = 2;
    const int box_w = (int)strlen(mode_text) * 6 * scale + 10;
    const int box_h = 7 * scale + 8;
    draw_filled_rect(r, PAD, PAD / 2, box_w, box_h, 0, 0, 0, 160);
    draw_text5x7(r, PAD + 5, PAD / 2 + 4, scale, mode_text, 255, 255, 255, 255);
}

/* ===========================
   ===== MOVEMENT ============
   =========================== */

static bool try_move(int* px, int* py, int dx, int dy) {
    int x = *px, y = *py;
    int nx = x + dx, ny = y + dy;
    if (!in_bounds(nx, ny)) return false;

    uint8_t w = g[y][x].walls;

    if (dx == 0 && dy == -1 && (w & WALL_N)) return false;
    if (dx == 1 && dy == 0  && (w & WALL_E)) return false;
    if (dx == 0 && dy == 1  && (w & WALL_S)) return false;
    if (dx == -1 && dy == 0 && (w & WALL_W)) return false;

    *px = nx;
    *py = ny;
    return true;
}

static void reset_mission_stats(void) {
    mission_start_time = time(NULL);
    mission_active = true;
    moves_left = moves_right = moves_straight = moves_reverse = 0;
    moves_total = 0;
    distance_traveled = 0.0;
}

static void record_mission_end(bool success) {
    if (g_mission_history_count < (int)(sizeof(g_mission_history) / sizeof(g_mission_history[0]))) {
        g_mission_history[g_mission_history_count] = success;
        g_mission_history_count++;
    }
    g_missions_run++;
    if (success) g_missions_success++;
}

static void regenerate(int* px, int* py, SDL_Window* win) {
    // If a mission is active and user regenerates, treat it as aborted.
    if (mission_active) {
        print_full_mission_json("MISSION_001", "aborted", "regenerated");
        mission_active = false;
        record_mission_end(false);
    }
    maze_init();
    maze_generate(0, 0);
    *px = 0; *py = 0;

    SDL_SetWindowTitle(win, "SDL2 Maze - Reach the green goal (R to regenerate)");
    printed_status = false;

    reset_mission_stats();
}

/* ===========================
   ===== AUTOPLAY CLIENT ======
   =========================== */

static void brain_send_init(void) {
    if (!g_brain_init_url) return;

    char json[20000];
    int pos = 0;

    pos += snprintf(json + pos, sizeof(json) - pos,
        "{"
          "\"session_id\":\"%s\","
          "\"width\":%d,"
          "\"height\":%d,"
          "\"cells\":[",
        session_id, MAZE_W, MAZE_H
    );

    for (int y = 0; y < MAZE_H; y++) {
        for (int x = 0; x < MAZE_W; x++) {
            pos += snprintf(json + pos, sizeof(json) - pos,
                "{\"walls\":%d}%s",
                (int)g[y][x].walls,
                (x == MAZE_W - 1 && y == MAZE_H - 1) ? "" : ","
            );
        }
    }

    pos += snprintf(json + pos, sizeof(json) - pos,
        "],"
        "\"start_x\":0,\"start_y\":0,"
        "\"goal_x\":%d,\"goal_y\":%d"
        "}",
        MAZE_W - 1, MAZE_H - 1
    );

    char resp[2048];
    int rc = http_post_json(g_brain_init_url, json, resp, sizeof(resp), 15000L);
    if (rc != 0) {
        fprintf(stderr, "AI init POST failed to %s\n", g_brain_init_url);
    }
}

static void parse_action(const char* json, char* action_out, size_t action_cap)
{
    if (!json || !action_out || action_cap == 0) return;

    action_out[0] = '\0';

    const char* key = strstr(json, "\"action\"");
    if (!key) key = strstr(json, "\"move\"");
    if (!key) key = strstr(json, "\"direction\"");
    if (!key) return;

    const char* colon = strchr(key, ':');
    if (!colon) return;
    colon++;

    while (*colon == ' ' || *colon == '\t') colon++;

    if (*colon != '\"') return;
    colon++;

    size_t i = 0;
    while (*colon && *colon != '\"' && i < action_cap - 1) {
        char c = *colon++;
        if (c >= 'a' && c <= 'z') c = (char)(c - 'a' + 'A');
        action_out[i++] = c;
    }
    action_out[i] = '\0';
}

static bool autoplay_step(int* px, int* py, int* move_sequence, bool* won) {
    if (!g_brain_next_url) return false;

    char req[256];
    snprintf(req, sizeof(req),
        "{"
          "\"session_id\":\"%s\","
          "\"x\":%d,"
          "\"y\":%d"
        "}",
        session_id,
        *px,
        *py
    );

    char resp[2048];
    if (http_post_json(g_brain_next_url, req, resp, sizeof(resp), 15000L) != 0) {
        fprintf(stderr, "AI next POST failed to %s\n", g_brain_next_url);
        return false;
    }

    char act[16];
    parse_action(resp, act, sizeof(act));

    if (strcmp(act, "DONE") == 0) return false;

    int dx = 0, dy = 0;
    if (strcmp(act, "UP") == 0) dy = -1;
    else if (strcmp(act, "DOWN") == 0) dy = 1;
    else if (strcmp(act, "LEFT") == 0) dx = -1;
    else if (strcmp(act, "RIGHT") == 0) dx = 1;
    else return false;

    bool moved = false;
    if (dx == 0 && dy == -1) { moved = try_move(px, py, 0, -1); if (moved) moves_straight++; }
    if (dx == 1 && dy == 0)  { moved = try_move(px, py, 1, 0);  if (moved) moves_right++; }
    if (dx == 0 && dy == 1)  { moved = try_move(px, py, 0, 1);  if (moved) moves_reverse++; }
    if (dx == -1 && dy == 0) { moved = try_move(px, py, -1, 0); if (moved) moves_left++; }

    if (!moved) return false;

    (*move_sequence)++;
    moves_total++;
    distance_traveled += 1.0;

    bool goal = (*px == MAZE_W - 1 && *py == MAZE_H - 1);

    save_json_move(session_id, *px, *py, *move_sequence, goal);
    save_https_move(session_id, *px, *py, *move_sequence, goal, g_logging_url);
    save_https_move(session_id, *px, *py, *move_sequence, goal, g_ai_url);

    if (goal && mission_active) {
        *won = true;
        print_full_mission_json("MISSION_001", "success", "none");
        record_mission_end(true);
        mission_active = false;
    }

    return true;
}

static void set_autoplay(bool enabled) {
    if (g_autoplay == enabled) return;
    g_autoplay = enabled;
    printf("Autoplay: %s\n", g_autoplay ? "ENABLED" : "disabled");
    if (g_autoplay) {
        brain_send_init();
    }
}

static void apply_move_and_emit(int* px, int* py, int* move_sequence, bool* won, int dx, int dy, SDL_Window* win) {
    bool moved = false;
    if (dx == 0 && dy == -1) { moved = try_move(px, py, 0, -1); if (moved) moves_straight++; }
    if (dx == 1 && dy == 0)  { moved = try_move(px, py, 1, 0);  if (moved) moves_right++; }
    if (dx == 0 && dy == 1)  { moved = try_move(px, py, 0, 1);  if (moved) moves_reverse++; }
    if (dx == -1 && dy == 0) { moved = try_move(px, py, -1, 0); if (moved) moves_left++; }
    if (!moved) return;

    (*move_sequence)++;
    moves_total++;
    distance_traveled += 1.0;

    bool goal = (*px == MAZE_W - 1 && *py == MAZE_H - 1);
    save_json_move(session_id, *px, *py, *move_sequence, goal);
    save_https_move(session_id, *px, *py, *move_sequence, goal, g_logging_url);
    save_https_move(session_id, *px, *py, *move_sequence, goal, g_ai_url);

    if (goal && mission_active) {
        *won = true;
        print_full_mission_json("MISSION_001", "success", "none");
        record_mission_end(true);
        mission_active = false;
        SDL_SetWindowTitle(win, "You win! Press R to regenerate, Esc to quit");
    }
}

/* ===========================
   ===== MAIN ================
   =========================== */

int main(int argc, char** argv) {
    (void)argc; (void)argv;
    srand((unsigned)time(NULL));

    // Initialize libcurl globally (required before any curl calls)
    curl_global_init(CURL_GLOBAL_DEFAULT);

    uuid_t binuuid;
    uuid_generate_random(binuuid);
    uuid_unparse_lower(binuuid, session_id);

    g_logging_url = getenv("MAZE_LOGGING_URL");
    g_ai_url      = getenv("MAZE_AI_URL");
    g_mission_url = getenv("MAZE_MISSION_URL");
    g_dashboard_url = getenv("MAZE_DASHBOARD_URL");
    g_tls_ca_file = getenv("MAZE_TLS_CA_FILE");
    g_tls_client_cert = getenv("MAZE_TLS_CLIENT_CERT");
    g_tls_client_key = getenv("MAZE_TLS_CLIENT_KEY");

    const char* tls_insecure = getenv("MAZE_TLS_INSECURE");
    if (tls_insecure && strcmp(tls_insecure, "1") == 0) {
        g_tls_insecure = true;
    }

    if (!g_logging_url) g_logging_url = "https://10.170.8.130:8443/move";
    if (!g_ai_url)      g_ai_url      = "https://10.170.8.109:8443/move";
    if (!g_mission_url) g_mission_url = "https://10.170.8.109:8443/mission";
    if (!g_dashboard_url) g_dashboard_url = "http://127.0.0.1:8000/index.html?apiPort=8443";

    // Brain endpoints
    g_brain_init_url = getenv("MAZE_BRAIN_INIT_URL");
    g_brain_next_url = getenv("MAZE_BRAIN_NEXT_URL");
    if (!g_brain_init_url) g_brain_init_url = "http://127.0.0.1:8000/init";
    if (!g_brain_next_url) g_brain_next_url = "http://127.0.0.1:8000/next";

    const char* ap = getenv("MAZE_AUTOPLAY");
    if (ap && strcmp(ap, "1") == 0) g_autoplay = true;

    printf("Mission payload will post to: %s\n", g_mission_url);
    printf("Posting telemetry to logging: %s\n", g_logging_url);
    printf("Posting telemetry to AI:      %s\n", g_ai_url);
    printf("TLS mode:                    %s\n", g_tls_insecure ? "INSECURE (debug only)" : "VERIFY");
    printf("TLS CA:                      %s\n", (g_tls_ca_file && g_tls_ca_file[0]) ? g_tls_ca_file : "(system/default)");
    printf("TLS client cert:             %s\n", (g_tls_client_cert && g_tls_client_cert[0]) ? g_tls_client_cert : "(none)");
    printf("TLS client key:              %s\n", (g_tls_client_key && g_tls_client_key[0]) ? g_tls_client_key : "(none)");
    printf("Dashboard URL:              %s\n", g_dashboard_url);
    printf("Dashboard mode:             in-window HTML embed (macOS), overlay fallback (others)\n");
    printf("Autoplay: %s\n", g_autoplay ? "ENABLED" : "disabled");
    if (g_autoplay) {
        printf("Brain init: %s\n", g_brain_init_url);
        printf("Brain next: %s\n", g_brain_next_url);
    }

    // Print status once at program start
    printf("{\"status\":\"ok\"}\n");
    printed_status = true;

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMECONTROLLER) != 0) {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return 1;
    }
    for (int i = 0; i < SDL_NumJoysticks(); i++) {
        if (SDL_IsGameController(i)) {
            g_controller = SDL_GameControllerOpen(i);
            if (g_controller) {
                printf("GameController connected: %s\n", SDL_GameControllerName(g_controller));
            }
            break;
        }
    }

    int win_w = PAD * 2 + MAZE_W * CELL;
    int win_h = PAD * 2 + MAZE_H * CELL;

    SDL_Window* win = SDL_CreateWindow(
        "SDL2 Maze - Reach the green goal (R to regenerate)",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        win_w, win_h,
        SDL_WINDOW_SHOWN
    );
    if (!win) {
        fprintf(stderr, "SDL_CreateWindow failed: %s\n", SDL_GetError());
        SDL_Quit();
        return 1;
    }

    SDL_Renderer* r = SDL_CreateRenderer(
        win, -1,
        SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC
    );
    if (!r) {
        fprintf(stderr, "SDL_CreateRenderer failed: %s\n", SDL_GetError());
        SDL_DestroyWindow(win);
        SDL_Quit();
        return 1;
    }

    // Maze + mission start
    maze_init();
    maze_generate(0, 0);

    int px = 0, py = 0;
    int move_sequence = 0;
    bool running = true;
    bool won = false;

    reset_mission_stats();

    // If autoplay, send maze to brain once
    if (g_autoplay) {
        brain_send_init();
    }

    while (running) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {

            if (e.type == SDL_QUIT) {
                if (mission_active) {
                    print_full_mission_json("MISSION_001", "aborted", "window closed");
                    record_mission_end(false);
                    mission_active = false;
                }
#if defined(__APPLE__)
                dashboard_embed_hide();
#endif
                running = false;
            }

            if (e.type == SDL_MOUSEBUTTONDOWN) {
                if (g_in_dashboard) {
                    g_in_dashboard = false;
#if defined(__APPLE__)
                    dashboard_embed_hide();
#endif
                    continue;
                }
            }

            if (e.type == SDL_KEYDOWN) {
                SDL_Keycode k = e.key.keysym.sym;

                if (k == SDLK_ESCAPE) {
                    if (mission_active) {
                        print_full_mission_json("MISSION_001", "aborted", "user exited");
                        record_mission_end(false);
                        mission_active = false;
                    }
#if defined(__APPLE__)
                    dashboard_embed_hide();
#endif
                    running = false;
                    break;
                }

                if (k == SDLK_l) {
                    g_in_dashboard = !g_in_dashboard;
                    g_draw_dashboard_overlay = g_in_dashboard;
#if defined(__APPLE__)
                    if (g_in_dashboard) {
                        int ok = dashboard_embed_show(win, g_dashboard_url);
                        if (ok) {
                            g_draw_dashboard_overlay = false; // use real HTML view
                        }
                    } else {
                        dashboard_embed_hide();
                    }
#endif
                    continue;
                }

                if (k == SDLK_p) {
                    set_autoplay(!g_autoplay);
                    continue;
                }

                if (k == SDLK_r) {
                    regenerate(&px, &py, win);
                    won = false;
                    move_sequence = 0;

                    if (g_autoplay) {
                        brain_send_init();
                    }
                    continue;
                }

                // Manual movement only when autoplay is off (and dashboard overlay isn't open)
                if (!g_autoplay && !won && !g_in_dashboard) {
                    if (k == SDLK_UP || k == SDLK_w)    apply_move_and_emit(&px, &py, &move_sequence, &won, 0, -1, win);
                    if (k == SDLK_RIGHT || k == SDLK_d) apply_move_and_emit(&px, &py, &move_sequence, &won, 1, 0, win);
                    if (k == SDLK_DOWN || k == SDLK_s)  apply_move_and_emit(&px, &py, &move_sequence, &won, 0, 1, win);
                    if (k == SDLK_LEFT || k == SDLK_a)  apply_move_and_emit(&px, &py, &move_sequence, &won, -1, 0, win);
                }
            }

            if (e.type == SDL_CONTROLLERBUTTONDOWN) {
                SDL_GameControllerButton b = (SDL_GameControllerButton)e.cbutton.button;

                // Left shoulder toggles AI autoplay on/off (with Y as fallback mapping).
                if (b == SDL_CONTROLLER_BUTTON_LEFTSHOULDER || b == SDL_CONTROLLER_BUTTON_Y) {
                    set_autoplay(!g_autoplay);
                    continue;
                }

                // Back button mirrors L key dashboard toggle.
                if (b == SDL_CONTROLLER_BUTTON_BACK) {
                    g_in_dashboard = !g_in_dashboard;
                    g_draw_dashboard_overlay = g_in_dashboard;
#if defined(__APPLE__)
                    if (g_in_dashboard) {
                        int ok = dashboard_embed_show(win, g_dashboard_url);
                        if (ok) g_draw_dashboard_overlay = false;
                    } else {
                        dashboard_embed_hide();
                    }
#endif
                    continue;
                }

                // Start button mirrors R key regenerate.
                if (b == SDL_CONTROLLER_BUTTON_START) {
                    regenerate(&px, &py, win);
                    won = false;
                    move_sequence = 0;
                    if (g_autoplay) {
                        brain_send_init();
                    }
                    continue;
                }

                if (!g_autoplay && !won && !g_in_dashboard) {
                    if (b == SDL_CONTROLLER_BUTTON_DPAD_UP)    apply_move_and_emit(&px, &py, &move_sequence, &won, 0, -1, win);
                    if (b == SDL_CONTROLLER_BUTTON_DPAD_RIGHT) apply_move_and_emit(&px, &py, &move_sequence, &won, 1, 0, win);
                    if (b == SDL_CONTROLLER_BUTTON_DPAD_DOWN)  apply_move_and_emit(&px, &py, &move_sequence, &won, 0, 1, win);
                    if (b == SDL_CONTROLLER_BUTTON_DPAD_LEFT)  apply_move_and_emit(&px, &py, &move_sequence, &won, -1, 0, win);
                }
            }
        }

        if (g_autoplay && !won && !g_in_dashboard) {
            (void)autoplay_step(&px, &py, &move_sequence, &won);
            if (won) SDL_SetWindowTitle(win, "AI won! Press R to regenerate, Esc to quit");
            SDL_Delay(40);
        }

        SDL_SetRenderDrawColor(r, 15, 15, 18, 255);
        SDL_RenderClear(r);

        draw_maze(r);
        draw_player_goal(r, px, py);
        draw_mode_hud(r);

        if (g_in_dashboard && g_draw_dashboard_overlay) {
            draw_dashboard_overlay(r, win_w, win_h, won);
        }

        SDL_RenderPresent(r);
    }

    curl_global_cleanup();
    if (g_controller) {
        SDL_GameControllerClose(g_controller);
        g_controller = NULL;
    }
    SDL_DestroyRenderer(r);
    SDL_DestroyWindow(win);
    SDL_Quit();
    return 0;
}

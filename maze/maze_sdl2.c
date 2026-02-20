// maze_sdl2.c
// Simple SDL2 maze: generate (DFS backtracker), draw, move player to goal.
// Controls: Arrow keys or WASD. R = regenerate. Esc = quit.


#include <SDL2/SDL.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <uuid/uuid.h>
#include <curl/curl.h>


static void build_mission_json(
    char* out,
    size_t out_size,
    const char* mission_id,
    const char* result,
    const char* abort_reason
);

static void save_https_mission(const char* json, const char* mission_url);


static const char *g_logging_url = NULL;
static const char *g_ai_url      = NULL;
static const char *g_mission_url = NULL;

static void print_full_mission_json(const char* mission_id,
                                    const char* result,
                                    const char* abort_reason); 
                                                                    


#define MAZE_W 21   // number of cells horizontally
#define MAZE_H 15   // number of cells vertically
#define CELL   32   // pixels per cell
#define PAD    16   // window padding around maze

// ===== Mission stats =====
static time_t mission_start_time = 0;
static int moves_left = 0;
static int moves_right = 0;
static int moves_straight = 0;
static int moves_reverse = 0;
static int moves_total = 0;
static double distance_traveled = 0.0;
static bool mission_active = false;



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

// Gets time in ISO-8601
static void get_iso8601_time(char* buf, size_t len) {
    time_t now = time(NULL);
    struct tm* gmt = gmtime(&now);
    strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", gmt);
}

// Saves move to HTTPS endpoint
static void save_https_move(
    const char* session_id,
    int px, int py,
    int move_sequence, bool goal_reached,
    const char* HTTPS_URL
){   

    CURL* curl = curl_easy_init();
    if (!curl) return;

    char timestamp[32];
    get_iso8601_time(timestamp, sizeof(timestamp));

    char json[512];
    snprintf(json, sizeof(json),
        "{" "\"team\": \"team1tt\","
            "\"event_type\": \"player_move\","
            "\"input\": {\"device\":\"keyboard\",\"move_sequence\":%d},"
            "\"player\": {\"position\":{\"x\":%d,\"y\":%d}},"
            "\"goal_reached\":%s,"
            "\"timestamp\":\"%s\","
            "\"session_id\":\"%s\""
        "}",
        move_sequence,
        px, py,
        goal_reached ? "true" : "false",
        timestamp,
        session_id
    );
    printf("Posting telemetry JSON:\n%s\n", json);


    struct curl_slist* headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, HTTPS_URL);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

    // Self-signed cert
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);

    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 500L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 300L);



    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        fprintf(stderr, "HTTPS POST failed: %s\n", curl_easy_strerror(res));
    } else if (!printed_status) {
        printf("{\"status\":\"ok\"}\n");
        printed_status = true;
    }

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
}

// Local Log
static void save_json_move(
    const char* session_id,
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
        session_id, move_sequence, px, py,
        goal_reached ? "true" : "false",
        timestamp
    );

    fclose(f);
}

// Maze Logic
static inline bool in_bounds(int x, int y) {
    return (x >= 0 && x < MAZE_W && y >= 0 && y < MAZE_H);
}

// Remove wall between (x,y) and (nx,ny)
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

// Iterative DFS "recursive backtracker"
static void maze_generate(int sx, int sy) {
    typedef struct { int x, y; } P;
    P stack[MAZE_W * MAZE_H];
    int top = 0;

    g[sy][sx].visited = true;
    stack[top++] = (P){sx, sy};

    while (top > 0) {
        P cur = stack[top - 1];
        int x = cur.x, y = cur.y;

        // Collect unvisited neighbors
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

    // Clear visited flags
    for (int y = 0; y < MAZE_H; y++)
        for (int x = 0; x < MAZE_W; x++)
            g[y][x].visited = false;
}

// Draw maze walls as lines
static void draw_maze(SDL_Renderer* r) {
    int ox = PAD;
    int oy = PAD;

    SDL_SetRenderDrawColor(r, 230, 230, 230, 255); // maze walls

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

// Player / goal rendering
static void draw_player_goal(SDL_Renderer* r, int px, int py) {
    int ox = PAD;
    int oy = PAD;

    // Goal cell highlight
    SDL_Rect goal = {
        ox + (MAZE_W - 1) * CELL + 6,
        oy + (MAZE_H - 1) * CELL + 6,
        CELL - 12,
        CELL - 12
    };
    SDL_SetRenderDrawColor(r, 40, 160, 70, 255);
    SDL_RenderFillRect(r, &goal);

    // Player
    SDL_Rect p = {
        ox + px * CELL + 8,
        oy + py * CELL + 8,
        CELL - 16,
        CELL - 16
    };
    SDL_SetRenderDrawColor(r, 255, 255, 0, 255);
    SDL_RenderFillRect(r, &p);
}

// Attempt to move player; returns true if moved
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

static void regenerate(int* px, int* py, SDL_Window* win) {
    maze_init();
    maze_generate(0, 0);
    *px = 0; *py = 0;
    SDL_SetWindowTitle(win, "SDL2 Maze - Reach the green goal (R to regenerate)");

    // Reset printed_status when starting a new maze
    printed_status = false;
}


static void save_https_mission(const char* json, const char* mission_url) {

    printf("MISSION POST URL = %s\n", mission_url);
    CURL* curl = curl_easy_init();
    if (!curl) return;

    struct curl_slist* headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, mission_url);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS,json);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);

    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 800L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 500L);

    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        fprintf(stderr, "Mission POST failed (%s): %s\n", mission_url, curl_easy_strerror(res));
    } else {
        printf("Mission payload sent to %s\n", mission_url);
    }

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
}

static void print_full_mission_json(const char* mission_id,
                                    const char* result,
                                    const char* abort_reason) {
    char mission_json[1024];

    build_mission_json(mission_json, sizeof(mission_json),
                       mission_id, result, abort_reason);

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

int main(int argc, char** argv) {
    (void)argc; (void)argv;
    srand((unsigned)time(NULL));

    const char *TELEMETRY_URL = "https://10.170.8.109:8443/move";
    const char *MISSION_URL = getenv("MAZE_MISSION_URL");
    if (!MISSION_URL) MISSION_URL = "https://10.170.8.109:8443/mission";
	
    g_logging_url = getenv("MAZE_LOGGING_URL");
    g_ai_url      = getenv("MAZE_AI_URL");
    g_mission_url = getenv("MAZE_MISSION_URL");

    if (!g_logging_url) g_logging_url = "https://10.170.8.101:8443/move";
    if (!g_ai_url)      g_ai_url      = "https://10.170.8.109:8443/move";
    if (!g_mission_url) g_mission_url = "https://10.170.8.109:8443/mission";

    printf("Mission payload will post to: %s\n", g_mission_url);
    printf("Posting telemetry to logging: %s\n",g_logging_url );
    printf("Posting telemetry to AI: %s\n", g_ai_url);
                                   
        
    // Generates session UUID
    uuid_t binuuid; uuid_generate_random(binuuid);
    uuid_unparse_lower(binuuid, session_id);

    // Print status once at program start
    printf("{\"status\":\"ok\"}\n");
    printed_status = true;

    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return 1;
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

    SDL_Renderer* r = SDL_CreateRenderer(win, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    // ===== Start mission ===== 
    mission_start_time = time(NULL);
    mission_active = true;

    moves_left = moves_right = moves_straight = moves_reverse = 0;
    moves_total = 0;
    distance_traveled = 0.0;

    if (!r) {
        fprintf(stderr, "SDL_CreateRenderer failed: %s\n", SDL_GetError());
        SDL_DestroyWindow(win);
        SDL_Quit();
        return 1;
    }

    int px = 0, py = 0;
    int move_sequence = 0; // Tracks the number of moves
    regenerate(&px, &py, win);

    bool running = true;
    bool won = false;

    while (running) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) {
                if (mission_active) {
                    print_full_mission_json("MISSION_001", "aborted", "window closed");
                    mission_active = false;
                }
                running = false;
            }

            if (e.type == SDL_KEYDOWN) {
                SDL_Keycode k = e.key.keysym.sym;

                if (k == SDLK_ESCAPE) {
                    if (mission_active) {
                        print_full_mission_json("MISSION_001", "aborted", "user exited");
                        mission_active = false;
                    }
                    running = false;
                    break;
                }

                if (k == SDLK_r) {
                    regenerate(&px, &py, win);
                    won = false;
                    move_sequence = 0;

                    mission_start_time = time(NULL);
                    mission_active = true;
                    moves_left = moves_right = moves_straight = moves_reverse = 0;
                    moves_total = 0;
                    distance_traveled = 0.0;
                    continue;
                }

                if (!won) {
                    bool moved = false;

                    if (k == SDLK_UP || k == SDLK_w)    { moved |= try_move(&px, &py, 0, -1); if (moved) moves_straight++; }
                    if (k == SDLK_RIGHT || k == SDLK_d) { moved |= try_move(&px, &py, 1, 0);  if (moved) moves_right++; }
                    if (k == SDLK_DOWN || k == SDLK_s)  { moved |= try_move(&px, &py, 0, 1);  if (moved) moves_reverse++; }
                    if (k == SDLK_LEFT || k == SDLK_a)  { moved |= try_move(&px, &py, -1, 0); if (moved) moves_left++; }

                    if (moved) {
                        move_sequence++;
                        moves_total++;
                        distance_traveled += 1.0;

                        bool goal = (px == MAZE_W - 1 && py == MAZE_H - 1);

                        save_json_move(session_id, px, py, move_sequence, goal);
                        save_https_move(session_id, px, py, move_sequence, goal, g_logging_url);
                        save_https_move(session_id, px, py, move_sequence, goal, g_ai_url);

                        if (goal && mission_active) {
                            won = true;
                            print_full_mission_json("MISSION_001", "success", "none");
                            mission_active = false;
                            SDL_SetWindowTitle(win, "You win! Press R to regenerate, Esc to quit");
                        }
                    }
                }
            }
        }

        SDL_SetRenderDrawColor(r, 15, 15, 18, 255);
        SDL_RenderClear(r);
        draw_maze(r);
        draw_player_goal(r, px, py);
        SDL_RenderPresent(r);
    }

    curl_global_cleanup();
    SDL_DestroyRenderer(r);
    SDL_DestroyWindow(win);
    SDL_Quit();
    return 0;
}

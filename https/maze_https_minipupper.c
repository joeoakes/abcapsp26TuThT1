// https/maze_https_minipupper.c
// HTTPS server for Mini-Pupper v1.
//
// Receives POST /move telemetry JSON (same schema as maze_sdl2 client),
// parses the "move_dir" field, and publishes a geometry_msgs/msg/Twist
// message to the ROS2 /cmd_vel topic so the Mini-Pupper moves.
//
// Supported move_dir values: forward, backward, left, right, stop
//
// Build:
//   gcc -O2 -Wall -Wextra -std=c11 maze_https_minipupper.c \
//       -o maze_https_minipupper \
//       $(pkg-config --cflags --libs libmicrohttpd gnutls)
//
// Run (on the Mini-Pupper):
//   ./maze_https_minipupper
//
// Test with curl:
//   curl -k -X POST https://localhost:8443/move \
//        -H "Content-Type: application/json" \
//        -d '{"event_type":"player_move","move_dir":"forward"}'

#include <errno.h>
#include <microhttpd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define DEFAULT_PORT 8443
#define CMD_BUF_SIZE 512

// ROS2 cmd_vel linear/angular speeds (m/s and rad/s)
#define LINEAR_SPEED  0.2
#define ANGULAR_SPEED 0.5

static const char *cert_file = "certs/server.crt";
static const char *key_file  = "certs/server.key";

struct connection_info {
    char *data;
    size_t size;
};

static char *read_file(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(n + 1);
    if (!buf) { fclose(f); return NULL; }
    if (fread(buf, 1, n, f) != (size_t)n) { fclose(f); free(buf); return NULL; }
    buf[n] = '\0';
    fclose(f);
    return buf;
}

static void get_utc_iso8601(char *buf, size_t len) {
    time_t now = time(NULL);
    struct tm tm;
    gmtime_r(&now, &tm);
    strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

// Simple extraction of "move_dir" value from JSON string.
// Returns pointer to a static buffer with the value, or NULL.
static const char *parse_move_dir(const char *json) {
    static char val[32];
    const char *key = "\"move_dir\"";
    const char *p = strstr(json, key);
    if (!p) return NULL;

    p += strlen(key);
    // skip whitespace and colon
    while (*p == ' ' || *p == ':' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    if (*p != '"') return NULL;
    p++; // skip opening quote

    size_t i = 0;
    while (*p && *p != '"' && i < sizeof(val) - 1) {
        val[i++] = *p++;
    }
    val[i] = '\0';
    return val;
}

// Publish a Twist message to /cmd_vel via ros2 CLI.
static void publish_cmd_vel(double linear_x, double angular_z) {
    char cmd[CMD_BUF_SIZE];
    snprintf(cmd, sizeof(cmd),
        "ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "
        "\"{linear: {x: %.2f, y: 0.0, z: 0.0}, "
        "angular: {x: 0.0, y: 0.0, z: %.2f}}\" "
        ">/dev/null 2>&1 &",
        linear_x, angular_z);

    printf("ROS2 cmd: %s\n", cmd);
    int ret = system(cmd);
    if (ret != 0) {
        fprintf(stderr, "Warning: ros2 topic pub returned %d\n", ret);
    }
}

// Map move_dir string to cmd_vel values and publish.
static void handle_move_dir(const char *dir) {
    if (!dir) return;

    double lx = 0.0, az = 0.0;

    if (strcmp(dir, "forward") == 0) {
        lx = LINEAR_SPEED;
    } else if (strcmp(dir, "backward") == 0) {
        lx = -LINEAR_SPEED;
    } else if (strcmp(dir, "left") == 0) {
        az = ANGULAR_SPEED;
    } else if (strcmp(dir, "right") == 0) {
        az = -ANGULAR_SPEED;
    } else if (strcmp(dir, "stop") == 0) {
        lx = 0.0; az = 0.0;
    } else {
        fprintf(stderr, "Unknown move_dir: %s\n", dir);
        return;
    }

    printf("move_dir=%s -> linear.x=%.2f angular.z=%.2f\n", dir, lx, az);
    publish_cmd_vel(lx, az);
}

static enum MHD_Result handle_post(void *cls,
                       struct MHD_Connection *connection,
                       const char *url,
                       const char *method,
                       const char *version,
                       const char *upload_data,
                       size_t *upload_data_size,
                       void **con_cls)
{
    (void)version;
    (void)cls;

    if (strcmp(method, "POST") != 0 || strcmp(url, "/move") != 0)
        return MHD_NO;

    if (*con_cls == NULL) {
        struct connection_info *ci = calloc(1, sizeof(*ci));
        *con_cls = ci;
        return MHD_YES;
    }

    struct connection_info *ci = *con_cls;

    if (*upload_data_size != 0) {
        ci->data = realloc(ci->data, ci->size + *upload_data_size + 1);
        memcpy(ci->data + ci->size, upload_data, *upload_data_size);
        ci->size += *upload_data_size;
        ci->data[ci->size] = '\0';
        *upload_data_size = 0;
        return MHD_YES;
    }

    // Log received JSON
    char ts[64];
    get_utc_iso8601(ts, sizeof(ts));
    printf("[%s] Received: %s\n", ts, ci->data);

    // Parse move_dir and send to Mini-Pupper
    const char *dir = parse_move_dir(ci->data);
    if (dir) {
        handle_move_dir(dir);
    } else {
        printf("No move_dir found in JSON (telemetry-only message)\n");
    }

    const char *response = "{\"status\":\"ok\"}";
    struct MHD_Response *resp =
        MHD_create_response_from_buffer(strlen(response),
                                         (void *)response,
                                         MHD_RESPMEM_PERSISTENT);

    int ret = MHD_queue_response(connection, MHD_HTTP_OK, resp);
    MHD_destroy_response(resp);

    free(ci->data);
    free(ci);
    *con_cls = NULL;

    return ret;
}

int main(void) {
    char *cert_pem = read_file(cert_file);
    char *key_pem  = read_file(key_file);
    if (!cert_pem || !key_pem) {
        fprintf(stderr, "Failed to read cert/key files (%s, %s)\n",
                cert_file, key_file);
        return 1;
    }

    struct MHD_Daemon *daemon = MHD_start_daemon(
        MHD_USE_THREAD_PER_CONNECTION | MHD_USE_TLS,
        DEFAULT_PORT,
        NULL, NULL,
        &handle_post, NULL,
        MHD_OPTION_HTTPS_MEM_CERT,
        cert_pem,
        MHD_OPTION_HTTPS_MEM_KEY,
        key_pem,
        MHD_OPTION_END);

    if (!daemon) {
        fprintf(stderr, "Failed to start HTTPS server on port %d\n",
                DEFAULT_PORT);
        return 1;
    }

    printf("========================================\n");
    printf("  Mini-Pupper v1 HTTPS Telemetry Server\n");
    printf("========================================\n");
    printf("Listening on https://0.0.0.0:%d\n", DEFAULT_PORT);
    printf("POST JSON to /move\n");
    printf("Supported move_dir: forward, backward, left, right, stop\n");
    printf("ROS2 topic: /cmd_vel\n");
    printf("========================================\n");
    printf("Press Enter to stop...\n");

    getchar();

    MHD_stop_daemon(daemon);
    free(cert_pem);
    free(key_pem);
    return 0;
}

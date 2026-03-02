#include <errno.h>
#include <microhttpd.h>
#include <hiredis/hiredis.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define DEFAULT_PORT 8443
#define POSTBUFFERSIZE  4096
#define MAXNAMESIZE     64
#define MAXANSWERSIZE   512
#define DEFAULT_MONGO_URI "mongodb://localhost:27017"
#define DEFAULT_MONGO_DB  "maze"
#define DEFAULT_MONGO_COL "moves"

static const char *cert_file = "certs/server.crt";
static const char *key_file  = "certs/server.key";
/* Optional: when set, server requires client certificates (mTLS) */
static const char *ca_file   = "certs/ca.crt";
static redisContext *redis;

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

struct app_config {
    const char *mongo_uri;
    const char *mongo_db;
    const char *mongo_col;
};

static struct app_config config;

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

    /* MongoDB insert */
    redisReply *reply = redisCommand(redis,
    "RPUSH team1tt_pupbyte1 %s", ci->data);

    if (!reply) {
    	fprintf(stderr, "Redis insert failed\n");
    } else {
    	printf("Redis insert success\n");
    	freeReplyObject(reply);
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
    config.mongo_uri = getenv("MONGO_URI");
    if (!config.mongo_uri || !*config.mongo_uri)
        config.mongo_uri = DEFAULT_MONGO_URI;

    config.mongo_db = getenv("MONGO_DB");
    if (!config.mongo_db || !*config.mongo_db)
        config.mongo_db = DEFAULT_MONGO_DB;

    config.mongo_col = getenv("MONGO_COL");
    if (!config.mongo_col || !*config.mongo_col)
        config.mongo_col = DEFAULT_MONGO_COL;


    redis = redisConnect("127.0.0.1", 6379);
    if (redis == NULL || redis->err) {
    	fprintf(stderr, "Failed to connect to Redis\n");
    	return 1;
}


	char *cert_pem = read_file(cert_file);
	char *key_pem  = read_file(key_file);
	if (!cert_pem || !key_pem) {
    	fprintf(stderr, "Failed to read cert/key files\n");
    	return 1;
	}

	const char *ca_path = getenv("CA_FILE");
	if (!ca_path || !*ca_path)
		ca_path = ca_file;
	char *ca_pem = read_file(ca_path);
	int use_mtls = (ca_pem != NULL);

	struct MHD_Daemon *daemon;
	if (use_mtls) {
		daemon = MHD_start_daemon(
			MHD_USE_THREAD_PER_CONNECTION | MHD_USE_TLS,
			DEFAULT_PORT,
			NULL, NULL,
			&handle_post, NULL,
			MHD_OPTION_HTTPS_MEM_CERT,
			cert_pem,
			MHD_OPTION_HTTPS_MEM_KEY,
			key_pem,
			MHD_OPTION_HTTPS_MEM_TRUST,
			ca_pem,
			MHD_OPTION_END);
	} else {
		daemon = MHD_start_daemon(
			MHD_USE_THREAD_PER_CONNECTION | MHD_USE_TLS,
			DEFAULT_PORT,
			NULL, NULL,
			&handle_post, NULL,
			MHD_OPTION_HTTPS_MEM_CERT,
			cert_pem,
			MHD_OPTION_HTTPS_MEM_KEY,
			key_pem,
			MHD_OPTION_END);
	}

    if (!daemon) {
        fprintf(stderr, "Failed to start HTTPS server\n");
        return 1;
    }

    	printf("========================================\n");
	if (use_mtls)
		printf("mTLS: client certificates required (CA: %s)\n", ca_path);
	else
		printf("TLS only (no client cert required). Set CA_FILE for mTLS.\n");
	printf("Database backend: Redis\n");
	printf("Redis host: 127.0.0.1\n");
	printf("Redis port: 6379\n");
	printf("Key namespace example: team1ttmission\n");
	printf("========================================\n\n");

	printf("HTTPS Redis mission server running on port %d\n", DEFAULT_PORT);

    getchar();

    MHD_stop_daemon(daemon);
	free(cert_pem);
	free(key_pem);
	if (ca_pem)
		free(ca_pem);
    redisFree(redis);
    return 0;
}

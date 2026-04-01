/*
 * botos.h — single-header C client for botOS components
 *
 * Usage:
 *   #include "botos.h"
 *
 *   int main() {
 *       botos_connect();
 *       botos_publish("/s/sensor/data", "{\"value\":42}");
 *
 *       char buf[4096];
 *       while (1) {
 *           if (botos_receive(buf, sizeof(buf)) > 0) {
 *               // buf contains the JSON body string
 *           }
 *       }
 *       return 0;
 *   }
 */

#pragma once

#include <arpa/inet.h>
#include <netdb.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static int _botos_fd = -1;

static int _botos_send_raw(const char *json, size_t len) {
    uint32_t net_len = htonl((uint32_t)len);
    if (send(_botos_fd, &net_len, 4, 0) != 4) return -1;
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = send(_botos_fd, json + sent, len - sent, 0);
        if (n <= 0) return -1;
        sent += n;
    }
    return 0;
}

static int _botos_recv_raw(char *buf, size_t bufsz) {
    uint32_t net_len;
    if (recv(_botos_fd, &net_len, 4, MSG_WAITALL) != 4) return -1;
    uint32_t len = ntohl(net_len);
    if (len >= bufsz) return -1;
    if ((size_t)recv(_botos_fd, buf, len, MSG_WAITALL) != len) return -1;
    buf[len] = '\0';
    return (int)len;
}

static void botos_connect(void) {
    const char *host = getenv("BOTOS_ROUTER_HOST");
    const char *port_str = getenv("BOTOS_ROUTER_PORT");
    const char *name = getenv("BOTOS_COMPONENT_NAME");
    const char *channels = getenv("BOTOS_CHANNELS");

    if (!host) host = "localhost";
    if (!port_str) port_str = "5555";
    if (!name) name = "unknown";
    if (!channels) channels = "{}";

    struct addrinfo hints = {0}, *res;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, port_str, &hints, &res) != 0) {
        perror("botos: getaddrinfo");
        exit(1);
    }

    _botos_fd = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (_botos_fd < 0) { perror("botos: socket"); exit(1); }
    if (connect(_botos_fd, res->ai_addr, res->ai_addrlen) < 0) {
        perror("botos: connect");
        exit(1);
    }
    freeaddrinfo(res);

    /* register */
    char reg[4096];
    snprintf(reg, sizeof(reg),
        "{\"type\":\"register\",\"component\":\"%s\",\"paths\":%s}",
        name, channels);
    _botos_send_raw(reg, strlen(reg));

    char ack[256];
    _botos_recv_raw(ack, sizeof(ack));
    if (!strstr(ack, "\"ok\"")) {
        fprintf(stderr, "botos: registration failed: %s\n", ack);
        exit(1);
    }
}

static int botos_publish(const char *path, const char *json_body) {
    char msg[8192];
    snprintf(msg, sizeof(msg),
        "{\"verb\":\"write\",\"path\":\"%s\",\"body\":%s}",
        path, json_body);
    return _botos_send_raw(msg, strlen(msg));
}

/* Returns length of body JSON written to buf, or -1 on error. */
static int botos_receive(char *buf, size_t bufsz) {
    char raw[65536];
    int len = _botos_recv_raw(raw, sizeof(raw));
    if (len < 0) return -1;
    /* extract "body": ... — naive but avoids a JSON dep */
    char *body = strstr(raw, "\"body\":");
    if (!body) { buf[0] = '\0'; return 0; }
    body += 7;
    size_t blen = strlen(body);
    if (blen >= bufsz) return -1;
    memcpy(buf, body, blen + 1);
    return (int)blen;
}

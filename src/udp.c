#include "udp.h"
#include <stdio.h>
#include <winsock2.h>
#include <ws2tcpip.h>

#ifdef _MSC_VER
#pragma comment(lib, "ws2_32.lib")
#endif

int udp_init(void)
{
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        fprintf(stderr, "WSAStartup 失败: %d\n", WSAGetLastError());
        return -1;
    }
    return 0;
}

void udp_cleanup(void)
{
    WSACleanup();
}

sock_handle_t udp_create_data_socket(const char *local_ip, uint16_t port, uint32_t timeout_sec)
{
    SOCKET sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == INVALID_SOCKET) {
        fprintf(stderr, "创建数据 socket 失败: %d\n", WSAGetLastError());
        return (sock_handle_t)INVALID_SOCKET;
    }

    /* 设置接收超时 */
    DWORD tv = timeout_sec * 1000;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, (const char *)&tv, sizeof(tv));

    /* 设置接收缓冲区 */
    int rcvbuf = 64 * 1024 * 1024; /* 64MB */
    setsockopt(sock, SOL_SOCKET, SO_RCVBUF, (const char *)&rcvbuf, sizeof(rcvbuf));

    /* 绑定端口 */
    struct sockaddr_in addr;
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(port);

    if (local_ip && local_ip[0] != '\0') {
        if (inet_pton(AF_INET, local_ip, &addr.sin_addr) != 1) {
            fprintf(stderr, "无效的本机 IP: %s\n", local_ip);
            closesocket(sock);
            return (sock_handle_t)INVALID_SOCKET;
        }
    } else {
        addr.sin_addr.s_addr = INADDR_ANY;
    }

    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) == SOCKET_ERROR) {
        fprintf(stderr, "绑定数据端口 %hu 失败: %d\n", port, WSAGetLastError());
        closesocket(sock);
        return (sock_handle_t)INVALID_SOCKET;
    }

    return (sock_handle_t)sock;
}

sock_handle_t udp_create_cmd_socket(const char *local_ip, const char *target_ip, uint16_t port)
{
    SOCKET sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == INVALID_SOCKET) {
        fprintf(stderr, "创建命令 socket 失败: %d\n", WSAGetLastError());
        return (sock_handle_t)INVALID_SOCKET;
    }

    /* 指定本机 IP 时先 bind */
    if (local_ip && local_ip[0] != '\0') {
        struct sockaddr_in local_addr;
        local_addr.sin_family = AF_INET;
        local_addr.sin_port   = 0;
        if (inet_pton(AF_INET, local_ip, &local_addr.sin_addr) != 1) {
            fprintf(stderr, "无效的本机 IP: %s\n", local_ip);
            closesocket(sock);
            return (sock_handle_t)INVALID_SOCKET;
        }
        if (bind(sock, (struct sockaddr *)&local_addr, sizeof(local_addr)) == SOCKET_ERROR) {
            fprintf(stderr, "绑定本机 IP %s 失败: %d\n", local_ip, WSAGetLastError());
            closesocket(sock);
            return (sock_handle_t)INVALID_SOCKET;
        }
    }

    /* 设置目标地址 */
    struct sockaddr_in addr;
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(port);
    if (inet_pton(AF_INET, target_ip, &addr.sin_addr) != 1) {
        fprintf(stderr, "无效的目标 IP: %s\n", target_ip);
        closesocket(sock);
        return (sock_handle_t)INVALID_SOCKET;
    }

    if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) == SOCKET_ERROR) {
        fprintf(stderr, "connect 命令 socket 失败: %d\n", WSAGetLastError());
        closesocket(sock);
        return (sock_handle_t)INVALID_SOCKET;
    }

    return (sock_handle_t)sock;
}

int udp_send_cmd(sock_handle_t sock, uint8_t cmd)
{
    int ret = send((SOCKET)sock, (const char *)&cmd, 1, 0);
    if (ret == SOCKET_ERROR) {
        fprintf(stderr, "发送命令 0x%02X 失败: %d\n", cmd, WSAGetLastError());
        return -1;
    }
    fprintf(stderr, "[CMD] 已发送命令 0x%02X (%s)\n",
            cmd, cmd == 0x01 ? "START" : "STOP");
    return 0;
}

int udp_recv_data(sock_handle_t sock, uint8_t *buf, size_t buf_len,
                  size_t *bytes_received)
{
    int ret = recvfrom((SOCKET)sock, (char *)buf, (int)buf_len, 0, NULL, NULL);
    if (ret == SOCKET_ERROR) {
        int err = WSAGetLastError();
        if (err == WSAETIMEDOUT) {
            return 1; /* 超时 */
        }
        fprintf(stderr, "recvfrom 失败: %d\n", err);
        return -1;
    }
    *bytes_received = (size_t)ret;
    return 0;
}

void udp_close(sock_handle_t sock)
{
    if (sock != (sock_handle_t)INVALID_SOCKET) {
        closesocket((SOCKET)sock);
    }
}

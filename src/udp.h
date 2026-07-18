#ifndef UDP_H
#define UDP_H

#include <stdint.h>
#include <stddef.h>

/* socket 句柄，INVALID_SOCKET 表示无效 */
typedef intptr_t sock_handle_t;

int         udp_init(void);
void        udp_cleanup(void);
sock_handle_t udp_create_data_socket(const char *local_ip, uint16_t port, uint32_t timeout_sec);
sock_handle_t udp_create_tx_socket(const char *local_ip, const char *target_ip, uint16_t port);
int         udp_send_cmd(sock_handle_t sock, uint8_t cmd);
int         udp_send_cmd_bytes(sock_handle_t sock, const uint8_t *data, size_t len);
int         udp_recv_data(sock_handle_t sock, uint8_t *buf, size_t buf_len,
                          size_t *bytes_received);
void        udp_close(sock_handle_t sock);

#endif /* UDP_H */

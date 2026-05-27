#ifndef COE_H
#define COE_H

#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint8_t *data;
    size_t   len;
} coe_data_t;

int  coe_parse(const char *filepath, coe_data_t *coe_data);
void coe_free(coe_data_t *coe_data);

#endif /* COE_H */

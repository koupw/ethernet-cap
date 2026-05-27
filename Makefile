CC      = gcc
CFLAGS  = -std=c11 -Wall -Wextra -O2
LDFLAGS = -lws2_32

SRCS    = src/main.c src/udp.c src/ringbuf.c src/writer.c src/stats.c src/coe.c
OBJS    = $(SRCS:.c=.o)
TARGET  = ethernet-cap.exe

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)

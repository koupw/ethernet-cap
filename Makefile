CC      = gcc
CFLAGS  = -std=c11 -Wall -Wextra -O2
LDFLAGS = -lws2_32

SRCS    = src/main.c src/udp.c src/ringbuf.c src/writer.c src/stats.c src/coe.c src/utils.c
OBJS    = $(SRCS:.c=.o)
TARGET  = ethernet-cap.exe

TEST_SRCS = tests/runtests.c tests/test_ringbuf.c tests/test_coe.c tests/test_utils.c tests/test_stats.c \
            src/ringbuf.c src/coe.c src/stats.c src/utils.c
TEST_TARGET = tests/runtests.exe

.PHONY: all clean test

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

test: $(TEST_TARGET)
	./$(TEST_TARGET)

$(TEST_TARGET): $(TEST_SRCS)
	$(CC) $(CFLAGS) -Isrc -Itests -o $@ $(TEST_SRCS) $(LDFLAGS)

clean:
	rm -f $(OBJS) $(TARGET) $(TEST_TARGET) tests/*.o

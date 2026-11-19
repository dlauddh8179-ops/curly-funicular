CC ?= gcc
CFLAGS = -std=c11 -O2 -Wall -Wextra -Werror -I../include -I.
SRC = ../src/aac_crc.c ../src/aac_adpcm.c ../src/aac_pkg.c ../src/aac_player.c ../src/aac_events.c ../src/aac_update.c mock_hal.c test_main.c
test_aac: $(SRC)
	$(CC) $(CFLAGS) -o $@ $(SRC)
run: test_aac
	./test_aac data/v1.aacpkg data/v2.aacpkg data/reference.txt
clean:
	rm -f test_aac

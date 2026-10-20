// Читает 172 байта пакета из stdin, раскладывает по полям driver/src/protocol.h
// и печатает значения. Используется tests/test_core.py, чтобы убедиться,
// что Python и C++ одинаково понимают формат пакета.
#include <cstdio>
#include <cstring>

#include "../driver/src/protocol.h"

int main() {
    vrhand::Packet p;
    if (std::fread(&p, 1, sizeof(p), stdin) != sizeof(p)) {
        std::fprintf(stderr, "need %zu bytes\n", sizeof(p));
        return 1;
    }
    std::printf("magic %u\nseq %u\n", p.magic, p.seq);
    std::printf("head");
    for (int i = 0; i < 7; i++) std::printf(" %.6f", p.head[i]);
    for (int h = 0; h < 2; h++) {
        std::printf("\nhand%d", h);
        for (int i = 0; i < 7; i++) std::printf(" %.6f", p.hand[h][i]);
    }
    std::printf("\ntrigger %.6f %.6f\ngrip %.6f %.6f\n", p.trigger[0], p.trigger[1], p.grip[0], p.grip[1]);
    std::printf("stick %.6f %.6f %.6f %.6f\n", p.stick[0][0], p.stick[0][1], p.stick[1][0], p.stick[1][1]);
    std::printf("buttons %u %u\n", p.buttons[0], p.buttons[1]);
    for (int h = 0; h < 2; h++) {
        std::printf("fingers%d", h);
        for (int i = 0; i < 5; i++) std::printf(" %.6f", p.fingers[h][i]);
        std::printf("\n");
    }
    std::printf("sizeof %zu\n", sizeof(p));
    return 0;
}

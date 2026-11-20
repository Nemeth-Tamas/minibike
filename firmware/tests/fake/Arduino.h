#pragma once
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <algorithm>
using std::min;
inline uint32_t millis() { static uint32_t now = 1; return ++now; }
inline void delay(int) {}
struct FakeSerial {
  template <typename ... Args> void printf(const char*, Args...) {}
} ;
extern FakeSerial Serial;

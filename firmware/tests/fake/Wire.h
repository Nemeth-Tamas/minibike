#pragma once
#include <cstdint>
#include <cstddef>
#include <vector>
struct FakeWire {
  uint8_t memory[32768];
  uint16_t cursor = 0;
  std::vector<uint8_t> send;
  FakeWire();
  void begin(uint8_t,uint8_t,uint32_t) {}
  void beginTransmission(uint8_t) { send.clear(); }
  size_t write(uint8_t value) { send.push_back(value); return 1; }
  size_t write(const uint8_t *src,size_t n) { send.insert(send.end(),src,src+n); return n; }
  uint8_t endTransmission(bool stop=true);
  int requestFrom(int,size_t count);
  int read();
  int left=0;
};
extern FakeWire Wire;

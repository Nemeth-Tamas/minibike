#pragma once
#include <Arduino.h>
#include <Wire.h>
#include "Config.h"

// One single-page-write slot per accepted revolution. 1024 x 32 bytes = 32 KiB.
// Status is excluded from CRC: torn ACK bytes cause harmless replay, not seq reset.
struct __attribute__((packed)) RevRecord {
  uint16_t magic;
  uint8_t version;
  uint8_t status;
  uint64_t seq;
  uint64_t epoch_ms;   // 0 means unknown at capture
  uint32_t uptime_ms; // since THAT record's boot
  uint32_t boot_token;
  uint32_t crc;
};
static_assert(sizeof(RevRecord) == 32, "EEPROM journal records must be exactly 32 bytes");

class RevJournal {
public:
  static constexpr uint16_t kSlots = 1024;
  static constexpr uint8_t kPending = 0xA5;
  static constexpr uint8_t kAcked = 0x5A;
  static constexpr uint16_t kMagic = 0xD6C6;
  bool begin();
  bool append(uint64_t epochMs, uint32_t uptimeMs, uint32_t bootToken);
  bool markAcked(uint64_t seq);
  uint64_t highestSeq() const { return newestSeq_; }
  uint32_t pendingCount() const;
  uint32_t overwrittenUnacked() const { return overflowCount_; }
  const RevRecord *bySequence(uint64_t seq) const;
  // Return up to `maxRecords` events in sequence order from one boot.
  size_t oldestPending(RevRecord *out, size_t maxRecords) const;

private:
  RevRecord slots_[kSlots] = {};
  uint64_t newestSeq_ = 0;
  uint32_t overflowCount_ = 0;
  uint32_t crc32(const RevRecord &r) const;
  bool valid(const RevRecord &r) const;
  bool readBytes(uint16_t addr, uint8_t *dst, size_t len);
  bool writeBytes(uint16_t addr, const uint8_t *src, size_t len);
  static uint16_t slotIndex(uint64_t seq) { return static_cast<uint16_t>(seq % kSlots); }
};

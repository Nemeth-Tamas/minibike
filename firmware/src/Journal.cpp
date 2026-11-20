#include "Journal.h"
#include <cstring>

// Conventional IEEE CRC-32; intentionally excludes mutable status and the CRC field.
uint32_t RevJournal::crc32(const RevRecord &r) const {
  const uint8_t *p = reinterpret_cast<const uint8_t *>(&r);
  uint32_t crc = 0xFFFFFFFFu;
  for (size_t i = 0; i < offsetof(RevRecord, crc); ++i) {
    if (i == offsetof(RevRecord, status)) continue;
    crc ^= p[i];
    for (uint8_t b = 0; b < 8; ++b) crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320u : 0);
  }
  return ~crc;
}

bool RevJournal::valid(const RevRecord &r) const {
  return r.magic == kMagic && r.version == 1 && r.seq > 0 && r.crc == crc32(r);
}

bool RevJournal::readBytes(uint16_t addr, uint8_t *dst, size_t len) {
  size_t pos = 0;
  while (pos < len) {
    const size_t take = min(static_cast<size_t>(32), len - pos);
    const uint16_t a = addr + pos;
    Wire.beginTransmission(cfg::EEPROM_ADDR);
    Wire.write(static_cast<uint8_t>(a >> 8));
    Wire.write(static_cast<uint8_t>(a & 0xFF));
    if (Wire.endTransmission(false) != 0) return false;
    if (static_cast<size_t>(Wire.requestFrom(static_cast<int>(cfg::EEPROM_ADDR), static_cast<int>(take))) != take) return false;
    for (size_t i = 0; i < take; ++i) dst[pos + i] = static_cast<uint8_t>(Wire.read());
    pos += take;
  }
  return true;
}

bool RevJournal::writeBytes(uint16_t addr, const uint8_t *src, size_t len) {
  // Caller guarantees never crossing the 64-byte EEPROM page boundary.
  if (!len || len > 64 || (addr / 64) != ((addr + len - 1) / 64)) return false;
  Wire.beginTransmission(cfg::EEPROM_ADDR);
  Wire.write(static_cast<uint8_t>(addr >> 8));
  Wire.write(static_cast<uint8_t>(addr & 0xFF));
  if (Wire.write(src, len) != len || Wire.endTransmission(true) != 0) return false;
  const uint32_t start = millis();
  while (millis() - start < 30) { // EEPROM ACK polling, often about 5 ms
    Wire.beginTransmission(cfg::EEPROM_ADDR);
    if (Wire.endTransmission() == 0) return true;
    delay(1);
  }
  return false;
}

bool RevJournal::begin() {
  Wire.begin(cfg::I2C_SDA, cfg::I2C_SCL, 100000); // conservative until module is tested
  Wire.beginTransmission(cfg::EEPROM_ADDR);
  if (Wire.endTransmission() != 0) return false;
  newestSeq_ = 0;
  for (uint16_t i = 0; i < kSlots; ++i) {
    if (!readBytes(i * sizeof(RevRecord), reinterpret_cast<uint8_t *>(&slots_[i]), sizeof(RevRecord))) return false;
    if (!valid(slots_[i])) { memset(&slots_[i], 0, sizeof(RevRecord)); continue; }
    if (slots_[i].seq > newestSeq_) newestSeq_ = slots_[i].seq;
  }
  Serial.printf("[journal] recovered seq=%llu pending=%lu\n",
                static_cast<unsigned long long>(newestSeq_), static_cast<unsigned long>(pendingCount()));
  return true;
}

uint32_t RevJournal::pendingCount() const {
  uint32_t count = 0;
  for (const RevRecord &r : slots_) if (valid(r) && r.status != kAcked) ++count;
  return count;
}

const RevRecord *RevJournal::bySequence(uint64_t seq) const {
  const RevRecord &r = slots_[slotIndex(seq)];
  return valid(r) && r.seq == seq ? &r : nullptr;
}

bool RevJournal::append(uint64_t epochMs, uint32_t uptimeMs, uint32_t bootToken) {
  if (newestSeq_ == UINT64_MAX) return false;
  RevRecord r = {};
  r.magic = kMagic;
  r.version = 1;
  r.status = kPending;
  r.seq = newestSeq_ + 1;
  r.epoch_ms = epochMs;
  r.uptime_ms = uptimeMs;
  r.boot_token = bootToken;
  r.crc = crc32(r);
  const uint16_t i = slotIndex(r.seq);
  RevRecord old = slots_[i];
  if (!writeBytes(i * sizeof(RevRecord), reinterpret_cast<const uint8_t *>(&r), sizeof(r))) return false;
  RevRecord check;
  if (!readBytes(i * sizeof(RevRecord), reinterpret_cast<uint8_t *>(&check), sizeof(check)) ||
      !valid(check) || check.seq != r.seq) return false;
  if (valid(old) && old.status != kAcked) {
    ++overflowCount_; // after >1024 unacknowledged revolutions we retain lifetime, not raw history
    Serial.printf("[journal] WARNING: overwrote unsent seq=%llu (offline queue full)\n",
                  static_cast<unsigned long long>(old.seq));
  }
  slots_[i] = check;
  newestSeq_ = r.seq; // Only advance after EEPROM readback verifies durability
  return true;
}

bool RevJournal::markAcked(uint64_t seq) {
  const uint16_t i = slotIndex(seq);
  RevRecord &r = slots_[i];
  if (!valid(r) || r.seq != seq) return false;
  if (r.status == kAcked) return true;
  const uint8_t acked = kAcked;
  const uint16_t addr = i * sizeof(RevRecord) + offsetof(RevRecord, status);
  if (!writeBytes(addr, &acked, 1)) return false;
  uint8_t verify = 0;
  if (!readBytes(addr, &verify, 1) || verify != acked) return false;
  r.status = kAcked;
  return true;
}

size_t RevJournal::oldestPending(RevRecord *out, size_t maxRecords) const {
  uint64_t oldest = UINT64_MAX;
  for (const RevRecord &r : slots_) {
    if (valid(r) && r.status != kAcked && r.seq < oldest) oldest = r.seq;
  }
  if (oldest == UINT64_MAX || !maxRecords) return 0;
  const RevRecord *first = bySequence(oldest);
  if (!first) return 0;
  const uint32_t boot = first->boot_token;
  size_t count = 0;
  for (uint64_t seq = oldest; count < maxRecords && seq <= newestSeq_; ++seq) {
    const RevRecord *r = bySequence(seq);
    if (!r || r->status == kAcked || r->boot_token != boot) break;
    out[count++] = *r;
  }
  return count;
}

#include <cstring>
#include <cstdio>
#include <cassert>
#include "fake/Arduino.h"
#include "fake/Wire.h"
#include "Journal.h"

FakeSerial Serial;
FakeWire Wire;
FakeWire::FakeWire() { memset(memory,0xFF,sizeof(memory)); }
uint8_t FakeWire::endTransmission(bool stop) {
  if (send.empty()) return 0;
  if (send.size()<2) return 1;
  cursor=(uint16_t(send[0])<<8)|send[1];
  if (stop && send.size()>2) {
    for(size_t i=2; i<send.size(); ++i) memory[cursor+i-2]=send[i];
  }
  return 0;
}
int FakeWire::requestFrom(int,size_t count) { left=static_cast<int>(count);return left; }
int FakeWire::read() { if(left--<1)return -1;return memory[cursor++]; }

int main() {
  static RevJournal first;
  assert(first.begin());
  assert(first.highestSeq()==0);
  assert(first.append(1794770000000ULL, 1000, 0xABCD));
  assert(first.append(1794770001000ULL, 2000, 0xABCD));
  assert(first.pendingCount()==2);
  assert(first.markAcked(1));
  assert(first.pendingCount()==1);
  static RevJournal recovered;
  assert(recovered.begin());
  assert(recovered.highestSeq()==2);
  assert(recovered.pendingCount()==1);
  RevRecord records[8];
  assert(recovered.oldestPending(records,8)==1 && records[0].seq==2);
  assert(recovered.markAcked(2));
  for(uint32_t i=0;i<RevJournal::kSlots + 5;i++) {
    assert(recovered.append(0,10000+i,0xCDEF));
    // Backend online: at most one event outstanding, all slots can be safely reused.
    assert(recovered.markAcked(recovered.highestSeq()));
  }
  static RevJournal recoveredAgain;
  assert(recoveredAgain.begin());
  assert(recoveredAgain.highestSeq()==2+RevJournal::kSlots+5);
  assert(recoveredAgain.pendingCount()==0);
  // During a long offline period, the ring never resets the lifetime sequence.
  for(uint32_t i=0;i<RevJournal::kSlots+1;i++) assert(recoveredAgain.append(0,40000+i,0xDDDD));
  assert(recoveredAgain.pendingCount()==RevJournal::kSlots);
  assert(recoveredAgain.overwrittenUnacked()==1);
  assert(recoveredAgain.oldestPending(records,8)==8);
  assert(records[0].seq == recoveredAgain.highestSeq() - RevJournal::kSlots + 1);
  std::puts("Journal tests passed: restart, ACK, wrap, offline overflow, permanent sequence");
}

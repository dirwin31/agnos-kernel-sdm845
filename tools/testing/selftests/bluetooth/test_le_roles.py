#!/usr/bin/env python3
"""Check the driver's LE role gates against HCI supported-state combinations."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[4]

def function(source, name):
  position = source.index(name + '(')
  start = source.rfind('\nstatic ', 0, position) + 1
  opening = source.index('{', position)
  level, end = 1, opening + 1
  while level:
    level += (source[end] == '{') - (source[end] == '}')
    end += 1
  return source[start:end]

request = (root / 'net/bluetooth/hci_request.c').read_text()
event = (root / 'net/bluetooth/hci_event.c').read_text()
advertising = function(request, 'is_advertising_allowed')
pending = function(event, 'check_pending_le_conn')
start = pending.index('if (hdev->conn_hash.le_num_slave') + len('if (')
level, end = 1, start
while level:
  level += (pending[end] == '(') - (pending[end] == ')')
  end += 1
condition = pending[start:end-1]
prelude = r"""
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define LE_LINK 1
#define LE_ADV_IND 0x00
#define LE_ADV_SCAN_IND 0x02
#define LE_ADV_NONCONN_IND 0x03
typedef uint8_t u8;
struct hci_dev {
  struct { unsigned int le_num_slave; } conn_hash;
  unsigned int connections;
  uint8_t le_states[8];
};
static unsigned int hci_conn_num(struct hci_dev *hdev, int type)
{ (void)type; return hdev->connections; }
"""
main = r"""
int main(void)
{
  const unsigned int bits[] = {17, 18, 19, 28, 35, 41};
  const unsigned int roles[][2] = {{0,0}, {1,0}, {2,0}, {1,1}, {2,1}};
  const u8 types[] = {LE_ADV_IND, LE_ADV_SCAN_IND, LE_ADV_NONCONN_IND};
  unsigned int failed = 0, cases = 0;
  for (unsigned int mask = 0; mask < 64; ++mask) {
    uint64_t states = 0;
    for (unsigned int bit = 0; bit < 6; ++bit)
      if (mask & (1U << bit)) states |= UINT64_C(1) << bits[bit];
    for (unsigned int role = 0; role < 5; ++role) {
      struct hci_dev hdev = {.connections = roles[role][0]};
      hdev.conn_hash.le_num_slave = roles[role][1];
      for (unsigned int byte = 0; byte < 8; ++byte)
        hdev.le_states[byte] = states >> (8 * byte);
      for (unsigned int type = 0; type < 3; ++type) {
        bool expected = !hdev.connections || (!hdev.conn_hash.le_num_slave &&
          (types[type] == LE_ADV_NONCONN_IND ? !!(states & (UINT64_C(1) << 18)) :
           ((states & (UINT64_C(1) << 19)) &&
            (types[type] == LE_ADV_SCAN_IND || (states & (UINT64_C(1) << 35))))));
        failed += is_advertising_allowed(&hdev, types[type]) != expected;
        ++cases;
      }
      bool expected = !hdev.conn_hash.le_num_slave ||
                      !!(states & (UINT64_C(1) << 41));
      failed += pending_allowed(&hdev) != expected;
      ++cases;
    }
  }
  printf("%u role/capability cases; %u failed\n", cases, failed);
  return failed != 0;
}
"""
with tempfile.TemporaryDirectory(prefix='le-roles-') as directory:
  source = Path(directory) / 'roles.c'
  binary = Path(directory) / 'roles'
  source.write_text(prelude + advertising + '\nstatic bool pending_allowed(struct hci_dev *hdev) { return !(' + condition + '); }\n' + main)
  subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
  subprocess.run([str(binary)], check=True)

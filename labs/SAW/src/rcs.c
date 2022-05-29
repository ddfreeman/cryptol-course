#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>

uint32_t RCS(uint32_t bits, uint32_t shift) {
  return (bits << (sizeof(bits) * 8 - shift)) | (bits >> shift);
}

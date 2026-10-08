/** Bounded CR/LF framing. An oversized frame is discarded in full, never as a suffix. */
export function createSerialFramer(maxLength = 1024) {
  let buffer = '';
  let overflow = false;
  return {
    push(chunk: string): {codes: string[]; overflowed: boolean} {
      const codes: string[] = [];
      let overflowed = false;
      for (const character of chunk) {
        if (character === '\r' || character === '\n') {
          if (!overflow && buffer.trim()) codes.push(buffer.trim());
          buffer = ''; overflow = false;
        } else if (!overflow) {
          if (buffer.length >= maxLength) {buffer = ''; overflow = true; overflowed = true;}
          else buffer += character;
        }
      }
      return {codes, overflowed};
    },
    flush(): string | null {
      const code = overflow ? null : buffer.trim() || null;
      buffer = ''; overflow = false;
      return code;
    },
  };
}

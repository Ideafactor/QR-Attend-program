"""Optional host-only serial bridge; install pyserial separately."""

import asyncio
import logging


async def scanner_loop(attendance, port, tenant_id="default"):
    import serial

    logger = logging.getLogger(__name__)
    while True:
        try:
            with serial.Serial(port, timeout=1) as connection:
                pending = bytearray()
                while True:
                    raw = await asyncio.to_thread(connection.read_until, b"\r", 1024)
                    pending.extend(raw)
                    if len(pending) > 1024:
                        pending.clear()
                        logger.warning("Discarded oversized scanner input")
                        continue
                    if not raw.endswith(b"\r"):
                        continue
                    code = pending.decode("utf-8", errors="strict").strip()
                    pending.clear()
                    if code:
                        try:
                            await attendance.record_scan(
                                code=code, source="kiosk", tenant_id=tenant_id
                            )
                        except Exception:
                            logger.exception("Scan could not be recorded")
        except (serial.SerialException, OSError, UnicodeError):
            logger.exception("Scanner disconnected; retrying")
            await asyncio.sleep(2)

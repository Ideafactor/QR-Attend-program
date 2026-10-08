import asyncio
from types import SimpleNamespace
import pytest
from examples.scanner import scanner_loop


async def test_partial_serial_reads_are_joined_until_cr(monkeypatch):
    chunks = iter([b"att-", b"", b"employee\r"])
    recorded = []

    class SerialConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read_until(self, terminator, limit):
            assert terminator == b"\r"
            return next(chunks)

    class Attendance:
        async def record_scan(self, **kwargs):
            recorded.append(kwargs)
            raise asyncio.CancelledError()

    monkeypatch.setitem(
        __import__("sys").modules,
        "serial",
        SimpleNamespace(Serial=lambda *a, **kw: SerialConnection(), SerialException=OSError),
    )
    with pytest.raises(asyncio.CancelledError):
        await scanner_loop(Attendance(), "/test/port", tenant_id="company")
    assert recorded == [{"code": "att-employee", "source": "kiosk", "tenant_id": "company"}]

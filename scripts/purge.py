"""Schedule once a day in the host. Never infer a tenant from untrusted client input."""

import argparse
import asyncio
from examples.app import attendance, engine
from attendance_fastapi.retention import purge_expired


async def main(tenant):
    try:
        print(await purge_expired(attendance, tenant))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="default")
    asyncio.run(main(parser.parse_args().tenant))

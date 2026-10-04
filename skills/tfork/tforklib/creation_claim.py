"""Atomic creation boundary for dispatcher-owned preparation intent."""
import fcntl
import json
import os
import stat

from .errors import err_bad_arguments


def consume_creation_claim(path, owner):
    """Start creation only for the caller's current preparation intent."""
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            metadata = os.fstat(stream.fileno())
            current = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("claim was removed or replaced")
            value = json.load(stream)
            if not isinstance(value, dict) or set(value) != {"dispatch_id", "record", "creation_started"}:
                raise ValueError("invalid creation intent schema")
            if value.get("dispatch_id") != owner or value.get("record") is not None or value.get("creation_started") is not False:
                raise ValueError("claim is stale, consumed, or owned by another dispatch")
            value["creation_started"] = True
            stream.seek(0)
            json.dump(value, stream)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise err_bad_arguments(f"workspace creation claim refused: {exc}") from exc

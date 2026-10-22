"""Atomic creation boundary for dispatcher-owned preparation intent."""
import fcntl
import json
import os
import stat

from .errors import err_bad_arguments

_SCHEMA = {"dispatch_id", "record", "creation_started"}


def consume_creation_claim(path, owner):
    """Start creation only for the caller's current preparation intent.

    Returns the claim file's ``(st_dev, st_ino)`` identity so a later
    ``release_creation_claim`` can tell the same file from a replacement."""
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            metadata = os.fstat(stream.fileno())
            current = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("claim was removed or replaced")
            value = json.load(stream)
            if not isinstance(value, dict) or set(value) != _SCHEMA:
                raise ValueError("invalid creation intent schema")
            if value.get("dispatch_id") != owner or value.get("record") is not None or value.get("creation_started") is not False:
                raise ValueError("claim is stale, consumed, or owned by another dispatch")
            value["creation_started"] = True
            stream.seek(0)
            json.dump(value, stream)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            return (metadata.st_dev, metadata.st_ino)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise err_bad_arguments(f"workspace creation claim refused: {exc}") from exc


def release_creation_claim(path, owner, identity):
    """Give back a claim this call consumed, after its workspace was closed.

    Sets ``creation_started`` back to false in place, under the same lock,
    only when the file is still the one ``consume_creation_claim`` started
    (same inode as ``identity``), still has the exact schema, is still owned
    by ``owner``, and still has ``record`` null and ``creation_started`` true.
    Anything else — a replaced, removed, or rewritten claim — is left alone.

    Returns None when released, else a short reason. Never raises: a release
    problem must not mask the launch failure being reported."""
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            metadata = os.fstat(stream.fileno())
            current = os.stat(path, follow_symlinks=False)
            held = (metadata.st_dev, metadata.st_ino)
            if (not stat.S_ISREG(metadata.st_mode)
                    or held != (current.st_dev, current.st_ino)
                    or held != tuple(identity)):
                return "claim was removed or replaced"
            value = json.load(stream)
            if not isinstance(value, dict) or set(value) != _SCHEMA:
                return "invalid creation intent schema"
            if value.get("dispatch_id") != owner or value.get("record") is not None or value.get("creation_started") is not True:
                return "claim is no longer this dispatch's started creation"
            value["creation_started"] = False
            stream.seek(0)
            json.dump(value, stream)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            return None
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return str(exc) or type(exc).__name__

"""Serialized native group ownership at a caller-supplied directory."""
import contextlib
import fcntl
import json
import os
import secrets
import stat
from pathlib import Path
from uuid import UUID


@contextlib.contextmanager
def group_claim(directory, window_id, group_name, owner):
    # Walk without following symlinks, matching the previous dispatch boundary.
    path = Path(directory).absolute()
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        filename = f'{UUID(window_id)}.json'
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        except FileNotFoundError:
            owners = {}
        else:
            with os.fdopen(fd, 'r', encoding='utf-8') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('Unreadable repository group ownership')
                owners = json.load(stream)
        if not isinstance(owners, dict):
            raise ValueError('Unreadable repository group ownership')

        def claim(group_id):
            group_id = str(UUID(group_id)) if group_id is not None else None
            previous = owners.get(group_name)
            if previous is not None:
                if (not isinstance(previous, dict)
                        or set(previous) != {'repo_identity', 'group_id'}
                        or not isinstance(previous['repo_identity'], str)):
                    raise ValueError('Unreadable repository group ownership')
                prior_id = previous['group_id']
                prior_id = str(UUID(prior_id)) if prior_id is not None else None
                if (group_id is not None and prior_id in (None, group_id)
                        and previous['repo_identity'] != owner):
                    raise ValueError(f'Group {group_name!r} in this window belongs to another repository: '
                                     f'{previous["repo_identity"]}')
            binding = dict(repo_identity=owner, group_id=group_id)
            if previous != binding:
                owners[group_name] = binding
                temporary = f'.{filename}.{secrets.token_hex(8)}'
                try:
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=descriptor)
                    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                        json.dump(owners, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=descriptor)
                    except FileNotFoundError:
                        pass
        yield claim
    finally:
        os.close(descriptor)

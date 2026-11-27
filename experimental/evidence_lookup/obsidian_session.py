"""Coordinate short-lived Windows Obsidian sessions across Consumer processes."""

from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
from threading import Thread
import time
from uuid import uuid4

from . import backends as b


COLLECT_SECONDS = 1.25
PREPARE_SECONDS = 15
IDLE_SECONDS = 1
REQUEST_SECONDS = 105
POLL_SECONDS = .08
MAX_REQUESTS = 12


@contextmanager
def byte_lock(path, offset, timeout):
    import msvcrt

    with path.open('a+b') as stream:
        b.no_links(path)
        b.require(os.fstat(stream.fileno()).st_nlink == 1, 'OBSIDIAN_COORDINATION_PATH')
        deadline = time.monotonic() + timeout
        while True:
            stream.seek(offset)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(POLL_SECONDS)
        try:
            yield True
        finally:
            stream.seek(offset)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class Session:
    def __init__(self):
        # The only shared files are rendezvous metadata in the user's OS temp
        # directory. Every Vault and the app profile live in Consumer caches.
        directory = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'agent-core-obsidian-v1'
        b.no_links(directory.parent)
        directory.mkdir(exist_ok=True)
        b.no_links(directory)
        self.lock = directory / 'session.lock'
        if self.lock.exists():
            b.no_links(self.lock)
        self.state = directory / 'requests.json'

    @contextmanager
    def requests(self):
        with byte_lock(self.lock, 0, 5) as locked:
            b.require(locked, 'OBSIDIAN_COORDINATION_BUSY')
            if self.state.exists():
                original = b.safe_read(self.state)[0]
                entries = json.loads(original)
            else:
                original, entries = b'{}', {}
            now = time.monotonic()
            for key in list(entries):
                if not 0 <= now - entries[key]['created'] <= 2 * REQUEST_SECONDS:
                    del entries[key]
            yield entries
            if not entries:
                self.state.unlink(missing_ok=True)
            else:
                payload = json.dumps(entries, separators=(',', ':')).encode('utf-8')
                if payload != original:
                    temp = self.state.with_name(uuid4().hex + '.tmp')
                    try:
                        with temp.open('xb') as stream:
                            stream.write(payload)
                        temp.replace(self.state)
                    finally:
                        temp.unlink(missing_ok=True)


def existing_obsidian():
    command = Path(os.environ['SystemRoot']) / 'System32/tasklist.exe'
    listing = subprocess.run([str(command), '/FI', 'IMAGENAME eq Obsidian.exe', '/FO', 'CSV', '/NH'],
                             capture_output=True, check=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
    return any(line.lower().startswith(b'"obsidian.exe",') for line in listing.stdout.splitlines())


def server_pid():
    """Identify the process listening on this Windows user's Obsidian CLI pipe."""
    kernel = c.WinDLL('kernel32', use_last_error=True)
    username = c.create_unicode_buffer(257)
    size = w.DWORD(len(username))
    b.require(c.WinDLL('advapi32').GetUserNameW(username, c.byref(size)), 'OBSIDIAN_USER_UNKNOWN')
    open_pipe = kernel.CreateFileW
    open_pipe.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
    open_pipe.restype = w.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [w.HANDLE]
    owner = kernel.GetNamedPipeServerProcessId
    owner.argtypes = [w.HANDLE, c.POINTER(w.ULONG)]
    handle = open_pipe(r'\\.\pipe\obsidian-cli-' + username.value, 0, 0, None, 3, 0, None)
    if handle == c.c_void_p(-1).value:
        return None
    try:
        pid = w.ULONG()
        return pid.value if owner(handle, c.byref(pid)) else None
    finally:
        close(handle)


def launch(executable, runtime, vaults):
    b.require(not existing_obsidian(), 'OBSIDIAN_ALREADY_RUNNING')
    profile = runtime / 'profile'
    profile.mkdir()
    (profile / 'obsidian.json').write_text(json.dumps({
        'vaults': {key: {'path': path, 'ts': 0, 'open': True} for key, path in vaults.items()},
        'cli': True, 'updateDisabled': True,
    }), encoding='utf-8')
    env = b.isolated_env(runtime)
    env['PATH'] = str(executable.parent) + os.pathsep + env['PATH']
    return b.OwnedProcess(
        [str(executable), '--user-data-dir=' + str(profile), '--disable-background-networking',
         '--disable-component-update', '--no-first-run'], runtime, env, runtime / 'app.log',
    )


def make_vault(runtime, files):
    vault = runtime / 'vault'
    b.write_sources(vault, files)
    settings = vault / '.obsidian'
    settings.mkdir()
    for name, value in {
        'app.json': {'checkForUpdates': False}, 'community-plugins.json': [],
        'core-plugins.json': ['backlink', 'outgoing-link'],
    }.items():
        (settings / name).write_text(json.dumps(value), encoding='utf-8')
    return vault


def query(exe, runtime, vault, key, pid, note, files):
    env = b.isolated_env(runtime)
    env['PATH'] = str(exe.parent) + os.pathsep + env['PATH']
    command = [str(exe.with_suffix('.com')), 'vault=' + key]
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        owner = server_pid()
        b.require(owner in (None, pid), 'OBSIDIAN_ALREADY_RUNNING')
        if owner == pid:
            try:
                reply = b.run_bounded(command + ['vault', 'info=path'], vault, env, 5, runtime)
            except b.Rejected:
                pass
            else:
                if os.path.normcase(reply.decode('utf-8').strip()) == os.path.normcase(str(vault)):
                    break
        time.sleep(POLL_SECONDS)
    else:
        raise b.Rejected('OBSIDIAN_BINDING_TIMEOUT')
    b.require(server_pid() == pid, 'OBSIDIAN_SESSION_LOST')
    reply = b.run_bounded(command + ['backlinks', 'path=' + note], vault, env, 20, runtime).decode('utf-8')
    b.require(not any(error in reply for error in ('Error:', 'Vault not found.', 'CLI is unable')),
              'OBSIDIAN_QUERY_FAILED')
    paths = sorted({line.strip().replace(chr(92), '/') for line in reply.splitlines() if line.strip()})
    b.require(all(path in files and path != note for path in paths), 'OBSIDIAN_RESULT_OUTSIDE_SCOPE')
    return paths


class Request:
    def __init__(self, executable):
        b.require(os.name == 'nt', 'OBSIDIAN_WINDOWS_ONLY')
        self.executable = Path(executable)
        b.require(self.executable.name.casefold() == 'obsidian.exe', 'OBSIDIAN_EXECUTABLE_REQUIRED')
        b.no_links(self.executable)
        b.no_links(self.executable.with_suffix('.com'))
        self.session = Session()
        self.key = 'evidence' + uuid4().hex
        with self.session.requests() as entries:
            b.require(len(entries) < MAX_REQUESTS, 'OBSIDIAN_QUEUE_FULL')
            entries[self.key] = {'created': time.monotonic(), 'phase': 'pending',
                                 'exe': os.path.normcase(str(self.executable))}

    def close(self):
        with self.session.requests() as entries:
            entries.pop(self.key, None)

    def collect(self):
        # Wait for other registered requests in the same cold start to prepare their Vaults.
        deadline = time.monotonic() + COLLECT_SECONDS
        time.sleep(COLLECT_SECONDS)
        while True:
            with self.session.requests() as entries:
                group = {key: entry for key, entry in entries.items()
                         if entry['phase'] in ('pending', 'ready') and entry['created'] <= deadline
                         and entry['exe'] == entries[self.key]['exe']}
                waiting = any(entry['phase'] == 'pending' for entry in group.values())
                if not waiting or time.monotonic() >= deadline + PREPARE_SECONDS:
                    ready = {key: entry['vault'] for key, entry in group.items() if entry['phase'] == 'ready'}
                    for key in ready:
                        entries[key]['phase'] = 'starting'
                    return ready
            time.sleep(POLL_SECONDS)

    def serve(self, runtime):
        with byte_lock(self.session.lock, 1, 0) as leader:
            if not leader:
                return
            with self.session.requests() as entries:
                for entry in entries.values():
                    if entry['phase'] in ('starting', 'active'):
                        entry.update(phase='closed', error='OBSIDIAN_SESSION_LOST')
                if entries.get(self.key, {}).get('phase') != 'ready':
                    return
            vaults = self.collect()
            error = None
            owned = None
            try:
                for path in vaults.values():
                    vault = Path(path)
                    b.require(vault.is_absolute() and vault.name == 'vault'
                              and vault.parent.name.startswith('obsidian-'), 'OBSIDIAN_VAULT_PATH')
                    b.no_links(vault)
                owned = launch(self.executable, runtime, vaults)
                with self.session.requests() as entries:
                    for key in vaults.keys() & entries.keys():
                        entries[key].update(phase='active', pid=owned.process.pid)
                deadline = time.monotonic() + 52
                while True:
                    with self.session.requests() as entries:
                        active = any(not entries[key].get('done') for key in vaults.keys() & entries.keys())
                    if not active:
                        time.sleep(IDLE_SECONDS)
                        break
                    b.require(time.monotonic() < deadline and owned.process.poll() is None,
                              'OBSIDIAN_SESSION_LOST')
                    time.sleep(POLL_SECONDS)
            except (b.Rejected, OSError, subprocess.SubprocessError) as exc:
                error = getattr(exc, 'code', type(exc).__name__)
            finally:
                try:
                    if owned is not None:
                        owned.close()
                except (b.Rejected, OSError):
                    error = 'OBSIDIAN_CLEANUP_FAILED'
                finally:
                    with self.session.requests() as entries:
                        for key in vaults.keys() & entries.keys():
                            entries[key].update(phase='closed', error=error)

    def lookup(self, files, note, runtime):
        vault = make_vault(runtime, files)
        with self.session.requests() as entries:
            entries[self.key].update(phase='ready', vault=str(vault))
        owner = None
        next_election = 0
        deadline = time.monotonic() + REQUEST_SECONDS
        result = None
        failure = None
        while time.monotonic() < deadline:
            with self.session.requests() as entries:
                entry = entries[self.key].copy()
            phase = entry['phase']
            if phase == 'closed':
                if owner is not None:
                    owner.join()
                b.require(entry['error'] is None, entry['error'])
                if failure is not None:
                    raise failure
                return result
            if phase == 'ready' and time.monotonic() >= next_election and (owner is None or not owner.is_alive()):
                owner = Thread(target=self.serve, args=(runtime,))
                owner.start()
                next_election = time.monotonic() + .4
            elif phase == 'active' and not entry.get('done'):
                try:
                    result = query(self.executable, runtime, vault, self.key, entry['pid'], note, files)
                except (b.Rejected, OSError, subprocess.SubprocessError, UnicodeError) as exc:
                    failure = exc
                finally:
                    with self.session.requests() as entries:
                        entries[self.key]['done'] = True
            time.sleep(POLL_SECONDS)
        if owner is not None:
            owner.join()
        raise b.Rejected('OBSIDIAN_QUEUE_TIMEOUT')

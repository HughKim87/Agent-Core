"""Local evidence lookups over explicitly selected Consumer snapshots."""
from __future__ import annotations

import ast
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import time
from urllib.parse import unquote
import uuid

MAX_FILE = 1024 * 1024


class Rejected(Exception):
    def __init__(self, code):
        self.code = code


def require(condition, code):
    if not condition:
        raise Rejected(code)


def signature(s):
    # Windows path stat and fd stat can expose different ctime semantics.
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)


def path_signature(s):
    return (*signature(s), s.st_ctime_ns)


def no_links(path):
    for p in [*reversed(path.parents), path]:
        s = p.lstat()
        require(not stat.S_ISLNK(s.st_mode)
                and not (getattr(s, 'st_file_attributes', 0) & 0x400), 'LINK_REJECTED')


def final_handle_path(fd, expected):
    if os.name != 'nt':
        return
    import msvcrt
    api = c.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
    api.argtypes = [c.c_void_p, c.c_wchar_p, c.c_uint32, c.c_uint32]
    api.restype = c.c_uint32
    buf = c.create_unicode_buffer(32768)
    count = api(msvcrt.get_osfhandle(fd), buf, len(buf), 0)
    require(0 < count < len(buf), 'HANDLE_PATH_UNAVAILABLE')
    actual = buf.value
    if actual.startswith('\\\\?\\'):
        actual = actual[4:]
    require(os.path.normcase(actual) == os.path.normcase(str(expected)), 'PATH_CHANGED')


def safe_read(path):
    """Check ancestors, open readonly, validate the handle, bind bytes and metadata."""
    no_links(path)
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'NOT_SINGLE_REGULAR_FILE')
    require(before.st_size <= MAX_FILE, 'FILE_LIMIT')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        require(signature(before) == signature(opened), 'SOURCE_CHANGED')
        final_handle_path(fd, path)
        chunks = []; size = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            size += len(chunk)
            require(size <= MAX_FILE, 'FILE_LIMIT')
            chunks.append(chunk)
        after_fd = os.fstat(fd)
        require(signature(opened) == signature(after_fd)
                and opened.st_ctime_ns == after_fd.st_ctime_ns, 'SOURCE_CHANGED')
        no_links(path)
        after_path = path.stat()
        require(signature(opened) == signature(after_path)
                and before.st_ctime_ns == after_path.st_ctime_ns, 'SOURCE_CHANGED')
        data = b''.join(chunks)
        return data, path_signature(after_path)
    finally:
        os.close(fd)


class BasicLimit(c.Structure):
    _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
        ('min_ws', c.c_size_t), ('max_ws', c.c_size_t), ('active', w.DWORD),
        ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class IOCounters(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read', 'write', 'other')]


class ExtendedLimit(c.Structure):
    _fields_ = [('basic', BasicLimit), ('io', IOCounters), ('process_memory', c.c_size_t),
        ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]


class OwnedProcess:
    """A private Windows Job for lifecycle cleanup, not an OS access sandbox."""
    def __init__(self, argv, cwd, env, output):
        require(os.name == 'nt', 'PLATFORM_UNSUPPORTED')
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [w.LPVOID, w.LPCWSTR], w.HANDLE),
            ('SetInformationJobObject', [w.HANDLE, c.c_int, w.LPVOID, w.DWORD], w.BOOL),
            ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
            ('QueryInformationJobObject', [w.HANDLE, c.c_int, w.LPVOID, w.DWORD, w.LPVOID], w.BOOL),
            ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
            ('CloseHandle', [w.HANDLE], w.BOOL)):
            fn = getattr(self.kernel, name); fn.argtypes = args; fn.restype = result
        self.job = self.kernel.CreateJobObjectW(None, None)
        require(bool(self.job), 'JOB_UNAVAILABLE')
        limits = ExtendedLimit(); limits.basic.flags = 0x2000
        if not self.kernel.SetInformationJobObject(self.job, 9, c.byref(limits), c.sizeof(limits)):
            self.kernel.CloseHandle(self.job)
            raise Rejected('JOB_UNAVAILABLE')
        self.process = None
        self.cleanup = None
        self.log = output.open('wb')
        try:
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=self.log, stderr=self.log,
                                            startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW)
            require(bool(self.kernel.AssignProcessToJobObject(self.job, int(self.process._handle))), 'JOB_UNAVAILABLE')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        if self.job:
            ok = self.kernel.TerminateJobObject(self.job, 1)
            # BASIC_ACCOUNTING_INFORMATION has four int64 times followed by
            # page faults, total, active and terminated DWORD counts.
            accounting = c.create_string_buffer(48)
            deadline = time.monotonic() + 5
            active = None
            while ok and time.monotonic() < deadline:
                if not self.kernel.QueryInformationJobObject(self.job, 1, accounting, 48, None):
                    break
                active = c.c_uint32.from_buffer(accounting, 40).value
                if active == 0: break
                time.sleep(.02)
            self.kernel.CloseHandle(self.job); self.job = None
            self.cleanup = {'job_terminated': bool(ok), 'active_processes_after': active}
        if self.process is not None:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
        self.log.close()
        require(self.cleanup is not None and self.cleanup['job_terminated']
                and self.cleanup['active_processes_after'] == 0, 'CLEANUP_FAILED')


def run_bounded(argv, cwd, env, timeout, root, output_limit=4*1024*1024):
    """Bound output while the child runs; terminate on timeout or overflow."""
    prefix = root / ('cli-' + uuid.uuid4().hex)
    stdout, stderr = prefix.with_suffix('.out'), prefix.with_suffix('.err')
    with stdout.open('xb') as out, stderr.open('xb') as err:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + timeout
        try:
            while child.poll() is None:
                require(stdout.stat().st_size <= output_limit and stderr.stat().st_size <= 65536, 'OUTPUT_LIMIT')
                require(time.monotonic() < deadline, 'PRODUCT_TIMEOUT')
                time.sleep(.01)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
    require(stdout.stat().st_size <= output_limit and stderr.stat().st_size <= 65536, 'OUTPUT_LIMIT')
    require(child.returncode == 0, 'PRODUCT_FAILED')
    return stdout.read_bytes()


def isolated_env(root):
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "SystemDrive", "COMSPEC")
           if key in os.environ}
    for key in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE"):
        target = root / "state" / key
        target.mkdir(parents=True, exist_ok=True)
        no_links(target)
        env[key] = str(target)
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    return env


def matches_graph_symbol(symbol, output, files):
    header = re.match(
        r"\ANode:\s*\.?([A-Za-z_]\w*)(\(\))?\r?\n"
        r" +ID:[^\r\n]+\r?\n +Source: +([^\r\n]+) L([1-9]\d*)\r?\n"
        r" +Type: +code\r?$", output, flags=re.M,
    )
    if not header:
        return False
    name, _, source, line = header.groups()
    source = source.replace("\\", "/")
    if source not in files or name != symbol.rsplit(".", 1)[-1]:
        return False
    module = source.removesuffix(".py").replace("/", ".")
    pending = [(ast.parse(files[source]), "")]
    while pending:
        node, parents = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parents = f"{parents}.{node.name}" if parents else node.name
            start_lines = {node.lineno, *(item.lineno for item in node.decorator_list)}
            if node.name == name and int(line) in start_lines:
                qualified = f"{module}.{parents}"
                return qualified == symbol or qualified.endswith("." + symbol)
        pending.extend((child, parents) for child in ast.iter_child_nodes(node))
    return False


def obsidian(files, note, executable, runtime):
    require(os.name == 'nt', 'OBSIDIAN_WINDOWS_ONLY')
    executable = Path(executable)
    require(executable.name.casefold() == 'obsidian.exe', 'OBSIDIAN_EXECUTABLE_REQUIRED')
    cli = executable.with_suffix('.com')
    no_links(executable)
    no_links(cli)
    vault = runtime / 'vault'
    profile = runtime / 'profile'
    profile.mkdir()
    write_sources(vault, files)
    settings = vault / ".obsidian"
    settings.mkdir()
    for name, value in {
        "app.json": {"checkForUpdates": False},
        "community-plugins.json": [],
        "core-plugins.json": ["backlink", "outgoing-link"],
    }.items():
        (settings / name).write_text(json.dumps(value), encoding="utf-8")
    vault_id = "evidence" + uuid.uuid4().hex
    (profile / "obsidian.json").write_text(json.dumps({
        "vaults": {vault_id: {"path": str(vault), "ts": 0, "open": True}},
        "cli": True, "updateDisabled": True,
    }), encoding="utf-8")
    env = isolated_env(runtime)
    env["PATH"] = str(executable.parent) + os.pathsep + env["PATH"]
    owned = OwnedProcess(
        [str(executable), "--user-data-dir=" + str(profile), "--disable-background-networking",
         "--disable-component-update", "--no-first-run"], vault, env, runtime / "app.log",
    )
    command = [str(cli), "vault=" + vault_id]
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            require(owned.process.poll() is None, "OBSIDIAN_START_FAILED")
            try:
                output = run_bounded(command + ["vault", "info=path"], vault, env, 5, runtime)
            except Rejected:
                continue
            if os.path.normcase(output.decode("utf-8").strip()) == os.path.normcase(str(vault)):
                break
            time.sleep(0.2)
        else:
            raise Rejected("OBSIDIAN_BINDING_TIMEOUT")
        output = run_bounded(command + ["backlinks", "path=" + note], vault, env, 20, runtime)
        result = output.decode("utf-8")
        require(not any(error in result for error in ("Error:", "Vault not found.", "CLI is unable")),
                "OBSIDIAN_QUERY_FAILED")
        paths = sorted({line.strip().replace(chr(92), '/') for line in result.splitlines() if line.strip()})
        require(all(path in files and path != note for path in paths), 'OBSIDIAN_RESULT_OUTSIDE_SCOPE')
        return paths
    finally:
        owned.close()


def write_sources(destination, files):
    for name, data in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def markdown_backlinks(files, target):
    matches = []
    for source, data in files.items():
        if source == target:
            continue
        text = re.sub(r'```.*?```|`[^`]*`', '', data.decode('utf-8-sig'), flags=re.S)
        for link in re.findall(r'(?<!!)\[[^\]\n]*\]\(([^\s)]+)\)', text):
            link = unquote(link.split('#', 1)[0]).strip('<>')
            if not link or ':' in link or '\\' in link or link.startswith('/'):
                continue
            resolved = os.path.normpath(str(PurePosixPath(source).parent / link)).replace('\\', '/')
            if resolved == target:
                matches.append(source)
                break
    return sorted(matches)


def graphify(files, symbol, executable, runtime, cache):
    executable = Path(executable)
    no_links(executable)
    env = isolated_env(runtime)
    env.update(GRAPHIFY_BACKEND='none', GRAPHIFY_QUERY_LOG_DISABLE='1',
               PYTHONIOENCODING='utf-8')
    version = run_bounded([str(executable), '-B', '-I', '-c',
                           'from importlib.metadata import version; print(version("graphifyy"))'],
                          runtime, env, 30, runtime).decode('utf-8').strip()
    require(version == '0.9.120', 'GRAPHIFY_VERSION_UNTESTED')
    key = hashlib.sha256(f'{executable}\0{version}'.encode())
    for name, data in files.items():
        key.update(name.encode() + b'\0' + hashlib.sha256(data).digest())
    graph = cache / f'graph-v1-{key.hexdigest()}.json'
    command = [str(executable), '-X', 'utf8', '-B', '-I', '-m', 'graphify']
    mode = 'reused_index' if graph.exists() else 'new_index'
    if mode == 'new_index':
        source, output = runtime / 'source', runtime / 'index'
        write_sources(source, files)
        run_bounded(command + ['extract', str(source), '--code-only', '--no-cluster',
                               '--max-workers', '1', '--out', str(output)], runtime, env, 150, runtime)
        generated = output / 'graphify-out/graph.json'
        no_links(generated)
        generated.replace(graph)
    no_links(graph)
    require(graph.stat().st_nlink == 1, 'LINK_REJECTED')
    result = run_bounded(command + ['explain', symbol, '--graph', str(graph)],
                         runtime, env, 30, runtime).decode('utf-8')
    require(matches_graph_symbol(symbol, result, files), 'GRAPH_SYMBOL_MISMATCH')
    return result, mode


def python_definitions(files, symbol):
    found = []
    for name, data in files.items():
        try:
            tree = ast.parse(data)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == symbol.rsplit('.', 1)[-1]:
                    found.append({'path': name, 'line': node.lineno, 'symbol': node.name})
    return sorted(found, key=lambda hit: (hit['path'], hit['line']))


def python_call_sites(files, symbol):
    """Find syntactic call candidates. A matching name does not prove resolution."""
    name = symbol.rsplit(".", 1)[-1]
    matches = []
    incomplete = False
    for path, data in sorted(files.items()):
        try:
            tree = ast.parse(data)
        except SyntaxError:
            incomplete = True
            continue
        lines = set()
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            fn = call.func
            if (isinstance(fn, ast.Name) and fn.id == name) or (
                isinstance(fn, ast.Attribute) and fn.attr == name
            ):
                lines.add(call.lineno)
        matches.extend({"path": path, "line": line} for line in sorted(lines))
        if len(matches) > 100:
            return matches[:100], True
    return matches, incomplete

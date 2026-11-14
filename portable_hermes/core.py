"""Install, update, check and adopt the upstream Hermes core (stdlib only).

The core is NousResearch/hermes-agent, fetched as a GitHub source archive:
latest ``main`` by default, an explicit ref or commit, or a local ZIP. Every
installed file is recorded in ``.portable/core-state.json`` with its hash, so
a later update removes only files it installed and that are still unchanged.

Flow (all-or-nothing):

1. stage the archive under ``.portable/s`` (safe extraction; refused up front
   with a precise reason if the folder path is too long for this PC);
2. check that ``requires-python`` and the dependency set apply to this
   interpreter. A core that needs a newer Python than this folder's portable
   runtime is reported as ``runtime_too_old`` (exit code 4); UPDATE.bat and
   install.bat then move the runtime to the pinned version in place
   (``portable_hermes/launch/runtime.cmd``) and run the install again;
3. install dependencies from the core's ``uv.lock`` (exact, hash-checked, no
   resolver). Without a usable lock a first install refuses (and falls back
   to the last-known-good core); an update of an existing core uses the
   ranges in ``pyproject.toml`` without hashes and says so. A marker file
   (``.portable/deps-pending.json``) records the package set from before the
   change until the new core commits or the old set is fully restored;
4. verify the staged tree in a fresh process with this interpreter;
5. swap files and the state file under a journal (old content kept by hard
   link, so a file is never missing; a standalone recovery script settles a
   kill at any point);
6. verify the live tree again; only then commit. Files whose content was not
   what we recorded installing (user edits, unknown files) are kept in a
   dated ``.portable/kept/`` folder, never deleted.

Any failure rolls the files and the dependency changes back, and says so when
packages could not all be put back. A fresh install whose newest upstream
fails falls back to the wrapper's last-known-good commit.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from portable_hermes import common, ownership
from portable_hermes.common import UpdateError, log

UPSTREAM_REPO = "NousResearch/hermes-agent"
STATE_FILE = "core-state.json"
DATA_DIR = Path(__file__).resolve().parent / "manifests"

#: Optional dependency groups the portable product installs when the core
#: defines them (missing names are skipped and reported).
WRAPPER_EXTRAS = (
    "messaging", "cron", "cli", "mcp", "honcho", "pty", "tts-premium",
    "homeassistant", "anthropic",
)
#: Packages the portable tools and GUI need on top of the core.
WRAPPER_REQUIREMENTS = ("ddgs", "lmstudio", "Pillow")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_KEPT = 3      # the update failed, the existing core was kept unchanged
EXIT_RUNTIME = 4   # the core needs a newer portable Python (see runtime.cmd)

#: Written before packages change, removed once the new core commits or the
#: previous package set is fully back. Launchers warn while it exists.
DEPS_MARKER = "deps-pending.json"
#: Lives in the runtime's own site-packages: which dependency set that
#: runtime has. A rebuilt or replaced runtime has none, so nothing is skipped.
DEPS_STAMP = "portable_hermes_deps.json"
RUNTIME_PIN = "python-runtime.txt"


# --------------------------------------------------------------------------
# PEP 508 markers and PEP 440 specifiers (the subset dependency files use)
# --------------------------------------------------------------------------

def marker_environment() -> dict:
    impl = sys.implementation
    iv = impl.version
    impl_version = f"{iv.major}.{iv.minor}.{iv.micro}"
    if iv.releaselevel != "final":
        impl_version += iv.releaselevel[0] + str(iv.serial)
    return {
        "implementation_name": impl.name,
        "implementation_version": impl_version,
        "os_name": os.name,
        "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
        "platform_version": platform.version(),
        "python_full_version": platform.python_version(),
        "python_version": "%d.%d" % sys.version_info[:2],
        "sys_platform": sys.platform,
        "extra": "",
    }


_VERSION_VARS = {"python_version", "python_full_version", "implementation_version"}
_TOKEN_RE = re.compile(
    r"\s*(?:(?P<str>'[^']*'|\"[^\"]*\")|(?P<op>===|==|!=|<=|>=|~=|<|>)|"
    r"(?P<paren>[()])|(?P<word>[A-Za-z_][A-Za-z0-9_.]*))"
)


def _version_tuple(text: str) -> tuple[int, ...]:
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text)
    if not match:
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(p) for p in match.group(1).split("."))


def version_compare(left: str, op: str, right: str) -> bool:
    """Compare *left* with the specifier ``op right`` (PEP 440 subset)."""
    right = right.strip()
    if op in ("==", "!=") and right.endswith(".*"):
        prefix = _version_tuple(right[:-2])
        value = _version_tuple(left)[:len(prefix)]
        value += (0,) * (len(prefix) - len(value))
        return (value == prefix) == (op == "==")
    if op == "===":
        return left.strip() == right
    a, b = _version_tuple(left), _version_tuple(right)
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    if op == "~=":
        upper = _version_tuple(right)[:-1]
        return a >= b and _version_tuple(left)[:len(upper)] == upper
    return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b,
            ">": a > b, ">=": a >= b}[op]


def specifier_matches(spec: str, version: str) -> bool:
    """True if *version* satisfies a comma-separated specifier set."""
    for clause in (c.strip() for c in (spec or "").split(",")):
        if not clause:
            continue
        match = re.match(r"(===|==|!=|<=|>=|~=|<|>)\s*(.+)", clause)
        if not match or not version_compare(version, match.group(1), match.group(2)):
            return False
    return True


def evaluate_marker(marker: str, env: dict | None = None) -> bool:
    """Evaluate a PEP 508 environment marker."""
    env = env or marker_environment()
    tokens = []
    pos = 0
    text = marker.strip()
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if not match or match.end() == pos:
            raise ValueError(f"cannot parse marker {marker!r} at {pos}")
        pos = match.end()
        kind = match.lastgroup
        tokens.append((kind, match.group(kind)))
        while pos < len(text) and text[pos].isspace():
            pos += 1
    index = 0

    def peek():
        return tokens[index] if index < len(tokens) else (None, None)

    def take():
        nonlocal index
        token = peek()
        index += 1
        return token

    def value():
        kind, tok = take()
        if kind == "str":
            return tok[1:-1], None
        if kind == "word":
            if tok not in env:
                raise ValueError(f"unknown marker variable {tok!r}")
            return str(env[tok]), tok
        raise ValueError(f"unexpected token {tok!r} in marker {marker!r}")

    def comparison():
        kind, tok = peek()
        if kind == "paren" and tok == "(":
            take()
            result = disjunction()
            if take() != ("paren", ")"):
                raise ValueError(f"unbalanced parenthesis in marker {marker!r}")
            return result
        left, left_var = value()
        kind, tok = take()
        if kind == "word" and tok == "not":
            if take() != ("word", "in"):
                raise ValueError(f"expected 'in' after 'not' in {marker!r}")
            op = "not in"
        elif kind == "word" and tok == "in":
            op = "in"
        elif kind == "op":
            op = tok
        else:
            raise ValueError(f"expected an operator in marker {marker!r}")
        right, right_var = value()
        if op in ("in", "not in"):
            return (left in right) == (op == "in")
        if "extra" in (left_var, right_var):
            norm = lambda s: re.sub(r"[-_.]+", "-", s).lower()  # noqa: E731
            left, right = norm(left), norm(right)
        if left_var in _VERSION_VARS or right_var in _VERSION_VARS:
            try:
                if left_var in _VERSION_VARS:
                    return version_compare(left, op, right)
                # 'X' op var: flip to var op' X
                flipped = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}.get(op, op)
                return version_compare(right, flipped, left)
            except ValueError:
                pass
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        return {"<": left < right, "<=": left <= right,
                ">": left > right, ">=": left >= right}.get(op, False)

    def conjunction():
        result = comparison()
        while peek() == ("word", "and"):
            take()
            rhs = comparison()
            result = result and rhs
        return result

    def disjunction():
        result = conjunction()
        while peek() == ("word", "or"):
            take()
            rhs = conjunction()
            result = result or rhs
        return result

    result = disjunction()
    if index != len(tokens):
        raise ValueError(f"trailing tokens in marker {marker!r}")
    return result


_REQ_RE = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_applies(requirement: str, env: dict) -> bool:
    if ";" not in requirement:
        return True
    return evaluate_marker(requirement.split(";", 1)[1], env)


# --------------------------------------------------------------------------
# dependency plans
# --------------------------------------------------------------------------

def read_project(pyproject: Path) -> dict:
    import tomllib
    with open(pyproject, "rb") as fh:
        return tomllib.load(fh).get("project", {})


def _lock_requirements(lock: dict, extras: list[str], env: dict) -> list[str]:
    """Walk a uv.lock from the root package; return hash-pinned requirement lines."""
    packages = lock.get("package", [])
    by_name: dict[str, list[dict]] = {}
    for pkg in packages:
        by_name.setdefault(canonical(pkg["name"]), []).append(pkg)
    roots = [p for p in packages if isinstance(p.get("source"), dict)
             and (p["source"].get("editable") == "." or p["source"].get("virtual") == ".")]
    if len(roots) != 1:
        raise UpdateError("uv.lock has no single root package", code="lock_unusable")
    root = roots[0]
    root_name = canonical(root["name"])

    def pick(dep: dict) -> dict:
        candidates = by_name.get(canonical(dep["name"]), [])
        if "version" in dep:
            candidates = [c for c in candidates if c.get("version") == dep["version"]]
        if len(candidates) > 1:
            def fits(c):
                markers = c.get("resolution-markers")
                return not markers or any(evaluate_marker(m, env) for m in markers)
            candidates = [c for c in candidates if fits(c)]
        if len(candidates) != 1:
            raise UpdateError(f"uv.lock: cannot choose a version of {dep['name']}",
                              code="lock_unusable")
        return candidates[0]

    selected: dict[tuple[str, str], dict] = {}
    seen: set[tuple[str, str, str]] = set()
    queue: list[tuple[dict, list[str]]] = [(root, list(extras))]
    while queue:
        pkg, pkg_extras = queue.pop()
        deps = list(pkg.get("dependencies", []))
        optional = pkg.get("optional-dependencies", {})
        for extra in pkg_extras:
            deps.extend(optional.get(extra, []))
        for dep in deps:
            marker = dep.get("marker")
            if marker and not evaluate_marker(marker, env):
                continue
            dep_extras = list(dep.get("extra", []))
            if canonical(dep["name"]) == root_name:
                target = root
            else:
                target = pick(dep)
                selected[(canonical(target["name"]), target["version"])] = target
            for extra in dep_extras or [""]:
                key = (canonical(target["name"]), target.get("version", ""), extra)
                if key in seen:
                    continue
                seen.add(key)
                queue.append((target, [extra] if extra else []))
    lines = []
    for (name, version), pkg in sorted(selected.items()):
        source = pkg.get("source", {})
        if "registry" not in source:
            raise UpdateError(f"uv.lock: {name} {version} comes from {source}, which the "
                              "portable installer cannot hash-check", code="lock_unusable")
        hashes = [w["hash"] for w in pkg.get("wheels", []) if w.get("hash")]
        if pkg.get("sdist", {}).get("hash"):
            hashes.append(pkg["sdist"]["hash"])
        if not hashes:
            raise UpdateError(f"uv.lock: no hashes recorded for {name} {version}",
                              code="lock_unusable")
        lines.append(f"{name}=={version} " + " ".join(f"--hash={h}" for h in hashes))
    return lines


def _pyproject_requirements(project: dict, extras: list[str], env: dict) -> list[str]:
    optional = project.get("optional-dependencies", {})
    own = canonical(project.get("name", "hermes-agent"))
    out, seen = [], set()

    def add(reqs):
        for req in reqs:
            match = _REQ_RE.match(req)
            if match and canonical(match.group(1)) == own:
                for extra in (match.group(2) or "").split(","):
                    extra = extra.strip()
                    if extra and extra not in seen:
                        seen.add(extra)
                        add(optional.get(extra, []))
            elif requirement_applies(req, env):
                out.append(req.split(";", 1)[0].strip() + (
                    f"; {req.split(';', 1)[1].strip()}" if ";" in req else ""))

    add(project.get("dependencies", []))
    for extra in extras:
        if extra not in seen:
            seen.add(extra)
            add(optional.get(extra, []))
    return out


def target_python() -> str | None:
    """The portable Python version this wrapper release installs (one pin,
    shipped and updated by the wrapper channel, read by install.bat too)."""
    try:
        text = (DATA_DIR / RUNTIME_PIN).read_text(encoding="ascii").strip()
    except OSError:
        return None
    return text if re.fullmatch(r"\d+\.\d+\.\d+", text) else None


def _env_for(env: dict, version: str) -> dict:
    return dict(env, python_full_version=version,
                python_version=".".join(version.split(".")[:2]),
                implementation_version=version)


def _python_fit(project: dict, env: dict) -> tuple[bool, str]:
    """(fits, why not) for the core's requires-python and base dependency gates."""
    python = env["python_full_version"]
    spec = project.get("requires-python", "")
    if spec and not specifier_matches(spec, python):
        return False, f"requires Python {spec}"
    base = project.get("dependencies", [])
    if base and not any(requirement_applies(r, env) for r in base):
        gates = sorted({r.split(";", 1)[1].strip() for r in base if ";" in r}, key=len)[:1]
        return False, (f"none of its {len(base)} runtime dependencies apply to Python "
                       f"{python} (they are gated on: {'; '.join(gates)})")
    return True, ""


def runtime_too_old_sentence(current: str | None, target: str | None,
                             requires: str | None = None) -> str:
    """The one sentence for ``runtime_too_old``: the Python the pin provides
    (``requires-python`` alone can be satisfied by the current Python when
    the core's dependencies are gated on a newer one)."""
    if target and re.fullmatch(r"\d+\.\d+(\.\d+)?", str(target)):
        needed = ".".join(str(target).split(".")[:2])
    else:
        needed = f"a newer version ({requires})" if requires else "a newer version"
    return (f"The newest Hermes core needs Python {needed}; this folder's portable Python "
            f"is {current or 'older'}.")


def check_python(project: dict, env: dict) -> None:
    """Raise ``runtime_too_old`` or ``python_incompatible`` when the core
    cannot run on this interpreter."""
    python = env["python_full_version"]
    fits, why = _python_fit(project, env)
    if fits:
        return
    spec = project.get("requires-python", "") or "a different Python"
    target = target_python()
    details = {"current_python": python, "target_python": target, "requires_python": spec}
    newer = False
    if target:
        try:
            newer = _version_tuple(target) > _version_tuple(python)
        except ValueError:
            newer = False
    if target and newer and _python_fit(project, _env_for(env, target))[0]:
        raise UpdateError(
            f"this Hermes core {why}; the portable Python in this folder is {python}. "
            f"UPDATE.bat (or install.bat) moves the portable Python to {target} in place, "
            "keeping everything in this folder, and then installs the core.",
            code="runtime_too_old", details=details)
    raise UpdateError(
        f"this Hermes core {why}; the portable Python here is {python}"
        + (f" and this Portable Hermes release can move it to {target}, which is not enough"
           if target and newer else "")
        + ". Update the portable wrapper first (UPDATE.bat); a newer release moves to the "
          "Python this core needs.", code="python_incompatible", details=details)


def dependency_plan(tree: Path, env: dict | None = None, *, allow_unpinned: bool = True) -> dict:
    """Decide how to install the dependencies of the core in *tree*.

    Without a usable ``uv.lock`` the plan falls back to the version ranges in
    ``pyproject.toml`` (no hashes) only when *allow_unpinned*; otherwise it
    raises ``lock_unusable`` (a first install then tries the last-known-good
    core instead).
    """
    env = env or marker_environment()
    tree = Path(tree)
    pyproject = tree / "pyproject.toml"
    if not pyproject.is_file():
        raise UpdateError("the core has no pyproject.toml", code="not_a_core")
    project = read_project(pyproject)
    python = env["python_full_version"]
    check_python(project, env)
    optional = project.get("optional-dependencies", {})
    extras = [e for e in WRAPPER_EXTRAS if e in optional]
    missing_extras = [e for e in WRAPPER_EXTRAS if e not in optional]
    plan = {"extras": extras, "missing_extras": missing_extras,
            "wrapper_requirements": list(WRAPPER_REQUIREMENTS)}
    lock_path = tree / "uv.lock"
    lock_note = "no uv.lock"
    if lock_path.is_file():
        import tomllib
        try:
            lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
            supported = lock.get("supported-markers")
            lock_spec = lock.get("requires-python", "")
            if supported and not any(evaluate_marker(m, env) for m in supported):
                lock_note = f"uv.lock does not cover Python {python} ({', '.join(supported)})"
            elif lock_spec and not specifier_matches(lock_spec, python):
                lock_note = f"uv.lock requires Python {lock_spec}"
            else:
                plan.update(strategy="uv.lock", requirements=_lock_requirements(lock, extras, env))
                return plan
        except UpdateError as exc:
            lock_note = exc.reason
        except (ValueError, KeyError, TypeError) as exc:
            lock_note = f"uv.lock unreadable: {exc}"
    if not allow_unpinned:
        raise UpdateError(f"the core's dependency lock cannot be used here ({lock_note}); a "
                          "first install only uses exact, hash-checked dependencies",
                          code="lock_unusable")
    plan.update(strategy="pyproject", lock_note=lock_note + "; installed from the version "
                "ranges in pyproject.toml, without hashes",
                requirements=_pyproject_requirements(project, extras, env))
    return plan


def plan_fingerprint(plan: dict) -> str:
    text = json.dumps([plan.get("strategy"), plan.get("requirements"),
                       plan.get("wrapper_requirements")], sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# the lifecycle
# --------------------------------------------------------------------------

def _clean_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


class CoreLifecycle:
    """Core install/update/check for one install root.

    ``python`` is the product interpreter. ``run_pip`` and ``run_verify`` can
    be replaced (tests use synthetic archives and fake interpreters).
    """

    def __init__(self, root: Path, *, python: str | None = None, quiet: bool = False,
                 run_pip=None, run_verify=None, repo: str = UPSTREAM_REPO):
        self.root = Path(root).resolve()
        self.python = python or sys.executable
        self.quiet = quiet
        self.repo = repo
        self._run_pip = run_pip or self._default_pip
        self._run_verify = run_verify or self._default_verify

    # ----- helpers --------------------------------------------------------
    @property
    def state_path(self) -> Path:
        return common.state_dir(self.root) / STATE_FILE

    def read_state(self) -> dict | None:
        return common.read_json(self.state_path)

    def say(self, message: str) -> None:
        log(message, quiet=self.quiet)

    def _default_pip(self, args: list[str], timeout: float = 3600) -> tuple[int, str]:
        cmd = [self.python, "-m", "pip", *args]
        common.flush_output()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, cwd=str(self.root),
                                  env=common.clean_python_env())
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, f"could not run pip: {exc}"
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def _verify_env(self) -> dict:
        home = tempfile.mkdtemp(prefix="portable-verify-home-")
        extra = {"HERMES_HOME": home, "PORTABLE_HERMES_NO_HOOK": "1"}
        tcl = self.root / "python_embedded" / "tcl"
        if tcl.is_dir():
            for name, prefix in (("TCL_LIBRARY", "tcl8"), ("TK_LIBRARY", "tk8")):
                found = sorted(p for p in tcl.iterdir() if p.name.startswith(prefix))
                if found:
                    extra[name] = str(found[-1])
        return common.clean_python_env(extra)

    def _default_verify(self, tree: Path, gui: bool = True) -> dict:
        env = self._verify_env()
        cmd = [self.python, "-X", "utf8", "-c", common.VERIFY_BOOT, str(tree),
               "--root", str(tree), "--json"] + ([] if gui else ["--no-gui"])
        common.flush_output()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=900, cwd=str(tree), env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "reason": f"verification process failed to run: {exc}"}
        finally:
            shutil.rmtree(env["HERMES_HOME"], ignore_errors=True)
        for line in reversed((proc.stdout or "").splitlines()):
            if line.startswith("PORTABLE_VERIFY_RESULT "):
                try:
                    return json.loads(line.split(" ", 1)[1])
                except ValueError:
                    break
        tail = ((proc.stderr or "") + (proc.stdout or ""))[-1500:]
        return {"ok": False, "reason": f"verification process exited {proc.returncode} "
                                       f"without a result: {tail.strip()}"}

    def is_git_checkout(self) -> bool:
        return (self.root / ".git").exists()

    def existing_core(self) -> str:
        if self.read_state():
            return "recorded"
        if (self.root / "run_agent.py").is_file():
            return "legacy"
        return "none"

    def last_known_good(self) -> dict | None:
        data = common.read_json(DATA_DIR / "last-known-good.json") or {}
        python = marker_environment()["python_full_version"]
        for cand in data.get("candidates", []):
            if specifier_matches(cand.get("python", ""), python):
                return dict(cand, repository=data.get("repository", UPSTREAM_REPO))
        return None

    def legacy_files(self) -> dict:
        path = DATA_DIR / "legacy-core-files.txt"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        return {ownership.normalize(l): None for l in lines
                if l.strip() and not l.startswith("#")}

    # ----- source ---------------------------------------------------------
    def _fetch(self, staging: Path, *, ref: str | None, zip_path: str | None,
               commit: str | None, repo: str) -> dict:
        if zip_path:
            archive = Path(zip_path).resolve()
            if not archive.is_file():
                raise UpdateError(f"core archive not found: {archive}", code="no_archive")
            sha = commit or common.archive_commit(archive)
            return {"archive": archive, "commit": sha, "ref": ref or "local-zip",
                    "source": f"local ZIP {archive.name}"}
        ref = ref or "main"
        url = f"https://github.com/{repo}/archive/{ref}.zip"
        self.say(f"Downloading {repo} {ref} ...")
        archive = common.download(url, staging / "core.zip", quiet=self.quiet)
        sha = common.archive_commit(archive)
        if not sha and re.fullmatch(r"[0-9a-f]{40}", ref):
            sha = ref
        if not sha:
            try:
                sha = common.github_commit_sha(repo, ref)
            except UpdateError as exc:
                self.say(f"  commit not recorded: {exc.reason}")
        return {"archive": archive, "commit": sha, "ref": ref, "source": url}

    # ----- dependencies ----------------------------------------------------
    @property
    def deps_marker_path(self) -> Path:
        return common.state_dir(self.root) / DEPS_MARKER

    def pending_dependencies(self) -> dict | None:
        """The marker of a package change that has not finished, if any."""
        return common.read_json(self.deps_marker_path)

    def _stamp_path(self) -> Path | None:
        from portable_hermes import bridge
        site = bridge.site_packages(self.root / "python_embedded")
        return site / DEPS_STAMP if site else None

    def _runtime_has(self, fingerprint: str | None) -> bool:
        """True when this runtime has the dependency set *fingerprint*.

        The stamp lives inside the runtime, so a rebuilt or upgraded
        ``python_embedded`` never takes a "nothing to install" shortcut. A
        tree without ``python_embedded`` (developer setups) relies on the
        recorded state alone.
        """
        if not fingerprint:
            return False
        path = self._stamp_path()
        if path is None:
            return True
        stamp = common.read_json(path) or {}
        return stamp.get("fingerprint") == fingerprint and \
            stamp.get("python") == common.python_tag()

    def _write_stamp(self, fingerprint: str | None, commit: str | None) -> None:
        path = self._stamp_path()
        if path is None or not fingerprint:
            return
        common.write_json_atomic(path, {"fingerprint": fingerprint, "commit": commit,
                                        "python": common.python_tag(),
                                        "written": common.now_iso()})

    def _pip_list(self) -> dict[str, str]:
        rc, out = self._run_pip(["list", "--format=json", "--disable-pip-version-check"])
        if rc != 0:
            raise UpdateError(f"pip list failed: {out.strip()[-500:]}", code="pip")
        try:
            start = out.index("[")
            items = json.loads(out[start:out.rindex("]") + 1])
        except ValueError as exc:
            raise UpdateError("pip list returned unreadable output", code="pip") from exc
        return {canonical(i["name"]): i["version"] for i in items}

    def _install_dependencies(self, plan: dict, workdir: Path, fingerprint: str,
                              ctx: dict) -> dict:
        marker = self.pending_dependencies() or {}
        before = marker.get("before")
        if not (isinstance(before, dict) and marker.get("python") == common.python_tag()):
            before = self._pip_list()
        # An earlier interrupted change keeps its original "before" set, so a
        # restore puts back what the user really had.
        common.write_json_atomic(self.deps_marker_path, {
            "schema": 1, "started": common.now_iso(), "python": common.python_tag(),
            "target": fingerprint, "strategy": plan["strategy"], "before": before,
        })
        report = {"strategy": plan["strategy"], "before": before,
                  "requirements": len(plan["requirements"]),
                  "extras": plan["extras"], "missing_extras": plan["missing_extras"]}
        ctx["deps"] = report
        req_file = workdir / "core-requirements.txt"
        req_file.write_text("\n".join(plan["requirements"]) + "\n", encoding="utf-8")
        args = ["install", "--no-input", "--disable-pip-version-check", "-r", str(req_file)]
        if plan["strategy"] == "uv.lock":
            args[1:1] = ["--no-deps", "--require-hashes"]
        self.say(f"Installing core dependencies ({plan['strategy']}, "
                 f"{len(plan['requirements'])} requirements) ...")
        rc, out = self._run_pip(args)
        if rc != 0:
            report["error"] = out.strip()[-2000:]
            raise UpdateError("installing the core's dependencies failed: "
                              + _last_error_line(out), code="dependencies_failed")
        if not plan["wrapper_requirements"]:
            return report
        wrapper_args = ["install", "--no-input", "--disable-pip-version-check"]
        if plan["strategy"] == "uv.lock":
            pins = workdir / "core-constraints.txt"
            pins.write_text("\n".join(line.split(" ", 1)[0] for line in plan["requirements"])
                            + "\n", encoding="utf-8")
            wrapper_args += ["-c", str(pins)]
        rc, out = self._run_pip(wrapper_args + list(plan["wrapper_requirements"]))
        if rc != 0:
            report["wrapper_warning"] = ("portable tool packages could not be installed: "
                                         + _last_error_line(out))
            self.say("  warning: " + report["wrapper_warning"])
        return report

    def _restore_dependencies(self, report: dict) -> bool:
        """Put the package set back to what ``pip list`` showed before.

        Returns True only when a fresh ``pip list`` matches the old set
        exactly; then the marker is removed. Otherwise the marker stays (the
        launchers warn, the next update reinstalls) and the report says what
        is still different.
        """
        before = report.get("before") or {}
        notes = []
        try:
            after = self._pip_list()
        except UpdateError as exc:
            report.update(restore=f"not restored: {exc.reason}", restored=False)
            return False
        changed = sorted(f"{name}=={ver}" for name, ver in before.items()
                         if after.get(name) != ver)
        added = sorted(name for name in after if name not in before)
        if changed:
            rc, out = self._run_pip(["install", "--no-input", "--no-deps",
                                     "--disable-pip-version-check", *changed])
            notes.append(f"reinstalled {len(changed)} previous versions" if rc == 0 else
                         f"could not reinstall previous versions: {_last_error_line(out)}")
        if added:
            rc, out = self._run_pip(["uninstall", "-y", *added])
            notes.append(f"removed {len(added)} new packages" if rc == 0 else
                         f"could not remove new packages: {_last_error_line(out)}")
        try:
            final = self._pip_list()
        except UpdateError as exc:
            notes.append(f"could not check the result: {exc.reason}")
            final = None
        report["restore"] = "; ".join(notes) or "nothing to restore"
        if final is None:
            report["restored"] = False
            return False
        still = [f"{name} {final.get(name, 'missing')} (was {ver})"
                 for name, ver in sorted(before.items()) if final.get(name) != ver]
        still += [f"{name} {final[name]} (new)" for name in sorted(final) if name not in before]
        report["restored"] = not still
        if still:
            report["not_restored"] = still[:20]
            report["not_restored_count"] = len(still)
            return False
        with contextlib.suppress(OSError):
            self.deps_marker_path.unlink()
        return True

    # ----- one attempt ------------------------------------------------------
    def _attempt(self, **kwargs) -> dict:
        """One install attempt. Any failure, expected or not, is converted to
        an ``UpdateError`` after undoing the file swap and the package changes."""
        staging = common.staging_dir(self.root)
        _clean_dir(staging)
        staging.mkdir(parents=True)
        ctx: dict = {"deps": None, "txn": None}
        try:
            return self._attempt_in(staging, ctx, **kwargs)
        except Exception as exc:  # noqa: BLE001 - the result promise: never raise
            error = exc if isinstance(exc, UpdateError) else UpdateError(
                f"unexpected {type(exc).__name__} during the core update: {exc}",
                code="internal")
            self._undo(ctx, error)
            if error is exc:
                raise
            raise error from exc
        finally:
            _clean_dir(staging)

    def _undo(self, ctx: dict, error: UpdateError) -> None:
        txn = ctx.get("txn")
        if txn is not None and txn.applied and not txn.committed:
            try:
                txn.rollback()
            except (OSError, UpdateError) as undo:
                error.details["files_restored"] = False
                error.reason += (f"; undoing the file swap failed ({undo}). Close every Hermes "
                                 "window and start Hermes again: the launcher finishes the undo")
        deps = ctx.get("deps")
        if deps is not None and not (txn is not None and txn.committed):
            restored = self._restore_dependencies(deps)
            error.details["dependencies_restored"] = restored
            error.details["dependencies"] = {k: v for k, v in deps.items() if k != "before"}
            if not restored:
                missing = "; ".join(deps.get("not_restored", [])[:5])
                error.reason += (
                    "; the previous core's files are unchanged, but its Python packages could "
                    f"not all be put back ({deps.get('restore')}"
                    + (f"; still different: {missing}" if missing else "")
                    + "). Run UPDATE.bat again to finish")

    def _attempt_in(self, staging: Path, ctx: dict, *, ref, zip_path, commit, repo,
                    skip_deps, force, allow_unpinned) -> dict:
        state = self.read_state()
        pending = self.pending_dependencies()
        runtime_ok = self._runtime_has((state or {}).get("dependencies_fingerprint"))
        shortcuts = bool(state) and not force and not pending and runtime_ok
        fetched = self._fetch(staging, ref=ref, zip_path=zip_path, commit=commit, repo=repo)
        sha = fetched["commit"]
        if shortcuts and sha and state.get("commit") == sha:
            return {"ok": True, "changed": False, "commit": sha, "repository": repo,
                    "message": f"core already at {sha[:12]}"}
        self.say("Unpacking ...")
        names = common.archive_names(fetched["archive"])
        top_name = common.single_top_dir(names)
        rels = [n.split("/", 1)[1] if top_name else n for n in names]
        # Staged files sit at <root>/.portable/s/c/<rel>, backups at
        # .portable/b/<id>/<rel>, kept user edits at .portable/kept/<date>/<rel>.
        common.check_path_lengths(self.root, [r for r in rels if ownership.is_core_installable(r)],
                                  overhead=common.STATE_PATH_OVERHEAD, what="this core")
        top = staging / "c"
        # Only files the core may install are written (generated website docs,
        # upstream's test suites and CI files never touch the disk).
        extracted = common.safe_extract(fetched["archive"], top, strip_top=True,
                                        keep=ownership.is_core_installable)
        candidate = sorted({ownership.normalize(n) for n in extracted})
        if "run_agent.py" not in candidate or "pyproject.toml" not in candidate:
            raise UpdateError("the archive does not look like a Hermes core "
                              "(run_agent.py or pyproject.toml missing)", code="not_a_core")
        plan = dependency_plan(top, allow_unpinned=allow_unpinned)

        # Overlay the live wrapper so the staged tree is the complete product.
        for rel in ownership.iter_wrapper_files(self.root):
            dst = top / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root / rel, dst)

        deps_report = {"strategy": plan["strategy"], "skipped": True}
        fingerprint = plan_fingerprint(plan)
        if skip_deps:
            deps_report["reason"] = "skipped on request"
        elif shortcuts and state.get("dependencies_fingerprint") == fingerprint:
            deps_report["reason"] = "dependency set unchanged"
        else:
            if pending:
                self.say("Finishing an earlier package change that was interrupted ...")
            deps_report = self._install_dependencies(plan, staging, fingerprint, ctx)
        if plan.get("lock_note"):
            deps_report["lock_note"] = plan["lock_note"]

        self.say("Verifying the new core in a fresh process ...")
        result = self._run_verify(top)
        if not result.get("ok"):
            raise UpdateError(f"verification of {(sha or 'the new core')[:12]} failed: "
                              f"{result.get('reason')}", code="verify_failed")

        # Plan the swap. A live file whose content is not what we recorded
        # installing (a user edit, or a file we never installed) is kept.
        hashes = {rel: common.sha256_file(top / rel) for rel in candidate}
        previous = (state or {}).get("files") or {}
        adopted = False
        if not state and (self.root / "run_agent.py").is_file():
            previous = self.legacy_files()
            adopted = True
        recorded_by_key = {ownership.key(r): h for r, h in previous.items()}
        # Release-only files (the LICENSE a release ZIP carries) count as
        # installed by us when they still match the release manifest, so the
        # first core install replaces them without keeping a copy.
        release_files = (common.read_json(self.root / ownership.RELEASE_MANIFEST) or {}).get(
            "files")
        if isinstance(release_files, dict):
            for rel, digest in release_files.items():
                if ownership.is_release_only(rel) and \
                        recorded_by_key.get(ownership.key(rel)) is None:
                    recorded_by_key[ownership.key(rel)] = digest
        txn = common.Transaction(self.root, "core")
        ctx["txn"] = txn
        for rel in candidate:
            live = self.root / rel
            if live.is_dir():
                raise UpdateError(f"cannot install {rel}: a directory is in the way",
                                  code="swap_failed")
            preserve = False
            if live.is_file():
                live_hash = common.sha256_file(live)
                if live_hash == hashes[rel]:
                    continue
                recorded = recorded_by_key.get(ownership.key(rel))
                preserve = recorded is None or live_hash != recorded
            txn.put(rel, top / rel, preserve=preserve)
        removed, kept_modified = [], []
        candidate_keys = {ownership.key(r) for r in candidate}
        for rel, recorded in sorted(previous.items()):
            if ownership.key(rel) in candidate_keys or ownership.classify(rel) != "core":
                continue
            live = self.root / rel
            if not live.is_file():
                continue
            if recorded is None:            # adopted legacy file: no hash, keep a copy
                txn.remove(rel, preserve=True)
                removed.append(rel)
            elif common.sha256_file(live) == recorded:
                txn.remove(rel)
                removed.append(rel)
            else:
                kept_modified.append(rel)
        installed_deps = not deps_report.get("skipped")
        new_state = {
            "schema": 1,
            "repository": repo,
            "ref": fetched["ref"],
            "commit": sha,
            "source": fetched["source"],
            "installed_at": common.now_iso(),
            "python": common.python_tag(),
            "files": hashes,
            "dependencies_strategy": plan["strategy"],
            "dependencies_fingerprint": fingerprint if not skip_deps else
            (state or {}).get("dependencies_fingerprint"),
        }
        if adopted:
            new_state["adopted_from"] = "legacy portable install"
        # The state file is swapped with the files it describes.
        staged_state = staging / "st" / STATE_FILE
        common.write_json_atomic(staged_state, new_state)
        txn.put(f"{common.STATE_DIR}/{STATE_FILE}", staged_state)
        written = len(txn.file_ops) - len(removed)
        self.say(f"Replacing {written} files, removing {len(removed)} ...")
        txn.apply()
        live_result = self._run_verify(self.root)
        if not live_result.get("ok"):
            raise UpdateError("the installed core failed verification and was rolled back: "
                              f"{live_result.get('reason')}", code="verify_failed")
        kept = txn.commit()
        # Committed: nothing below may fail the update.
        warnings = []
        kept_mb = None
        try:
            if kept["kept"] and kept["keep"]:
                kept_mb = common.folder_size_mb(self.root / kept["keep"])
            common.prune_empty_dirs(self.root, removed)
            if installed_deps or deps_report.get("reason") == "dependency set unchanged":
                self._write_stamp(new_state["dependencies_fingerprint"], sha)
            if installed_deps:
                self.deps_marker_path.unlink(missing_ok=True)
        except OSError as exc:
            warnings.append(f"post-install bookkeeping: {exc}")
        from portable_hermes import bridge
        hook = bridge.ensure_pth(bridge.site_packages(self.root / "python_embedded"))
        deps_report.pop("before", None)
        result = {
            "ok": True, "changed": True, "commit": sha, "repository": repo,
            "ref": fetched["ref"], "source": fetched["source"],
            "files_written": written, "files_removed": len(removed),
            "kept_modified": kept_modified[:50], "kept_modified_count": len(kept_modified),
            "kept_edits": kept["keep"], "kept_edits_count": kept["kept"],
            "kept_edits_mb": kept_mb,
            "adopted": adopted, "dependencies": deps_report, "hook": hook,
            "verification": [c["name"] for c in live_result.get("checks", []) if c.get("ok")],
            "warnings": warnings + [c["detail"] for c in live_result.get("checks", [])
                                    if c.get("warning")],
            "message": f"core installed at {(sha or 'unknown commit')[:12]}",
        }
        return result

    # ----- public -----------------------------------------------------------
    def install(self, *, ref: str | None = None, zip_path: str | None = None,
                commit: str | None = None, skip_deps: bool = False, force: bool = False,
                allow_fallback: bool = True, allow_git: bool = False) -> dict:
        """Install or update the core. Returns a result dict (never raises)."""
        if self.is_git_checkout() and not allow_git:
            return {"ok": False, "code": "git_checkout", "exit": EXIT_KEPT,
                    "reason": "this install is a git checkout; update it with git "
                              "(the portable core updater only manages ZIP installs)"}
        existing = "unknown"
        try:
            with common.InstallLock(self.root):
                recovered = common.recover(self.root)
                existing = self.existing_core()
                try:
                    result = self._attempt(ref=ref, zip_path=zip_path, commit=commit,
                                           repo=self.repo, skip_deps=skip_deps, force=force,
                                           allow_unpinned=existing != "none")
                except UpdateError as primary:
                    # Fall back only when there is no working core to keep, the
                    # caller did not ask for a specific source and the problem
                    # is not this folder's Python (a runtime upgrade fixes that).
                    if (existing != "none" or ref or zip_path or not allow_fallback
                            or primary.code == "runtime_too_old"):
                        return self._failure(primary, existing)
                    lkg = self.last_known_good()
                    if lkg is None:
                        return self._failure(primary, existing)
                    self.say(f"Newest core failed ({primary.reason}).")
                    self.say(f"Falling back to last-known-good {lkg['commit'][:12]} ...")
                    try:
                        result = self._attempt(ref=lkg["commit"], zip_path=None,
                                               commit=lkg["commit"],
                                               repo=lkg.get("repository", self.repo),
                                               skip_deps=skip_deps, force=True,
                                               allow_unpinned=False)
                    except UpdateError as second:
                        failure = self._failure(second, existing)
                        failure["reason"] = (f"newest core failed: {primary.reason}; "
                                             f"last-known-good failed: {second.reason}")
                        return failure
                    result["fallback"] = {"reason": primary.reason, "commit": lkg["commit"]}
                    result["message"] += " (last-known-good fallback)"
                if recovered:
                    result["recovered"] = recovered
                result["exit"] = EXIT_OK
                return result
        except UpdateError as exc:
            return self._failure(exc, existing)
        except Exception as exc:  # noqa: BLE001 - the result promise: never raise
            return self._failure(UpdateError(f"unexpected {type(exc).__name__}: {exc}",
                                             code="internal"), existing)

    def _failure(self, exc: UpdateError, existing: str) -> dict:
        details = dict(exc.details)
        restored = (details.get("dependencies_restored", True) is not False
                    and details.get("files_restored", True) is not False)
        kept = existing in ("recorded", "legacy") and restored
        if exc.code == "runtime_too_old":
            code = EXIT_RUNTIME
        else:
            code = EXIT_KEPT if kept else EXIT_FAILED
        result = {"ok": False, "code": exc.code, "reason": exc.reason, "exit": code,
                  "kept_existing_core": kept}
        for key, value in details.items():
            result.setdefault(key, value)
        return result

    def check(self, *, ref: str = "main", timeout: float = 20) -> dict:
        """Report what is installed and how far behind upstream it is."""
        info: dict = {"ok": True, "root": str(self.root)}
        if self.is_git_checkout():
            head = _git_head(self.root)
            info.update(install_type="git", commit=head,
                        message="git checkout: update it with git; the portable core "
                                "updater does not rewrite developer clones")
            return info
        state = self.read_state()
        if state:
            info.update(install_type="zip", repository=state.get("repository"),
                        ref=state.get("ref"), commit=state.get("commit"),
                        installed_at=state.get("installed_at"))
            # Existence only (hashing every file would make this check slow):
            # recorded core files that are no longer on disk.
            missing = sum(1 for rel in list(state.get("files", {}))[:20000]
                          if not (self.root / rel).is_file())
            if missing:
                info["missing_files"] = missing
            if self.pending_dependencies():
                info["dependencies_pending"] = True
                info["message"] = ("an earlier update was interrupted while changing Python "
                                   "packages; the next core update finishes it")
        elif (self.root / "run_agent.py").is_file():
            info.update(install_type="legacy", commit=None,
                        message="core installed by an older portable release; "
                                "the next update adopts it")
        else:
            info.update(install_type="none", message="no core installed")
        repo = (state or {}).get("repository") or self.repo
        try:
            latest = common.github_commit_sha(repo, ref, timeout=timeout)
            info["latest_commit"] = latest
            current = info.get("commit")
            if current and current == latest:
                info["behind_by"] = 0
                info["update_available"] = False
            elif current:
                try:
                    cmp = common.github_compare(repo, current, latest, timeout=timeout)
                    info["behind_by"] = cmp.get("ahead_by")
                    info["compare_status"] = cmp.get("status")
                except UpdateError as exc:
                    info["behind_by"] = None
                    info["compare_error"] = exc.reason
                info["update_available"] = True
            else:
                info["update_available"] = True
        except UpdateError as exc:
            info["latest_commit"] = None
            info["update_available"] = None
            info["network_error"] = exc.reason
        return info


def _last_error_line(output: str) -> str:
    lines = [l.strip() for l in (output or "").splitlines() if l.strip()]
    for line in reversed(lines):
        if line.startswith("ERROR"):
            return line[:400]
    return (lines[-1] if lines else "no output")[:400]


def _git_head(root: Path) -> str | None:
    head = Path(root) / ".git"
    try:
        if head.is_file():  # worktree: "gitdir: <path>"
            target = head.read_text(encoding="utf-8").split(":", 1)[1].strip()
            head = Path(target)
        text = (head / "HEAD").read_text(encoding="utf-8").strip()
        if text.startswith("ref:"):
            ref = text.split(":", 1)[1].strip()
            ref_file = head / ref
            if ref_file.is_file():
                return ref_file.read_text(encoding="utf-8").strip()
            return ref
        return text
    except (OSError, IndexError):
        return None

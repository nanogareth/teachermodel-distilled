"""Worlds built once per test session (speed): several tests start from the same expensive store, so it is built once and
copied into each test's tmp_path (importable: pythonpath has tests/). conftest sets FACTORY to the session's
tmp_path_factory and clears WORLDS at the end. A plain module, so conftest and the test modules share one instance."""

import shutil

FACTORY: list = []  # [the session's tmp_path_factory]
WORLDS: dict = {}  # key -> the directory the world was built in


def assert_relocatable(base):
    """A built world may be copied elsewhere only if no file in it names the directory it was built in."""
    needles = {str(base), base.as_posix(), str(base).replace("\\", "\\\\")}
    for path in base.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            hit = [n for n in needles if n.encode("utf-8") in data]
            assert not hit, f"{path.relative_to(base)} names its build directory; the world cannot be cached"


def copy_world(key, build, dest):
    """`build(base)` runs once per session per key, in a fresh directory laid out as a test's tmp_path is (`private/` from
    make_fictional_store, `root/` from make_privacy_root, files beside them); its result is copied over `dest` (the test's
    tmp_path). Each test gets its own copy, so a test that changes the world changes only its own. The build must make
    the same files a test's fixtures would, so the copy only adds to or replaces them. The key must name everything the
    build depends on."""
    if key not in WORLDS:
        base = FACTORY[0].mktemp("world")
        build(base)
        assert_relocatable(base)
        WORLDS[key] = base
    shutil.copytree(WORLDS[key], dest, dirs_exist_ok=True)
    return dest

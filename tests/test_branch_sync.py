"""The deployer keeps the foundation branch level with main, so a cPanel Deploy click never restores old code."""
import subprocess

import run_deploy


def sh(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def make_origin(tmp_path):
    work, origin = tmp_path / "work", tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    for k, v in (("user.name", "t"), ("user.email", "t@example.com")):
        sh(work, "config", k, v)
    (work / ".cpanel.yml").write_text("DEPLOYPATH=$HOME/public_html\n")
    (work / "page.txt").write_text("v1\n")
    sh(work, "add", "-A")
    sh(work, "commit", "-qm", "init")
    sh(work, "remote", "add", "origin", str(origin))
    sh(work, "push", "-q", "origin", "main")
    sh(work, "checkout", "-qb", "foundation")
    (work / ".cpanel.yml").write_text("DEPLOYPATH=$HOME/public_html/foundation.example.org\n")
    sh(work, "commit", "-qam", "foundation path")
    sh(work, "push", "-q", "origin", "foundation")
    sh(work, "checkout", "-q", "main")
    return work, origin


def test_sync_merges_main_into_foundation_and_keeps_its_deploy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNC_BRANCHES", "foundation")
    work, origin = make_origin(tmp_path)
    (work / "page.txt").write_text("v2 with SEO fix\n")
    sh(work, "commit", "-qam", "seo fix")
    sh(work, "push", "-q", "origin", "main")
    head = sh(work, "rev-parse", "HEAD")

    assert run_deploy.sync_branches(str(origin), None, head) == [f"foundation: synced to {head[:8]}"]
    assert sh(origin, "show", "foundation:page.txt") == "v2 with SEO fix"
    assert sh(origin, "show", "foundation:.cpanel.yml") == "DEPLOYPATH=$HOME/public_html/foundation.example.org"
    sh(origin, "merge-base", "--is-ancestor", head, "foundation")  # raises if not contained

    # Already level: nothing to do, branch untouched.
    tip = sh(origin, "rev-parse", "foundation")
    assert run_deploy.sync_branches(str(origin), None, head) == []
    assert sh(origin, "rev-parse", "foundation") == tip


def test_sync_conflict_leaves_branch_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNC_BRANCHES", "foundation")
    work, origin = make_origin(tmp_path)
    (work / ".cpanel.yml").write_text("DEPLOYPATH=$HOME/somewhere_else\n")
    sh(work, "commit", "-qam", "conflicting deploy path")
    sh(work, "push", "-q", "origin", "main")
    before = sh(origin, "rev-parse", "foundation")
    out = run_deploy.sync_branches(str(origin), None, sh(work, "rev-parse", "HEAD"))
    assert out and "conflict" in out[0]
    assert sh(origin, "rev-parse", "foundation") == before


def test_missing_branch_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNC_BRANCHES", "nope")
    work, origin = make_origin(tmp_path)
    assert run_deploy.sync_branches(str(origin), None, sh(work, "rev-parse", "HEAD")) == ["nope: branch not found, skipped"]

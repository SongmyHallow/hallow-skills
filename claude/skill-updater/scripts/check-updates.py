"""
Skill Updater — 检查、更新、同步所有 skill。

Commands:
  inventory              → 完整分类清单（JSON）
  check-all              → 检查所有第三方插件更新
  check <name>           → 检查特定插件更新
  update <name> [--dry-run] → 更新插件
  lookup-skillsmp <name> → 在 skillsmp.com 上搜索 skill
  add-source <name> <url> [path] → 添加一个 GitHub 第三方来源
  add-own <name>         → 标记一个 skill 为"自己的"
  sync-hallow [--dry-run] → 同步自己的 skill 到 hallow-skills
  update-github <name> [--dry-run] → 从 GitHub 源更新一个直接 skill
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
HOME = Path.home()
SKILL_DIR = Path(__file__).parent.parent  # ~/.claude/skills/skill-updater/
SCRIPTS_DIR = Path(__file__).parent
SKILLS_DIR = HOME / ".claude" / "skills"
PLUGINS_DIR = HOME / ".claude" / "plugins"
INSTALLED_PLUGINS = PLUGINS_DIR / "installed_plugins.json"
KNOWN_MARKETPLACES = PLUGINS_DIR / "known_marketplaces.json"
CACHE_DIR = PLUGINS_DIR / "cache"
MARKETPLACES_DIR = PLUGINS_DIR / "marketplaces"
KNOWN_SOURCES = SKILL_DIR / "known-sources.json"


def reconfigure_stdout():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")


# ── JSON helpers ───────────────────────────────────────────────────────────

def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Known sources management ──────────────────────────────────────────────

def get_known_sources():
    return read_json(KNOWN_SOURCES)


def save_known_sources(data):
    write_json(KNOWN_SOURCES, data)


def get_third_party_github_map():
    return get_known_sources().get("third_party_github", {})


def get_own_skills_list():
    return get_known_sources().get("own_skills", [])


def get_hallow_config():
    return get_known_sources().get("hallow_sync", {})


# ── Git helpers ────────────────────────────────────────────────────────────

def git_ls_remote_tags(repo_url):
    try:
        r = subprocess.run(
            ["git", "ls-remote", "--tags", repo_url],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return {"error": r.stderr.strip()}
        tags = []
        for line in r.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                tag = parts[1].replace("refs/tags/", "").replace("^{}", "")
                tags.append(tag)
        return {"tags": tags}
    except Exception as e:
        return {"error": str(e)}


def git_ls_remote_head(repo_url, ref="HEAD"):
    try:
        r = subprocess.run(
            ["git", "ls-remote", repo_url, ref],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return {"error": r.stderr.strip()}
        sha = r.stdout.strip().split("\t")[0] if r.stdout.strip() else None
        return {"sha": sha}
    except Exception as e:
        return {"error": str(e)}


def parse_semver(tag):
    tag = tag.lstrip("vV")
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(int(g) for g in m.groups()) if m else None


def latest_semver_tag(tags):
    parsed = [(parse_semver(t), t) for t in tags if parse_semver(t)]
    if not parsed:
        return None
    parsed.sort(key=lambda x: x[0])
    return parsed[-1][1]


# ── Installed state ────────────────────────────────────────────────────────

def get_installed_plugins():
    data = read_json(INSTALLED_PLUGINS)
    result = {}
    for key, entries in data.get("plugins", {}).items():
        if entries and isinstance(entries, list):
            info = entries[0].copy()
            info["plugin_key"] = key
            result[key] = info
    return result


def get_installed_skills():
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(d.name for d in SKILLS_DIR.iterdir() if d.is_dir() and (d / "SKILL.md").exists())


def get_marketplaces():
    return read_json(KNOWN_MARKETPLACES)


def get_marketplace_catalog(mp_name, mp_info):
    install_path = mp_info.get("installLocation")
    if not install_path:
        return {}
    for try_path in [Path(install_path) / ".claude-plugin" / "marketplace.json",
                     Path(install_path) / "marketplace.json"]:
        data = read_json(try_path)
        if "_error" not in data and data:
            return data
    return {}


def get_skill_frontmatter_field(skill_dir, field="name"):
    sk = SKILLS_DIR / skill_dir / "SKILL.md"
    if not sk.exists():
        return None
    content = sk.read_text(encoding="utf-8", errors="replace")
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    fm = content[3:end]
    for line in fm.strip().splitlines():
        if line.startswith(f"{field}:"):
            val = line.split(":", 1)[1].strip().strip("\"'")
            return val
        stripped = line.strip()
        if stripped == f"{field}: |" or stripped == f"{field}: >":
            rest = fm.split(line, 1)[1].strip()
            return rest[:80].strip("\"'")
    return None


def get_skill_license_info(skill_name):
    lic_file = SKILLS_DIR / skill_name / "LICENSE.txt"
    if lic_file.exists():
        content = lic_file.read_text(encoding="utf-8", errors="replace")
        for line in content.strip().splitlines():
            if "anthropic" in line.lower():
                return "© Anthropic"
            if "apache" in line.lower():
                return "Apache-2.0"
        return content[:80].strip()
    lic_fm = get_skill_frontmatter_field(skill_name, "license")
    return lic_fm.strip() if lic_fm else None


def get_superpowers_skill_list():
    sp_cache = CACHE_DIR / "superpowers-marketplace" / "superpowers"
    if not sp_cache.is_dir():
        return []
    versions = sorted(sp_cache.iterdir())
    if not versions:
        return []
    skills_dir = versions[-1] / "skills"
    return [d.name for d in skills_dir.iterdir() if d.is_dir()] if skills_dir.is_dir() else []


# ── Classification ─────────────────────────────────────────────────────────

def is_anthropic_official(mp_name, plugin_entry):
    if "official" not in mp_name:
        return False
    author = plugin_entry.get("author", {})
    return isinstance(author, dict) and author.get("name") == "Anthropic"


def classify_all():
    installed_plugins = get_installed_plugins()
    installed_skills = get_installed_skills()
    marketplaces = get_marketplaces()
    known_tp = get_third_party_github_map()
    own_list = get_own_skills_list()

    # Build catalog: map plugin_name → [{entry, marketplace}]
    all_catalog = {}
    for mp_name, mp_info in marketplaces.items():
        if not isinstance(mp_info, dict) or "source" not in mp_info:
            continue
        catalog = get_marketplace_catalog(mp_name, mp_info)
        for entry in catalog.get("plugins", []):
            pname = entry.get("name")
            if pname:
                entry["_marketplace"] = mp_name
                all_catalog.setdefault(pname, []).append(entry)

    result = {
        "first_party": [],
        "third_party_managed": [],
        "third_party_github": [],
        "third_party_direct": [],
        "own": [],
        "unknown": [],
    }

    # Classify plugin-managed
    for plugin_key, info in installed_plugins.items():
        name = plugin_key.split("@")[0]
        marketplace = plugin_key.split("@")[1] if "@" in plugin_key else "unknown"
        catalog_entries = all_catalog.get(name, [])

        if any(is_anthropic_official(mp.get("_marketplace", ""), mp) for mp in catalog_entries):
            result["first_party"].append({
                "name": name, "plugin_key": plugin_key,
                "version": info.get("version"), "source": f"plugin:{plugin_key}", "managed": True,
            })
        else:
            result["third_party_managed"].append({
                "name": name, "plugin_key": plugin_key,
                "version": info.get("version"), "sha": info.get("gitCommitSha"),
                "marketplace": marketplace, "catalog_entries": catalog_entries,
                "source": f"plugin:{plugin_key}", "managed": True,
            })
            if name in installed_skills:
                installed_skills.remove(name)

    # Classify direct skills
    for skill_name in installed_skills:
        # Skip self
        if skill_name == "skill-updater":
            continue

        catalog_entries = all_catalog.get(skill_name, [])
        license_copyright = get_skill_license_info(skill_name)

        # 1. User's own skills
        if skill_name in own_list:
            result["own"].append({"name": skill_name, "source": "known-own", "managed": False})
            continue

        # 2. Check superpowers plugin cache
        sp_skills = get_superpowers_skill_list()
        if skill_name.lower().replace("-", "") in [s.lower().replace("-", "") for s in sp_skills]:
            result["third_party_direct"].append({
                "name": skill_name, "source": "superpowers-cache", "managed": False,
            })
            continue

        # 3. Known third-party GitHub source
        if skill_name in known_tp:
            result["third_party_github"].append({
                "name": skill_name, "source": "known-github",
                "managed": False, "github_info": known_tp[skill_name],
            })
            continue

        # 4. In marketplace catalog
        if catalog_entries:
            if any(is_anthropic_official(mp.get("_marketplace", ""), mp) for mp in catalog_entries):
                result["first_party"].append({
                    "name": skill_name, "source": "marketplace", "managed": False,
                    "license": license_copyright,
                })
            else:
                result["third_party_direct"].append({
                    "name": skill_name, "source": "marketplace", "managed": False,
                    "catalog_entries": catalog_entries, "license": license_copyright,
                })
            continue

        # 5. Detect by license
        is_anthropic_license = (
            (license_copyright and "anthropic" in license_copyright.lower())
            or license_copyright == "Apache-2.0"
        )
        if is_anthropic_license:
            result["first_party"].append({
                "name": skill_name, "source": "license-detected", "managed": False,
                "license": license_copyright,
            })
            continue

        # 6. Unknown
        result["unknown"].append({
            "name": skill_name, "source": "unknown", "managed": False,
            "skill_name_from_fm": get_skill_frontmatter_field(skill_name, "name"),
            "license": license_copyright,
        })

    return result


# ── Update checks (plugin-managed) ─────────────────────────────────────────

def check_plugin_update(plugin_key, info, catalog_entries):
    result = {
        "plugin_key": plugin_key,
        "current_version": info.get("version"),
        "current_sha": info.get("gitCommitSha"),
        "update_available": False,
        "latest_version": None,
        "latest_sha": None,
        "source_url": None,
        "error": None,
    }

    for entry in catalog_entries:
        source = entry.get("source", {})
        if not isinstance(source, dict):
            continue

        url = source.get("url")
        mkt_version = entry.get("version")

        # Check marketplace version
        if mkt_version and mkt_version != result["current_version"]:
            cv = parse_semver(result.get("current_version") or "0.0.0")
            mv = parse_semver(mkt_version)
            if mv and cv and mv > cv:
                result["update_available"] = True
                result["latest_version"] = mkt_version
                result["source_url"] = url
                result["update_type"] = "marketplace-version"

        # Check git tags
        if url and ("github.com" in url or "git@" in url):
            result["source_url"] = url
            tags_resp = git_ls_remote_tags(url)
            if "tags" in tags_resp:
                latest_tag = latest_semver_tag(tags_resp["tags"])
                if latest_tag:
                    result["latest_tag"] = latest_tag
                    cv = parse_semver(result.get("current_version") or "0.0.0")
                    lv = parse_semver(latest_tag)
                    if lv and cv and lv > cv:
                        result["update_available"] = True
                        result["latest_version"] = latest_tag.lstrip("vV")
                        result["update_type"] = "git-tag"
            elif "error" in tags_resp:
                result["git_tag_error"] = tags_resp["error"]

    return result


def get_catalog_for_plugin(plugin_key):
    name = plugin_key.split("@")[0]
    marketplace = plugin_key.split("@")[1] if "@" in plugin_key else None
    if not marketplace:
        return []
    marketplaces = get_marketplaces()
    mp_info = marketplaces.get(marketplace)
    if not mp_info or not isinstance(mp_info, dict):
        return []
    catalog = get_marketplace_catalog(marketplace, mp_info)
    return [e for e in catalog.get("plugins", []) if e.get("name") == name]


def check_all_updates():
    classification = classify_all()
    results = []
    installed = get_installed_plugins()
    for item in classification.get("third_party_managed", []):
        plugin_key = item.get("plugin_key")
        info = installed.get(plugin_key, {})
        catalog = item.get("catalog_entries", [])
        cr = check_plugin_update(plugin_key, info, catalog)
        cr["name"] = item.get("name")
        results.append(cr)
    return results


# ── Execute plugin update ──────────────────────────────────────────────────

def execute_plugin_update(plugin_key, dry_run=False):
    installed = get_installed_plugins()
    info = installed.get(plugin_key)
    if not info:
        return {"success": False, "message": f"未找到插件 '{plugin_key}'"}

    name = plugin_key.split("@")[0]
    marketplace = plugin_key.split("@")[1] if "@" in plugin_key else None
    marketplaces = get_marketplaces()
    catalog_entries = []

    if marketplace and marketplace in marketplaces:
        mp_info = marketplaces[marketplace]
        if isinstance(mp_info, dict):
            catalog = get_marketplace_catalog(marketplace, mp_info)
            for entry in catalog.get("plugins", []):
                if entry.get("name") == name:
                    catalog_entries.append(entry)

    if not catalog_entries:
        return {"success": False, "message": f"未在市场中找到 '{name}' 的条目"}

    entry = catalog_entries[0]
    source = entry.get("source", {})
    if not isinstance(source, dict):
        return {"success": False, "message": f"'{name}' 缺少 source 配置"}

    url = source.get("url")
    if not url:
        return {"success": False, "message": f"'{name}' 缺少 source URL"}

    ref = source.get("ref", "HEAD")
    current_sha = info.get("gitCommitSha")
    install_path = Path(info.get("installPath", ""))

    head_info = git_ls_remote_head(url, ref)
    if "sha" not in head_info or not head_info["sha"]:
        tags_resp = git_ls_remote_tags(url)
        if "tags" in tags_resp:
            latest_tag = latest_semver_tag(tags_resp.get("tags", []))
            if latest_tag:
                ref = latest_tag
                head_info = git_ls_remote_head(url, f"refs/tags/{ref}")

    latest_sha = head_info.get("sha")
    if not latest_sha:
        return {"success": False, "message": f"无法获取 '{name}' 的最新 SHA（可能需要网络连接）"}

    if latest_sha == current_sha:
        return {"success": True, "message": f"'{name}' 已是最新", "already_current": True}

    if dry_run:
        return {
            "success": True, "message": f"将更新 '{name}': {current_sha[:12] if current_sha else '?'} → {latest_sha[:12]}",
            "dry_run": True, "source_url": url, "ref": ref, "new_sha": latest_sha,
        }

    try:
        with tempfile.TemporaryDirectory(prefix="skill-updater-") as tmpdir:
            # Clone
            clone_cmd = ["git", "clone", "--depth", "1", url, "--branch", ref, tmpdir]
            r = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                clone_cmd = ["git", "clone", "--depth", "1", url, tmpdir]
                r = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=120)
                if r.returncode != 0:
                    return {"success": False, "message": f"克隆失败: {r.stderr.strip()}"}

            # Determine new version
            new_version = ref.lstrip("vV")
            if not new_version or new_version == ref:
                tag_r = subprocess.run(
                    ["git", "-C", tmpdir, "describe", "--tags", "--abbrev=0"],
                    capture_output=True, text=True, timeout=10,
                )
                if tag_r.returncode == 0:
                    new_version = tag_r.stdout.strip().lstrip("vV")
                else:
                    new_version = latest_sha[:8]

            # Copy to cache
            new_cache_dir = install_path.parent / new_version
            skills_src = Path(tmpdir) / "skills"
            if install_path.exists() and skills_src.is_dir():
                if new_cache_dir.exists():
                    shutil.rmtree(new_cache_dir)
                shutil.copytree(skills_src, new_cache_dir / "skills")
                for f in ["package.json", "README.md", "CHANGELOG.md", "LICENSE"]:
                    src_file = Path(tmpdir) / f
                    if src_file.exists():
                        shutil.copy2(src_file, new_cache_dir / f)

                # Update installed_plugins.json
                plug_data = read_json(INSTALLED_PLUGINS)
                if plug_data:
                    plugins = plug_data.get("plugins", {})
                    if plugin_key in plugins:
                        oi = plugins[plugin_key][0]
                        oi["version"] = new_version
                        oi["gitCommitSha"] = latest_sha
                        oi["lastUpdated"] = datetime.utcnow().isoformat() + "Z"
                        oi["installPath"] = str(new_cache_dir)
                        write_json(INSTALLED_PLUGINS, plug_data)

                return {
                    "success": True, "message": f"已更新 '{name}' → v{new_version}",
                    "old_version": info.get("version"), "new_version": new_version,
                    "old_sha": current_sha, "new_sha": latest_sha,
                }
            else:
                return {"success": False, "message": f"安装路径不存在或缺少 skills 目录"}
    except Exception as e:
        return {"success": False, "message": f"更新失败: {str(e)}"}


# ── Update from GitHub (direct skills) ─────────────────────────────────────

def update_from_github(skill_name, dry_run=False):
    """Update a direct skill from its known GitHub source."""
    known_tp = get_third_party_github_map()
    info = known_tp.get(skill_name)
    if not info:
        return {"success": False, "message": f"'{skill_name}' 未在 known-sources.json 的 third_party_github 中"}

    url = info.get("url")
    path_in_repo = info.get("path", "")
    if not url:
        return {"success": False, "message": f"'{skill_name}' 缺少 GitHub URL"}

    target_dir = SKILLS_DIR / skill_name
    if not target_dir.is_dir():
        return {"success": False, "message": f"本地未找到 skill 目录: {target_dir}"}

    # Check latest commit in repo
    head_info = git_ls_remote_head(url, "HEAD")
    if "sha" not in head_info or not head_info["sha"]:
        return {"success": False, "message": f"无法访问 {url}（可能需要网络连接）"}

    latest_sha = head_info["sha"]

    if dry_run:
        return {
            "success": True, "message": f"将更新 '{skill_name}' 从 GitHub ({url})",
            "dry_run": True, "source_url": url, "path": path_in_repo, "sha": latest_sha,
        }

    try:
        with tempfile.TemporaryDirectory(prefix="skill-updater-") as tmpdir:
            r = subprocess.run(
                ["git", "clone", "--depth", "1", url, tmpdir],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                return {"success": False, "message": f"克隆失败: {r.stderr.strip()}"}

            # Find the skill source
            skill_src = Path(tmpdir) / path_in_repo if path_in_repo else Path(tmpdir)
            if not skill_src.is_dir():
                return {"success": False, "message": f"仓库中未找到路径 '{path_in_repo}'"}

            # Backup old skill
            backup_dir = SKILL_DIR / "backups" / f"{skill_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            shutil.copytree(target_dir, backup_dir)

            # Remove old and copy new
            shutil.rmtree(target_dir)
            shutil.copytree(skill_src, target_dir)

            return {
                "success": True,
                "message": f"已更新 '{skill_name}'（备份位于 {backup_dir.name}）",
                "backup": str(backup_dir),
            }
    except Exception as e:
        return {"success": False, "message": f"更新失败: {str(e)}"}


# ── Lookup skillsmp.com ────────────────────────────────────────────────────

def lookup_skillsmp(skill_name):
    """
    Look up a skill on skillsmp.com via WebSearch.
    Returns info about the skill including possible GitHub source.
    """
    # This function generates the search instructions for the SKILL.md flow.
    # The actual WebSearch/WebFetch is done by Claude, not the script.
    # So this just returns the search strategy.
    return {
        "search_url": f"https://skillsmp.com/skills?q={skill_name}",
        "search_query": f"site:skillsmp.com \"{skill_name}\"",
        "strategy": "Claude should use WebSearch or WebFetch to look up the skill on skillsmp.com, find its GitHub source URL, then add it to known-sources.json",
    }


# ── Sync own skills to hallow-skills ───────────────────────────────────────

def sync_to_hallow(dry_run=False):
    """Sync user's own skills to the hallow-skills directory."""
    config = get_hallow_config()
    target_base = Path(config.get("target_dir", ""))
    claude_subdir = config.get("claude_subdir", "claude")

    if not target_base.is_dir():
        return {"success": False, "message": f"目标目录不存在: {target_base}"}

    target_claude = target_base / claude_subdir
    own_skills = get_own_skills_list()

    synced = []
    errors = []

    for skill_name in own_skills:
        src = SKILLS_DIR / skill_name
        dst = target_claude / skill_name
        if not src.is_dir():
            errors.append(f"'{skill_name}' 本地不存在")
            continue

        if dry_run:
            synced.append(f"将复制: {src} → {dst}")
            continue

        # Remove old, copy new
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        synced.append(skill_name)

    if dry_run:
        return {"success": True, "dry_run": True, "would_sync": synced, "errors": errors}

    # Update README
    readme_path = target_base / "README.md"
    readme_ok = _update_hallow_readme(readme_path, target_claude)

    # Git commit
    git_ok = _git_commit(target_base, f"同步 Claude skills: {', '.join(synced)}")

    return {
        "success": True,
        "synced": synced,
        "errors": errors,
        "readme_updated": readme_ok,
        "git_committed": git_ok,
    }


def _update_hallow_readme(readme_path, skills_dir):
    """Update README.md with detailed skill table (khazix-skills style)."""
    try:
        import re as _re

        # Predefined emoji + one-liner for known own skills
        SKILL_INFO = {
            "agent-the-chariot": ("🏛️", "战车", "执行者——将教皇的方案/计划文档落地执行，一步步按确认完成任务"),
            "agent-the-hierophant": ("👑", "教皇", "规划者——将模糊的想法转化为详细可行的工作流 + 技术栈报告"),
            "agent-the-lovers": ("💕", "恋人", "创造者——游戏美术设计、角色原画、动效/特效、文案包装与世界观架构"),
            "agent-the-magician": ("🎩", "魔术师", "灵感者——头脑风暴、创意提案、打破常规的突破性解决思路"),
            "agent-the-star": ("⭐", "星星", "管理者——项目进度管理、任务追踪、排期规划与进度报告生成"),
        }

        skills_list = sorted(
            d.name for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        )

        content = """# Hallow Skills

我的个人 AI skill 库，用于 Claude Code 和 Gemini CLI 的自定义技能。

## 目录结构

```
hallow-skills/
├── claude/        # Claude Code 技能
├── gemini/        # Gemini CLI 技能
├── shared/        # 跨平台技能
└── tools/         # 辅助工具
```

## 使用方式

将 claude/ 目录中需要的 skill 复制到 Claude Code 的 skills 目录即可：

```bash
cp -r claude/<skill-name> ~/.claude/skills/
```

## Claude Skills

| 名字 | 一句话 | 说明 |
|---|---|---|
"""

        for skill_name in skills_list:
            info = SKILL_INFO.get(skill_name, ("📦", "自定义", "自定义 skill"))
            emoji, zh_name, one_liner = info

            # Build a short usage description from SKILL.md body
            desc = ""
            sk_path = skills_dir / skill_name / "SKILL.md"
            if sk_path.exists():
                body = sk_path.read_text(encoding="utf-8", errors="replace")
                # Skip frontmatter
                body_end = body.find("---", 3)
                if body_end != -1:
                    body = body[body_end + 3:].strip()
                # Get first non-blank, non-heading line
                for line in body.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith(">") and not line.startswith("---"):
                        desc = line.strip().strip('"').strip("'")[:120]
                        break

            content += f"| {emoji} **{skill_name}（{zh_name}）** | {one_liner} | {desc} |\n"

        content += f"""

---

*自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
        readme_path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        return False


def _git_commit(repo_path, message):
    """Run git add + commit + push. Returns True on success, False if git fails."""
    try:
        # git add
        r1 = subprocess.run(
            ["git", "add", str(repo_path / "claude")],
            capture_output=True, text=True, timeout=30, cwd=str(repo_path),
        )
        if r1.returncode != 0:
            return False

        # Also add README.md if changed
        subprocess.run(
            ["git", "add", str(repo_path / "README.md")],
            capture_output=True, text=True, timeout=30, cwd=str(repo_path),
        )

        # git commit (only if there are changes)
        r2 = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True, timeout=10, cwd=str(repo_path),
        )
        if r2.returncode == 0:
            return True  # nothing to commit

        r3 = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=30, cwd=str(repo_path),
        )
        if r3.returncode != 0:
            return False

        # git push
        r4 = subprocess.run(
            ["git", "push"],
            capture_output=True, text=True, timeout=60, cwd=str(repo_path),
        )
        return r4.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ── Add source / own commands ──────────────────────────────────────────────

def cmd_add_source(name, url, path_in_repo=""):
    data = get_known_sources()
    tp = data.setdefault("third_party_github", {})
    info = {"url": url, "path": path_in_repo, "type": "git-subdir" if path_in_repo else "git-root"}
    if name in tp:
        old = tp[name]
        info["_previous"] = old
    tp[name] = info
    save_known_sources(data)
    return {"success": True, "message": f"已{'更新' if '_previous' in info else '添加'} '{name}' → {url}"}


def cmd_add_own(name):
    data = get_known_sources()
    own = data.setdefault("own_skills", [])
    if name not in own:
        own.append(name)
        # Also remove from ignored if present
        ignored = data.get("ignored", [])
        if name in ignored:
            data["ignored"].remove(name)
        save_known_sources(data)
    return {"success": True, "message": f"已将 '{name}' 标记为自己的 skill"}


# ── CLI commands ───────────────────────────────────────────────────────────

def cmd_inventory():
    result = {
        "installed_plugins": {k: {"version": v.get("version"), "sha": v.get("gitCommitSha", "")[:12] if v.get("gitCommitSha") else None}
                               for k, v in get_installed_plugins().items()},
        "installed_skills": get_installed_skills(),
        "known_github_sources": list(get_third_party_github_map().keys()),
        "own_skills": get_own_skills_list(),
        "classification": classify_all(),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def cmd_check_all():
    results = check_all_updates()
    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))


def cmd_check(name):
    installed = get_installed_plugins()
    for key, info in installed.items():
        if name in key:
            catalog = get_catalog_for_plugin(key)
            r = check_plugin_update(key, info, catalog)
            print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
            return
    # Check if it's a known GitHub source
    known_tp = get_third_party_github_map()
    if name in known_tp:
        info = known_tp[name]
        head = git_ls_remote_head(info["url"], "HEAD")
        print(json.dumps({
            "name": name, "type": "known-github",
            "url": info["url"], "path": info.get("path"),
            "latest_sha": head.get("sha"),
            "error": head.get("error"),
        }, indent=2, ensure_ascii=False, default=str))
        return
    print(json.dumps({"error": f"未找到 '{name}'"}, ensure_ascii=False))


def cmd_update(name, dry_run=False):
    installed = get_installed_plugins()
    for key in installed:
        if name in key:
            r = execute_plugin_update(key, dry_run=dry_run)
            print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
            return
    # Try as GitHub source update
    if name in get_third_party_github_map():
        r = update_from_github(name, dry_run=dry_run)
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        return
    print(json.dumps({"error": f"未找到可更新的 '{name}'"}, ensure_ascii=False))


def cmd_lookup_skillsmp(name):
    r = lookup_skillsmp(name)
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))


def cmd_add_source_cli(name, url, path_in_repo=""):
    r = cmd_add_source(name, url, path_in_repo)
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))


def cmd_add_own_cli(name):
    r = cmd_add_own(name)
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))


def cmd_sync_hallow(dry_run=False):
    r = sync_to_hallow(dry_run=dry_run)
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))


def cmd_update_github(name, dry_run=False):
    r = update_from_github(name, dry_run=dry_run)
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    reconfigure_stdout()

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "inventory":
        cmd_inventory()
    elif command == "check-all":
        cmd_check_all()
    elif command == "check" and len(sys.argv) > 2:
        cmd_check(sys.argv[2])
    elif command == "update" and len(sys.argv) > 2:
        dry_run = "--dry-run" in sys.argv
        cmd_update(sys.argv[2], dry_run=dry_run)
    elif command == "lookup-skillsmp" and len(sys.argv) > 2:
        cmd_lookup_skillsmp(sys.argv[2])
    elif command == "add-source" and len(sys.argv) > 3:
        path_arg = sys.argv[4] if len(sys.argv) > 4 else ""
        cmd_add_source_cli(sys.argv[2], sys.argv[3], path_arg)
    elif command == "add-own" and len(sys.argv) > 2:
        cmd_add_own_cli(sys.argv[2])
    elif command == "sync-hallow":
        dry_run = "--dry-run" in sys.argv
        cmd_sync_hallow(dry_run=dry_run)
    elif command == "update-github" and len(sys.argv) > 2:
        dry_run = "--dry-run" in sys.argv
        cmd_update_github(sys.argv[2], dry_run=dry_run)
    else:
        print(f"未知命令: {command}")
        print(__doc__)
        sys.exit(1)

//! The card's repo rows: the git repos where you most recently started a Claude Code session or
//! sent a prompt, with their latest GitHub Actions runs from `gh`.

use std::collections::VecDeque;
use std::io::Read;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::LazyLock;
use std::time::{Duration, Instant};

use serde_json::{Value, json};
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;

use crate::{
    CI_POLL_AFTER, CI_POLL_WHILE_RUNNING, Json, PATHS, age, list_dir, modified, now, read_json,
    read_text, remove, write_json,
};

/// Run a program and return what it printed, or None if it failed or took longer than timeout.
pub fn run(program: &Path, arguments: &[&str], timeout: Duration) -> Option<String> {
    let mut child = Command::new(program)
        .args(arguments)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW) // the agent has no console, so each would open one
        .spawn()
        .ok()?;
    let mut stdout = child.stdout.take()?;
    let reader = std::thread::spawn(move || {
        let mut out = Vec::new();
        let _ = stdout.read_to_end(&mut out);
        out
    });
    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(20)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    };
    let out = reader.join().ok()?;
    status.success().then(|| String::from_utf8_lossy(&out).trim().to_string())
}

/// A program on PATH, or where its installer puts it. The agent keeps the PATH it started with, so
/// something installed since then is only in the second place.
fn find_program(name: &str, installed: &[&str]) -> Option<PathBuf> {
    let path = std::env::var_os("PATH").unwrap_or_default();
    std::env::split_paths(&path)
        .map(|dir| dir.join(name))
        .chain(installed.iter().map(|p| PathBuf::from(expand(p))))
        .find(|p| p.is_file())
}

fn expand(path: &str) -> String {
    ["ProgramFiles", "LOCALAPPDATA", "USERPROFILE"].iter().fold(path.to_string(), |p, var| {
        p.replace(&format!("%{var}%"), &std::env::var(var).unwrap_or_default())
    })
}

static GIT: LazyLock<Option<PathBuf>> =
    LazyLock::new(|| find_program("git.exe", &["%ProgramFiles%\\Git\\cmd\\git.exe"]));

static GH: LazyLock<Option<PathBuf>> = LazyLock::new(|| {
    find_program("gh.exe", &[
        "%ProgramFiles%\\GitHub CLI\\gh.exe",
        "%LOCALAPPDATA%\\Microsoft\\WinGet\\Links\\gh.exe",
        "%USERPROFILE%\\scoop\\shims\\gh.exe",
    ])
});

pub fn gh_installed() -> bool {
    GH.is_some()
}

fn git(dir: &str, arguments: &[&str]) -> Option<String> {
    run(GIT.as_ref()?, &[&["-C", dir], arguments].concat(), Duration::from_secs(5))
}

/// One file per working directory, touched when a session starts or you send a prompt there.
pub fn project_file(cwd: &str) -> PathBuf {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325; // FNV-1a
    for byte in cwd.bytes() {
        hash = (hash ^ byte as u64).wrapping_mul(0x100_0000_01b3);
    }
    PATHS.projects.join(format!("{hash:x}"))
}

#[derive(Clone)]
pub struct Repo {
    pub root: String, // the main checkout, shared by its worktrees
    pub name: String,
    pub slug: Option<String>, // owner/name on GitHub
}

/// owner/name from a GitHub remote URL, over HTTPS or SSH.
pub fn github_slug(remote: &str) -> Option<String> {
    let rest = &remote[remote.find("github.com")? + "github.com".len()..];
    let rest = rest.strip_prefix([':', '/'])?;
    let (owner, name) = rest.split_once('/')?;
    let name = name.strip_suffix(".git").unwrap_or(name);
    (!owner.is_empty() && !name.is_empty() && !name.contains('/')).then(|| format!("{owner}/{name}"))
}

/// The most recently used git repos, newest first.
pub fn recent_repos(limit: usize) -> Vec<Repo> {
    let mut files = list_dir(&PATHS.projects);
    files.sort_by(|a, b| modified(b).unwrap_or(0.0).total_cmp(&modified(a).unwrap_or(0.0)));
    let mut repos: Vec<Repo> = Vec::new();
    for file in files {
        if repos.len() >= limit {
            break;
        }
        let fresh = age(&file).is_some_and(|age| age < 30.0 * 24.0 * 3600.0);
        let Some(cwd) = read_text(&file).filter(|cwd| fresh && Path::new(cwd).exists()) else {
            remove(&file);
            continue;
        };
        let Some(common) = git(&cwd, &["rev-parse", "--path-format=absolute", "--git-common-dir"]) else {
            continue;
        };
        let common_path = Path::new(&common);
        let root = match common_path.parent() {
            Some(parent) if common_path.file_name().is_some_and(|n| n == ".git") => {
                parent.to_string_lossy().into_owned()
            }
            _ => common.clone(),
        };
        if repos.iter().any(|repo| repo.root == root) {
            continue;
        }
        let slug = git(&cwd, &["remote", "get-url", "origin"]).and_then(|remote| github_slug(&remote));
        let name = match &slug {
            Some(slug) => slug.rsplit('/').next().unwrap_or(slug).to_string(),
            None => Path::new(&root).file_name().map_or(root.clone(), |n| n.to_string_lossy().into_owned()),
        };
        repos.push(Repo { root, name, slug });
    }
    repos
}

/// The latest commit's GitHub Actions runs, together: failed if any failed, else running if any
/// hasn't finished, else ok. None if gh couldn't say (offline, signed out, not installed).
fn ci_state(slug: &str) -> Option<u64> {
    let arguments = ["run", "list", "-R", slug, "-L", "20", "--json", "headSha,status,conclusion"];
    let out = run(GH.as_ref()?, &arguments, Duration::from_secs(20))?;
    let Value::Array(runs) = serde_json::from_str(&out).ok()? else { return None };
    let Some(head) = runs.first().and_then(|run| run["headSha"].as_str()) else { return Some(0) };
    let latest: Vec<&Value> = runs.iter().filter(|run| run["headSha"].as_str() == Some(head)).collect();
    let conclusions: Vec<&str> = latest.iter().filter_map(|run| run["conclusion"].as_str()).collect();
    if conclusions.iter().any(|c| ["failure", "timed_out", "startup_failure"].contains(c)) {
        return Some(2);
    }
    if latest.iter().any(|run| run["status"].as_str() != Some("completed")) {
        return Some(3);
    }
    if conclusions.iter().any(|c| ["success", "neutral", "skipped"].contains(c)) {
        return Some(1);
    }
    Some(0)
}

/// Keep each repo on the row it had, so the same repos in a new order don't resend every row. A
/// repo that's new to the list takes the row of one that dropped out.
pub fn stable_order(repos: &[Repo], previous: &[String]) -> Vec<Repo> {
    let mut rows: Vec<Option<Repo>> =
        previous.iter().map(|root| repos.iter().find(|repo| &repo.root == root).cloned()).collect();
    let mut newcomers: VecDeque<Repo> =
        repos.iter().filter(|repo| !previous.contains(&repo.root)).cloned().collect();
    for row in rows.iter_mut().filter(|row| row.is_none()) {
        *row = newcomers.pop_front();
    }
    rows.into_iter().flatten().chain(newcomers).collect()
}

/// Repo rows from ci.json, polled again when they're due or the recent repos changed.
pub fn repo_rows(poll: bool) -> Vec<Json> {
    let cache = read_json(&PATHS.ci);
    let cached: Vec<Json> = cache
        .get("rows")
        .and_then(Value::as_array)
        .map(|rows| rows.iter().filter_map(|row| row.as_object().cloned()).collect())
        .unwrap_or_default();
    if !poll {
        return cached;
    }
    let roots: Vec<String> =
        cached.iter().filter_map(|row| row.get("root")?.as_str().map(String::from)).collect();
    let repos = stable_order(&recent_repos(3), &roots);
    let same_repos = repos.iter().map(|repo| &repo.root).eq(roots.iter());
    if same_repos && cache.get("next").and_then(Value::as_f64).is_some_and(|next| now() < next) {
        return cached;
    }
    let rows: Vec<Json> = repos
        .iter()
        .map(|repo| {
            let previous = cached
                .iter()
                .find(|row| row.get("root").and_then(Value::as_str) == Some(&repo.root))
                .and_then(|row| row.get("ci")?.as_u64())
                .unwrap_or(0);
            let ci = repo.slug.as_deref().and_then(ci_state).unwrap_or(previous);
            let Value::Object(row) = json!({ "root": repo.root, "name": repo.name, "ci": ci }) else {
                unreachable!()
            };
            row
        })
        .collect();
    let running = rows.iter().any(|row| row.get("ci").and_then(Value::as_u64) == Some(3));
    let next = now() + if running { CI_POLL_WHILE_RUNNING } else { CI_POLL_AFTER };
    let Value::Object(cache) = json!({ "rows": rows, "next": next }) else { unreachable!() };
    write_json(&PATHS.ci, &cache);
    rows
}

pub fn ci_due() -> bool {
    read_json(&PATHS.ci).get("next").and_then(Value::as_f64).is_none_or(|next| now() >= next)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo(root: &str) -> Repo {
        Repo { root: root.into(), name: root.into(), slug: None }
    }

    #[test]
    fn slugs_come_from_https_and_ssh_remotes() {
        assert_eq!(github_slug("https://github.com/kylephillipsau/zmk-config-sofle.git").as_deref(),
                   Some("kylephillipsau/zmk-config-sofle"));
        assert_eq!(github_slug("git@github.com:owner/repo").as_deref(), Some("owner/repo"));
        assert_eq!(github_slug("https://gitlab.com/owner/repo.git"), None);
        assert_eq!(github_slug("https://github.com/owner"), None);
    }

    #[test]
    fn repos_keep_their_rows() {
        let previous: Vec<String> = ["a", "b", "c"].map(String::from).to_vec();
        let order = |repos: &[Repo]| stable_order(repos, &previous).into_iter().map(|r| r.root).collect::<Vec<_>>();
        assert_eq!(order(&[repo("c"), repo("a"), repo("b")]), ["a", "b", "c"]);
        assert_eq!(order(&[repo("d"), repo("c"), repo("a")]), ["a", "d", "c"]);
        assert_eq!(order(&[repo("d")]), ["d"]);
    }
}

//! sofle-status for Windows: feeds the keyboard's left screen from this PC: Claude Code's status,
//! the time, Claude usage limits and CI for the repos you're working in. A port of
//! host/sofle-status.swift, the Mac side, sending the same reports.
//!
//! The Mac sends them in keyboard indicator lights macOS doesn't use. Windows won't let an app do
//! that: it keeps keyboards for itself and refuses an app's output reports to them. So the left half
//! also has a vendor-defined HID interface (zmk-raw-hid, in config/west.yml), and this tool writes
//! the same report bytes to it, up to 32 in each HID report. The firmware feeds them one at a time
//! to the decoder in boards/shields/nice_view_legend/widgets/host_link.c, which documents the
//! format:
//!
//!   Num Lock off   Scroll Lock and Compose are two flags: some session is working, or needs
//!                  you. Either lights the ✳ badge.
//!   Num Lock on    a frame, 2 bits per report: the clock, the usage limits, or one repo row.
//!                  The next report with Num Lock off ends it and carries the flags again.
//!
//! Sources:
//!   flags   Claude Code hooks; each session keeps its state in %LOCALAPPDATA%\sofle-status\sessions,
//!           so concurrent sessions add up instead of overwriting each other
//!   usage   Claude Code's status line input (rate_limits), cached in usage.json
//!   repos   the 3 git repos where you most recently started a session or sent a prompt, with
//!           the latest GitHub Actions runs from `gh run list`, cached in ci.json
//!   event   calendar.json, in the format the Mac's launch agent writes (nothing writes it on
//!           Windows yet, so the card shows the repos)
//!
//! Two binaries: `sofle-status` for hooks, the status line and commands (src/cli.rs), and
//! `sofle-status-agent`, which runs in the background from sign-in (src/daemon.rs).

pub mod cli;
pub mod daemon;
pub mod frames;
pub mod keyboard;
pub mod push;
pub mod repos;

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value};

pub type Json = Map<String, Value>;

// Session states older than this are treated as stale (a session that crashed or was killed).
pub const STALE_AFTER: f64 = 30.0 * 60.0;
pub const RESEND_AFTER: f64 = 30.0;
pub const CARDS_RESEND_AFTER: f64 = 30.0 * 60.0;
pub const CLOCK_RESEND_AFTER: f64 = 60.0 * 60.0;
// The keyboard shows the card only while frames keep coming (at least every 15 minutes), so if
// nothing else went out for this long, a clock frame does.
pub const KEEPALIVE_AFTER: f64 = 10.0 * 60.0;
// A usage percentage that changes on its own waits this long between sends; a new reset time or
// reaching 100% goes at once.
pub const USAGE_RESEND_AFTER: f64 = 3.0 * 60.0;
pub const CI_POLL_AFTER: f64 = 120.0;
pub const CI_POLL_WHILE_RUNNING: f64 = 45.0;

// Names shared by every sofle-status process in this sign-in session
pub const AGENT_MUTEX: &str = "Local\\sofle-status-agent";
pub const PUSH_EVENT: &str = "Local\\sofle-status-push-requested";
pub const PUSH_LOCK: &str = "Local\\sofle-status-pushing";
pub const SEND_LOCK: &str = "Local\\sofle-status-sending";

pub static PRODUCT: LazyLock<String> =
    LazyLock::new(|| std::env::var("SOFLE_PRODUCT").unwrap_or_else(|_| "Kyles Sofle".into()));
pub static CLOCK_24H: LazyLock<bool> =
    LazyLock::new(|| std::env::var("SOFLE_CLOCK_24H").is_ok_and(|v| v == "1"));

pub struct Paths {
    pub dir: PathBuf,
    pub sessions: PathBuf,
    pub projects: PathBuf,
    pub last_sent: PathBuf,
    pub paused: PathBuf,
    pub usage: PathBuf,
    pub ci: PathBuf,
    pub calendar: PathBuf,
    pub sent: PathBuf,
    pub log: PathBuf,
}

pub static PATHS: LazyLock<Paths> = LazyLock::new(|| {
    let dir = std::env::var_os("SOFLE_STATE_DIR") // for tests
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap_or_default()).join("sofle-status")
        });
    Paths {
        sessions: dir.join("sessions"),
        projects: dir.join("projects"),
        last_sent: dir.join("last-sent"),
        paused: dir.join("paused"),
        usage: dir.join("usage.json"),
        ci: dir.join("ci.json"),
        calendar: dir.join("calendar.json"),
        sent: dir.join("sent.json"),
        log: dir.join("sofle-status.log"),
        dir,
    }
});

/// Seconds since 1970, like the Mac's Date().timeIntervalSince1970.
pub fn now() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map_or(0.0, |d| d.as_secs_f64())
}

pub fn warn(message: &str) {
    eprintln!("sofle-status: {message}");
}

/// Writes to the agent's log, where everything that runs in the background reports.
pub fn log(message: &str) {
    let line = format!("{} {message}\n", chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%:z"));
    eprint!("{line}");
    let _ = fs::create_dir_all(&PATHS.dir);
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(&PATHS.log) {
        let _ = file.write_all(line.as_bytes());
    }
}

// State files

pub fn modified(path: &Path) -> Option<f64> {
    let time = fs::metadata(path).ok()?.modified().ok()?;
    Some(time.duration_since(UNIX_EPOCH).ok()?.as_secs_f64())
}

pub fn age(path: &Path) -> Option<f64> {
    modified(path).map(|at| now() - at)
}

pub fn read_text(path: &Path) -> Option<String> {
    fs::read_to_string(path).ok()
}

/// Replaces the file whole, so a reader never sees half of it. The temporary file goes in the
/// state folder rather than next to the file, so it never shows up as a session or a project.
pub fn write_bytes(path: &Path, bytes: &[u8]) {
    static COUNT: AtomicU32 = AtomicU32::new(0);
    let _ = fs::create_dir_all(&PATHS.dir);
    if let Some(dir) = path.parent() {
        let _ = fs::create_dir_all(dir);
    }
    let n = COUNT.fetch_add(1, Ordering::Relaxed);
    let temp = PATHS.dir.join(format!(".write-{}-{n}", std::process::id()));
    if fs::write(&temp, bytes).is_err() || fs::rename(&temp, path).is_err() {
        let _ = fs::remove_file(&temp);
    }
}

pub fn write_text(path: &Path, text: &str) {
    write_bytes(path, text.as_bytes());
}

pub fn read_json(path: &Path) -> Json {
    match fs::read(path).ok().and_then(|data| serde_json::from_slice(&data).ok()) {
        Some(Value::Object(object)) => object,
        _ => Json::new(),
    }
}

/// Keys come out sorted, so the same data always writes the same bytes.
pub fn write_json(path: &Path, object: &Json) {
    if let Ok(data) = serde_json::to_vec(object) {
        write_bytes(path, &data);
    }
}

pub fn remove(path: &Path) {
    let _ = fs::remove_file(path);
}

/// The files in a folder (none if it doesn't exist).
pub fn list_dir(dir: &Path) -> Vec<PathBuf> {
    fs::read_dir(dir)
        .map(|entries| {
            entries
                .filter_map(|entry| entry.ok())
                .filter(|entry| entry.file_type().is_ok_and(|t| t.is_file()))
                .map(|entry| entry.path())
                .collect()
        })
        .unwrap_or_default()
}

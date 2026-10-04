//! The flags, the cards, and when each goes out.

use std::cell::Cell;

use serde_json::{Value, json};
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::System::Threading::{EVENT_MODIFY_STATE, OpenEventW, SetEvent};

use crate::frames::{NEEDS_BIT, WORKING_BIT, clock_frame, event_card, frame_reports, repo_cards, usage_card};
use crate::keyboard::{NamedLock, Step, connection_ids, send, wide};
use crate::repos::{ci_due, project_file, repo_rows};
use crate::{
    CARDS_RESEND_AFTER, CLOCK_RESEND_AFTER, Json, KEEPALIVE_AFTER, PATHS, PUSH_EVENT, PUSH_LOCK,
    RESEND_AFTER, STALE_AFTER, age, list_dir, now, read_json, read_text, remove, write_bytes,
    write_json, write_text,
};

// Flags

/// Send the flags unless the same flags went out recently. Never waits: while a push is sending,
/// it ends every frame with the current flags, and sends them again when it finishes.
pub fn show(bits: u8) {
    if read_text(&PATHS.last_sent).is_some_and(|last| last == bits.to_string())
        && age(&PATHS.last_sent).is_some_and(|age| age < RESEND_AFTER)
    {
        return;
    }
    if send(&[Box::new(move || vec![bits])], false).is_some_and(|n| n > 0) {
        write_text(&PATHS.last_sent, &bits.to_string());
    }
}

/// Combine every live session into the two flags.
pub fn aggregate() -> u8 {
    let mut bits = 0;
    for file in list_dir(&PATHS.sessions) {
        let (Some(state), Some(age)) = (read_text(&file), age(&file)) else { continue };
        if age > 24.0 * 3600.0 {
            remove(&file);
            continue;
        }
        match state.as_str() {
            "working" if age < STALE_AFTER => bits |= WORKING_BIT,
            "needs" if age < STALE_AFTER => bits |= NEEDS_BIT,
            _ => {}
        }
    }
    bits
}

pub fn paused() -> bool {
    PATHS.paused.exists()
}

/// The flags the keyboard should rest on after a frame.
pub fn current_flags() -> u8 {
    if paused() {
        return read_text(&PATHS.last_sent).and_then(|bits| bits.parse().ok()).unwrap_or(0);
    }
    aggregate()
}

// Frames

/// The current flags, then each frame and the current flags to end it. The flags last sent are
/// written to last_sent. Windows sends the keyboard its own lights whenever they change, and with
/// Num Lock on, the keyboard takes that for the start of a frame, so the flags go first to end it.
pub fn frame_steps<'a>(frames: Vec<&'a dyn Fn() -> Vec<u8>>, last_sent: &'a Cell<u8>) -> Vec<Step<'a>> {
    let mut steps: Vec<Step<'a>> = vec![Box::new(|| vec![current_flags()])];
    for frame in frames {
        steps.push(Box::new(move || frame_reports(&frame())));
        steps.push(Box::new(move || {
            let flags = current_flags();
            last_sent.set(flags);
            vec![flags]
        }));
    }
    steps
}

/// Send the cards that changed, or all of them if forced or the keyboard reconnected. A clock
/// frame goes first when the keyboard reconnected or the last sync is old.
fn push_once(force: bool, clock: bool) {
    let connection = connection_ids();
    if connection.is_empty() {
        return;
    }
    let rows = repo_rows(true);
    let mut sent = read_json(&PATHS.sent);
    let reconnected = sent.get("connection").and_then(Value::as_str) != Some(&connection);
    let at = now();
    let cards: Vec<_> = [usage_card()].into_iter().chain(repo_cards(&rows)).chain([event_card()]).collect();
    let due: Vec<_> = cards
        .iter()
        .filter(|card| {
            let last = sent.get(&card.key).and_then(Value::as_object);
            let field = |key: &str| last.and_then(|last| last.get(key));
            let age = at - field("at").and_then(Value::as_f64).unwrap_or(0.0);
            if force || reconnected || age > CARDS_RESEND_AFTER {
                return true;
            }
            if field("content").and_then(Value::as_str) == Some(&card.content) {
                return false;
            }
            card.urgent.is_none()
                || field("urgent").and_then(Value::as_str) != card.urgent.as_deref()
                || age > card.min_interval
        })
        .collect();
    let since = |key: &str| at - sent.get(key).and_then(Value::as_f64).unwrap_or(0.0);
    let clock_due = clock
        || reconnected
        || since("clock") > CLOCK_RESEND_AFTER
        || (due.is_empty() && since("last") > KEEPALIVE_AFTER);
    if !clock_due && due.is_empty() {
        return;
    }
    let mut frames: Vec<&dyn Fn() -> Vec<u8>> = Vec::new();
    if clock_due {
        frames.push(&clock_frame);
    }
    frames.extend(due.iter().map(|card| &*card.frame));
    let flags = Cell::new(0);
    if !send(&frame_steps(frames, &flags), true).is_some_and(|n| n > 0) {
        return;
    }
    write_text(&PATHS.last_sent, &flags.get().to_string());
    sent.insert("connection".into(), connection.into());
    sent.insert("last".into(), at.into());
    if clock_due {
        sent.insert("clock".into(), at.into());
    }
    for card in due {
        let urgent = card.urgent.clone().unwrap_or_default();
        sent.insert(card.key.clone(), json!({ "content": card.content, "urgent": urgent, "at": at }));
    }
    write_json(&PATHS.sent, &sent);
}

/// One push at a time. The agent pushes when the keyboard connects; hooks and the status line ask
/// it to with request_push.
pub fn push(force: bool, clock: bool) {
    let Some(_lock) = NamedLock::acquire(PUSH_LOCK, true) else { return };
    push_once(force, clock);
    // in case a hook changed the flags after the last frame went out
    if !paused() {
        show(aggregate());
    }
}

/// Ask the agent to push, so hooks and the status line return at once. False if it isn't running.
pub fn request_push() -> bool {
    let name = wide(PUSH_EVENT);
    // SAFETY: name is NUL-terminated
    let event = unsafe { OpenEventW(EVENT_MODIFY_STATE, 0, name.as_ptr()) };
    if event.is_null() {
        return false;
    }
    unsafe {
        SetEvent(event);
        CloseHandle(event);
    }
    true
}

// Claude Code

/// Record a Claude Code hook event (JSON on stdin) as its session's state. Returns whether the
/// cards may need sending: a new repo, or CI is due for another look.
pub fn record_hook_event(input: &[u8]) -> bool {
    let Ok(Value::Object(event)) = serde_json::from_slice::<Value>(input) else { return false };
    let text = |key: &str| event.get(key).and_then(Value::as_str);
    let (Some(name), Some(session)) = (text("hook_event_name"), text("session_id")) else { return false };
    if session.is_empty() || !session.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return false;
    }
    let file = PATHS.sessions.join(session);
    let mut new_project = false;
    if matches!(name, "SessionStart" | "UserPromptSubmit")
        && let Some(cwd) = text("cwd")
    {
        new_project = !project_file(cwd).exists();
        write_text(&project_file(cwd), cwd);
    }
    match name {
        "SessionStart" | "Stop" | "StopFailure" => write_text(&file, "idle"),
        "SessionEnd" => remove(&file),
        // PostToolUse also clears "needs" once a permission is approved
        "UserPromptSubmit" | "PostToolUse" => write_text(&file, "working"),
        "PermissionRequest" => write_text(&file, "needs"),
        "Notification" if text("notification_type") == Some("permission_prompt") => write_text(&file, "needs"),
        _ => {}
    }
    new_project || ci_due()
}

/// Claude Code passes rate_limits to the status line command: used_percentage and resets_at
/// (Unix seconds) for the five_hour and seven_day windows. Returns whether the cache changed.
pub fn record_usage(input: &[u8]) -> bool {
    let Ok(Value::Object(status)) = serde_json::from_slice::<Value>(input) else { return false };
    let Some(limits) = status.get("rate_limits").and_then(Value::as_object) else { return false };
    let mut usage = Json::new();
    for window in ["five_hour", "seven_day"] {
        let Some(limit) = limits.get(window).and_then(Value::as_object) else { continue };
        let mut entry = Json::new();
        if let Some(pct) = limit.get("used_percentage").and_then(Value::as_f64) {
            entry.insert("pct".into(), (pct.round() as i64).into());
        }
        if let Some(reset) = limit.get("resets_at").and_then(Value::as_f64) {
            entry.insert("resets_at".into(), (reset as i64).into());
        }
        usage.insert(window.into(), entry.into());
    }
    let Ok(new) = serde_json::to_vec(&usage) else { return false };
    if usage.is_empty() || std::fs::read(&PATHS.usage).is_ok_and(|old| old == new) {
        return false;
    }
    write_bytes(&PATHS.usage, &new);
    true
}

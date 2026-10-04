//! The commands, as on the Mac:
//!
//!   sofle-status hook                      read a Claude Code hook event on stdin (used by hooks)
//!   sofle-status statusline                read Claude Code's status line input (prints nothing)
//!   sofle-status push                      send the cards if they changed
//!   sofle-status cards                     show the cards, then send them all
//!   sofle-status time                      sync the keyboard's clock now
//!   sofle-status daemon                    run the agent here instead of in the background
//!   sofle-status pause | resume            stop or restart hook updates of the flags
//!   sofle-status idle|working|needs        show flags by hand (also pauses hooks)
//!   sofle-status status                    show each session's state, the combined flags and
//!                                          whether the agent is running
//!   sofle-status encode [--raw]            print the reports `cards` would send, in hex, one per
//!                                          line, or with --raw as the HID reports that carry them
//!   sofle-status list | report <hex>       show matching keyboards / send one report byte

use std::cell::Cell;
use std::io::Read;

use serde_json::Value;

use crate::frames::{EVENT_LEAD, clock_frame, event_card, event_title, local, repo_cards, reset_label, time_label, usage_card};
use crate::frames::{NEEDS_BIT, WORKING_BIT};
use crate::keyboard::{RAW_REPORT_SIZE, keyboards, pad, send};
use crate::push::{aggregate, frame_steps, paused, push, record_hook_event, record_usage, request_push, show};
use crate::repos::{gh_installed, repo_rows};
use crate::{Json, PATHS, PRODUCT, age, daemon, list_dir, read_json, read_text, remove, write_text};

const USAGE: &str = "usage: sofle-status hook | statusline | push | cards | time | daemon | pause | resume | status | idle|working|needs | encode [--raw] | list | report <hex>";

/// Returns the exit code: 0 even when the keyboard is asleep or disconnected, so a Claude Code hook
/// never fails.
pub fn run(args: &[String]) -> i32 {
    match args.first().map(String::as_str) {
        Some("hook") => {
            let push_due = record_hook_event(&stdin());
            if !paused() {
                show(aggregate());
            }
            if push_due {
                request_push();
            }
        }
        Some("statusline") => {
            if record_usage(&stdin()) {
                request_push();
            }
        }
        Some("push") => push(false, false),
        Some("cards") => {
            describe_cards(&repo_rows(true));
            push(true, false);
        }
        Some("encode") => encode(args.get(1).is_some_and(|arg| arg == "--raw")),
        Some("time") => {
            let flags = Cell::new(0);
            let n = send(&frame_steps(vec![&clock_frame], &flags), true).unwrap_or(0);
            if n > 0 {
                write_text(&PATHS.last_sent, &flags.get().to_string());
            }
            println!("clock synced on {n} keyboard interface(s)");
        }
        Some("daemon") => daemon::run(),
        Some("pause") => {
            write_text(&PATHS.paused, "");
            println!("hooks paused; 'sofle-status resume' restarts them");
        }
        Some("resume") => {
            remove(&PATHS.paused);
            remove(&PATHS.last_sent);
            show(aggregate());
            println!("hooks resumed");
        }
        Some(name @ ("idle" | "working" | "needs")) => {
            write_text(&PATHS.paused, "");
            remove(&PATHS.last_sent);
            show(match name {
                "working" => WORKING_BIT,
                "needs" => NEEDS_BIT,
                _ => 0,
            });
        }
        Some("status") => status(),
        Some("list") => {
            let found = keyboards();
            if found.is_empty() {
                println!("No \"{}\" keyboard connected with a raw HID interface", *PRODUCT);
            }
            for keyboard in found {
                println!("{} via {}  ({})", *PRODUCT, keyboard.transport, keyboard.instance_id);
            }
        }
        Some("report") => {
            let bits = u8::from_str_radix(args.get(1).map_or("0", String::as_str), 16).unwrap_or(0);
            let n = send(&[Box::new(move || vec![bits])], true).unwrap_or(0);
            println!("sent 0x{bits:x} to {n} keyboard interface(s)");
        }
        _ => {
            eprintln!("{USAGE}");
            return 2;
        }
    }
    0
}

fn stdin() -> Vec<u8> {
    let mut input = Vec::new();
    let _ = std::io::stdin().read_to_end(&mut input);
    input
}

fn encode(raw: bool) {
    let (usage, repos, event) = (usage_card(), repo_cards(&repo_rows(false)), event_card());
    let mut frames: Vec<&dyn Fn() -> Vec<u8>> = vec![&clock_frame, &*usage.frame];
    frames.extend(repos.iter().map(|card| &*card.frame));
    frames.push(&*event.frame);
    let flags = Cell::new(0);
    let reports: Vec<u8> = frame_steps(frames, &flags).iter().flat_map(|step| step()).collect();
    if raw {
        for chunk in reports.chunks(RAW_REPORT_SIZE) {
            let bytes: Vec<String> = pad(chunk, RAW_REPORT_SIZE).iter().map(|b| format!("{b:02x}")).collect();
            println!("{}", bytes.join(" "));
        }
    } else {
        for report in reports {
            println!("{report:02x}");
        }
    }
}

fn status() {
    let mut files = list_dir(&PATHS.sessions);
    files.sort();
    for file in files {
        let state = read_text(&file).unwrap_or_else(|| "?".into());
        let seconds = age(&file).map_or(-1, |age| age as i64);
        let name = file.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        println!("{}  {state}  {seconds}s ago", name.get(..8).unwrap_or(&name));
    }
    let bits = aggregate();
    let names: Vec<&str> = [(WORKING_BIT, "working"), (NEEDS_BIT, "needs")]
        .into_iter()
        .filter(|(bit, _)| bits & bit != 0)
        .map(|(_, name)| name)
        .collect();
    let flags = if names.is_empty() { "none".to_string() } else { names.join(" + ") };
    println!("flags: {flags}{}", if paused() { "  (hooks paused)" } else { "" });
    println!("agent: {}", if daemon::running() { "running" } else { "not running (start sofle-status-agent)" });
}

fn describe_cards(rows: &[Json]) {
    let usage = read_json(&PATHS.usage);
    for (label, window) in [("5H", "five_hour"), ("WK", "seven_day")] {
        let entry = usage.get(window).and_then(Value::as_object);
        let field = |key: &str| entry.and_then(|e| e.get(key)).and_then(Value::as_i64);
        let pct = field("pct").map_or("--".to_string(), |pct| format!("{pct}%"));
        let reset = field("resets_at").map_or("--".to_string(), |r| reset_label(local(r as f64), window == "seven_day"));
        println!("{label}  {pct}  resets {reset}");
    }
    let states = ["-", "ok", "FAIL", "running"];
    for row in rows {
        let text = |key: &str| row.get(key).and_then(Value::as_str).unwrap_or("?");
        let ci = row.get("ci").and_then(Value::as_u64).unwrap_or(0).min(3) as usize;
        println!("{}  {}  ({})", text("name"), states[ci], text("root"));
    }
    if rows.is_empty() {
        println!("no repos yet: they appear after a Claude Code session starts or gets a prompt in one");
    }
    if !gh_installed() {
        println!("no CI: gh isn't installed (winget install GitHub.cli, then gh auth login)");
    }
    let event = read_json(&PATHS.calendar);
    match event.get("start").and_then(Value::as_f64) {
        Some(start) => println!(
            "next event: {} at {}, shows from {}",
            event_title(event.get("title").and_then(Value::as_str).unwrap_or("")),
            time_label(local(start)),
            time_label(local(start - EVENT_LEAD as f64 * 60.0)),
        ),
        None if PATHS.calendar.exists() => println!("next event: none in the next 24 hours"),
        None => println!("next event: no calendar on Windows yet"),
    }
}

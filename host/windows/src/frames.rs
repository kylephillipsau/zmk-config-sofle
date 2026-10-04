//! Frames and the cards they carry, byte for byte what sofle-status.swift sends, except that the
//! Mac also carries its Caps Lock state in every report (a light report replaces every light at
//! once) and a raw HID report doesn't touch the lights.

use chrono::{DateTime, Local, TimeZone, Timelike};
use serde_json::Value;
use unicode_normalization::UnicodeNormalization;
use unicode_normalization::char::is_combining_mark;

use crate::{CLOCK_24H, Json, PATHS, USAGE_RESEND_AFTER, now, read_json};

// Report bits (HID LED usage minus one)
pub const NUM_BIT: u8 = 1 << 0; // marks a frame report
pub const WORKING_BIT: u8 = 1 << 2; // Scroll Lock
pub const NEEDS_BIT: u8 = 1 << 3; // Compose
pub const KANA_BIT: u8 = 1 << 4; // alternates in frame reports

pub const FRAME_CLOCK: u8 = 1;
pub const FRAME_USAGE: u8 = 2;
pub const FRAME_REPO: u8 = 3;
pub const FRAME_EVENT: u8 = 4;
const USAGE_LABEL_LENGTH: usize = 5;
const REPO_NAME_LENGTH: usize = 12;
const EVENT_LABEL_LENGTH: usize = 5;
const EVENT_TITLE_LENGTH: usize = 24;
pub const EVENT_LEAD: u8 = 30; // minutes before an event starts that it takes over the repo rows
const EVENT_SHOW_AFTER_START: i64 = 15; // minutes after it starts that it keeps them, at most

// Over Bluetooth the keyboard can take a few hundred ms to pick up a report (ZMK lets it skip
// radio events while idle), so a frame's times count from its first report, which arrives within
// about this long.
const FIRST_REPORT_LEAD: f64 = 0.2;

pub fn crc8(bytes: &[u8]) -> u8 {
    let mut crc = 0u8;
    for &byte in bytes {
        crc ^= byte;
        for _ in 0..8 {
            crc = if crc & 0x80 != 0 { (crc << 1) ^ 0x07 } else { crc << 1 };
        }
    }
    crc
}

/// A frame's reports: Num Lock on, 2 bits each in Scroll Lock and Compose, Kana alternating.
pub fn frame_reports(body: &[u8]) -> Vec<u8> {
    let mut reports = Vec::with_capacity((body.len() + 1) * 4);
    for byte in body.iter().copied().chain([crc8(body)]) {
        for shift in [6, 4, 2, 0] {
            let chunk = (byte >> shift) & 3;
            let mut report = NUM_BIT;
            if chunk & 2 != 0 {
                report |= WORKING_BIT;
            }
            if chunk & 1 != 0 {
                report |= NEEDS_BIT;
            }
            if reports.len() & 1 != 0 {
                report |= KANA_BIT;
            }
            reports.push(report);
        }
    }
    reports
}

/// Uppercase printable ASCII, cut or padded with NULs to length.
pub fn text(s: &str, length: usize) -> Vec<u8> {
    let mut bytes: Vec<u8> =
        s.to_uppercase().chars().filter(|c| (' '..='~').contains(c)).map(|c| c as u8).collect();
    bytes.resize(length, 0);
    bytes
}

pub fn local(seconds: f64) -> DateTime<Local> {
    Local.timestamp_opt(seconds.floor() as i64, 0).earliest().unwrap_or_else(Local::now)
}

/// The time when the frame's first report reaches the keyboard, which is when the keyboard takes it.
pub fn clock_frame() -> Vec<u8> {
    let at = local(now() + FIRST_REPORT_LEAD);
    let bits = (at.hour() * 60 + at.minute()) << 6 | at.second();
    vec![FRAME_CLOCK, (bits >> 16) as u8, (bits >> 8) as u8, bits as u8]
}

pub fn time_label(at: DateTime<Local>) -> String {
    let hour = match at.hour() {
        h if *CLOCK_24H => h,
        h if h % 12 == 0 => 12,
        h => h % 12,
    };
    format!("{hour}:{:02}", at.minute())
}

/// The 5 hour limit resets within the day, so it shows a time. The weekly one shows a weekday
/// until the day it resets.
pub fn reset_label(reset: DateTime<Local>, weekly: bool) -> String {
    if !weekly || reset.date_naive() == Local::now().date_naive() {
        return time_label(reset);
    }
    reset.format("%a").to_string().to_uppercase()
}

pub struct Card {
    pub key: String,            // what this card is: usage, repo0..2, event
    pub content: String,        // changes when what it shows changes
    pub urgent: Option<String>, // the part of content that can't wait for min_interval
    pub min_interval: f64,      // between sends of changes outside urgent
    pub frame: Box<dyn Fn() -> Vec<u8>>,
}

impl Card {
    fn new(key: &str, content: String, frame: impl Fn() -> Vec<u8> + 'static) -> Card {
        Card { key: key.into(), content, urgent: None, min_interval: 0.0, frame: Box::new(frame) }
    }
}

// Usage

struct UsageRow {
    pct: u8,
    reset: Option<i64>,
    label: String,
}

pub fn usage_card() -> Card {
    let usage = read_json(&PATHS.usage);
    let (mut content, mut urgent, mut rows) = (vec![], vec![], vec![]);
    for (i, window) in ["five_hour", "seven_day"].into_iter().enumerate() {
        let entry = usage.get(window).and_then(Value::as_object);
        let field = |key: &str| entry.and_then(|e| e.get(key)).and_then(Value::as_i64);
        let mut pct = field("pct").map_or(0xff, |p| p.clamp(0, 100) as u8);
        let mut reset = field("resets_at");
        if reset.is_some_and(|r| r as f64 <= now()) {
            pct = 0; // the window reset since Claude Code last said
            reset = None;
        }
        let label = reset.map(|r| reset_label(local(r as f64), i == 1)).unwrap_or_default();
        content.push(format!("{pct} {} {label}", reset.unwrap_or(0)));
        urgent.push(format!("{} {} {label}", pct >= 100, reset.unwrap_or(0)));
        rows.push(UsageRow { pct, reset, label });
    }
    Card {
        urgent: Some(urgent.join(" | ")),
        min_interval: USAGE_RESEND_AFTER,
        ..Card::new("usage", content.join(" | "), move || {
            let mut body = vec![FRAME_USAGE];
            for row in &rows {
                // minutes until the reset, counted from when the frame's first report arrives
                let minutes = row.reset.map_or(0xffff, |r| {
                    ((r as f64 - now() - FIRST_REPORT_LEAD) / 60.0).ceil().clamp(0.0, 65534.0) as u16
                });
                body.extend([row.pct, (minutes >> 8) as u8, minutes as u8]);
            }
            for row in &rows {
                body.extend(text(&row.label, USAGE_LABEL_LENGTH));
            }
            body
        })
    }
}

// Repos

pub fn repo_cards(rows: &[Json]) -> Vec<Card> {
    (0..3u8)
        .map(|i| {
            let row = rows.get(i as usize);
            let name = row.and_then(|r| r.get("name")).and_then(Value::as_str).unwrap_or("").to_string();
            let ci = row.and_then(|r| r.get("ci")).and_then(Value::as_u64).unwrap_or(0) as u8;
            Card::new(&format!("repo{i}"), format!("{name} {ci}"), move || {
                [vec![FRAME_REPO, i, ci], text(&name, REPO_NAME_LENGTH)].concat()
            })
        })
        .collect()
}

// Calendar

/// Uppercase ASCII with single spaces, at most EVENT_TITLE_LENGTH characters, cut at a word if it can.
pub fn event_title(title: &str) -> String {
    let folded: String = title.nfkd().filter(|&c| !is_combining_mark(c)).collect::<String>().to_uppercase();
    let ascii: String = folded
        .chars()
        .filter_map(|c| match c {
            c if c.is_whitespace() => Some(' '),
            '!'..='~' => Some(c),
            _ => None,
        })
        .collect();
    let words = ascii.split_whitespace().collect::<Vec<_>>().join(" ");
    if words.len() <= EVENT_TITLE_LENGTH {
        return words;
    }
    let cut = &words[..EVENT_TITLE_LENGTH];
    match cut.rfind(' ') {
        Some(space) if words.as_bytes()[EVENT_TITLE_LENGTH] != b' ' => cut[..space].to_string(),
        _ => cut.to_string(),
    }
}

pub fn event_card() -> Card {
    let entry = read_json(&PATHS.calendar);
    let title = event_title(entry.get("title").and_then(Value::as_str).unwrap_or(""));
    let start = entry.get("start").and_then(Value::as_f64);
    let end = entry.get("end").and_then(Value::as_f64);
    let (Some(start), Some(end)) = (start, end) else { return no_event() };
    if title.is_empty() || end <= now() {
        return no_event();
    }
    let label = time_label(local(start));
    let show_after = EVENT_SHOW_AFTER_START.min((((end - start) / 60.0) as i64).max(1)) as u8;
    Card::new("event", format!("{title} {} {show_after} {label}", start as i64), move || {
        // seconds until it starts, counted from when the frame's first report arrives
        let seconds = (start - now() - FIRST_REPORT_LEAD).round().clamp(i32::MIN as f64, i32::MAX as f64) as i32;
        [
            vec![FRAME_EVENT],
            seconds.to_be_bytes().to_vec(),
            vec![EVENT_LEAD, show_after],
            text(&label, EVENT_LABEL_LENGTH),
            text(&title, EVENT_TITLE_LENGTH),
        ]
        .concat()
    })
}

fn no_event() -> Card {
    Card::new("event", "none".into(), || {
        [vec![FRAME_EVENT], vec![0; 6 + EVENT_LABEL_LENGTH + EVENT_TITLE_LENGTH]].concat()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc_of_a_frame_and_its_crc_is_zero() {
        let body = [FRAME_CLOCK, 0x12, 0x34, 0x56];
        assert_eq!(crc8(&[&body[..], &[crc8(&body)]].concat()), 0);
        assert_eq!(crc8(b"123456789"), 0xf4); // CRC-8 (polynomial 0x07) check value
    }

    #[test]
    fn frame_reports_carry_two_bits_each_with_kana_alternating() {
        let reports = frame_reports(&[0b11_01_00_10]);
        assert_eq!(reports.len(), 8); // the byte, then the CRC
        assert_eq!(reports[..4], [
            NUM_BIT | WORKING_BIT | NEEDS_BIT, // 11
            NUM_BIT | NEEDS_BIT | KANA_BIT,    // 01
            NUM_BIT,                           // 00
            NUM_BIT | WORKING_BIT | KANA_BIT,  // 10
        ]);
        assert!(reports.windows(2).all(|pair| pair[0] != pair[1]));
    }

    #[test]
    fn text_is_uppercase_ascii_padded_with_nuls() {
        assert_eq!(text("kyles-sofle ✓", 14), b"KYLES-SOFLE \0\0".to_vec());
        assert_eq!(text("a long repository name", 12), b"A LONG REPOS".to_vec());
    }

    #[test]
    fn event_titles_fold_accents_and_cut_at_a_word() {
        assert_eq!(event_title("  Café   standup\t– Q4 "), "CAFE STANDUP Q4");
        assert_eq!(event_title("Quarterly planning with the platform team"), "QUARTERLY PLANNING WITH");
        assert_eq!(event_title("Supercalifragilisticexpialidocious"), "SUPERCALIFRAGILISTICEXPI");
    }
}

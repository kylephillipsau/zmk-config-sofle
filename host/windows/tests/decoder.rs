//! Runs the keyboard's decoder (host/test_host_link.c and the firmware's host_link.c, built with
//! MSVC) on the HID reports `sofle-status encode --raw` prints, which are the ones it sends, and
//! checks that a dropped or flipped report only ever loses its frame.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

#[test]
fn keyboard_decodes_what_the_host_sends() {
    let Some(mut cl) = cc::windows_registry::find(std::env::consts::ARCH, "cl.exe") else {
        eprintln!("skipped: no MSVC compiler");
        return;
    };
    let host = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
    let widgets = host.parent().unwrap().join("boards/shields/nice_view_legend/widgets");
    let dir = PathBuf::from(env!("CARGO_TARGET_TMPDIR")).join("decoder");
    let state = dir.join("state");
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(state.join("sessions")).unwrap();

    let decoder = dir.join("test_host_link.exe");
    let built = cl
        .current_dir(&dir)
        .arg("/nologo")
        .arg(format!("/I{}", widgets.display()))
        .arg(host.join("test_host_link.c"))
        .arg(widgets.join("host_link.c"))
        .arg(format!("/Fe{}", decoder.display()))
        .output()
        .unwrap();
    assert!(built.status.success(), "cl failed:\n{}", String::from_utf8_lossy(&built.stdout));

    // a card with everything on it, and a session that's working
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
    let usage = format!(
        r#"{{"five_hour":{{"pct":42,"resets_at":{}}},"seven_day":{{"pct":100,"resets_at":{}}}}}"#,
        now + 3600,
        now + 3 * 86400
    );
    let ci = format!(
        r#"{{"next":{},"rows":[{{"root":"C:/a","name":"kyles-sofle","ci":1}},{{"root":"C:/b","name":"website","ci":2}},{{"root":"C:/c","name":"api","ci":3}}]}}"#,
        now + 86400
    );
    let calendar = format!(r#"{{"title":"Café standup – Q4","start":{},"end":{}}}"#, now + 600, now + 1800);
    fs::write(state.join("usage.json"), usage).unwrap();
    fs::write(state.join("ci.json"), ci).unwrap();
    fs::write(state.join("calendar.json"), calendar).unwrap();
    fs::write(state.join("sessions/test-session"), "working").unwrap();

    let encoded = Command::new(env!("CARGO_BIN_EXE_sofle-status"))
        .args(["encode", "--raw"])
        .env("SOFLE_STATE_DIR", &state)
        .output()
        .unwrap();
    assert!(encoded.status.success());
    let reports = String::from_utf8(encoded.stdout).unwrap();
    assert!(reports.lines().all(|line| line.split(' ').count() == 32), "not 32 bytes a report:\n{reports}");

    let mut decode = Command::new(&decoder)
        .arg("--damage")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    decode.stdin.take().unwrap().write_all(reports.as_bytes()).unwrap();
    let decoded = decode.wait_with_output().unwrap();
    let out = String::from_utf8_lossy(&decoded.stdout);
    assert!(decoded.status.success(), "the decoder garbled a damaged frame:\n{out}");
    let expected = [
        "flags   working".to_string(),
        "usage   5H  42%".to_string(),
        "usage   WK 100%".to_string(),
        format!("repo 0  {:<12} ok", "KYLES-SOFLE"),
        format!("repo 1  {:<12} FAIL", "WEBSITE"),
        format!("repo 2  {:<12} running", "API"),
        "\"CAFE STANDUP Q4\"".to_string(),
        " 0 garbled".to_string(),
    ];
    for line in expected {
        assert!(out.contains(&line), "no {line:?} in:\n{out}");
    }
}

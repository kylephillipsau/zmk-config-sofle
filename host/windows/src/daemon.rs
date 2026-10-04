//! The agent: pushes when the keyboard connects or reconnects (which includes waking from sleep,
//! coming back from another Bluetooth slot and being unplugged), when a hook or the status line
//! asks, and every minute.

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::ptr::null;
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{CloseHandle, ERROR_ALREADY_EXISTS, GetLastError, WAIT_OBJECT_0};
use windows_sys::Win32::System::Threading::{
    CreateEventW, CreateMutexW, OpenMutexW, SYNCHRONIZATION_SYNCHRONIZE, WaitForSingleObject,
};

use crate::keyboard::{keyboards, wide};
use crate::push::push;
use crate::{AGENT_MUTEX, PATHS, PUSH_EVENT, log};

// How often to look for the keyboard connecting. Windows can say when a device arrives, but a
// Bluetooth keyboard's devices can stay while it's away, with only their connection state
// changing.
const POLL: Duration = Duration::from_secs(2);

pub fn run() -> ! {
    let name = wide(AGENT_MUTEX);
    // SAFETY: name is NUL-terminated. The mutex is never released, so it marks this process as
    // the agent until it exits.
    let instance = unsafe { CreateMutexW(null(), 1, name.as_ptr()) };
    if instance.is_null() || unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
        log("sofle-status agent is already running");
        std::process::exit(0);
    }
    let name = wide(PUSH_EVENT);
    let requested = unsafe { CreateEventW(null(), 0, 0, name.as_ptr()) }; // resets when a wait returns
    rotate_log();
    log("sofle-status agent started");

    let mut connection = String::new();
    let mut last_tick = Instant::now();
    let mut ticks = 0u64;
    loop {
        let asked = unsafe { WaitForSingleObject(requested, POLL.as_millis() as u32) } == WAIT_OBJECT_0;
        let result = catch_unwind(AssertUnwindSafe(|| {
            let found = keyboards();
            let mut ids: Vec<&str> = found.iter().map(|k| k.connection.as_str()).collect();
            ids.sort();
            let ids = ids.join(",");
            if ids != connection {
                connection = ids;
                if found.is_empty() {
                    log("keyboard disconnected");
                } else {
                    let via: Vec<String> = found.iter().map(|k| k.transport.to_string()).collect();
                    log(&format!("keyboard connected via {}", via.join(" and ")));
                    // let the connection settle, as the Mac does
                    std::thread::sleep(Duration::from_secs(2));
                    push(true, true);
                    return;
                }
            }
            if asked {
                push(false, false);
            }
            if last_tick.elapsed() >= Duration::from_secs(60) {
                last_tick = Instant::now();
                ticks += 1;
                push(false, ticks.is_multiple_of(5));
            }
        }));
        if let Err(panic) = result {
            let message = panic
                .downcast_ref::<&str>()
                .map(|s| s.to_string())
                .or_else(|| panic.downcast_ref::<String>().cloned())
                .unwrap_or_default();
            log(&format!("agent error: {message}"));
        }
    }
}

pub fn running() -> bool {
    let name = wide(AGENT_MUTEX);
    // SAFETY: name is NUL-terminated
    let instance = unsafe { OpenMutexW(SYNCHRONIZATION_SYNCHRONIZE, 0, name.as_ptr()) };
    if instance.is_null() {
        return false;
    }
    unsafe { CloseHandle(instance) };
    true
}

/// Start a new log when the old one passes 1 MB, keeping the old one.
fn rotate_log() {
    if std::fs::metadata(&PATHS.log).is_ok_and(|m| m.len() > 1 << 20) {
        let _ = std::fs::rename(&PATHS.log, PATHS.log.with_extension("log.old"));
    }
}

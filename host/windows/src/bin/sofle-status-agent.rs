//! The agent, started at sign-in. A windowed program, so Windows doesn't give it a console window;
//! `sofle-status daemon` runs the same loop in a terminal.
#![windows_subsystem = "windows"]

fn main() {
    sofle_status::daemon::run()
}

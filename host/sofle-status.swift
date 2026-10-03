// sofle-status: show Claude Code's status on the keyboard's left screen.
//
// Three flags travel in keyboard indicator lights that macOS doesn't use, sent as a raw HID LED
// output report over USB or Bluetooth. The firmware reads them through ZMK's HID indicators
// (boards/shields/nice_view_legend/widgets/status.c):
//
//   Scroll Lock  some session is working          lights the ✳ badge
//   Compose      some session needs you           solid "CLAUDE / NEEDS YOU" banner
//   Kana         a session finished since your    outlined "CLAUDE / DONE" banner
//                last prompt in any session
//
// Each Claude Code session keeps its own state in ~/.cache/sofle-status/sessions, so concurrent
// sessions add up instead of overwriting each other.
//
//   sofle-status hook                      read a Claude Code hook event on stdin (used by hooks)
//   sofle-status pause | resume            stop or restart hook updates (for testing)
//   sofle-status idle|working|needs|done   show a state by hand (also pauses hooks)
//   sofle-status status                    show each session's state and the combined flags
//   sofle-status list | report <hex>       show matching keyboards / send a raw LED byte
//
// Build: host/install.sh

import CoreGraphics
import Foundation
import IOKit.hid

let productName = ProcessInfo.processInfo.environment["SOFLE_PRODUCT"] ?? "Kyles Sofle"

// LED output report bits (HID LED usage minus one)
let capsBit: UInt8 = 1 << 1
let workingBit: UInt8 = 1 << 2  // Scroll Lock
let needsBit: UInt8 = 1 << 3    // Compose
let doneBit: UInt8 = 1 << 4     // Kana

let manualStates: [String: UInt8] = ["idle": 0, "working": workingBit, "needs": needsBit, "done": doneBit]

// Session states older than this are treated as stale (a session that crashed or was killed).
let staleAfter: TimeInterval = 30 * 60
let resendAfter: TimeInterval = 30

let fm = FileManager.default
let stateDir = fm.homeDirectoryForCurrentUser.appendingPathComponent(".cache/sofle-status")
let sessionsDir = stateDir.appendingPathComponent("sessions")
let lastPromptFile = stateDir.appendingPathComponent("last-prompt")
let lastSentFile = stateDir.appendingPathComponent("last-sent")
let pausedFile = stateDir.appendingPathComponent("paused")

func warn(_ message: String) {
    FileHandle.standardError.write("sofle-status: \(message)\n".data(using: .utf8)!)
}

// MARK: Keyboard

func prop(_ device: IOHIDDevice, _ key: String) -> String {
    return IOHIDDeviceGetProperty(device, key as CFString).map { "\($0)" } ?? "?"
}

// Every keyboard interface with the keyboard's product name: Bluetooth and, if plugged in, USB.
// Filtered by hand because the Mac's own keyboard has the same LED elements and must be left alone.
func keyboards() -> [IOHIDDevice] {
    let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
    IOHIDManagerSetDeviceMatching(manager, [kIOHIDProductKey: productName] as CFDictionary)
    IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone))
    let devices = IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice> ?? []
    return devices.filter {
        prop($0, kIOHIDProductKey) == productName
            && prop($0, kIOHIDPrimaryUsagePageKey) == "1" && prop($0, kIOHIDPrimaryUsageKey) == "6"
    }
}

// Send one LED output report (report ID 1 is ZMK's keyboard report) to each keyboard interface.
@discardableResult
func sendLEDs(_ bits: UInt8) -> Int {
    var sent = 0
    for device in keyboards() {
        let opened = IOHIDDeviceOpen(device, IOOptionBits(kIOHIDOptionsTypeNone))
        guard opened == kIOReturnSuccess else {
            warn("can't open \(prop(device, kIOHIDTransportKey)) (0x\(String(UInt32(bitPattern: opened), radix: 16)))")
            continue
        }
        defer { IOHIDDeviceClose(device, IOOptionBits(kIOHIDOptionsTypeNone)) }
        let report: [UInt8] = [0x01, bits]
        let result = report.withUnsafeBufferPointer {
            IOHIDDeviceSetReport(device, kIOHIDReportTypeOutput, 1, $0.baseAddress!, $0.count)
        }
        if result == kIOReturnSuccess {
            sent += 1
        } else {
            warn("\(prop(device, kIOHIDTransportKey)) report failed (0x\(String(UInt32(bitPattern: result), radix: 16)))")
        }
    }
    return sent
}

// The report replaces every light at once, so carry the Mac's real Caps Lock state along.
func withCaps(_ bits: UInt8) -> UInt8 {
    return CGEventSource.flagsState(.hidSystemState).contains(.maskAlphaShift) ? bits | capsBit : bits
}

// MARK: State files

func modified(_ url: URL) -> Date? {
    return (try? fm.attributesOfItem(atPath: url.path))?[.modificationDate] as? Date
}

func write(_ text: String, to url: URL) {
    try? fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try? text.write(to: url, atomically: true, encoding: .utf8)
}

// Send the flags unless the same flags went out recently.
func show(_ bits: UInt8) {
    if let last = try? String(contentsOf: lastSentFile, encoding: .utf8), last == String(bits),
       let at = modified(lastSentFile), Date().timeIntervalSince(at) < resendAfter {
        return
    }
    if sendLEDs(withCaps(bits)) > 0 { write(String(bits), to: lastSentFile) }
}

// Combine every live session into the three flags.
func aggregate() -> UInt8 {
    let lastPrompt = modified(lastPromptFile) ?? .distantPast
    let files = (try? fm.contentsOfDirectory(at: sessionsDir, includingPropertiesForKeys: nil)) ?? []
    var bits: UInt8 = 0
    for file in files {
        guard let state = try? String(contentsOf: file, encoding: .utf8), let at = modified(file) else { continue }
        let age = Date().timeIntervalSince(at)
        if age > 24 * 3600 { try? fm.removeItem(at: file); continue }
        switch state {
        case "working" where age < staleAfter: bits |= workingBit
        case "needs" where age < staleAfter: bits |= needsBit
        case "done" where at > lastPrompt: bits |= doneBit
        default: break
        }
    }
    return bits
}

// Record a Claude Code hook event (JSON on stdin) as its session's state.
func recordHookEvent() {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    guard let event = (try? JSONSerialization.jsonObject(with: input)) as? [String: Any],
          let name = event["hook_event_name"] as? String,
          let session = event["session_id"] as? String, !session.contains("/") else { return }
    let file = sessionsDir.appendingPathComponent(session)
    switch name {
    case "SessionStart":
        write("idle", to: file)
    case "SessionEnd":
        try? fm.removeItem(at: file)
    case "UserPromptSubmit":
        write("working", to: file)
        write("", to: lastPromptFile)  // clears "done" everywhere
    case "PostToolUse":  // also clears "needs" once a permission is approved
        write("working", to: file)
    case "PermissionRequest":
        write("needs", to: file)
    case "Notification" where event["notification_type"] as? String == "permission_prompt":
        write("needs", to: file)
    case "Stop", "StopFailure":
        write("done", to: file)
    default:
        return
    }
}

// MARK: Commands

// Earlier versions kept a single cache file at this path; it's a folder now.
var isDirectory: ObjCBool = false
if fm.fileExists(atPath: stateDir.path, isDirectory: &isDirectory), !isDirectory.boolValue {
    try? fm.removeItem(at: stateDir)
}

let args = Array(CommandLine.arguments.dropFirst())
switch args.first {
case "hook":
    recordHookEvent()
    if !fm.fileExists(atPath: pausedFile.path) { show(aggregate()) }
case "pause":
    write("", to: pausedFile)
    print("hooks paused; 'sofle-status resume' restarts them")
case "resume":
    try? fm.removeItem(at: pausedFile)
    try? fm.removeItem(at: lastSentFile)
    show(aggregate())
    print("hooks resumed")
case let name? where manualStates[name] != nil:
    write("", to: pausedFile)
    try? fm.removeItem(at: lastSentFile)
    show(manualStates[name]!)
case "status":
    let lastPrompt = modified(lastPromptFile)
    for file in ((try? fm.contentsOfDirectory(at: sessionsDir, includingPropertiesForKeys: nil)) ?? []).sorted(by: { $0.path < $1.path }) {
        let state = (try? String(contentsOf: file, encoding: .utf8)) ?? "?"
        let age = modified(file).map { Int(Date().timeIntervalSince($0)) } ?? -1
        print("\(file.lastPathComponent.prefix(8))  \(state)  \(age)s ago")
    }
    let bits = aggregate()
    let names = [(workingBit, "working"), (needsBit, "needs"), (doneBit, "done")].filter { bits & $0.0 != 0 }.map { $0.1 }
    print("last prompt: \(lastPrompt.map { "\(Int(Date().timeIntervalSince($0)))s ago" } ?? "never")")
    print("flags: \(names.isEmpty ? "none" : names.joined(separator: " + "))\(fm.fileExists(atPath: pausedFile.path) ? "  (hooks paused)" : "")")
case "list":
    let devices = keyboards()
    if devices.isEmpty { print("No \"\(productName)\" keyboard connected") }
    for d in devices { print("\(prop(d, kIOHIDProductKey)) via \(prop(d, kIOHIDTransportKey))") }
case "report":
    let bits = UInt8(args.count > 1 ? args[1] : "0", radix: 16) ?? 0
    print("sent 0x\(String(bits, radix: 16)) to \(sendLEDs(bits)) keyboard interface(s)")
default:
    print("usage: sofle-status hook | pause | resume | status | idle|working|needs|done | list | report <hex>")
    exit(2)
}
// Exit 0 even when the keyboard is asleep or disconnected, so a Claude Code hook never fails.
exit(0)

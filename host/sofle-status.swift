// sofle-status: show Claude Code's state on the keyboard's left screen.
//
// The state travels in two keyboard indicator lights that macOS doesn't use, Compose and Kana,
// sent as a raw LED output report over USB or Bluetooth. The firmware reads them through ZMK's
// HID indicators (boards/shields/nice_view_legend/widgets/status.c).
//
//   sofle-status hook          read a Claude Code hook event on stdin and show the matching state
//   sofle-status idle | working | needs | done
//   sofle-status list          show matching keyboards
//   sofle-status report <hex>  send a raw LED byte (for debugging)
//
// Build: swiftc -O -o sofle-status sofle-status.swift  (or host/install.sh)

import CoreGraphics
import Foundation
import IOKit.hid

let productName = ProcessInfo.processInfo.environment["SOFLE_PRODUCT"] ?? "Kyles Sofle"

// LED output report bits (HID LED usage minus one)
let capsBit: UInt8 = 1 << 1     // Caps Lock
let composeBit: UInt8 = 1 << 3  // Compose
let kanaBit: UInt8 = 1 << 4     // Kana

// Two-bit Claude state: Compose is bit 0, Kana is bit 1 (AGENT_* in the firmware's util.h)
let states: [String: UInt8] = ["idle": 0, "working": 1, "needs": 2, "done": 3]

func warn(_ message: String) {
    FileHandle.standardError.write("sofle-status: \(message)\n".data(using: .utf8)!)
}

func prop(_ device: IOHIDDevice, _ key: String) -> String {
    return IOHIDDeviceGetProperty(device, key as CFString).map { "\($0)" } ?? "?"
}

// Every HID device with the keyboard's product name: the Bluetooth link and, if plugged in, USB.
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
func macCapsLock() -> Bool {
    return CGEventSource.flagsState(.hidSystemState).contains(.maskAlphaShift)
}

// Map a Claude Code hook event (JSON on stdin) to a state, or nil to leave the state alone.
func stateForHookEvent() -> String? {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    guard let event = (try? JSONSerialization.jsonObject(with: input)) as? [String: Any],
          let name = event["hook_event_name"] as? String else { return nil }
    switch name {
    case "SessionStart", "SessionEnd": return "idle"
    case "UserPromptSubmit", "PostToolUse": return "working"   // PostToolUse also clears "needs" after an approval
    case "PermissionRequest": return "needs"
    case "Notification": return event["notification_type"] as? String == "permission_prompt" ? "needs" : nil
    case "Stop", "StopFailure": return "done"
    default: return nil
    }
}

// Skip resending an unchanged state for a while, so busy sessions don't send a Bluetooth report on
// every tool call. Resend after 30 s in case the keyboard slept and lost it.
let cacheURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".cache/sofle-status")

func alreadySent(_ state: String) -> Bool {
    guard let attrs = try? FileManager.default.attributesOfItem(atPath: cacheURL.path),
          let modified = attrs[.modificationDate] as? Date,
          let last = try? String(contentsOf: cacheURL, encoding: .utf8) else { return false }
    return last == state && Date().timeIntervalSince(modified) < 30
}

func remember(_ state: String) {
    try? FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    try? state.write(to: cacheURL, atomically: true, encoding: .utf8)
}

func show(_ name: String) {
    let state = states[name]!
    var bits: UInt8 = macCapsLock() ? capsBit : 0
    if state & 1 != 0 { bits |= composeBit }
    if state & 2 != 0 { bits |= kanaBit }
    if sendLEDs(bits) > 0 { remember(name) }
}

let args = Array(CommandLine.arguments.dropFirst())
switch args.first {
case "list":
    let devices = keyboards()
    if devices.isEmpty { print("No \"\(productName)\" keyboard connected") }
    for d in devices { print("\(prop(d, kIOHIDProductKey)) via \(prop(d, kIOHIDTransportKey))") }
case "report":
    let bits = UInt8(args.count > 1 ? args[1] : "0", radix: 16) ?? 0
    print("sent 0x\(String(bits, radix: 16)) to \(sendLEDs(bits)) keyboard interface(s)")
case "hook":
    if let name = stateForHookEvent(), !alreadySent(name) { show(name) }
case let name? where states[name] != nil:
    show(name)
default:
    print("usage: sofle-status hook | idle|working|needs|done | list | report <hex>")
    exit(2)
}
// Exit 0 even when the keyboard is asleep or disconnected, so a Claude Code hook never fails.
exit(0)

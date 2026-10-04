// sofle-status: feed the keyboard's left screen from the Mac: Claude Code's status, the time,
// Claude usage limits and CI for the repos you're working in.
//
// Everything travels in keyboard indicator lights macOS doesn't use, as raw HID LED output reports
// over USB or Bluetooth. The firmware decodes them in
// boards/shields/nice_view_legend/widgets/host_link.c, which documents the format:
//
//   Num Lock off   Scroll Lock, Compose and Kana are three flags: some session is working,
//                  needs you, or finished since your last prompt. Working or needs you lights
//                  the ✳ badge.
//   Num Lock on    a frame, 2 bits per report: the clock, the usage limits, or one repo row.
//                  The next report with Num Lock off ends it and carries the flags again.
//
// There's no way to hear back from the keyboard, so frames carry a CRC, the keyboard drops any
// frame that arrives damaged, and the cards are sent again when they change, every 10 minutes,
// and whenever the keyboard reconnects.
//
// Sources:
//   flags   Claude Code hooks; each session keeps its state in ~/.cache/sofle-status/sessions,
//           so concurrent sessions add up instead of overwriting each other
//   usage   Claude Code's status line input (rate_limits), cached in usage.json
//   repos   the 3 git repos where you most recently started a session or sent a prompt, with
//           the latest GitHub Actions runs from `gh run list`, cached in ci.json
//
//   sofle-status hook                      read a Claude Code hook event on stdin (used by hooks)
//   sofle-status statusline                read Claude Code's status line input (prints nothing)
//   sofle-status push                      send the cards if they changed (started by the above)
//   sofle-status cards                     show the cards, then send them all
//   sofle-status time                      sync the keyboard's clock now
//   sofle-status daemon                    sync on connect and every minute
//                                          (run by the au.kyle.sofle-status launch agent)
//   sofle-status pause | resume            stop or restart hook updates of the flags
//   sofle-status idle|working|needs|done   show flags by hand (also pauses hooks)
//   sofle-status status                    show each session's state and the combined flags
//   sofle-status encode                    print the reports `cards` would send, in hex
//   sofle-status list | report <hex>       show matching keyboards / send a raw LED byte
//
// Build: host/install.sh

import CoreGraphics
import Foundation
import IOKit.hid

let productName = ProcessInfo.processInfo.environment["SOFLE_PRODUCT"] ?? "Kyles Sofle"
let clock24h = ProcessInfo.processInfo.environment["SOFLE_CLOCK_24H"] == "1"

// LED output report bits (HID LED usage minus one)
let numBit: UInt8 = 1 << 0      // marks a frame report
let capsBit: UInt8 = 1 << 1
let workingBit: UInt8 = 1 << 2  // Scroll Lock
let needsBit: UInt8 = 1 << 3    // Compose
let doneBit: UInt8 = 1 << 4     // Kana

let manualStates: [String: UInt8] = ["idle": 0, "working": workingBit, "needs": needsBit, "done": doneBit]

// Session states older than this are treated as stale (a session that crashed or was killed).
let staleAfter: TimeInterval = 30 * 60
let resendAfter: TimeInterval = 30
let cardsResendAfter: TimeInterval = 10 * 60
let clockResendAfter: TimeInterval = 60 * 60
let ciPollAfter: TimeInterval = 120
let ciPollWhileRunning: TimeInterval = 45
let reportInterval: useconds_t = 10_000
// Over Bluetooth the keyboard can take a few hundred ms to pick up a report (ZMK lets it skip
// radio events while idle), so a frame's times count from its first report, which arrives within
// about this long.
let firstReportLead: TimeInterval = 0.2

let fm = FileManager.default
let stateDir = ProcessInfo.processInfo.environment["SOFLE_STATE_DIR"].map { URL(fileURLWithPath: $0) }  // for tests
    ?? fm.homeDirectoryForCurrentUser.appendingPathComponent(".cache/sofle-status")
let sessionsDir = stateDir.appendingPathComponent("sessions")
let projectsDir = stateDir.appendingPathComponent("projects")
let lastPromptFile = stateDir.appendingPathComponent("last-prompt")
let lastSentFile = stateDir.appendingPathComponent("last-sent")
let pausedFile = stateDir.appendingPathComponent("paused")
let lockFile = stateDir.appendingPathComponent("lock")
let pushLockFile = stateDir.appendingPathComponent("push.lock")
let pushPendingFile = stateDir.appendingPathComponent("push-pending")
let usageFile = stateDir.appendingPathComponent("usage.json")
let ciFile = stateDir.appendingPathComponent("ci.json")
let sentFile = stateDir.appendingPathComponent("sent.json")
let logFile = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/sofle-status.log")

func warn(_ message: String) {
    FileHandle.standardError.write("sofle-status: \(message)\n".data(using: .utf8)!)
}

func log(_ message: String) {
    let stamp = ISO8601DateFormatter().string(from: Date())
    FileHandle.standardError.write("\(stamp) \(message)\n".data(using: .utf8)!)
}

// For processes whose stderr goes nowhere (pushes started by hooks): append to the agent's log.
func logToFile(_ message: String) {
    let line = "\(ISO8601DateFormatter().string(from: Date())) \(message)\n"
    guard let handle = try? FileHandle(forWritingTo: logFile) else { return }
    handle.seekToEndOfFile()
    handle.write(line.data(using: .utf8)!)
    try? handle.close()
}

// MARK: Keyboard

func prop(_ device: IOHIDDevice, _ key: String) -> String {
    return IOHIDDeviceGetProperty(device, key as CFString).map { "\($0)" } ?? "?"
}

func isKeyboard(_ device: IOHIDDevice) -> Bool {
    return prop(device, kIOHIDProductKey) == productName
        && prop(device, kIOHIDPrimaryUsagePageKey) == "1" && prop(device, kIOHIDPrimaryUsageKey) == "6"
}

// Every keyboard interface with the keyboard's product name: Bluetooth and, if plugged in, USB.
// Filtered by hand because the Mac's own keyboard has the same LED elements and must be left alone.
func keyboards() -> [IOHIDDevice] {
    let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
    IOHIDManagerSetDeviceMatching(manager, [kIOHIDProductKey: productName] as CFDictionary)
    IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone))
    let devices = IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice> ?? []
    return devices.filter(isKeyboard)
}

// A connection's identity: it changes whenever the keyboard reconnects, which includes waking up,
// and the keyboard forgets the clock and the cards when it sleeps.
func connectionIDs() -> String {
    return keyboards().map { device -> UInt64 in
        var id: UInt64 = 0
        IORegistryEntryGetRegistryEntryID(IOHIDDeviceGetService(device), &id)
        return id
    }.sorted().map(String.init).joined(separator: ",")
}

// Hold an exclusive lock while sending, so reports from two processes can't interleave on the wire.
// With wait false, returns nil instead of waiting when another process holds it.
func withLock<T>(_ url: URL, wait: Bool = true, _ body: () -> T) -> T? {
    try? fm.createDirectory(at: stateDir, withIntermediateDirectories: true)
    let fd = open(url.path, O_CREAT | O_RDWR, 0o644)
    guard fd >= 0 else { return body() }
    defer { close(fd) }
    guard flock(fd, wait ? LOCK_EX : LOCK_EX | LOCK_NB) == 0 else { return nil }
    defer { flock(fd, LOCK_UN) }
    return body()
}

// Part of a report sequence, built right before it goes out, so a clock frame and the flags
// after each frame are current even when the frames before them took a while.
typealias Step = () -> [UInt8]

// Send LED output reports (report ID 1 is ZMK's keyboard report) to each keyboard interface, in
// order. Returns how many interfaces took them all, or nil if another process is sending and
// wait is false.
@discardableResult
func sendLEDs(_ bits: UInt8, wait: Bool = true) -> Int? {
    return send([{ [bits] }], wait: wait)
}

@discardableResult
func send(_ steps: [Step], wait: Bool = true) -> Int? {
    return withLock(lockFile, wait: wait) {
        var sent = 0
        for device in keyboards() {
            let transport = prop(device, kIOHIDTransportKey)
            let opened = IOHIDDeviceOpen(device, IOOptionBits(kIOHIDOptionsTypeNone))
            guard opened == kIOReturnSuccess else {
                warn("can't open \(transport) (0x\(String(UInt32(bitPattern: opened), radix: 16)))")
                continue
            }
            defer { IOHIDDeviceClose(device, IOOptionBits(kIOHIDOptionsTypeNone)) }
            let start = Date()
            var count = 0
            var ok = true
            sending: for step in steps {
                for bits in step() {
                    if count > 0 { usleep(reportInterval) }
                    let report: [UInt8] = [0x01, bits]
                    let result = report.withUnsafeBufferPointer {
                        IOHIDDeviceSetReport(device, kIOHIDReportTypeOutput, 1, $0.baseAddress!, $0.count)
                    }
                    if result != kIOReturnSuccess {
                        warn("\(transport) report failed (0x\(String(UInt32(bitPattern: result), radix: 16)))")
                        ok = false
                        break sending
                    }
                    count += 1
                }
            }
            if count > 1 {
                let each = Int(Date().timeIntervalSince(start) * 1000) / count
                logToFile("sent \(count) reports via \(transport), \(each) ms each")
            }
            if ok { sent += 1 }
        }
        return sent
    }
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

func readJSON(_ url: URL) -> [String: Any] {
    guard let data = try? Data(contentsOf: url) else { return [:] }
    return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
}

func writeJSON(_ object: [String: Any], to url: URL) {
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return }
    try? fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try? data.write(to: url, options: .atomic)
}

// MARK: Flags

// Send the flags unless the same flags went out recently. Never waits: while a push is sending,
// it ends every frame with the current flags, and sends them again when it finishes.
func show(_ bits: UInt8) {
    if let last = try? String(contentsOf: lastSentFile, encoding: .utf8), last == String(bits),
       let at = modified(lastSentFile), Date().timeIntervalSince(at) < resendAfter {
        return
    }
    if let n = sendLEDs(withCaps(bits), wait: false), n > 0 { write(String(bits), to: lastSentFile) }
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

// The flags the keyboard should rest on after a frame.
func currentFlags() -> UInt8 {
    if fm.fileExists(atPath: pausedFile.path) {
        return (try? String(contentsOf: lastSentFile, encoding: .utf8)).flatMap { UInt8($0) } ?? 0
    }
    return aggregate()
}

// MARK: Frames

let frameClock: UInt8 = 1
let frameUsage: UInt8 = 2
let frameRepo: UInt8 = 3
let usageLabelLength = 5
let repoNameLength = 12

func crc8(_ bytes: [UInt8]) -> UInt8 {
    var crc: UInt8 = 0
    for byte in bytes {
        crc ^= byte
        for _ in 0..<8 { crc = crc & 0x80 != 0 ? (crc << 1) ^ 0x07 : crc << 1 }
    }
    return crc
}

// A frame's reports: Num Lock on, 2 bits each in Scroll Lock and Compose, Kana alternating.
func frameReports(_ body: [UInt8]) -> [UInt8] {
    var reports: [UInt8] = []
    for byte in body + [crc8(body)] {
        for shift in stride(from: 6, through: 0, by: -2) {
            let chunk = (byte >> UInt8(shift)) & 3
            var report = numBit
            if chunk & 2 != 0 { report |= workingBit }
            if chunk & 1 != 0 { report |= needsBit }
            if reports.count & 1 != 0 { report |= doneBit }
            reports.append(withCaps(report))
        }
    }
    return reports
}

// Each frame, then the current flags to end it. The flags last sent are written to lastSent.
func frameSteps(_ frames: [() -> [UInt8]], lastSent: UnsafeMutablePointer<UInt8>? = nil) -> [Step] {
    return frames.flatMap { frame -> [Step] in
        [{ frameReports(frame()) }, {
            let flags = currentFlags()
            lastSent?.pointee = flags
            return [withCaps(flags)]
        }]
    }
}

func text(_ s: String, _ length: Int) -> [UInt8] {
    let ascii = s.uppercased().unicodeScalars.filter { $0.value >= 0x20 && $0.value < 0x7f }.map { UInt8($0.value) }
    return Array((ascii + [UInt8](repeating: 0, count: length)).prefix(length))
}

// The time when the frame's first report reaches the keyboard, which is when the keyboard takes it.
func clockFrame() -> [UInt8] {
    let now = Calendar.current.dateComponents([.hour, .minute, .second], from: Date().addingTimeInterval(firstReportLead))
    let bits = UInt32(now.hour! * 60 + now.minute!) << 6 | UInt32(now.second!)
    return [frameClock, UInt8(bits >> 16), UInt8(bits >> 8 & 0xff), UInt8(bits & 0xff)]
}

// MARK: Usage

// Claude Code passes rate_limits to the status line command: used_percentage and resets_at
// (Unix seconds) for the five_hour and seven_day windows. Returns whether the cache changed.
func recordUsage(_ input: Data) -> Bool {
    guard let status = (try? JSONSerialization.jsonObject(with: input)) as? [String: Any],
          let limits = status["rate_limits"] as? [String: Any] else { return false }
    var usage: [String: Any] = [:]
    for window in ["five_hour", "seven_day"] {
        guard let limit = limits[window] as? [String: Any] else { continue }
        var entry: [String: Any] = [:]
        if let pct = (limit["used_percentage"] as? NSNumber)?.doubleValue { entry["pct"] = Int(pct.rounded()) }
        if let reset = (limit["resets_at"] as? NSNumber)?.doubleValue { entry["resets_at"] = Int(reset) }
        usage[window] = entry
    }
    guard !usage.isEmpty else { return false }
    let old = (try? Data(contentsOf: usageFile)) ?? Data()
    guard let new = try? JSONSerialization.data(withJSONObject: usage, options: [.sortedKeys]), new != old else { return false }
    writeJSON(usage, to: usageFile)
    return true
}

func timeLabel(_ date: Date) -> String {
    let c = Calendar.current.dateComponents([.hour, .minute], from: date)
    let hour = clock24h ? c.hour! : (c.hour! % 12 == 0 ? 12 : c.hour! % 12)
    return String(format: "%d:%02d", hour, c.minute!)
}

// The 5 hour limit resets within the day, so it shows a time. The weekly one shows a weekday
// until the day it resets.
func resetLabel(_ reset: Date, weekly: Bool) -> String {
    if !weekly || Calendar.current.isDateInToday(reset) { return timeLabel(reset) }
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "EEE"
    return f.string(from: reset).uppercased()
}

struct Card {
    let key: String      // what this card is: usage, repo0..2
    let content: String  // changes when what it shows changes
    let frame: () -> [UInt8]
}

func usageCard() -> Card {
    let usage = readJSON(usageFile)
    var content: [String] = []
    var rows: [(pct: UInt8, reset: Date?, label: String)] = []
    for (i, window) in ["five_hour", "seven_day"].enumerated() {
        let entry = usage[window] as? [String: Any] ?? [:]
        var pct = (entry["pct"] as? Int).map { UInt8(clamping: min(max($0, 0), 100)) } ?? 0xff
        var reset = (entry["resets_at"] as? Int).map { Date(timeIntervalSince1970: TimeInterval($0)) }
        if let r = reset, r <= Date() {
            pct = 0  // the window reset since Claude Code last said
            reset = nil
        }
        let label = reset.map { resetLabel($0, weekly: i == 1) } ?? ""
        rows.append((pct, reset, label))
        content.append("\(pct) \(Int(reset?.timeIntervalSince1970 ?? 0)) \(label)")
    }
    return Card(key: "usage", content: content.joined(separator: " | ")) {
        var body: [UInt8] = [frameUsage]
        for row in rows {
            // minutes until the reset, counted from when the frame's first report arrives
            let minutes = row.reset.map {
                UInt16(min(max(ceil(($0.timeIntervalSinceNow - firstReportLead) / 60), 0), 65534))
            } ?? 0xffff
            body += [row.pct, UInt8(minutes >> 8), UInt8(minutes & 0xff)]
        }
        for row in rows { body += text(row.label, usageLabelLength) }
        return body
    }
}

// MARK: Repos

func run(_ executable: String, _ arguments: [String], timeout: TimeInterval = 20) -> String? {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments
    let out = Pipe()
    process.standardOutput = out
    process.standardError = FileHandle.nullDevice
    process.standardInput = FileHandle.nullDevice
    do { try process.run() } catch { return nil }
    let timer = DispatchWorkItem { process.terminate() }
    DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: timer)
    let data = out.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    timer.cancel()
    guard process.terminationStatus == 0 else { return nil }
    return String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
}

func git(_ dir: String, _ arguments: [String]) -> String? {
    return run("/usr/bin/git", ["-C", dir] + arguments, timeout: 5)
}

// The launch agent's PATH doesn't include Homebrew.
let ghPath = ["/opt/homebrew/bin/gh", "/usr/local/bin/gh"].first { fm.isExecutableFile(atPath: $0) }
    ?? (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":")
        .map { "\($0)/gh" }.first { fm.isExecutableFile(atPath: $0) }

// One file per working directory, touched when a session starts or you send a prompt there.
func projectFile(_ cwd: String) -> URL {
    var hash: UInt64 = 0xcbf2_9ce4_8422_2325  // FNV-1a
    for byte in cwd.utf8 { hash = (hash ^ UInt64(byte)) &* 0x100_0000_01b3 }
    return projectsDir.appendingPathComponent(String(hash, radix: 16))
}

struct Repo {
    let root: String   // the main checkout, shared by its worktrees
    let name: String
    let slug: String?  // owner/name on GitHub
}

// The most recently used git repos, newest first.
func recentRepos(limit: Int = 3) -> [Repo] {
    let files = (try? fm.contentsOfDirectory(at: projectsDir, includingPropertiesForKeys: nil)) ?? []
    var repos: [Repo] = []
    for file in files.sorted(by: { (modified($0) ?? .distantPast) > (modified($1) ?? .distantPast) }) {
        guard repos.count < limit else { break }
        guard let cwd = try? String(contentsOf: file, encoding: .utf8), fm.fileExists(atPath: cwd),
              Date().timeIntervalSince(modified(file) ?? .distantPast) < 30 * 24 * 3600 else {
            try? fm.removeItem(at: file)
            continue
        }
        guard let common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]) else { continue }
        let commonURL = URL(fileURLWithPath: common)
        let root = commonURL.lastPathComponent == ".git" ? commonURL.deletingLastPathComponent().path : common
        if repos.contains(where: { $0.root == root }) { continue }
        var slug: String?
        if let remote = git(cwd, ["remote", "get-url", "origin"]),
           let range = remote.range(of: #"github\.com[:/][^/]+/[^/]+$"#, options: .regularExpression) {
            slug = String(remote[range].dropFirst("github.com/".count))
                .replacingOccurrences(of: #"(\.git)?/?$"#, with: "", options: .regularExpression)
        }
        let name = slug.map { String($0.split(separator: "/").last!) } ?? URL(fileURLWithPath: root).lastPathComponent
        repos.append(Repo(root: root, name: name, slug: slug))
    }
    return repos
}

// The latest commit's GitHub Actions runs, together: failed if any failed, else running if any
// hasn't finished, else ok. Nil if gh couldn't say (offline, signed out).
func ciState(_ slug: String) -> Int? {
    guard let gh = ghPath,
          let out = run(gh, ["run", "list", "-R", slug, "-L", "20", "--json", "headSha,status,conclusion"]),
          let runs = (try? JSONSerialization.jsonObject(with: Data(out.utf8))) as? [[String: Any]] else { return nil }
    guard let head = runs.first?["headSha"] as? String else { return 0 }
    let latest = runs.filter { $0["headSha"] as? String == head }
    let conclusions = latest.compactMap { $0["conclusion"] as? String }
    if conclusions.contains(where: { ["failure", "timed_out", "startup_failure"].contains($0) }) { return 2 }
    if latest.contains(where: { $0["status"] as? String != "completed" }) { return 3 }
    if conclusions.contains(where: { ["success", "neutral", "skipped"].contains($0) }) { return 1 }
    return 0
}

// Repo rows from ci.json, polled again when they're due or the recent repos changed.
func repoRows(poll: Bool) -> [[String: Any]] {
    let cache = readJSON(ciFile)
    let cached = cache["rows"] as? [[String: Any]] ?? []
    guard poll else { return cached }
    let repos = recentRepos()
    let sameRepos = repos.map(\.root) == cached.compactMap { $0["root"] as? String }
    if sameRepos, let next = cache["next"] as? Double, Date().timeIntervalSince1970 < next { return cached }
    var rows: [[String: Any]] = []
    for repo in repos {
        let previous = cached.first { $0["root"] as? String == repo.root }?["ci"] as? Int ?? 0
        let ci = repo.slug.flatMap(ciState) ?? previous
        rows.append(["root": repo.root, "name": repo.name, "ci": ci])
    }
    let running = rows.contains { $0["ci"] as? Int == 3 }
    let next = Date().timeIntervalSince1970 + (running ? ciPollWhileRunning : ciPollAfter)
    writeJSON(["rows": rows, "next": next], to: ciFile)
    return rows
}

func ciDue() -> Bool {
    guard let next = readJSON(ciFile)["next"] as? Double else { return true }
    return Date().timeIntervalSince1970 >= next
}

func repoCards(_ rows: [[String: Any]]) -> [Card] {
    return (0..<3).map { i in
        let row = i < rows.count ? rows[i] : [:]
        let name = row["name"] as? String ?? ""
        let ci = UInt8(row["ci"] as? Int ?? 0)
        return Card(key: "repo\(i)", content: "\(name) \(ci)") {
            [frameRepo, UInt8(i), ci] + text(name, repoNameLength)
        }
    }
}

// MARK: Push

// Send the cards that changed, or all of them if forced or the keyboard reconnected. A clock frame
// goes first when the keyboard reconnected or the last sync is old.
func pushOnce(force: Bool, clock: Bool = false) {
    let connection = connectionIDs()
    guard !connection.isEmpty else { return }
    let rows = repoRows(poll: true)
    var sent = readJSON(sentFile)
    let reconnected = sent["connection"] as? String != connection
    let now = Date().timeIntervalSince1970
    let clockDue = clock || reconnected || now - (sent["clock"] as? Double ?? 0) > clockResendAfter
    let due = ([usageCard()] + repoCards(rows)).filter { card in
        let last = sent[card.key] as? [String: Any]
        return force || reconnected || last?["content"] as? String != card.content
            || now - (last?["at"] as? Double ?? 0) > cardsResendAfter
    }
    guard clockDue || !due.isEmpty else { return }
    var flags: UInt8 = 0
    let frames = (clockDue ? [clockFrame] : []) + due.map(\.frame)
    guard let n = send(frameSteps(frames, lastSent: &flags)), n > 0 else { return }
    write(String(flags), to: lastSentFile)
    sent["connection"] = connection
    if clockDue { sent["clock"] = now }
    for card in due { sent[card.key] = ["content": card.content, "at": now] }
    writeJSON(sent, to: sentFile)
}

// One push at a time: a push that finds another running leaves a note for it to go again.
func push(force: Bool = false, clock: Bool = false) {
    try? fm.createDirectory(at: stateDir, withIntermediateDirectories: true)
    let fd = open(pushLockFile.path, O_CREAT | O_RDWR, 0o644)
    guard fd >= 0 else { return }
    defer { close(fd) }
    guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
        write("", to: pushPendingFile)
        return
    }
    defer { flock(fd, LOCK_UN) }
    var force = force, clock = clock
    for _ in 0..<3 {
        try? fm.removeItem(at: pushPendingFile)
        pushOnce(force: force, clock: clock)
        force = false
        clock = false
        if !fm.fileExists(atPath: pushPendingFile.path) { break }
    }
    // in case a hook changed the flags after the last frame went out
    if !fm.fileExists(atPath: pausedFile.path) { show(aggregate()) }
}

// Start `sofle-status push` in the background, so hooks and the status line return at once.
func spawnPush() {
    guard let me = Bundle.main.executableURL else { return }
    let process = Process()
    process.executableURL = me
    process.arguments = ["push"]
    process.standardInput = FileHandle.nullDevice
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.nullDevice
    try? process.run()
}

// MARK: Hooks

// Record a Claude Code hook event (JSON on stdin) as its session's state. Returns whether the
// cards may need sending: a new repo, or CI is due for another look.
func recordHookEvent() -> Bool {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    guard let event = (try? JSONSerialization.jsonObject(with: input)) as? [String: Any],
          let name = event["hook_event_name"] as? String,
          let session = event["session_id"] as? String, !session.contains("/") else { return false }
    let file = sessionsDir.appendingPathComponent(session)
    var newProject = false
    if ["SessionStart", "UserPromptSubmit"].contains(name), let cwd = event["cwd"] as? String {
        newProject = !fm.fileExists(atPath: projectFile(cwd).path)
        write(cwd, to: projectFile(cwd))
    }
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
        break
    }
    return newProject || ciDue()
}

// MARK: Daemon

// Push whenever the keyboard (re)connects, which includes waking from sleep, and every minute.
func runDaemon() -> Never {
    let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
    IOHIDManagerSetDeviceMatching(manager, [kIOHIDProductKey: productName] as CFDictionary)
    IOHIDManagerRegisterDeviceMatchingCallback(manager, { _, _, _, device in
        guard isKeyboard(device) else { return }
        let transport = prop(device, kIOHIDTransportKey)
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            push(force: true, clock: true)
            log("keyboard connected via \(transport)")
        }
    }, nil)
    IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.defaultMode.rawValue)
    IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone))
    var ticks = 0
    Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
        ticks += 1
        push(clock: ticks % 5 == 0)
    }
    log("sofle-status daemon started")
    // Opening a keyboard needs Input Monitoring. Terminals usually have it; a launch agent doesn't.
    // Asking adds sofle-status to System Settings > Privacy & Security > Input Monitoring.
    if IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) != kIOHIDAccessTypeGranted {
        log("needs Input Monitoring: enable sofle-status in System Settings > Privacy & Security > Input Monitoring")
        IOHIDRequestAccess(kIOHIDRequestTypeListenEvent)
    }
    RunLoop.main.run()
    exit(0)
}

// MARK: Commands

func describeCards(_ rows: [[String: Any]]) {
    let usage = readJSON(usageFile)
    for (label, window) in [("5H", "five_hour"), ("WK", "seven_day")] {
        let entry = usage[window] as? [String: Any] ?? [:]
        let reset = (entry["resets_at"] as? Int).map { Date(timeIntervalSince1970: TimeInterval($0)) }
        print("\(label)  \((entry["pct"] as? Int).map { "\($0)%" } ?? "--")  resets \(reset.map { resetLabel($0, weekly: window == "seven_day") } ?? "--")")
    }
    let states = ["-", "ok", "FAIL", "running"]
    for row in rows {
        print("\(row["name"] as? String ?? "?")  \(states[min(row["ci"] as? Int ?? 0, 3)])  (\(row["root"] as? String ?? ""))")
    }
    if rows.isEmpty { print("no repos yet: they appear after a Claude Code session starts or gets a prompt in one") }
}

// Earlier versions kept a single cache file at this path; it's a folder now.
var isDirectory: ObjCBool = false
if fm.fileExists(atPath: stateDir.path, isDirectory: &isDirectory), !isDirectory.boolValue {
    try? fm.removeItem(at: stateDir)
}

let args = Array(CommandLine.arguments.dropFirst())
switch args.first {
case "hook":
    let pushDue = recordHookEvent()
    if !fm.fileExists(atPath: pausedFile.path) { show(aggregate()) }
    if pushDue { spawnPush() }
case "statusline":
    if recordUsage(FileHandle.standardInput.readDataToEndOfFile()) { spawnPush() }
case "push":
    push()
case "cards":
    describeCards(repoRows(poll: true))
    push(force: true)
case "encode":
    let frames = [clockFrame, usageCard().frame] + repoCards(repoRows(poll: false)).map(\.frame)
    for bits in frameSteps(frames).flatMap({ $0() }) { print(String(format: "%02x", bits)) }
case "time":
    var flags: UInt8 = 0
    let n = send(frameSteps([clockFrame], lastSent: &flags)) ?? 0
    if n > 0 { write(String(flags), to: lastSentFile) }
    print("clock synced on \(n) keyboard interface(s)")
case "daemon":
    runDaemon()
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
    print("sent 0x\(String(bits, radix: 16)) to \(sendLEDs(bits) ?? 0) keyboard interface(s)")
default:
    print("usage: sofle-status hook | statusline | push | cards | time | daemon | pause | resume | status | idle|working|needs|done | encode | list | report <hex>")
    exit(2)
}
// Exit 0 even when the keyboard is asleep or disconnected, so a Claude Code hook never fails.
exit(0)

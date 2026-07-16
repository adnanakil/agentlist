import AppKit
import ApplicationServices
import Foundation

private let findMyBundleID = "com.apple.findmy"

struct Rectangle: Codable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct ProbeSummary: Codable {
    let status: String
    let windowCount: Int
    let roleCounts: [String: Int]
    let labeledNodesByRole: [String: Int]
}

struct LookupResult: Codable {
    let status: String
    let label: String?
    let updated: String?
    let approximate: Bool?
    let source: String
}

struct InspectResult: Codable {
    let status: String
    let selectedName: String
    let detailStrings: [String]
}

struct Node {
    let element: AXUIElement
    let role: String
    let strings: [String]
    let frame: CGRect?
}

private func copyAttribute(_ element: AXUIElement, _ attribute: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else {
        return nil
    }
    return value
}

private func stringAttribute(_ element: AXUIElement, _ attribute: String) -> String? {
    guard let value = copyAttribute(element, attribute) else { return nil }
    if let string = value as? String {
        let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
    if let attributed = value as? NSAttributedString {
        let trimmed = attributed.string.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
    return nil
}

private func frameOf(_ element: AXUIElement) -> CGRect? {
    guard
        let positionRaw = copyAttribute(element, kAXPositionAttribute),
        CFGetTypeID(positionRaw) == AXValueGetTypeID(),
        let sizeRaw = copyAttribute(element, kAXSizeAttribute),
        CFGetTypeID(sizeRaw) == AXValueGetTypeID()
    else { return nil }
    let positionValue = unsafeBitCast(positionRaw, to: AXValue.self)
    let sizeValue = unsafeBitCast(sizeRaw, to: AXValue.self)

    var position = CGPoint.zero
    var size = CGSize.zero
    guard
        AXValueGetValue(positionValue, .cgPoint, &position),
        AXValueGetValue(sizeValue, .cgSize, &size)
    else { return nil }
    return CGRect(origin: position, size: size)
}

private func stringsOf(_ element: AXUIElement) -> [String] {
    let attributes = [
        kAXTitleAttribute,
        kAXValueAttribute,
        kAXDescriptionAttribute,
        kAXHelpAttribute,
        kAXRoleDescriptionAttribute,
    ]
    var seen = Set<String>()
    return attributes.compactMap { attribute in
        guard let value = stringAttribute(element, attribute) else { return nil }
        return seen.insert(value).inserted ? value : nil
    }
}

private func childrenOf(_ element: AXUIElement) -> [AXUIElement] {
    (copyAttribute(element, kAXChildrenAttribute) as? [AXUIElement]) ?? []
}

private func walk(_ root: AXUIElement, limit: Int = 5_000) -> [Node] {
    var result: [Node] = []
    var queue = [root]
    while !queue.isEmpty && result.count < limit {
        let element = queue.removeFirst()
        let role = stringAttribute(element, kAXRoleAttribute) ?? "unknown"
        result.append(
            Node(element: element, role: role, strings: stringsOf(element), frame: frameOf(element))
        )
        queue.append(contentsOf: childrenOf(element))
    }
    return result
}

private func normalize(_ value: String) -> String {
    value
        .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
        .trimmingCharacters(in: .whitespacesAndNewlines)
}

private func parentOf(_ element: AXUIElement) -> AXUIElement? {
    guard
        let raw = copyAttribute(element, kAXParentAttribute),
        CFGetTypeID(raw) == AXUIElementGetTypeID()
    else { return nil }
    return unsafeBitCast(raw, to: AXUIElement.self)
}

private func activate(_ element: AXUIElement) -> Bool {
    var candidate: AXUIElement? = element
    for _ in 0..<5 {
        guard let current = candidate else { break }
        if AXUIElementPerformAction(current, kAXPressAction as CFString) == .success {
            return true
        }
        if AXUIElementSetAttributeValue(
            current,
            kAXSelectedAttribute as CFString,
            kCFBooleanTrue
        ) == .success {
            return true
        }
        candidate = parentOf(current)
    }
    return false
}

private func findMyApplication() -> NSRunningApplication? {
    if let running = NSRunningApplication.runningApplications(withBundleIdentifier: findMyBundleID).first {
        return running
    }
    _ = NSWorkspace.shared.launchApplication(
        withBundleIdentifier: findMyBundleID,
        options: [.withoutActivation],
        additionalEventParamDescriptor: nil,
        launchIdentifier: nil
    )
    for _ in 0..<20 {
        if let running = NSRunningApplication.runningApplications(withBundleIdentifier: findMyBundleID).first {
            return running
        }
        Thread.sleep(forTimeInterval: 0.25)
    }
    return nil
}

private func windowsOf(_ app: AXUIElement) -> [AXUIElement] {
    (copyAttribute(app, kAXWindowsAttribute) as? [AXUIElement]) ?? []
}

private let ignoredLabels = Set(
    [
        "people", "devices", "items", "me", "directions", "contact", "notifications",
        "add", "remove", "stop sharing my location", "share my location", "info",
    ].map(normalize)
)

private func locationScore(_ text: String, selectedName: String) -> Int {
    let normalized = normalize(text)
    guard
        normalized != normalize(selectedName),
        !ignoredLabels.contains(normalized),
        text.count >= 3,
        text.count <= 240,
        !text.contains("@")
    else { return -100 }

    // Map controls such as "Heading: 0 degrees, North" contain a digit and
    // comma, which otherwise makes them look address-like to the heuristic.
    if text.range(
        of: #"(?:^|\b)(?:heading|bearing|compass|map scale)\s*:.*\bdegrees?\b"#,
        options: [.regularExpression, .caseInsensitive]
    ) != nil { return -100 }

    // Find My chrome that leaks into the detail pane and would otherwise score
    // on an incidental digit ("show in 3d") or comma. These are never a
    // location; reject them outright so the fallback can't emit a button label.
    if text.range(
        of: #"^(?:show (?:in )?3d|show map|show 2d|satellite|hybrid|play sound|mark as lost|remove this device|erase this device|notify when found|directions|add label|edit label|zoom (?:in|out))$"#,
        options: [.regularExpression, .caseInsensitive]
    ) != nil { return -100 }

    var score = 0
    if text.rangeOfCharacter(from: .decimalDigits) != nil { score += 2 }
    if text.contains(",") { score += 3 }
    if text.range(
        of: #"\b(st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|way|pl|place|ct|court|pkwy|parkway)\b"#,
        options: [.regularExpression, .caseInsensitive]
    ) != nil { score += 4 }
    if text.range(
        of: #"\b(home|work|school|airport|station|park|hospital|restaurant|hotel)\b"#,
        options: [.regularExpression, .caseInsensitive]
    ) != nil { score += 2 }
    if text.range(
        of: #"^(now|live|no location found|location not available|[0-9]+\s*(min|minute|hr|hour)s? ago)$"#,
        options: [.regularExpression, .caseInsensitive]
    ) != nil { score -= 8 }
    return score
}

private func freshness(_ strings: [String]) -> String? {
    strings.first {
        $0.range(
            of: #"^(now|live|[0-9]+\s*(min|minute|hr|hour)s? ago|yesterday.*)$"#,
            options: [.regularExpression, .caseInsensitive]
        ) != nil
    }
}

// The selected person's map pin renders a callout of the form
// "Northvale, NJ • 1 minute ago" — one string carrying both the location and
// its freshness. This is the primary extraction target; the scored heuristic
// below is only a fallback.
private let calloutRegex = try! NSRegularExpression(
    pattern: #"^(.{3,200}?)\s*[•·]\s*(now|live|[0-9]+\s*(?:min|minute|hr|hour)s?\.?\s*ago|yesterday[^•·]*|today[^•·]*)$"#,
    options: [.caseInsensitive]
)

private func parsePinCallout(_ text: String) -> (label: String, updated: String)? {
    let range = NSRange(text.startIndex..<text.endIndex, in: text)
    guard
        let match = calloutRegex.firstMatch(in: text, options: [], range: range),
        let labelRange = Range(match.range(at: 1), in: text),
        let updatedRange = Range(match.range(at: 2), in: text)
    else { return nil }
    let label = String(text[labelRange]).trimmingCharacters(in: .whitespacesAndNewlines)
    let updated = String(text[updatedRange]).trimmingCharacters(in: .whitespacesAndNewlines)
    guard !label.isEmpty else { return nil }
    return (label, updated)
}

private func bestCallout(
    in nodes: [Node], selectedName: String
) -> (label: String, updated: String)? {
    let normalizedName = normalize(selectedName)
    var nameIndices: [Int] = []
    var callouts: [(index: Int, label: String, updated: String)] = []
    for (index, node) in nodes.enumerated() {
        for string in node.strings {
            if normalize(string) == normalizedName {
                nameIndices.append(index)
            }
            if let (label, updated) = parsePinCallout(string),
               locationScore(label, selectedName: selectedName) >= 0 {
                callouts.append((index: index, label: label, updated: updated))
            }
        }
    }
    guard !callouts.isEmpty else { return nil }
    if callouts.count == 1 || nameIndices.isEmpty {
        return (callouts[0].label, callouts[0].updated)
    }
    // Multiple pins can be visible at once; take the callout closest to the
    // selected person's own name node so another share's bubble never wins.
    let chosen = callouts.min { lhs, rhs in
        let lhsDistance = nameIndices.map { abs($0 - lhs.index) }.min() ?? Int.max
        let rhsDistance = nameIndices.map { abs($0 - rhs.index) }.min() ?? Int.max
        return lhsDistance < rhsDistance
    }!
    return (chosen.label, chosen.updated)
}

private func writeJSON<T: Encodable>(_ value: T, to path: String) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    let data = try encoder.encode(value)
    let url = URL(fileURLWithPath: path)
    try data.write(to: url, options: .atomic)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path)
}

private func outputPath(from arguments: [String]) -> String? {
    guard let index = arguments.firstIndex(of: "--output"), index + 1 < arguments.count else {
        return nil
    }
    return arguments[index + 1]
}

private func fail(_ status: String, output: String, exitCode: Int32 = 1) -> Never {
    let result = LookupResult(
        status: status,
        label: nil,
        updated: nil,
        approximate: nil,
        source: "find_my"
    )
    try? writeJSON(result, to: output)
    exit(exitCode)
}

let arguments = Array(CommandLine.arguments.dropFirst())
guard let mode = arguments.first, let output = outputPath(from: arguments) else {
    fputs("usage: HalFindMyHelper probe|lookup <name> --output <path>\n", stderr)
    exit(64)
}

let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
guard AXIsProcessTrustedWithOptions([promptKey: true] as CFDictionary) else {
    fail("accessibility_permission_required", output: output, exitCode: 77)
}
guard let running = findMyApplication() else {
    fail("find_my_unavailable", output: output)
}
_ = running.activate(options: [.activateIgnoringOtherApps])
Thread.sleep(forTimeInterval: 1.5)

let appElement = AXUIElementCreateApplication(running.processIdentifier)
let windows = windowsOf(appElement)
guard !windows.isEmpty else {
    fail("find_my_window_unavailable", output: output)
}

if mode == "probe" {
    let nodes = windows.flatMap { walk($0) }
    let roleCounts = Dictionary(grouping: nodes, by: \Node.role).mapValues { $0.count }
    let labeled = Dictionary(grouping: nodes.filter { !$0.strings.isEmpty }, by: \Node.role)
        .mapValues { $0.count }
    let result = ProbeSummary(
        status: "ok",
        windowCount: windows.count,
        roleCounts: roleCounts,
        labeledNodesByRole: labeled
    )
    try writeJSON(result, to: output)
    exit(0)
}

guard (mode == "lookup" || mode == "inspect" || mode == "inspectall"), arguments.count >= 2 else {
    fail("invalid_request", output: output, exitCode: 64)
}
let selectedName = arguments[1]
let normalizedSelectedName = normalize(selectedName)

func detailNodesSnapshot() -> [Node] {
    let currentWindows = windowsOf(appElement)
    let windowFrames = currentWindows.compactMap(frameOf)
    let detailBoundary = windowFrames.map { $0.minX + max(260, $0.width * 0.28) }.min() ?? 260
    return currentWindows
        .flatMap { walk($0) }
        .filter { ($0.frame?.midX ?? 0) >= detailBoundary }
}

func uniqueStrings(_ nodes: [Node]) -> [String] {
    nodes
        .flatMap { $0.strings }
        .reduce(into: [String]()) { (values: inout [String], value: String) in
            if !values.contains(value) { values.append(value) }
        }
}

func succeed(label: String, updated: String?, approximate: Bool? = nil) -> Never {
    let result = LookupResult(
        status: "ok",
        label: label,
        updated: updated,
        approximate: approximate,
        source: "find_my"
    )
    try? writeJSON(result, to: output)
    exit(0)
}

// The people list itself can still be loading right after activation, so the
// person match gets a few attempts rather than one snapshot.
var match: Node?
for attempt in 0..<4 {
    if attempt > 0 { Thread.sleep(forTimeInterval: 0.75) }
    let nodes = windowsOf(appElement).flatMap { walk($0) }
    let matches = nodes.filter { node in
        node.strings.contains {
            let candidate = normalize($0)
            return candidate == normalizedSelectedName
                || candidate.contains(normalizedSelectedName)
                || (candidate.count >= 3 && normalizedSelectedName.contains(candidate))
        }
    }
    match = matches.min(by: {
        ($0.frame?.minX ?? CGFloat.greatestFiniteMagnitude)
            < ($1.frame?.minX ?? CGFloat.greatestFiniteMagnitude)
    })
    if match != nil { break }
}
guard let match = match else {
    fail("person_not_found", output: output)
}
guard activate(match.element) else {
    fail("person_not_selectable", output: output)
}
Thread.sleep(forTimeInterval: 0.8)

if mode == "inspect" || mode == "inspectall" {
    Thread.sleep(forTimeInterval: 1.2)
    // inspect: detail pane only (the lookup path's view of the world).
    // inspectall: every node in the window, sidebar included — for UI
    // archaeology when the extraction misses something visible on screen.
    let nodes = mode == "inspect"
        ? detailNodesSnapshot()
        : windowsOf(appElement).flatMap { walk($0) }
    try writeJSON(
        InspectResult(
            status: "ok",
            selectedName: selectedName,
            detailStrings: uniqueStrings(nodes)
        ),
        to: output
    )
    exit(0)
}

// The pin callout renders asynchronously after selection — a single fixed
// sleep is exactly what made lookups flaky (the compass control was often the
// only address-like string in the early snapshot). Poll until the callout
// appears; keep the best heuristic string as a deadline fallback.
let deadline = Date().addingTimeInterval(6.0)
var callout: (label: String, updated: String)?
var bestFallback: (text: String, score: Int)?
var sawNoLocation = false
while true {
    let nodes = detailNodesSnapshot()
    if let found = bestCallout(in: nodes, selectedName: selectedName) {
        callout = found
        break
    }
    let strings = uniqueStrings(nodes)
    if strings.contains(where: { normalize($0) == "no location found" }) {
        // Terminal in principle, but Find My sometimes shows it briefly while
        // still locating — remember it and keep polling until the deadline.
        sawNoLocation = true
    }
    for text in strings {
        let score = locationScore(text, selectedName: selectedName)
        if score > 0,
           score > (bestFallback?.score ?? 0)
               || (score == bestFallback?.score && text.count > bestFallback!.text.count) {
            bestFallback = (text: text, score: score)
        }
    }
    if Date() >= deadline { break }
    Thread.sleep(forTimeInterval: 0.6)
}

// The pin callout only carries city granularity ("New York, NY • Now") even
// when the underlying fix is street-precise; the full address lives one press
// deeper, in the person's More Info card. A street-level string (digit +
// street suffix, score >= 6) can only belong to the selected person — list
// rows for OTHER people never show more than "City, ST", so the neighboring-
// row misattribution that rules out a generic whole-window fallback cannot
// produce a false street address here. Name-node proximity breaks any tie.
let streetScoreFloor = 6
func scanForStreetAddress(baseScore: Int) -> (label: String, updated: String?)? {
    let all = windowsOf(appElement).flatMap { walk($0) }
    var nameIndices: [Int] = []
    var candidates: [(index: Int, text: String, score: Int)] = []
    for (index, node) in all.enumerated() {
        for string in node.strings {
            if normalize(string) == normalizedSelectedName { nameIndices.append(index) }
            let text = parsePinCallout(string)?.label ?? string
            let score = locationScore(text, selectedName: selectedName)
            if score >= streetScoreFloor, score > baseScore,
               !candidates.contains(where: { $0.text == text }) {
                candidates.append((index: index, text: text, score: score))
            }
        }
    }
    guard let chosen = candidates.min(by: { lhs, rhs in
        let lhsDistance = nameIndices.map { abs($0 - lhs.index) }.min() ?? Int.max
        let rhsDistance = nameIndices.map { abs($0 - rhs.index) }.min() ?? Int.max
        if lhsDistance != rhsDistance { return lhsDistance < rhsDistance }
        return lhs.score > rhs.score
    }) else { return nil }
    return (chosen.text, callout?.updated ?? freshness(all.flatMap { $0.strings }))
}

func refineToStreetAddress() -> (label: String, updated: String?)? {
    let baseScore = callout.map { locationScore($0.label, selectedName: selectedName) } ?? 0
    guard baseScore < streetScoreFloor else { return nil }  // already street-level
    // The card can still be open from a previous lookup — read before pressing.
    if let found = scanForStreetAddress(baseScore: baseScore) { return found }
    guard
        let button = detailNodesSnapshot().first(where: { node in
            node.role == "AXButton" && node.strings.contains { normalize($0) == "more info" }
        }),
        AXUIElementPerformAction(button.element, kAXPressAction as CFString) == .success
    else { return nil }
    let refineDeadline = Date().addingTimeInterval(3.0)
    while Date() < refineDeadline {
        Thread.sleep(forTimeInterval: 0.5)
        if let found = scanForStreetAddress(baseScore: baseScore) { return found }
    }
    return nil
}

if let refined = refineToStreetAddress() {
    succeed(label: refined.label, updated: refined.updated, approximate: false)
}
if let callout = callout {
    succeed(
        label: callout.label,
        updated: callout.updated,
        approximate: locationScore(callout.label, selectedName: selectedName) < streetScoreFloor
    )
}

// No whole-window last resort for the CITY-level fallback on purpose: a
// sidebar scan could attach a NEIGHBORING row's "<place> • <freshness>" to
// the wrong person when the selected share has no location. Asking the user
// beats that every time.
if let fallback = bestFallback {
    succeed(label: fallback.text, updated: freshness(uniqueStrings(detailNodesSnapshot())))
}
fail(
    sawNoLocation ? "no_location_found" : "location_label_unavailable",
    output: output
)

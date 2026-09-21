// A new process executes this query for each sample. NSWorkspace notifications
// are deliberately not used: their cache can freeze inside a headless server.
import AppKit
import Foundation

guard let app = NSWorkspace.shared.frontmostApplication else {
    print("{\"readable\":false}")
    exit(0)
}
let value: [String: Any] = [
    "readable": true,
    "bundle_id": app.bundleIdentifier ?? "",
    "name": app.localizedName ?? "",
    "pid": app.processIdentifier
]
let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)

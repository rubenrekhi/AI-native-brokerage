//
//  SevinoApp.swift
//  Sevino
//
//  Created by Ruben Rekhi on 2026-03-24.
//

import SwiftUI

@main
struct SevinoApp: App {
    private static let isTesting = ProcessInfo.processInfo.environment.keys.contains("XCTestBundlePath")

    var body: some Scene {
        WindowGroup {
            if Self.isTesting {
                // Avoid initializing AuthService.shared (and the Supabase
                // connection) when the app is launched as a test host.
                Text(verbatim: "Running tests…")
            } else {
                ContentView()
            }
        }
    }
}

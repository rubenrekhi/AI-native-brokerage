import Foundation
@testable import Sevino

@MainActor
final class MockDictationController: DictationControlling {
    var status: DictationController.Status = .idle {
        didSet { if oldValue != status { onStatusChange?(status) } }
    }
    var transcript: String = "" {
        didSet { onTranscriptChange?(transcript) }
    }

    var onStatusChange: ((DictationController.Status) -> Void)?
    var onTranscriptChange: ((String) -> Void)?

    var isRecording: Bool { status == .recording }

    var startHandler: (() async -> Void)?

    private(set) var startCallCount = 0
    private(set) var stopCallCount = 0
    private(set) var resetCallCount = 0

    func start() async {
        startCallCount += 1
        if let startHandler {
            await startHandler()
        } else {
            status = .recording
        }
    }

    func stop() {
        stopCallCount += 1
        status = .idle
    }

    func reset() {
        resetCallCount += 1
        transcript = ""
    }
}

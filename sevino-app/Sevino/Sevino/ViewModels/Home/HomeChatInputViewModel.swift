import Foundation

@MainActor
@Observable
final class HomeChatInputViewModel {
    enum Alert: Equatable {
        case permissionDenied
        case unavailable
        case failed

        var message: String {
            switch self {
            case .permissionDenied: L10n.Home.dictationPermissionDenied
            case .unavailable: L10n.Home.dictationUnavailable
            case .failed: L10n.Home.dictationFailed
            }
        }
    }

    var alert: Alert?

    var isRecording: Bool { dictation.isRecording }

    private let dictation: any DictationControlling
    private let mention: TickerMentionViewModel
    private var baseText: String = ""
    private var startTask: Task<Void, Never>?

    init(
        mention: TickerMentionViewModel,
        dictation: (any DictationControlling)? = nil
    ) {
        self.dictation = dictation ?? DictationController()
        self.mention = mention
        self.dictation.onTranscriptChange = { [weak self] transcript in
            self?.applyTranscript(transcript)
        }
        self.dictation.onStatusChange = { [weak self] status in
            self?.handleStatusChange(status)
        }
    }

    func toggleDictation() {
        if isRecording {
            dictation.stop()
            return
        }
        baseText = mention.text
        startTask?.cancel()
        startTask = Task { [weak self] in
            await self?.dictation.start()
        }
    }

    func stopIfRecording() {
        startTask?.cancel()
        startTask = nil
        if isRecording { dictation.stop() }
    }

    private func applyTranscript(_ transcript: String) {
        guard isRecording else { return }
        let separator = baseText.isEmpty || transcript.isEmpty ? "" : " "
        mention.updateText(baseText + separator + transcript)
    }

    private func handleStatusChange(_ status: DictationController.Status) {
        switch status {
        case .permissionDenied: alert = .permissionDenied
        case .unavailable: alert = .unavailable
        case .failed: alert = .failed
        case .idle, .recording: break
        }
    }
}

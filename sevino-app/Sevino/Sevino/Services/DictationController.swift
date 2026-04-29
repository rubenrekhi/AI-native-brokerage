import AVFoundation
import Foundation
import Speech

@MainActor
protocol DictationControlling: AnyObject {
    var status: DictationController.Status { get }
    var transcript: String { get }
    var isRecording: Bool { get }
    var onStatusChange: ((DictationController.Status) -> Void)? { get set }
    var onTranscriptChange: ((String) -> Void)? { get set }
    func start() async
    func stop()
    func reset()
}

@MainActor
@Observable
final class DictationController: DictationControlling {
    enum Status: Equatable {
        case idle
        case recording
        case unavailable
        case permissionDenied
        case failed
    }

    private(set) var status: Status = .idle {
        didSet { if oldValue != status { onStatusChange?(status) } }
    }
    private(set) var transcript: String = "" {
        didSet { onTranscriptChange?(transcript) }
    }

    @ObservationIgnored var onStatusChange: ((Status) -> Void)?
    @ObservationIgnored var onTranscriptChange: ((String) -> Void)?

    private let recognizer: SFSpeechRecognizer?
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var isStarting = false

    init(locale: Locale = .current) {
        recognizer = SFSpeechRecognizer(locale: locale) ?? SFSpeechRecognizer()
    }

    var isRecording: Bool { status == .recording }

    func start() async {
        guard !isRecording, !isStarting else { return }
        guard let recognizer, recognizer.isAvailable else {
            status = .unavailable
            return
        }
        isStarting = true
        defer { isStarting = false }
        guard await requestPermissions() else { return }
        do {
            try beginRecognition(recognizer: recognizer)
            status = .recording
        } catch {
            cleanup()
            status = .failed
        }
    }

    func stop() {
        guard isRecording else { return }
        task?.finish()
        cleanup()
        status = .idle
    }

    func reset() {
        transcript = ""
    }

    private func requestPermissions() async -> Bool {
        let speech = await withCheckedContinuation { (continuation: CheckedContinuation<SFSpeechRecognizerAuthorizationStatus, Never>) in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard speech == .authorized else {
            status = .permissionDenied
            return false
        }
        let mic = await AVAudioApplication.requestRecordPermission()
        guard mic else {
            status = .permissionDenied
            return false
        }
        return true
    }

    private func beginRecognition(recognizer: SFSpeechRecognizer) throws {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: .duckOthers)
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        #endif

        let newRequest = SFSpeechAudioBufferRecognitionRequest()
        newRequest.shouldReportPartialResults = true
        request = newRequest
        transcript = ""

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            newRequest.append(buffer)
        }

        audioEngine.prepare()
        try audioEngine.start()

        task = recognizer.recognitionTask(with: newRequest) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString
            let isFinal = result?.isFinal ?? false
            let failed = error != nil
            Task { @MainActor [weak self] in
                guard let self else { return }
                if let text { self.transcript = text }
                if failed {
                    self.cleanup()
                    self.status = .failed
                    return
                }
                if isFinal { self.stop() }
            }
        }
    }

    private func cleanup() {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        request?.endAudio()
        request = nil
        task = nil
        #if os(iOS)
        do {
            try AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        } catch {
            #if DEBUG
            print("DictationController: failed to deactivate audio session — \(error)")
            #endif
        }
        #endif
    }
}

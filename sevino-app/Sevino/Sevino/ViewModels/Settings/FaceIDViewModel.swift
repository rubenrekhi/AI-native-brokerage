import LocalAuthentication
import SwiftUI

@Observable
final class FaceIDViewModel {
    private(set) var isFaceIDAvailable = false
    private(set) var biometricType: LABiometryType = .none
    private(set) var isAuthenticating = false
    private(set) var error: String?

    @ObservationIgnored
    @AppStorage("faceIDEnabled") var isEnabled = false

    private let contextFactory: @Sendable () -> LAContext

    init(contextFactory: @escaping @Sendable () -> LAContext = { LAContext() }) {
        self.contextFactory = contextFactory
    }

    func checkAvailability() {
        let context = contextFactory()
        var evalError: NSError?
        let canEvaluate = context.canEvaluatePolicy(
            .deviceOwnerAuthenticationWithBiometrics,
            error: &evalError
        )
        isFaceIDAvailable = canEvaluate
        biometricType = canEvaluate ? context.biometryType : .none
        error = canEvaluate ? nil : evalError?.localizedDescription
        if !canEvaluate {
            isEnabled = false
        }
    }

    func confirmEnable() async {
        let success = await authenticate()
        if !success {
            isEnabled = false
        }
    }

    func authenticate() async -> Bool {
        isAuthenticating = true
        defer { isAuthenticating = false }
        error = nil

        let context = contextFactory()
        var evalError: NSError?
        guard context.canEvaluatePolicy(
            .deviceOwnerAuthenticationWithBiometrics,
            error: &evalError
        ) else {
            error = evalError?.localizedDescription
            return false
        }

        do {
            return try await context.evaluatePolicy(
                .deviceOwnerAuthenticationWithBiometrics,
                localizedReason: L10n.Settings.biometricAuthReason
            )
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    var biometricTypeLabel: String? {
        switch biometricType {
        case .faceID: return L10n.Settings.faceIDName
        case .touchID: return L10n.Settings.touchIDName
        case .opticID: return L10n.Settings.opticIDName
        case .none: return nil
        @unknown default: return nil
        }
    }
}

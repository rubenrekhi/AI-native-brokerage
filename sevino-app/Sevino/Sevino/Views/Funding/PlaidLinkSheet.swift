import LinkKit
import SwiftUI
import UIKit

/// SwiftUI sheet wrapping Plaid LinkKit.
///
/// Constructed fresh each time `isShowingPlaidLink` flips true. Callbacks feed
/// the owning `FundingViewModel` (see Phase 5 wiring in `FundingMorphingView`).
struct PlaidLinkSheet: UIViewControllerRepresentable {

    let linkToken: String
    let onSuccess: (
        _ publicToken: String,
        _ accountId: String,
        _ institutionName: String?,
        _ accountMask: String?,
        _ accountName: String?
    ) -> Void
    let onExit: (_ error: Error?) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onSuccess: onSuccess, onExit: onExit)
    }

    func makeUIViewController(context: Context) -> UIViewController {
        let host = UIViewController()
        host.view.backgroundColor = .clear

        var config = LinkTokenConfiguration(token: linkToken) { success in
            let meta = success.metadata
            let first = meta.accounts.first
            context.coordinator.onSuccess(
                success.publicToken,
                first?.id ?? "",
                meta.institution.name,
                first?.mask,
                first?.name
            )
        }
        config.onExit = { exit in
            context.coordinator.onExit(exit.error)
        }

        switch Plaid.create(config) {
        case .success(let handler):
            // Retain across the sheet's lifetime — LinkKit tears down silently
            // if the handler is released before onSuccess fires.
            context.coordinator.handler = handler
            // Dispatch so the host view controller is in the window hierarchy
            // before Plaid presents on top of it.
            DispatchQueue.main.async {
                handler.open(presentUsing: .viewController(host))
            }
        case .failure(let error):
            DispatchQueue.main.async {
                context.coordinator.onExit(error)
            }
        }

        return host
    }

    func updateUIViewController(_ uiViewController: UIViewController, context: Context) {}

    final class Coordinator {
        var handler: Handler?
        let onSuccess: (String, String, String?, String?, String?) -> Void
        let onExit: (Error?) -> Void

        init(
            onSuccess: @escaping (String, String, String?, String?, String?) -> Void,
            onExit: @escaping (Error?) -> Void
        ) {
            self.onSuccess = onSuccess
            self.onExit = onExit
        }
    }
}

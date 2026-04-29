import Foundation
import SwiftUI

/// Drives the documents list screen. `documentType` filters the request —
/// pass `nil` for the combined list, or a broker category like
/// "account_statement" / "tax_1099" for a filtered view.
@Observable
final class DocumentsViewModel {
    let documentType: String?

    private let settingsService: any SettingsServiceProtocol

    private(set) var documents: [DocumentDTO] = []
    private(set) var isLoading = false
    private(set) var error: String?
    private(set) var previewURL: URL?
    private(set) var downloadingDocumentId: String?
    private(set) var downloadError: String?

    init(
        documentType: String? = nil,
        settingsService: any SettingsServiceProtocol = SettingsService.shared
    ) {
        self.documentType = documentType
        self.settingsService = settingsService
    }

    func load() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            documents = try await settingsService.listDocuments(type: documentType)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func reload() async {
        await load()
    }

    /// Downloads the document PDF and sets `previewURL` so the view can
    /// present the QuickLook sheet. Only one download runs at a time — the
    /// row UI disables itself while `downloadingDocumentId` is set.
    func openDocument(_ document: DocumentDTO) async {
        guard downloadingDocumentId == nil else { return }
        downloadError = nil
        downloadingDocumentId = document.id
        defer { downloadingDocumentId = nil }
        do {
            previewURL = try await settingsService.downloadDocument(id: document.id)
        } catch {
            self.downloadError = error.localizedDescription
        }
    }

    func clearPreview() {
        previewURL = nil
    }

    func clearError() {
        error = nil
    }

    func clearDownloadError() {
        downloadError = nil
    }

    var previewBinding: Binding<URL?> {
        Binding(
            get: { self.previewURL },
            set: { newValue in
                if newValue == nil { self.previewURL = nil }
            }
        )
    }

    var showDownloadErrorBinding: Binding<Bool> {
        Binding(
            get: { self.downloadError != nil },
            set: { newValue in
                if !newValue { self.downloadError = nil }
            }
        )
    }
}

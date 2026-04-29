import XCTest
@testable import Sevino

@MainActor
final class DocumentsViewModelTests: XCTestCase {

    private var mockSettings: MockSettingsService!

    override func setUp() {
        mockSettings = MockSettingsService()
    }

    override func tearDown() {
        mockSettings = nil
    }

    // MARK: - load

    func testLoadForwardsDocumentTypeFilter() async {
        let vm = DocumentsViewModel(documentType: "tax_1099", settingsService: mockSettings)

        await vm.load()

        XCTAssertEqual(mockSettings.listDocumentsCalls, ["tax_1099"])
    }

    func testLoadPopulatesDocumentsAndClearsLoading() async {
        let docs = [
            DocumentDTO(id: "a", type: "account_statement", date: "2026-03-01", name: "March statement"),
            DocumentDTO(id: "b", type: "tax_1099", date: "2026-01-31", name: nil),
        ]
        mockSettings.listDocumentsResult = .success(docs)
        let vm = DocumentsViewModel(documentType: nil, settingsService: mockSettings)

        await vm.load()

        XCTAssertEqual(vm.documents, docs)
        XCTAssertFalse(vm.isLoading)
        XCTAssertNil(vm.error)
    }

    func testLoadFailureSurfacesError() async {
        struct LoadError: LocalizedError {
            var errorDescription: String? { "boom" }
        }
        mockSettings.listDocumentsResult = .failure(LoadError())
        let vm = DocumentsViewModel(settingsService: mockSettings)

        await vm.load()

        XCTAssertTrue(vm.documents.isEmpty)
        XCTAssertEqual(vm.error, "boom")
    }

    // MARK: - openDocument

    func testOpenDocumentSetsPreviewURLOnSuccess() async {
        let localURL = URL(fileURLWithPath: "/tmp/preview.pdf")
        mockSettings.downloadDocumentResult = .success(localURL)
        let vm = DocumentsViewModel(settingsService: mockSettings)
        let doc = DocumentDTO(id: "doc-1", type: "account_statement", date: "2026-03-01", name: nil)

        await vm.openDocument(doc)

        XCTAssertEqual(mockSettings.downloadDocumentCalls, ["doc-1"])
        XCTAssertEqual(vm.previewURL, localURL)
        XCTAssertNil(vm.downloadError)
        XCTAssertNil(vm.downloadingDocumentId)
    }

    func testOpenDocumentFailureSurfacesDownloadError() async {
        struct DownloadError: LocalizedError {
            var errorDescription: String? { "no pdf" }
        }
        mockSettings.downloadDocumentResult = .failure(DownloadError())
        let vm = DocumentsViewModel(settingsService: mockSettings)
        let doc = DocumentDTO(id: "doc-2", type: "tax_1099", date: "2026-01-31", name: nil)

        await vm.openDocument(doc)

        XCTAssertNil(vm.previewURL)
        XCTAssertEqual(vm.downloadError, "no pdf")
        XCTAssertNil(vm.downloadingDocumentId)
    }

    func testOpenDocumentWhileAnotherDownloadInFlightIsNoOp() async {
        let resumedURL = URL(fileURLWithPath: "/tmp/first.pdf")
        let release = AsyncChannel()
        mockSettings.downloadDocumentHandler = { _ in
            await release.wait()
            return resumedURL
        }
        let vm = DocumentsViewModel(settingsService: mockSettings)
        let first = DocumentDTO(id: "first", type: "account_statement", date: "2026-03-01", name: nil)
        let second = DocumentDTO(id: "second", type: "tax_1099", date: "2026-01-31", name: nil)

        let firstTask = Task { await vm.openDocument(first) }
        // Wait until the first call has entered the mock (and set downloadingDocumentId).
        while mockSettings.downloadDocumentCalls.isEmpty { await Task.yield() }

        await vm.openDocument(second)

        XCTAssertEqual(mockSettings.downloadDocumentCalls, ["first"])
        XCTAssertNil(vm.previewURL)
        XCTAssertNil(vm.downloadError)
        XCTAssertEqual(vm.downloadingDocumentId, "first")

        release.signal()
        await firstTask.value
        XCTAssertEqual(vm.previewURL, resumedURL)
    }

    func testClearPreviewResetsURL() async {
        mockSettings.downloadDocumentResult = .success(URL(fileURLWithPath: "/tmp/x.pdf"))
        let vm = DocumentsViewModel(settingsService: mockSettings)
        await vm.openDocument(
            DocumentDTO(id: "a", type: "account_statement", date: "2026-03-01", name: nil)
        )
        XCTAssertNotNil(vm.previewURL)

        vm.clearPreview()

        XCTAssertNil(vm.previewURL)
    }
}

/// One-shot async gate used to pin a mock call in-flight until the test releases it.
private final class AsyncChannel: @unchecked Sendable {
    private var continuation: CheckedContinuation<Void, Never>?
    private var isSignaled = false
    private let lock = NSLock()

    func wait() async {
        await withCheckedContinuation { cont in
            lock.lock()
            if isSignaled {
                lock.unlock()
                cont.resume()
            } else {
                continuation = cont
                lock.unlock()
            }
        }
    }

    func signal() {
        lock.lock()
        isSignaled = true
        let cont = continuation
        continuation = nil
        lock.unlock()
        cont?.resume()
    }
}

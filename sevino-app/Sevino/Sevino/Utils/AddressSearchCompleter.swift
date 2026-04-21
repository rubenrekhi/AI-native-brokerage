import MapKit

@Observable
final class AddressSearchCompleter: NSObject, MKLocalSearchCompleterDelegate {
    var results: [MKLocalSearchCompletion] = []
    private let completer = MKLocalSearchCompleter()

    override init() {
        super.init()
        completer.delegate = self
        completer.resultTypes = .address
    }

    func search(_ query: String) {
        guard !query.isEmpty else { results = []; return }
        completer.queryFragment = query
    }

    func clear() {
        results = []
    }

    nonisolated func completerDidUpdateResults(_ completer: MKLocalSearchCompleter) {
        Task { @MainActor in
            self.results = completer.results
        }
    }

    nonisolated func completer(_ completer: MKLocalSearchCompleter, didFailWithError error: Error) {
        print("[AddressSearchCompleter] Search failed: \(error.localizedDescription)")
    }
}

extension MKLocalSearchCompletion: @retroactive @unchecked Sendable {}

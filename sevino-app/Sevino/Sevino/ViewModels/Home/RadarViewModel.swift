import Foundation

@Observable
final class RadarViewModel {
    private let service: any RadarServiceProtocol

    private(set) var radarItems: [RadarItem] = []
    private(set) var isLoading = false
    private(set) var error: String?

    init(service: any RadarServiceProtocol = PlaceholderRadarService.shared) {
        self.service = service
    }

    func loadRadar() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            radarItems = try await service.fetchRadar()
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func toggleStar(for id: String) {
        guard let idx = radarItems.firstIndex(where: { $0.id == id }) else { return }
        radarItems[idx].isStarred.toggle()
    }

    func clearError() {
        error = nil
    }
}

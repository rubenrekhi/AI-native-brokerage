import Foundation

struct IdentifiableOption: Identifiable, Hashable {
    let id = UUID()
    let value: String
}

extension Array where Element == String {
    var asIdentifiableOptions: [IdentifiableOption] {
        map { IdentifiableOption(value: $0) }
    }
}

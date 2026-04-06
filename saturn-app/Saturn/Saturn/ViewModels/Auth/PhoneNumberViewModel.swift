import Foundation

@Observable
final class PhoneNumberViewModel {
    private(set) var phoneNumber = ""

    var isPhoneValid: Bool {
        phoneNumber.filter(\.isNumber).count == 10
    }

    func updatePhoneNumber(_ newValue: String) {
        let formatted = formatPhone(newValue)
        if phoneNumber != formatted {
            phoneNumber = formatted
        }
    }

    private func formatPhone(_ raw: String) -> String {
        let digits = String(raw.filter(\.isNumber).prefix(10))
        guard !digits.isEmpty else { return "" }

        let count = digits.count
        if count <= 3 {
            return digits
        } else if count <= 6 {
            let area = digits.prefix(3)
            let rest = digits.dropFirst(3)
            return "(\(area)) \(rest)"
        } else {
            let area = digits.prefix(3)
            let mid = digits.dropFirst(3).prefix(3)
            let end = digits.dropFirst(6)
            return "(\(area)) \(mid)-\(end)"
        }
    }
}

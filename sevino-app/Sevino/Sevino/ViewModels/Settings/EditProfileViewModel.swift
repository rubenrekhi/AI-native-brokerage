import Foundation

/// Shared view model backing the EditName, EditPhone, and EditAddress sheets.
/// Each `save*` method builds a `ProfileUpdateRequest` that carries only the
/// fields being edited and calls `SettingsServiceProtocol.updateProfile(_:)`.
@Observable
final class EditProfileViewModel {
    private let service: any SettingsServiceProtocol

    private(set) var isLoading = false
    private(set) var error: String?
    private(set) var didSave = false

    init(service: any SettingsServiceProtocol = SettingsService.shared) {
        self.service = service
    }

    func saveName(first: String, middle: String?, last: String) async {
        let trimmedFirst = first.trimmingCharacters(in: .whitespaces)
        let trimmedLast = last.trimmingCharacters(in: .whitespaces)
        let trimmedMiddle = middle?.trimmingCharacters(in: .whitespaces)

        guard !trimmedFirst.isEmpty, !trimmedLast.isEmpty else {
            error = L10n.Settings.editNameValidationError
            return
        }

        var request = ProfileUpdateRequest()
        request.firstName = trimmedFirst
        request.lastName = trimmedLast
        if let trimmedMiddle, !trimmedMiddle.isEmpty {
            request.middleName = trimmedMiddle
        }
        await submit(request)
    }

    func savePhone(_ phone: String) async {
        let trimmed = phone.trimmingCharacters(in: .whitespaces)
        guard Self.isValidPhone(trimmed) else {
            error = L10n.Settings.editPhoneValidationError
            return
        }

        var request = ProfileUpdateRequest()
        request.phoneNumber = trimmed
        await submit(request)
    }

    func saveAddress(street: [String], city: String, state: String, postalCode: String) async {
        var request = ProfileUpdateRequest()
        request.streetAddress = street
        request.city = city
        request.state = state
        request.postalCode = postalCode
        await submit(request)
    }

    func clearError() {
        error = nil
    }

    /// `ProfileUpdateRequest` accepts any subset of fields; validation lives in
    /// the caller so each sheet can surface field-specific error messages.
    private func submit(_ request: ProfileUpdateRequest) async {
        error = nil
        didSave = false
        isLoading = true
        defer { isLoading = false }
        do {
            _ = try await service.updateProfile(request)
            didSave = true
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// Minimal phone validation: 10–15 digits after stripping non-digit chars.
    /// Alpaca enforces E.164 on the backend; this just blocks obviously bad input.
    static func isValidPhone(_ raw: String) -> Bool {
        let digits = raw.filter(\.isNumber)
        return (10...15).contains(digits.count)
    }
}

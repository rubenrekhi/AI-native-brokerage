import Testing
@testable import Sevino

@Suite("PhoneFormatter")
struct PhoneFormatterTests {
    @Test("Formats 10-digit input")
    func formats10Digits() {
        #expect(PhoneFormatter.format("5551234567") == "(555) 123-4567")
    }

    @Test("Formats 11-digit US input by stripping leading 1")
    func formats11DigitsUS() {
        #expect(PhoneFormatter.format("15551234567") == "(555) 123-4567")
    }

    @Test("Formats E.164 with + prefix")
    func formatsE164() {
        #expect(PhoneFormatter.format("+15551234567") == "(555) 123-4567")
    }

    @Test("Strips embedded formatting characters")
    func stripsFormatting() {
        #expect(PhoneFormatter.format("+1 (555) 123 4567") == "(555) 123-4567")
        #expect(PhoneFormatter.format("(555) 123-4567") == "(555) 123-4567")
    }

    @Test("Returns input unchanged for empty string")
    func passesThroughEmpty() {
        #expect(PhoneFormatter.format("") == "")
    }

    @Test("Returns input unchanged for too few digits")
    func passesThroughShort() {
        #expect(PhoneFormatter.format("123") == "123")
    }

    @Test("Returns input unchanged for non-US 11-digit input")
    func passesThroughNonUS11() {
        // 11 digits without a leading "1" — out of scope until we support
        // non-US sign-ups, so leave the raw value alone instead of guessing.
        #expect(PhoneFormatter.format("44123456789") == "44123456789")
    }
}

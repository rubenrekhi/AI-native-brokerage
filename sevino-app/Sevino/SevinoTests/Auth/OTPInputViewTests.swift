import Testing
@testable import Sevino

@Suite("OTPInputView.sanitize")
struct OTPInputViewSanitizeTests {

    @Test("Strips non-digit characters")
    func stripsNonDigits() {
        #expect(OTPInputView.sanitize("AB12-34") == "1234")
        #expect(OTPInputView.sanitize("12 34") == "1234")
        #expect(OTPInputView.sanitize("(1)(2)") == "12")
    }

    @Test("Caps at six digits")
    func capsAtSixDigits() {
        #expect(OTPInputView.sanitize("123456789") == "123456")
        #expect(OTPInputView.sanitize("000000111") == "000000")
    }

    @Test("Preserves empty input")
    func preservesEmpty() {
        #expect(OTPInputView.sanitize("") == "")
    }

    @Test("Preserves valid 6-digit input")
    func preservesSixDigits() {
        #expect(OTPInputView.sanitize("123456") == "123456")
    }

    @Test("Preserves shorter all-digit input")
    func preservesPartial() {
        #expect(OTPInputView.sanitize("123") == "123")
    }

    @Test("Mixed input with letters past the 6th digit is still capped")
    func mixedInputCappedAtSix() {
        #expect(OTPInputView.sanitize("ABC123456789XYZ") == "123456")
    }
}

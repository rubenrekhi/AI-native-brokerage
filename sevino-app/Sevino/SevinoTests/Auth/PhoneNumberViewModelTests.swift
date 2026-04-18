import Testing
@testable import Sevino

@Suite("PhoneNumberViewModel")
struct PhoneNumberViewModelTests {
    @Test("Empty phone is invalid")
    func emptyPhoneIsInvalid() {
        let vm = PhoneNumberViewModel()
        #expect(!vm.isPhoneValid)
    }

    @Test("Partial phone is invalid")
    func partialPhoneIsInvalid() {
        let vm = PhoneNumberViewModel()
        vm.updatePhoneNumber("12345")
        #expect(!vm.isPhoneValid)
    }

    @Test("10 digits is valid")
    func tenDigitsIsValid() {
        let vm = PhoneNumberViewModel()
        vm.updatePhoneNumber("1234567890")
        #expect(vm.isPhoneValid)
    }

    @Test("Formats 3 digits without parentheses")
    func formatsThreeDigits() {
        let vm = PhoneNumberViewModel()
        vm.updatePhoneNumber("123")
        #expect(vm.phoneNumber == "123")
    }

    @Test("Formats 4 digits with area code")
    func formatsFourDigits() {
        let vm = PhoneNumberViewModel()
        vm.updatePhoneNumber("1234")
        #expect(vm.phoneNumber == "(123) 4")
    }

    @Test("Formats 7 digits with dash")
    func formatsSevenDigits() {
        let vm = PhoneNumberViewModel()
        vm.updatePhoneNumber("1234567")
        #expect(vm.phoneNumber == "(123) 456-7")
    }

    @Test("Formats full 10 digits")
    func formatsFullNumber() {
        let vm = PhoneNumberViewModel()
        vm.updatePhoneNumber("1234567890")
        #expect(vm.phoneNumber == "(123) 456-7890")
    }

    @Test("Strips non-digit characters")
    func stripsNonDigits() {
        let vm = PhoneNumberViewModel()
        vm.updatePhoneNumber("(123) 456-7890")
        #expect(vm.phoneNumber == "(123) 456-7890")
        #expect(vm.isPhoneValid)
    }

    @Test("Caps at 10 digits")
    func capsAtTenDigits() {
        let vm = PhoneNumberViewModel()
        vm.updatePhoneNumber("12345678901234")
        #expect(vm.phoneNumber == "(123) 456-7890")
    }

    @Test("Empty input clears number")
    func emptyInputClears() {
        let vm = PhoneNumberViewModel()
        vm.updatePhoneNumber("123")
        vm.updatePhoneNumber("")
        #expect(vm.phoneNumber == "")
        #expect(!vm.isPhoneValid)
    }
}

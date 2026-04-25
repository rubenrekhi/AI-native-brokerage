import XCTest
@testable import Sevino

@MainActor
final class PersonalDetailsSheetTests: XCTestCase {

    // MARK: countryName(forCode:)

    func testCountryNameMapsAlpha3ToLocalizedName() {
        // Locale is forced to en_US in the helper via Locale.current; this
        // assertion only checks the mapping is applied (alpha-3 → alpha-2 →
        // localized), tolerating locale variance for the actual string.
        let name = PersonalDetailsSheet.countryName(forCode: "USA")
        XCTAssertNotNil(name)
        XCTAssertNotEqual(name, "USA", "Expected alpha-3 to be mapped, not echoed")
    }

    func testCountryNameAcceptsAlpha2Directly() {
        let name = PersonalDetailsSheet.countryName(forCode: "US")
        XCTAssertNotNil(name)
        XCTAssertNotEqual(name, "US")
    }

    func testCountryNameReturnsRawCodeForUnknownAlpha3() {
        XCTAssertEqual(PersonalDetailsSheet.countryName(forCode: "XYZ"), "XYZ")
    }

    func testCountryNameReturnsNilForNil() {
        XCTAssertNil(PersonalDetailsSheet.countryName(forCode: nil))
    }

    func testCountryNameReturnsNilForEmpty() {
        XCTAssertNil(PersonalDetailsSheet.countryName(forCode: ""))
        XCTAssertNil(PersonalDetailsSheet.countryName(forCode: "   "))
    }

    func testCountryNameUppercasesInput() {
        let lower = PersonalDetailsSheet.countryName(forCode: "usa")
        let upper = PersonalDetailsSheet.countryName(forCode: "USA")
        XCTAssertEqual(lower, upper)
    }

    // MARK: maskedSSN(forLast4:)

    func testMaskedSSNRendersWhenLast4Present() {
        XCTAssertEqual(PersonalDetailsSheet.maskedSSN(forLast4: "6789"), "•••-••-6789")
    }

    func testMaskedSSNTrimsWhitespace() {
        XCTAssertEqual(PersonalDetailsSheet.maskedSSN(forLast4: " 6789 "), "•••-••-6789")
    }

    func testMaskedSSNReturnsNilForNil() {
        XCTAssertNil(PersonalDetailsSheet.maskedSSN(forLast4: nil))
    }

    func testMaskedSSNReturnsNilForWrongLength() {
        XCTAssertNil(PersonalDetailsSheet.maskedSSN(forLast4: ""))
        XCTAssertNil(PersonalDetailsSheet.maskedSSN(forLast4: "678"))
        XCTAssertNil(PersonalDetailsSheet.maskedSSN(forLast4: "67890"))
    }

    // MARK: formattedDateOfBirth

    func testFormattedDateOfBirthParsesISO() {
        let result = PersonalDetailsSheet.formattedDateOfBirth("1992-04-15")
        XCTAssertNotNil(result)
        XCTAssertNotEqual(result, "1992-04-15", "Expected ISO date to be reformatted")
    }

    func testFormattedDateOfBirthFallsBackToRawOnInvalidFormat() {
        XCTAssertEqual(PersonalDetailsSheet.formattedDateOfBirth("not-a-date"), "not-a-date")
    }

    func testFormattedDateOfBirthReturnsNilForNil() {
        XCTAssertNil(PersonalDetailsSheet.formattedDateOfBirth(nil))
    }
}

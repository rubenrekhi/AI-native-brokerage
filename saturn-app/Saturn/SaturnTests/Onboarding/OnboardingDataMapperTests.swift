import XCTest
@testable import Saturn

final class OnboardingDataMapperTests: XCTestCase {

    // MARK: - formatDateOfBirth

    func testFormatDOBStandard() {
        XCTAssertEqual(OnboardingDataMapper.formatDateOfBirth("03-15-1998"), "1998-03-15")
    }

    func testFormatDOBSingleDigitMonthDay() {
        XCTAssertEqual(OnboardingDataMapper.formatDateOfBirth("1-5-2000"), "2000-1-5")
    }

    func testFormatDOBInvalidFormat() {
        // Not enough parts — returns original string
        XCTAssertEqual(OnboardingDataMapper.formatDateOfBirth("1998"), "1998")
    }

    func testFormatDOBEmptyString() {
        XCTAssertEqual(OnboardingDataMapper.formatDateOfBirth(""), "")
    }

    // MARK: - splitLegalName

    func testSplitFirstAndLast() {
        let (first, last) = OnboardingDataMapper.splitLegalName("Riley Johnson")
        XCTAssertEqual(first, "Riley")
        XCTAssertEqual(last, "Johnson")
    }

    func testSplitFirstOnly() {
        let (first, last) = OnboardingDataMapper.splitLegalName("Riley")
        XCTAssertEqual(first, "Riley")
        XCTAssertEqual(last, "")
    }

    func testSplitThreeNames() {
        // "Riley James Johnson" → first="Riley", last="James Johnson"
        let (first, last) = OnboardingDataMapper.splitLegalName("Riley James Johnson")
        XCTAssertEqual(first, "Riley")
        XCTAssertEqual(last, "James Johnson")
    }

    func testSplitEmptyString() {
        let (first, last) = OnboardingDataMapper.splitLegalName("")
        XCTAssertEqual(first, "")
        XCTAssertEqual(last, "")
    }

    // MARK: - normalizeEmploymentStatus

    func testNormalizeEmployed() {
        XCTAssertEqual(OnboardingDataMapper.normalizeEmploymentStatus("Employed"), "employed")
    }

    func testNormalizeSelfEmployed() {
        XCTAssertEqual(OnboardingDataMapper.normalizeEmploymentStatus("Self-Employed"), "self_employed")
    }

    func testNormalizeUnemployed() {
        XCTAssertEqual(OnboardingDataMapper.normalizeEmploymentStatus("Unemployed"), "unemployed")
    }

    func testNormalizeStudent() {
        XCTAssertEqual(OnboardingDataMapper.normalizeEmploymentStatus("Student"), "student")
    }

    func testNormalizeRetired() {
        XCTAssertEqual(OnboardingDataMapper.normalizeEmploymentStatus("Retired"), "retired")
    }

    // MARK: - normalizeFundingSource

    func testNormalizeEmploymentIncome() {
        XCTAssertEqual(OnboardingDataMapper.normalizeFundingSource("Employment Income"), "employment_income")
    }

    func testNormalizeSavings() {
        XCTAssertEqual(OnboardingDataMapper.normalizeFundingSource("Savings"), "savings")
    }

    func testNormalizeBusinessIncome() {
        XCTAssertEqual(OnboardingDataMapper.normalizeFundingSource("Business income"), "business_income")
    }

    func testNormalizeExistingInvestments() {
        XCTAssertEqual(OnboardingDataMapper.normalizeFundingSource("Existing investments"), "investments")
    }

    // MARK: - buildAttribution

    func testAttributionWithExtra() {
        XCTAssertEqual(
            OnboardingDataMapper.buildAttribution(source: "Friend", extra: "John"),
            "Friend: John"
        )
    }

    func testAttributionWithoutExtra() {
        XCTAssertEqual(
            OnboardingDataMapper.buildAttribution(source: "TikTok", extra: nil),
            "TikTok"
        )
    }

    func testAttributionWithEmptyExtra() {
        XCTAssertEqual(
            OnboardingDataMapper.buildAttribution(source: "Reddit", extra: ""),
            "Reddit"
        )
    }
}

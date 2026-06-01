import XCTest
@testable import Sevino

final class USStateCodesTests: XCTestCase {

    func testAcceptsUSStates() {
        XCTAssertTrue(USStateCodes.isValid("CA"))
        XCTAssertTrue(USStateCodes.isValid("NY"))
    }

    func testAcceptsDCAndTerritories() {
        XCTAssertTrue(USStateCodes.isValid("DC"))
        XCTAssertTrue(USStateCodes.isValid("PR"))
        XCTAssertTrue(USStateCodes.isValid("GU"))
    }

    func testRejectsCanadianProvinces() {
        XCTAssertFalse(USStateCodes.isValid("ON"))
        XCTAssertFalse(USStateCodes.isValid("QC"))
        XCTAssertFalse(USStateCodes.isValid("BC"))
    }

    func testNormalizesCaseAndWhitespace() {
        XCTAssertTrue(USStateCodes.isValid(" ca "))
        XCTAssertTrue(USStateCodes.isValid("ny"))
    }

    func testRejectsEmptyAndUnknown() {
        XCTAssertFalse(USStateCodes.isValid(""))
        XCTAssertFalse(USStateCodes.isValid("XX"))
        XCTAssertFalse(USStateCodes.isValid("California"))
    }

    func testCoversFiftyStatesPlusDCAndSixTerritories() {
        XCTAssertEqual(USStateCodes.all.count, 57)
    }
}

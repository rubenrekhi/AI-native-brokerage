import XCTest
@testable import Sevino

@MainActor
final class OnboardingResumeManagerTests: XCTestCase {

    // MARK: - Routing to Home

    func testCompletedOnboardingGoesToHome() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: true,
            onboardingStep: "submitted",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .home = OnboardingResumeManager.destination(from: status) {
        } else {
            XCTFail("Expected .home")
        }
    }

    func testSubmittedStepGoesToHome() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "submitted",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .home = OnboardingResumeManager.destination(from: status) {
        } else {
            XCTFail("Expected .home")
        }
    }

    // MARK: - Routing to Onboarding (Phase 1)

    func testNilStepStartsOnboardingFromBeginning() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: nil,
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .onboarding(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 1)
        } else {
            XCTFail("Expected .onboarding")
        }
    }

    func testWelcomeStepResumesAtStep2() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "welcome",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .onboarding(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 2)
        } else {
            XCTFail("Expected .onboarding")
        }
    }

    func testPreferredNameResumesAtStep3() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "preferred_name",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .onboarding(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 3)
        } else {
            XCTFail("Expected .onboarding")
        }
    }

    func testAnnualIncomeResumesAtStep10() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "annual_income",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .onboarding(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 10)
        } else {
            XCTFail("Expected .onboarding")
        }
    }

    func testExperienceResumesAtStep17() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "experience",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .onboarding(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 17)
        } else {
            XCTFail("Expected .onboarding")
        }
    }

    // MARK: - Phase 1 complete → Alpaca Setup

    func testRiskDisclosureGoesToAlpacaSetup() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "risk_disclosure",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .alpacaSetup(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 1)
        } else {
            XCTFail("Expected .alpacaSetup")
        }
    }

    // MARK: - Routing to Alpaca Setup (Phase 2)

    func testKycIntroResumesAtStep2() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "kyc_intro",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .alpacaSetup(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 2)
        } else {
            XCTFail("Expected .alpacaSetup")
        }
    }

    func testLegalNameResumesAtAddress() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "legal_name",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .alpacaSetup(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 3, "legal_name should resume at address screen")
        } else {
            XCTFail("Expected .alpacaSetup")
        }
    }

    func testAddressResumesAtCitizenship() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "address",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .alpacaSetup(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 4, "address should resume at citizenship screen")
        } else {
            XCTFail("Expected .alpacaSetup")
        }
    }

    func testEmploymentResumesAtFundingSources() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "employment",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .alpacaSetup(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 6, "employment should resume at funding sources screen")
        } else {
            XCTFail("Expected .alpacaSetup")
        }
    }

    func testFundingSourcesResumesAtSSN() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "funding_sources",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .alpacaSetup(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 7, "funding_sources should resume at SSN screen")
        } else {
            XCTFail("Expected .alpacaSetup")
        }
    }

    func testDisclosuresResumesAtSSN() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "disclosures",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .alpacaSetup(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 7, "Steps past SSN should resume at SSN screen")
        } else {
            XCTFail("Expected .alpacaSetup")
        }
    }

    func testAgreementsResumesAtSSN() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "agreements",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .alpacaSetup(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 7, "Steps past SSN should resume at SSN screen")
        } else {
            XCTFail("Expected .alpacaSetup")
        }
    }

    // MARK: - Resume data population

    func testOnboardingResumeDataPopulatedFromStatus() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "annual_income",
            profile: ProfileData(
                preferredName: "Riley",
                dateOfBirth: "1998-03-15",
                attributionSource: "TikTok"
            ),
            financialProfile: FinancialProfileData(
                financialWorries: ["not_saving_enough"],
                investmentGoals: ["grow_wealth", "retirement"],
                annualIncome: "$50K – $99K"
            ),
            phoneVerified: true
        )

        if case .onboarding(_, let data) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(data.userName, "Riley")
            XCTAssertEqual(data.referralSource, "TikTok")
            XCTAssertEqual(data.mindsetSelections, ["not_saving_enough"])
            XCTAssertEqual(data.goalSelections, ["grow_wealth", "retirement"])
            XCTAssertEqual(data.incomeSelection, "$50K – $99K")
            // DOB should be converted from YYYY-MM-DD to MM-DD-YYYY
            XCTAssertEqual(data.dobString, "03-15-1998")
        } else {
            XCTFail("Expected .onboarding")
        }
    }

    func testAlpacaResumeDataPopulatedFromStatus() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "employment",
            profile: ProfileData(
                preferredName: "Riley",
                firstName: "Riley",
                lastName: "Johnson",
                streetAddress: ["123 Main St"],
                city: "New York",
                state: "NY",
                postalCode: "10001"
            ),
            financialProfile: FinancialProfileData(
                employmentInfo: ["employment_status": "employed", "employer_name": "Acme"],
                fundingSources: ["savings"]
            ),
            phoneVerified: true
        )

        if case .alpacaSetup(_, let data) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(data.userName, "Riley")
            XCTAssertEqual(data.legalName, "Riley Johnson")
            XCTAssertTrue(data.address.contains("New York"))
            XCTAssertEqual(data.streetAddress, "123 Main St")
            XCTAssertEqual(data.city, "New York")
            XCTAssertEqual(data.state, "NY")
            XCTAssertEqual(data.postalCode, "10001")
            XCTAssertEqual(data.employmentStatus, L10n.Onboarding.alpacaStatusEmployed)
            XCTAssertEqual(data.employerName, "Acme")
            XCTAssertEqual(data.fundingSources, [L10n.Onboarding.alpacaFundingSavings])
        } else {
            XCTFail("Expected .alpacaSetup")
        }
    }

    // MARK: - Unknown step fallback

    func testUnknownStepStartsFromBeginning() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "unknown_step",
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        if case .onboarding(let step, _) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(step, 1)
        } else {
            XCTFail("Expected .onboarding from beginning")
        }
    }

    // MARK: - Phone verification (SEV-448)

    func testUnverifiedWithPhoneRoutesToPhoneVerification() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: nil,
            profile: nil,
            financialProfile: nil,
            phoneVerified: false,
            phoneNumber: "+15551234567"
        )
        if case .phoneVerification(let phone) = OnboardingResumeManager.destination(from: status) {
            XCTAssertEqual(phone, "(555) 123-4567",
                           "phone is formatted for display so the resume screen matches the entry-view shape")
        } else {
            XCTFail("Expected .phoneVerification")
        }
    }

    func testUnverifiedWithoutPhoneRoutesToPhoneCapture() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: nil,
            profile: nil,
            financialProfile: nil,
            phoneVerified: false,
            phoneNumber: nil
        )
        if case .phone = OnboardingResumeManager.destination(from: status) {
            // pass
        } else {
            XCTFail("Expected .phone")
        }
    }

    func testUnverifiedWithEmptyPhoneRoutesToPhoneCapture() {
        let status = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: nil,
            profile: nil,
            financialProfile: nil,
            phoneVerified: false,
            phoneNumber: ""
        )
        if case .phone = OnboardingResumeManager.destination(from: status) {
            // pass
        } else {
            XCTFail("Expected .phone for empty phone string")
        }
    }

    func testCompletedOnboardingTakesPrecedenceOverUnverifiedPhone() {
        // Data-drift safety: a fully-onboarded user reaches home even if
        // phoneVerified is false (e.g. status response missing the field).
        let status = OnboardingStatusResponse(
            onboardingCompleted: true,
            onboardingStep: "submitted",
            profile: nil,
            financialProfile: nil,
            phoneVerified: false,
            phoneNumber: nil
        )
        if case .home = OnboardingResumeManager.destination(from: status) {
            // pass
        } else {
            XCTFail("Expected .home to take precedence")
        }
    }
}

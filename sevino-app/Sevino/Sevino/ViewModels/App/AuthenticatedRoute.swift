import Foundation

/// Mutually exclusive destinations for the authenticated root view. A single
/// enum replaces a fan of booleans so transitions are explicit and impossible
/// combinations (e.g. showing both onboarding and phone) are unrepresentable.
/// Paired with `ContentView.AuthRoute` which covers the pre-auth surface.
enum AuthenticatedRoute: Equatable {
    /// Pre-check state: the status fetch has not yet started. Distinct from
    /// `.home` so the view renders a neutral splash on cold launch rather than
    /// briefly mounting `HomeView`.
    case idle
    case loading
    case statusCheckFailed
    /// Inserted before `.phone` so a user with an unverified email can never
    /// reach phone capture / onboarding. The email is read from the active
    /// Supabase session and forwarded so the OTP screen title reflects it.
    case emailVerification(email: String)
    case phone
    /// Inserted between `.phone` and `.onboarding` so a user can't enter the
    /// 18-step onboarding without first verifying the SMS OTP. The phone number
    /// is the formatted display string (e.g. `"(555) 123-4567"`) used by the
    /// title and forwarded to the verification service.
    case phoneVerification(phoneNumber: String)
    case onboarding(step: Int, data: OnboardingResumeManager.OnboardingResumeData?)
    case alpacaSetup(step: Int, userName: String, data: OnboardingResumeManager.AlpacaResumeData?)
    case home
}

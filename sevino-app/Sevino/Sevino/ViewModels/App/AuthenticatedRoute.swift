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
    case phone
    case onboarding(step: Int, data: OnboardingResumeManager.OnboardingResumeData?)
    case alpacaSetup(step: Int, userName: String, data: OnboardingResumeManager.AlpacaResumeData?)
    case home
}

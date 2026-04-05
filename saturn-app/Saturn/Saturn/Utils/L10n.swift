import Foundation

enum L10n {

    enum General {
        static let appName = String(localized: "general.app_name")
    }

    enum Auth {
        static let signIn = String(localized: "auth.sign_in")
        static let signUp = String(localized: "auth.sign_up")
        static let signOut = String(localized: "auth.sign_out")
        static let emailPlaceholder = String(localized: "auth.email_placeholder")
        static let passwordPlaceholder = String(localized: "auth.password_placeholder")
        static let emailConfirmation = String(localized: "auth.email_confirmation")
        static let switchToSignIn = String(localized: "auth.switch_to_sign_in")
        static let switchToSignUp = String(localized: "auth.switch_to_sign_up")
    }
}

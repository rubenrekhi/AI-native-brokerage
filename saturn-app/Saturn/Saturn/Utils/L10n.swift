import Foundation
import SwiftUI

enum L10n {

    enum General {
        static let appName = String(localized: "general.app_name")
        static let back = String(localized: "general.back")
    }

    enum Auth {
        static let signIn = String(localized: "auth.sign_in")
        static let signUp = String(localized: "auth.sign_up")
        static let signOut = String(localized: "auth.sign_out")
        static let signUpTitle = String(localized: "auth.sign_up_title")
        static let signUpSubtitle = String(localized: "auth.sign_up_subtitle")
        static let signInTitle = String(localized: "auth.sign_in_title")
        static let signInSubtitle = String(localized: "auth.sign_in_subtitle")
        static let continueWithGoogle = String(localized: "auth.continue_with_google")
        static let continueWithApple = String(localized: "auth.continue_with_apple")
        static let orDivider = String(localized: "auth.or_divider")
        static let phoneTitle = String(localized: "auth.phone_title")
        static let phoneSubtitle = String(localized: "auth.phone_subtitle")
        static let phoneLabel = String(localized: "auth.phone_label")
        static let phoneNext = String(localized: "auth.phone_next")
        static let phoneCountryCode = String(localized: "auth.phone_country_code")
        static let phonePlaceholder = String(localized: "auth.phone_placeholder")
        static let emailPlaceholder = String(localized: "auth.email_placeholder")
        static let passwordPlaceholder = String(localized: "auth.password_placeholder")
        static let emailConfirmation = String(localized: "auth.email_confirmation")
        static let switchToSignIn = String(localized: "auth.switch_to_sign_in")
        static let switchToSignUp = String(localized: "auth.switch_to_sign_up")
        static let reqUppercase = String(localized: "auth.req_uppercase")
        static let reqLowercase = String(localized: "auth.req_lowercase")
        static let reqNumber = String(localized: "auth.req_number")
        static let reqLength = String(localized: "auth.req_length")
        static let reqSpecialChar = String(localized: "auth.req_special_char")
        static let reqNoSpaces = String(localized: "auth.req_no_spaces")
        static let reqContainsAt = String(localized: "auth.req_contains_at")
        static let reqValidDomain = String(localized: "auth.req_valid_domain")
        static let legalDisclaimer: LocalizedStringKey = "auth.legal_disclaimer"
    }

    enum Welcome {
        static let page1Title = String(localized: "welcome.page1_title")
        static let page1Subtitle = String(localized: "welcome.page1_subtitle")
        static let page2Title = String(localized: "welcome.page2_title")
        static let page2Subtitle = String(localized: "welcome.page2_subtitle")
        static let page3Title = String(localized: "welcome.page3_title")
        static let page3Subtitle = String(localized: "welcome.page3_subtitle")
        static let page4Title = String(localized: "welcome.page4_title")
        static let page4Subtitle = String(localized: "welcome.page4_subtitle")
        static let portfolioLabel = String(localized: "welcome.portfolio_label")
        static let portfolioValue = String(localized: "welcome.portfolio_value")
        static let portfolioGain = String(localized: "welcome.portfolio_gain")
        static let protectedValue = String(localized: "welcome.protected_value")
        static let tradeUserMessage = String(localized: "welcome.trade_user_message")
        static let tradeAIResponse = String(localized: "welcome.trade_ai_response")
        static let tradeStockName = String(localized: "welcome.trade_stock_name")
        static let tradeStockTicker = String(localized: "welcome.trade_stock_ticker")
        static let tradeEstimatedTotal = String(localized: "welcome.trade_estimated_total")
        static let tradeEstimatedValue = String(localized: "welcome.trade_estimated_value")
        static let tradeHoldToConfirm = String(localized: "welcome.trade_hold_to_confirm")
        static let researchQuery = String(localized: "welcome.research_query")
        static let logIn = String(localized: "welcome.log_in")
        static let signUp = String(localized: "welcome.sign_up")
    }
}

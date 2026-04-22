import Foundation

enum AppConfig {
    static var supabaseURL: String {
        Bundle.main.infoDictionary?["SUPABASE_URL"] as? String ?? ""
    }

    static var supabaseAnonKey: String {
        Bundle.main.infoDictionary?["SUPABASE_ANON_KEY"] as? String ?? ""
    }

    static var apiBaseURL: String {
        Bundle.main.infoDictionary?["API_BASE_URL"] as? String ?? ""
    }

    static var apiKey: String {
        Bundle.main.infoDictionary?["API_KEY"] as? String ?? ""
    }

    enum Contact {
        static let founderPhoneNumber = "4169189713"
        static let supportEmail = "admin@sevino.ai"

        static var founderPhoneURL: URL? { URL(string: "tel:\(founderPhoneNumber)") }
        static var founderTextURL: URL? { URL(string: "sms:\(founderPhoneNumber)") }
        static var supportEmailURL: URL? { URL(string: "mailto:\(supportEmail)") }
    }
}

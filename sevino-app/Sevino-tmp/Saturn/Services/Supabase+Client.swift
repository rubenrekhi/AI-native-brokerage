import Foundation
import Supabase

let supabase: SupabaseClient = {
    guard let url = URL(string: AppConfig.supabaseURL), !AppConfig.supabaseURL.isEmpty else {
        fatalError("SUPABASE_URL is missing or invalid in Info.plist build settings.")
    }
    return SupabaseClient(supabaseURL: url, supabaseKey: AppConfig.supabaseAnonKey)
}()

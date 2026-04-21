import SwiftUI

struct LinkedAccount: Identifiable {
    let id = UUID()
    let name: String
    let bankName: String
    let lastFour: String
    let logoDomain: String
}

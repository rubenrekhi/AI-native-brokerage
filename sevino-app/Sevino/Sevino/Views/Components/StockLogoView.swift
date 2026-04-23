import SwiftUI

/// Displays a company logo.
///
/// Two ways to create it:
/// - `init(ticker:size:)` — constructs the FMP logo URL from a symbol. Fallback letter is the ticker's first character.
/// - `init(logoUrl:size:)` — loads from a URL returned by the API. Fallback letter is derived from the URL filename (e.g. `.../TSLA.png` → "T"), or "?" when unavailable.
struct StockLogoView: View {
    private let url: URL?
    private let fallbackLetter: String
    let size: CGFloat

    init(ticker: String, size: CGFloat) {
        self.url = URL(string: "https://financialmodelingprep.com/image-stock/\(ticker).png")
        self.fallbackLetter = String(ticker.prefix(1))
        self.size = size
    }

    init(logoUrl: String?, size: CGFloat) {
        let url = logoUrl.flatMap(URL.init(string:))
        self.url = url
        self.fallbackLetter = Self.fallbackLetter(forLogoURL: url)
        self.size = size
    }

    static func fallbackLetter(forLogoURL url: URL?) -> String {
        guard let first = url?.deletingPathExtension().lastPathComponent.first,
              first.isLetter || first.isNumber else { return "?" }
        return String(first)
    }

    var body: some View {
        AsyncImage(url: url) { phase in
            switch phase {
            case .success(let image):
                image
                    .resizable()
                    .scaledToFit()
            default:
                fallbackIcon
            }
        }
        .frame(width: size, height: size)
        .clipShape(.rect(cornerRadius: size * 0.22))
        .accessibilityHidden(true)
    }

    private var fallbackIcon: some View {
        Text(fallbackLetter)
            .font(.system(size: size * 0.45, weight: .bold))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(width: size, height: size)
            .background(Color.sevinoGreyAccent.opacity(0.3))
    }
}

#Preview("From ticker") {
    HStack(spacing: 12) {
        StockLogoView(ticker: "TSLA", size: 40)
        StockLogoView(ticker: "AMD", size: 40)
        StockLogoView(ticker: "AAPL", size: 40)
        StockLogoView(ticker: "UNKNOWN", size: 40)
    }
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("From logoUrl") {
    HStack(spacing: 12) {
        StockLogoView(logoUrl: "https://financialmodelingprep.com/image-stock/TSLA.png", size: 40)
        StockLogoView(logoUrl: "https://financialmodelingprep.com/image-stock/NVDA.png", size: 40)
        StockLogoView(logoUrl: nil, size: 40)
    }
    .padding()
    .background(Color.sevinoPrimary)
}

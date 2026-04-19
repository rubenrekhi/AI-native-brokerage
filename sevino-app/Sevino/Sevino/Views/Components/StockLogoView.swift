import SwiftUI

/// Displays a company logo for a given stock ticker.
/// Loads from financialmodelingprep.com with a styled initial fallback.
struct StockLogoView: View {
    let ticker: String
    let size: CGFloat

    private var logoURL: URL? {
        URL(string: "https://financialmodelingprep.com/image-stock/\(ticker).png")
    }

    var body: some View {
        AsyncImage(url: logoURL) { phase in
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
        Text(String(ticker.prefix(1)))
            .font(.system(size: size * 0.45, weight: .bold))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(width: size, height: size)
            .background(Color.sevinoGreyAccent.opacity(0.3))
    }
}

#Preview {
    HStack(spacing: 12) {
        StockLogoView(ticker: "TSLA", size: 40)
        StockLogoView(ticker: "AMD", size: 40)
        StockLogoView(ticker: "AAPL", size: 40)
        StockLogoView(ticker: "UNKNOWN", size: 40)
    }
    .padding()
    .background(Color.sevinoPrimary)
}

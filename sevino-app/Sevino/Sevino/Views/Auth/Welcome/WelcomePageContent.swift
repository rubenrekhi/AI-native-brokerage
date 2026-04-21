import SwiftUI

struct WelcomePageContent: View {
    let page: WelcomePage
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 0) {
            Text(page.title)
                .font(.dmSerif(size: 36 * scale))
                .foregroundStyle(Color.welcomeText)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 20 * scale)
                .padding(.bottom, 12 * scale)

            Text(page.subtitle)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeTextSecondary)
                .multilineTextAlignment(.center)
                .lineSpacing(3 * scale)
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 0)

            switch page.kind {
            case .portfolio: PortfolioCardView(scale: scale)
            case .trade: TradeCardView(scale: scale)
            case .research: ResearchCardView(scale: scale)
            case .protected: ProtectedCardView(scale: scale)
            }

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 20 * scale)
    }
}

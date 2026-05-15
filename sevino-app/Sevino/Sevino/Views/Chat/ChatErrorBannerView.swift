import SwiftUI

struct ChatErrorBannerView: View {
    let code: SSEEvent.ErrorCode
    let message: String?
    let scale: CGFloat
    let onRetry: () -> Void

    var body: some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoNegative)
                .accessibilityHidden(true)

            Text(displayMessage)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)

            Button(action: onRetry) {
                Text(L10n.Chat.errorRetry)
                    .font(.system(size: 14 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
            }
        }
        .padding(12 * scale)
        .background(Color.sevinoNegative.opacity(0.15), in: .rect(cornerRadius: 16 * scale))
        .padding(.horizontal, 16 * scale)
    }

    private var displayMessage: String {
        switch code {
        case .modelOverloaded, .modelRateLimit:
            L10n.Chat.errorModelBusy
        case .toolTimeout, .toolError:
            L10n.Chat.errorGeneric
        case .turnIterationLimit, .toolCallLimit, .outputTokenLimit:
            L10n.Chat.errorTooLong
        case .cancelled:
            L10n.Chat.errorCancelled
        case .internalError, .validationError, .unknown:
            message ?? L10n.Chat.errorUnexpected
        }
    }
}

#Preview {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        ChatErrorBannerView(
            code: .modelOverloaded,
            message: nil,
            scale: 1,
            onRetry: {}
        )
    }
    .preferredColorScheme(.dark)
}

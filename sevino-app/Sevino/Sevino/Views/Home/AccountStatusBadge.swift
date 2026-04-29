import SwiftUI

/// Renders the non-`ACTIVE` account states as a small badge so the pill /
/// holdings list can communicate "your account isn't ready yet" without
/// bottoming out at a misleading `$0.00`.
enum AccountStatusKind {
    case active
    case pending
    case actionRequired
    case rejected
    case unknown

    init(rawStatus: String) {
        switch rawStatus.uppercased() {
        case "ACTIVE": self = .active
        case "APPROVAL_PENDING", "SUBMITTED": self = .pending
        case "ACTION_REQUIRED": self = .actionRequired
        case "REJECTED", "ACCOUNT_CLOSED": self = .rejected
        case "": self = .unknown
        default: self = .unknown
        }
    }
}

/// Compact label for use inline on the pill (no chevron, no padding).
struct AccountStatusPillLabel: View {
    let kind: AccountStatusKind
    let scale: CGFloat

    var body: some View {
        if let text = label {
            Text(text)
                .font(.system(size: 13 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
        }
    }

    private var label: String? {
        switch kind {
        case .pending: return L10n.Home.accountPendingShort
        case .actionRequired: return L10n.Home.accountActionRequiredShort
        case .rejected: return L10n.Home.accountRejectedShort
        case .active, .unknown: return nil
        }
    }
}

/// Full-width message for the holdings/portfolio modal explaining the state
/// and (where applicable) offering the next action. The `actionRequired`
/// case renders a "Finish setup" button; its action is wired up later when
/// onboarding deep-link navigation lands — for now it's a no-op so the
/// surface looks complete without claiming a destination we don't have yet.
struct AccountStatusMessage: View {
    let kind: AccountStatusKind
    let scale: CGFloat

    var body: some View {
        if let copy = body(for: kind) {
            VStack(alignment: .leading, spacing: 8 * scale) {
                Label {
                    Text(copy.title)
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)
                } icon: {
                    Image(systemName: copy.icon)
                        .foregroundStyle(Color.sevinoGreyContrast)
                }

                Text(copy.message)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .fixedSize(horizontal: false, vertical: true)

                if let cta = copy.cta {
                    Button(cta) {
                        // Stub — onboarding deep-link navigation is a separate
                        // ticket. Intentional no-op so the visual lands now.
                    }
                    .font(.system(size: 14 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
                    .padding(.horizontal, 20 * scale)
                    .padding(.vertical, 10 * scale)
                    .frame(minHeight: 44 * scale)
                    .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 22 * scale))
                    .padding(.top, 4 * scale)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16 * scale)
            .background(
                Color.sevinoGreyAccent.opacity(0.15),
                in: .rect(cornerRadius: 12 * scale)
            )
        }
    }

    private struct Copy {
        let title: String
        let message: String
        let icon: String
        let cta: String?
    }

    private func body(for kind: AccountStatusKind) -> Copy? {
        switch kind {
        case .pending:
            return Copy(
                title: L10n.Home.accountPendingTitle,
                message: L10n.Home.accountPendingMessage,
                icon: "clock",
                cta: nil
            )
        case .actionRequired:
            return Copy(
                title: L10n.Home.accountActionRequiredTitle,
                message: L10n.Home.accountActionRequiredMessage,
                icon: "exclamationmark.circle",
                cta: L10n.Home.accountActionRequiredCTA
            )
        case .rejected:
            return Copy(
                title: L10n.Home.accountRejectedTitle,
                message: L10n.Home.accountRejectedMessage,
                icon: "xmark.octagon",
                cta: nil
            )
        case .active, .unknown:
            return nil
        }
    }
}

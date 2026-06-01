import SwiftUI

/// State-colored FDIC sweep enrollment badge.
struct EnrollmentStatusPill: View {
    enum Size {
        case small
        case large
    }

    let state: EnrollmentState
    var apyText: String = ""
    var size: Size = .small
    var scale: CGFloat = 1

    var body: some View {
        HStack(spacing: 5 * scale) {
            if size == .large, let icon {
                Image(systemName: icon)
            }
            Text(text)
        }
        .font(.system(size: fontSize, weight: .semibold))
        .foregroundStyle(tint)
        .padding(.horizontal, horizontalPadding)
        .padding(.vertical, verticalPadding)
        .background(tint.opacity(0.15), in: .capsule)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(text)
    }

    private var fontSize: CGFloat { (size == .large ? 16 : 12) * scale }
    private var horizontalPadding: CGFloat { (size == .large ? 18 : 12) * scale }
    private var verticalPadding: CGFloat { (size == .large ? 10 : 5) * scale }

    private var text: String {
        switch (size, state) {
        case (.small, .active): return L10n.CashEnrollmentStatus.pillActive
        case (.small, .pending): return L10n.CashEnrollmentStatus.pillPending
        case (.small, .notEnrolled): return L10n.CashEnrollmentStatus.pillNotEnrolled
        case (.small, .unavailable): return L10n.CashEnrollmentStatus.pillUnavailable
        case (.large, .active): return L10n.CashEnrollmentStatus.statusActive(apyText)
        case (.large, .pending): return L10n.CashEnrollmentStatus.statusPending
        case (.large, .notEnrolled): return L10n.CashEnrollmentStatus.statusNotEnrolled
        case (.large, .unavailable): return L10n.CashEnrollmentStatus.statusUnavailable
        }
    }

    private var tint: Color {
        switch state {
        case .active: return .sevinoPositive
        case .pending: return .sevinoGreyContrast
        case .notEnrolled: return .sevinoWarning
        case .unavailable: return .sevinoGreyContrast
        }
    }

    private var icon: String? {
        switch state {
        case .active: return "checkmark.circle.fill"
        case .pending: return "clock"
        case .notEnrolled: return "exclamationmark.triangle.fill"
        case .unavailable: return nil
        }
    }
}

#Preview("Small") {
    VStack(spacing: 12) {
        EnrollmentStatusPill(state: .active, size: .small)
        EnrollmentStatusPill(state: .pending, size: .small)
        EnrollmentStatusPill(state: .notEnrolled, size: .small)
    }
    .padding()
    .preferredColorScheme(.dark)
}

#Preview("Large") {
    VStack(spacing: 12) {
        EnrollmentStatusPill(state: .active, apyText: "4.25%", size: .large)
        EnrollmentStatusPill(state: .pending, size: .large)
        EnrollmentStatusPill(state: .notEnrolled, size: .large)
        EnrollmentStatusPill(state: .unavailable, size: .large)
    }
    .padding()
    .preferredColorScheme(.dark)
}
